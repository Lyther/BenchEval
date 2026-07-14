"""GPQA Diamond model-only adapter via Inspect Evals (host pulls dataset)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id

GPQA_ADAPTER_ID = "gpqa"
_INSPECT_TASK = "inspect_evals/gpqa_diamond"
_OFFICIAL_SCORES_NAME = "official_scores.json"


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
    correct: int
    total: int
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
    ) -> GpqaCliResult: ...


def _inspect_model_string(plan: RunPlan) -> str:
    override = os.environ.get("BENCHEVAL_INSPECT_MODEL")
    if override and "\n" not in override:
        return override
    if plan.provider_id == "bytellm":
        return f"openai/{plan.model_id}"
    return f"{plan.provider_id}/{plan.model_id}"


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
    )


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


def _score_from_mapping(raw: dict[str, object], *, source: str) -> GpqaOfficialScore | None:
    accuracy = _as_float(raw.get("accuracy"))
    correct = raw.get("correct")
    total = raw.get("total")
    if accuracy is None and isinstance(correct, int) and isinstance(total, int) and total > 0:
        accuracy = correct / total
    if accuracy is None:
        return None
    clamped = min(max(accuracy, 0.0), 1.0)
    if isinstance(correct, int) and isinstance(total, int) and total > 0:
        return GpqaOfficialScore(clamped, correct, total, source)
    return GpqaOfficialScore(clamped, round(clamped), 1, source)


def _score_from_inspect_results(raw: dict[str, object], *, source: str) -> GpqaOfficialScore | None:
    results = raw.get("results")
    if not isinstance(results, dict):
        return None
    scores = results.get("scores")
    if not isinstance(scores, list):
        return None
    for entry in scores:
        if not isinstance(entry, dict):
            continue
        metrics = entry.get("metrics")
        if isinstance(metrics, dict):
            for key in ("accuracy", "acc", "mean"):
                metric = metrics.get(key)
                if isinstance(metric, dict) and "value" in metric:
                    value = _as_float(metric.get("value"))
                    if value is not None:
                        clamped = min(max(value, 0.0), 1.0)
                        return GpqaOfficialScore(clamped, round(clamped), 1, source)
                value = _as_float(metric)
                if value is not None:
                    clamped = min(max(value, 0.0), 1.0)
                    return GpqaOfficialScore(clamped, round(clamped), 1, source)
        value = _as_float(entry.get("value"))
        if value is not None:
            clamped = min(max(value, 0.0), 1.0)
            return GpqaOfficialScore(clamped, round(clamped), 1, source)
    return None


def parse_gpqa_official_score(log_dir: Path) -> GpqaOfficialScore | None:
    """Extract official accuracy from Inspect log dir artifacts."""
    preferred = log_dir / _OFFICIAL_SCORES_NAME
    candidates = [preferred, *sorted(log_dir.glob("*.json"))]
    seen: set[Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen or not path.is_file():
            continue
        seen.add(resolved)
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(parsed, dict):
            continue
        score = _score_from_mapping(parsed, source=str(path))
        if score is not None:
            return score
        score = _score_from_inspect_results(parsed, source=str(path))
        if score is not None:
            return score
    return None


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
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
    wall = timeout_sec if timeout_sec is not None else max(plan.max_wall_clock_sec, 60)
    runner = process_runner or _default_process_runner
    cli = runner(command, cwd=repo_root, timeout_sec=wall)

    stdout_file = artifacts_dir / "stdout.log"
    stderr_file = artifacts_dir / "stderr.log"
    stdout_file.write_text(cli.stdout, encoding="utf-8")
    stderr_file.write_text(cli.stderr, encoding="utf-8")
    summary_path = artifacts_dir / "gpqa_summary.json"

    official = parse_gpqa_official_score(log_dir) if cli.returncode == 0 else None
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
        primary_pass = official.accuracy >= 1.0 and official.total > 0
        counts = True
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
    meta = {
        "adapter_id": GPQA_ADAPTER_ID,
        "harness_kind": "inspect-evals",
        "gpqa_command": " ".join(cli.command),
        "interpretation": "adapter_smoke",
        "score_source": "official" if official is not None else "missing",
        "evidence_shape": "aggregate_slice",
    }
    shared_native: dict[str, object] = {
        "returncode": cli.returncode,
        "inspect_task": _INSPECT_TASK,
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
            verifier_log_path=str(summary_path.resolve()),
            adapter_metadata=meta,
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
