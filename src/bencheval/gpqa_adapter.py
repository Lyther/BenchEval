"""GPQA Diamond model-only adapter via Inspect Evals (host pulls dataset)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Protocol

from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.provider_registry import resolve_openai_compatible_launch

GPQA_ADAPTER_ID = "gpqa"
_INSPECT_TASK = "inspect_evals/gpqa_diamond"
_OFFICIAL_SCORES_NAME = "official_scores.json"
_INSPECT_EVALS_DIST = "inspect-evals"
# Inspect plain/rich panels print "Log: <path>"; strip optional rich markup around it.
_LOG_LOCATION_RE = re.compile(
    r"(?:^|\n)\s*(?:Log:\s+|log_location[\"']?\s*[:=]\s*[\"']?)([^\s\"'<>]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class GpqaCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GpqaOfficialScore:
    accuracy: float
    correct: int | None
    total: int | None
    source: str


@dataclass(frozen=True, slots=True)
class GpqaInstanceOutcome:
    instance_id: str
    primary_pass: bool
    partial_score: float
    cost_usd: float
    latency_sec: float
    native_score: dict[str, object]
    failure_class: FailureLabel | None
    stdout_path: str | None
    stderr_path: str | None
    verifier_log_path: str | None
    adapter_metadata: dict[str, str]
    counts_toward_pass_at_k: bool


class GpqaProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> GpqaCliResult: ...


def _inspect_model_string(plan: RunPlan) -> str:
    expected = (
        f"openai/{plan.model_id}"
        if plan.provider_id == "bytellm"
        else f"{plan.provider_id}/{plan.model_id}"
    )
    override = os.environ.get("BENCHEVAL_INSPECT_MODEL")
    if override is not None and override.strip() != expected:
        raise BenchEvalError(
            f"BENCHEVAL_INSPECT_MODEL must match the provider-resolved planned model {expected!r}",
        )
    return expected


def build_gpqa_run_command(
    *,
    plan: RunPlan,
    sample_limit: int,
    log_dir: Path,
) -> tuple[str, ...]:
    if plan.runtime_id is not None:
        raise BenchEvalError(
            f"gpqa adapter expects model-only (runtime_id=None), got {plan.runtime_id!r}",
        )
    if plan.agent_id is not None:
        raise BenchEvalError(
            f"gpqa adapter expects model-only (agent_id=None), got {plan.agent_id!r}",
        )
    limit = max(sample_limit, 1)
    return (
        "inspect",
        "eval",
        _INSPECT_TASK,
        "--model",
        _inspect_model_string(plan),
        "--limit",
        str(limit),
        "--log-dir",
        str(log_dir.resolve()),
        "--log-format",
        "json",
        "--json",
    )


def _inspect_evals_harness_version() -> str | None:
    try:
        return f"{_INSPECT_EVALS_DIST}@{distribution_version(_INSPECT_EVALS_DIST)}"
    except PackageNotFoundError:
        return None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _sample_totals(results: dict[str, object]) -> int | None:
    """Return a usable denominator only when completed and total agree."""
    completed_raw = results.get("completed_samples")
    total_raw = results.get("total_samples")
    completed = (
        completed_raw
        if isinstance(completed_raw, int) and not isinstance(completed_raw, bool)
        else None
    )
    total = total_raw if isinstance(total_raw, int) and not isinstance(total_raw, bool) else None
    if completed is None or total is None:
        return None
    if completed <= 0 or total <= 0 or completed != total:
        return None
    return total


def _counts_for_accuracy(accuracy: float, total: int | None) -> tuple[int | None, int | None]:
    if total is None:
        return None, None
    correct = round(accuracy * total)
    if total <= 0:
        return None, None
    if abs((correct / total) - accuracy) > 1e-9:
        return None, None
    return correct, total


def _score_from_inspect_results(raw: dict[str, object], *, source: str) -> GpqaOfficialScore | None:
    results = raw.get("results")
    if not isinstance(results, dict):
        return None
    scores = results.get("scores")
    if not isinstance(scores, list):
        return None
    sample_total = _sample_totals(results)
    for entry in scores:
        if not isinstance(entry, dict):
            continue
        metrics = entry.get("metrics")
        if isinstance(metrics, dict):
            for key in ("accuracy", "acc", "mean"):
                metric = metrics.get(key)
                if isinstance(metric, dict) and "value" in metric:
                    value = _as_float(metric.get("value"))
                    if value is not None and 0.0 <= value <= 1.0:
                        correct, total = _counts_for_accuracy(value, sample_total)
                        return GpqaOfficialScore(value, correct, total, source)
                value = _as_float(metric)
                if value is not None and 0.0 <= value <= 1.0:
                    correct, total = _counts_for_accuracy(value, sample_total)
                    return GpqaOfficialScore(value, correct, total, source)
        value = _as_float(entry.get("value"))
        if value is not None and 0.0 <= value <= 1.0:
            correct, total = _counts_for_accuracy(value, sample_total)
            return GpqaOfficialScore(value, correct, total, source)
    return None


def _looks_like_inspect_eval_log(
    raw: dict[str, object],
    *,
    expected_task: str,
    expected_model: str,
) -> bool:
    if raw.get("status") != "success":
        return False
    eval_spec = raw.get("eval")
    if not isinstance(eval_spec, dict):
        return False
    task = eval_spec.get("task")
    model = eval_spec.get("model")
    task_aliases = {expected_task, expected_task.rsplit("/", maxsplit=1)[-1]}
    if task not in task_aliases or model != expected_model:
        return False
    if not isinstance(raw.get("results"), dict):
        return False
    scores = raw["results"].get("scores") if isinstance(raw["results"], dict) else None
    return isinstance(scores, list)


def _load_json_object(
    path: Path,
    *,
    expected_task: str,
    expected_model: str,
) -> dict[str, object] | None:
    suffix = path.suffix.lower()
    if suffix == ".eval":
        try:
            from inspect_ai.log import read_eval_log
        except ImportError:
            return None
        try:
            log = read_eval_log(path, header_only=True)
        except (OSError, ValueError, TypeError):
            return None
        dumped = json.loads(log.model_dump_json())
        return dumped if isinstance(dumped, dict) else None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if suffix == ".jsonl":
        # Prefer the last JSON object that looks like an eval log.
        last: dict[str, object] | None = None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and _looks_like_inspect_eval_log(
                parsed,
                expected_task=expected_task,
                expected_model=expected_model,
            ):
                last = parsed
        return last
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _log_locations_from_text(text: str) -> list[Path]:
    found: list[Path] = []
    for match in _LOG_LOCATION_RE.finditer(text):
        raw = match.group(1).strip().rstrip("]")
        if not raw:
            continue
        path = Path(raw).expanduser()
        found.append(path)
    return found


def _log_locations_from_inspect_json(text: str) -> list[Path]:
    """Parse Inspect ``--json`` launch records; only ``done`` task log_location wins."""
    found: list[Path] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "done":
            continue
        tasks = payload.get("tasks")
        if not isinstance(tasks, list):
            continue
        for task in tasks:
            if not isinstance(task, dict):
                continue
            location = task.get("log_location")
            if isinstance(location, str) and location.strip():
                found.append(Path(location.strip()).expanduser())
    if found:
        return found
    # Whole-stdout JSON object (single launch record).
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict) or payload.get("type") != "done":
        return []
    tasks = payload.get("tasks")
    if not isinstance(tasks, list):
        return []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        location = task.get("log_location")
        if isinstance(location, str) and location.strip():
            found.append(Path(location.strip()).expanduser())
    return found


def _inspect_log_candidates(
    log_dir: Path,
    *,
    stdout: str,
    stderr: str,
) -> list[Path]:
    ordered: list[Path] = []
    seen: set[Path] = set()
    root = log_dir.resolve()

    def _add(path: Path) -> None:
        candidate = path if path.is_absolute() else log_dir / path
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            return
        if resolved in seen or not resolved.is_file():
            return
        seen.add(resolved)
        ordered.append(resolved)

    # Machine-readable done records own scoring identity when present.
    json_owned = _log_locations_from_inspect_json(stdout)
    if json_owned:
        for path in json_owned:
            _add(path)
        return ordered

    for text in (stdout, stderr):
        for path in _log_locations_from_text(text):
            _add(path)
    # Live runs require Inspect to name the current log; never scan stale files.
    return ordered


def parse_gpqa_official_score(
    log_dir: Path,
    *,
    expected_model: str | None = None,
    expected_task: str = _INSPECT_TASK,
    stdout: str = "",
    stderr: str = "",
) -> GpqaOfficialScore | None:
    """Extract official accuracy from Inspect eval logs only.

    Operator-authored ``official_scores.json`` is never pass-authoritative.
    """
    if expected_model is None:
        return None
    for path in _inspect_log_candidates(log_dir, stdout=stdout, stderr=stderr):
        candidate = path
        if not candidate.is_file() and not candidate.is_absolute():
            alt = log_dir / candidate
            if alt.is_file():
                candidate = alt
        if not candidate.is_file():
            continue
        # Never treat the operator override filename as an Inspect log.
        if candidate.name == _OFFICIAL_SCORES_NAME:
            continue
        parsed = _load_json_object(
            candidate,
            expected_task=expected_task,
            expected_model=expected_model,
        )
        if parsed is None or not _looks_like_inspect_eval_log(
            parsed,
            expected_task=expected_task,
            expected_model=expected_model,
        ):
            continue
        score = _score_from_inspect_results(parsed, source=str(candidate))
        if score is not None:
            return score
    return None


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
    env: Mapping[str, str],
) -> GpqaCliResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_sec,
            env=dict(env),
        )
    except subprocess.TimeoutExpired as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"inspect eval timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"gpqa_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"inspect eval launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"gpqa_command": " ".join(command)},
        ) from e
    return GpqaCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def run_gpqa_slice(
    *,
    plan: RunPlan,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: GpqaProcessRunner | None = None,
    timeout_sec: int | None = None,
) -> list[GpqaInstanceOutcome]:
    """Run one Inspect eval; score only from official log metrics, never exit code."""
    if plan.adapter_id != GPQA_ADAPTER_ID:
        raise BenchEvalError(f"gpqa adapter cannot run adapter_id={plan.adapter_id!r}")
    for inst in plan.instances:
        validate_control_plane_instance_id(inst.instance_id)
    log_dir = artifacts_dir / "inspect-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    command = build_gpqa_run_command(
        plan=plan,
        sample_limit=len(plan.instances),
        log_dir=log_dir,
    )
    effective_model = command[command.index("--model") + 1]
    launch = resolve_openai_compatible_launch(
        plan.provider_id,
        require_api_key=process_runner is None,
    )
    wall = timeout_sec if timeout_sec is not None else max(1, plan.max_wall_clock_sec)
    runner = process_runner or _default_process_runner
    cli = runner(command, cwd=repo_root, timeout_sec=wall, env=launch.environment)

    stdout_file = artifacts_dir / "stdout.log"
    stderr_file = artifacts_dir / "stderr.log"
    stdout_file.write_text(cli.stdout, encoding="utf-8")
    stderr_file.write_text(cli.stderr, encoding="utf-8")
    summary_path = artifacts_dir / "gpqa_summary.json"

    official = (
        parse_gpqa_official_score(
            log_dir,
            expected_model=effective_model,
            stdout=cli.stdout,
            stderr=cli.stderr,
        )
        if cli.returncode == 0
        else None
    )
    if cli.returncode != 0:
        primary_pass = False
        partial_score = 0.0
        counts = False
        failure: FailureLabel | None = "harness_failure"
    elif official is None:
        primary_pass = False
        partial_score = 0.0
        counts = False
        failure = "runtime_output_unparseable"
    else:
        partial_score = official.accuracy
        requested = len(plan.instances)
        complete = (
            official.total is not None
            and official.correct is not None
            and official.total == requested
            and official.correct <= official.total
        )
        primary_pass = bool(
            complete and official.accuracy >= 1.0 and official.correct == official.total,
        )
        counts = complete
        if not complete:
            failure = "runtime_output_unparseable"
            primary_pass = False
        else:
            failure = None if primary_pass else "model_wrong_solution"

    summary_path.write_text(
        json.dumps(
            {
                "returncode": cli.returncode,
                "limit": len(plan.instances),
                "official_score": (
                    None
                    if official is None
                    else {
                        "accuracy": official.accuracy,
                        "correct": official.correct,
                        "total": official.total,
                        "source": official.source,
                    }
                ),
                "primary_pass": primary_pass,
                "partial_score": partial_score,
                "counts_toward_pass_at_k": counts,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    harness_version = _inspect_evals_harness_version()
    meta = {
        "adapter_id": GPQA_ADAPTER_ID,
        "harness_kind": "inspect-evals",
        "gpqa_command": " ".join(cli.command),
        "interpretation": "adapter_smoke",
        "score_source": official.source if official is not None else "missing",
        "evidence_shape": "aggregate_slice",
        "effective_model_id": effective_model,
        "provider_config_hash": launch.config_hash,
    }
    if harness_version is not None:
        meta["harness_version"] = harness_version
    shared_native: dict[str, object] = {
        "returncode": cli.returncode,
        "inspect_task": _INSPECT_TASK,
        "effective_model_id": effective_model,
        "planned_sample_slots": len(plan.instances),
    }
    if official is not None:
        shared_native.update(
            {
                "accuracy": official.accuracy,
                "correct": official.correct,
                "total": official.total,
                "score_source": official.source,
            },
        )
    # Aggregate official metrics only: one evidence row (not N fake per-sample passes).
    aggregate_id = f"{plan.benchmark_id}-{plan.slice_id}-aggregate"
    validate_control_plane_instance_id(aggregate_id)
    # Summary alone is not a native verifier artifact — only Inspect log paths stamp.
    verifier_path = official.source if official is not None else None
    return [
        GpqaInstanceOutcome(
            instance_id=aggregate_id,
            primary_pass=primary_pass,
            partial_score=partial_score,
            cost_usd=0.0,
            latency_sec=cli.latency_sec,
            native_score=shared_native,
            failure_class=failure,
            stdout_path=str(stdout_file.resolve()),
            stderr_path=str(stderr_file.resolve()),
            verifier_log_path=verifier_path,
            adapter_metadata={
                **meta,
                "cost_cap": "unenforced_estimate",
                "reported_cost_usd": "unavailable",
            },
            counts_toward_pass_at_k=counts,
        ),
    ]


__all__ = [
    "GPQA_ADAPTER_ID",
    "GpqaCliResult",
    "GpqaInstanceOutcome",
    "GpqaOfficialScore",
    "GpqaProcessRunner",
    "build_gpqa_run_command",
    "parse_gpqa_official_score",
    "run_gpqa_slice",
]
