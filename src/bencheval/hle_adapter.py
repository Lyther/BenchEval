"""Humanity's Last Exam model-only adapter (official CAIS scripts on host)."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.provider_registry import resolve_openai_compatible_launch

HLE_ADAPTER_ID = "hle"
_HLE_HOME_ENV = "BENCHEVAL_HLE_HOME"
_MIN_HLE_WORKERS = 2
_SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9._+-]+")


def _path_is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


@dataclass(frozen=True, slots=True)
class HleCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HleOfficialScore:
    accuracy: float
    correct: int
    total: int
    source: str


@dataclass(frozen=True, slots=True)
class HleInstanceOutcome:
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


@dataclass(frozen=True, slots=True)
class HleRunPaths:
    work_dir: Path
    predictions_path: Path
    judged_path: Path
    default_predictions_path: Path


class HleProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> HleCliResult: ...


def _hle_root() -> Path:
    raw = os.environ.get(_HLE_HOME_ENV)
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd()


def _hle_eval_dir(root: Path) -> Path:
    return root / "hle_eval"


def _safe_token(value: str) -> str:
    cleaned = _SAFE_TOKEN_RE.sub("_", value.strip())
    return cleaned.strip("._") or "unknown"


def _model_basename(model_id: str) -> str:
    return _safe_token(Path(model_id).name.replace(os.sep, "_"))


def hle_work_dir(artifacts_dir: Path) -> Path:
    return artifacts_dir.resolve() / "hle-work"


def hle_output_stem(*, run_id: str, provider_id: str, model_id: str) -> str:
    """Stable stem including run_id and full provider/model identity."""
    return f"{_safe_token(run_id)}__{_safe_token(provider_id)}__{_safe_token(model_id)}"


def hle_run_paths(
    *,
    artifacts_dir: Path,
    run_id: str,
    provider_id: str,
    model_id: str,
) -> HleRunPaths:
    work_dir = hle_work_dir(artifacts_dir)
    stem = hle_output_stem(run_id=run_id, provider_id=provider_id, model_id=model_id)
    predictions = work_dir / f"hle_{stem}.json"
    return HleRunPaths(
        work_dir=work_dir,
        predictions_path=predictions,
        # CAIS uses f"judged_{basename(predictions)}.json". The predictions
        # basename already ends in .json, yielding the official .json.json name.
        judged_path=work_dir / f"judged_{predictions.name}.json",
        default_predictions_path=work_dir / f"hle_{_model_basename(model_id)}.json",
    )


def remaining_timeout_sec(
    deadline_monotonic: float,
    *,
    now_monotonic: float | None = None,
) -> int:
    """Seconds remaining until a cumulative wall-clock deadline (0 if exhausted)."""
    now = time.monotonic() if now_monotonic is None else now_monotonic
    left = deadline_monotonic - now
    if left <= 0:
        return 0
    return max(1, math.ceil(left))


def build_hle_run_commands(
    *,
    plan: RunPlan,
    max_samples: int,
    artifacts_dir: Path,
    run_id: str,
) -> tuple[tuple[str, ...], ...]:
    if plan.runtime_id is not None:
        raise BenchEvalError(
            f"hle adapter expects model-only (runtime_id=None), got {plan.runtime_id!r}",
        )
    if plan.agent_id is not None:
        raise BenchEvalError(
            f"hle adapter expects model-only (agent_id=None), got {plan.agent_id!r}",
        )
    if plan.judge_model_id is None:
        raise BenchEvalError("hle adapter requires a planned judge_model_id")
    root = _hle_root()
    eval_dir = _hle_eval_dir(root)
    pred_script = eval_dir / "run_model_predictions.py"
    judge_script = eval_dir / "run_judge_results.py"
    if not pred_script.is_file() or not judge_script.is_file():
        raise BenchEvalError(
            f"CAIS HLE scripts not found under {eval_dir}; "
            f"clone https://github.com/centerforaisafety/hle and set {_HLE_HOME_ENV}",
        )
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id=run_id,
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    n = max(max_samples, 1)
    workers = str(_MIN_HLE_WORKERS)
    pred_cmd = (
        "python",
        str(pred_script.resolve()),
        "--dataset",
        "cais/hle",
        "--model",
        plan.model_id,
        "--max_completion_tokens",
        "8192",
        "--num_workers",
        workers,
        "--max_samples",
        str(n),
    )
    judge_cmd = (
        "python",
        str(judge_script.resolve()),
        "--dataset",
        "cais/hle",
        "--predictions",
        str(paths.predictions_path),
        "--num_workers",
        workers,
        "--judge",
        plan.judge_model_id,
    )
    return (pred_cmd, judge_cmd)


def _clear_path(path: Path) -> None:
    if path.is_file():
        path.unlink()
    elif path.exists():
        raise BenchEvalError(f"refusing to reuse non-file HLE artifact path: {path}")


def prepare_hle_work_dir(paths: HleRunPaths) -> None:
    """Create run-local work dir and clear prior outputs for this run identity."""
    paths.work_dir.mkdir(parents=True, exist_ok=True)
    for path in (
        paths.predictions_path,
        paths.judged_path,
        paths.default_predictions_path,
        paths.work_dir / f"judged_{paths.default_predictions_path.name}.json",
    ):
        _clear_path(path)


def materialize_hle_predictions(paths: HleRunPaths) -> Path:
    """Map official basename output onto the run-isolated predictions path."""
    if paths.predictions_path.is_file():
        return paths.predictions_path
    if paths.default_predictions_path.is_file():
        paths.default_predictions_path.replace(paths.predictions_path)
        return paths.predictions_path
    raise AdapterFailureError(
        "hle predict finished without predictions file "
        f"(expected {paths.default_predictions_path.name} or {paths.predictions_path.name})",
        failure_label="runtime_output_unparseable",
        latency_sec=0.0,
        adapter_metadata={"hle_predictions": str(paths.predictions_path)},
    )


def parse_hle_official_score(
    *,
    eval_dir: Path,
    model_id: str,
    judge_stdout: str,
    max_samples: int,
    work_dir: Path | None = None,
    judged_path: Path | None = None,
) -> HleOfficialScore | None:
    """Parse the current run's official judged artifact into accuracy.

    Authority is the identity-bound judged JSON only (exact ``correct == "yes"``).
    Stdout metrics and BenchEval-authored summaries are never scoring authority.
    When ``work_dir`` is set, the judged file must resolve inside that tree.
    """
    _ = judge_stdout  # retained for call-site symmetry; never scoring authority
    candidates: list[Path] = []
    if judged_path is not None:
        candidates.append(judged_path)
    elif eval_dir.is_dir():
        candidates.append(eval_dir / f"judged_hle_{_model_basename(model_id)}.json.json")

    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if work_dir is not None and not _path_is_under(resolved, work_dir):
            continue
        if not path.is_file():
            continue
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict) and parsed:
            correct = 0
            total = 0
            for row in parsed.values():
                if not isinstance(row, dict):
                    continue
                judge = row.get("judge_response")
                if not isinstance(judge, dict):
                    # Missing judge response shrinks the denominator → reject.
                    return None
                answer = judge.get("correct")
                # Official HLE judge literals are exactly "yes" / "no".
                if answer not in ("yes", "no"):
                    return None
                total += 1
                if answer == "yes":
                    correct += 1
            if total <= 0 or total != max_samples:
                return None
            return HleOfficialScore(
                accuracy=correct / total,
                correct=correct,
                total=total,
                source=str(resolved),
            )
    return None


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
    env: Mapping[str, str],
) -> HleCliResult:
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
            f"hle harness timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"hle_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"hle harness launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"hle_command": " ".join(command)},
        ) from e
    return HleCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def run_hle_slice(
    *,
    plan: RunPlan,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: HleProcessRunner | None = None,
    timeout_sec: int | None = None,
    run_id: str = "hle-run",
    monotonic_clock: Callable[[], float] | None = None,
) -> list[HleInstanceOutcome]:
    if plan.adapter_id != HLE_ADAPTER_ID:
        raise BenchEvalError(f"hle adapter cannot run adapter_id={plan.adapter_id!r}")
    for inst in plan.instances:
        validate_control_plane_instance_id(inst.instance_id)
    launch = resolve_openai_compatible_launch(
        plan.provider_id,
        require_api_key=process_runner is None,
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id=run_id,
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    prepare_hle_work_dir(paths)
    commands = build_hle_run_commands(
        plan=plan,
        max_samples=len(plan.instances),
        artifacts_dir=artifacts_dir,
        run_id=run_id,
    )
    wall = timeout_sec if timeout_sec is not None else max(1, plan.max_wall_clock_sec)
    clock = monotonic_clock or time.monotonic
    deadline = clock() + wall
    runner = process_runner or _default_process_runner
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    total_latency = 0.0
    last_rc = 0
    last_cmd: tuple[str, ...] = ()
    root = _hle_root()
    eval_dir = _hle_eval_dir(root)
    cwd = paths.work_dir

    for index, command in enumerate(commands):
        remaining = remaining_timeout_sec(deadline, now_monotonic=clock())
        if remaining <= 0:
            raise AdapterFailureError(
                f"hle harness timed out after {wall}s",
                failure_label="runtime_budget_exceeded",
                latency_sec=total_latency,
                adapter_metadata={"hle_command": " ".join(command)},
            )
        cli = runner(command, cwd=cwd, timeout_sec=remaining, env=launch.environment)
        stdout_parts.append(cli.stdout)
        stderr_parts.append(cli.stderr)
        total_latency += cli.latency_sec
        last_rc = cli.returncode
        last_cmd = cli.command
        if cli.returncode != 0:
            break
        if index == 0:
            materialize_hle_predictions(paths)

    stdout_text = "\n".join(stdout_parts)
    stdout_file = artifacts_dir / "stdout.log"
    stderr_file = artifacts_dir / "stderr.log"
    stdout_file.write_text(stdout_text, encoding="utf-8")
    stderr_file.write_text("\n".join(stderr_parts), encoding="utf-8")
    summary_path = artifacts_dir / "hle_summary.json"

    official = (
        parse_hle_official_score(
            eval_dir=eval_dir,
            model_id=plan.model_id,
            judge_stdout=stdout_text,
            max_samples=len(plan.instances),
            work_dir=paths.work_dir,
            judged_path=paths.judged_path,
        )
        if last_rc == 0
        else None
    )
    if last_rc != 0:
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
        complete = official.total == requested and official.correct <= official.total
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
                "returncode": last_rc,
                "max_samples": len(plan.instances),
                "work_dir": str(paths.work_dir),
                "predictions_path": str(paths.predictions_path),
                "judged_path": str(paths.judged_path),
                "judge_model_id": plan.judge_model_id,
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
                "commands": [" ".join(c) for c in commands],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    meta = {
        "adapter_id": HLE_ADAPTER_ID,
        "harness_kind": "hle-native",
        "hle_command": " ".join(last_cmd),
        "interpretation": "adapter_smoke",
        "score_source": "official" if official is not None else "missing",
        "evidence_shape": "aggregate_slice",
        "effective_model_id": plan.model_id,
        "judge_model_id": plan.judge_model_id,
        "provider_config_hash": launch.config_hash,
    }
    native: dict[str, object] = {
        "returncode": last_rc,
        "planned_sample_slots": len(plan.instances),
        "work_dir": str(paths.work_dir),
        "effective_model_id": plan.model_id,
        "judge_model_id": plan.judge_model_id,
    }
    if official is not None:
        native.update(
            {
                "accuracy": official.accuracy,
                "correct": official.correct,
                "total": official.total,
                "score_source": official.source,
            },
        )
    _ = repo_root  # call-site symmetry; HLE scripts resolve under BENCHEVAL_HLE_HOME
    # Official judged artifact is the only native verifier path; never hle_summary.json.
    verifier_log: str | None = None
    if official is not None and paths.judged_path.is_file():
        verifier_log = str(paths.judged_path.resolve())
    aggregate_id = f"{plan.benchmark_id}-{plan.slice_id}-aggregate"
    validate_control_plane_instance_id(aggregate_id)
    return [
        HleInstanceOutcome(
            instance_id=aggregate_id,
            primary_pass=primary_pass,
            partial_score=partial_score,
            cost_usd=0.0,
            latency_sec=total_latency,
            native_score=native,
            failure_class=failure,
            stdout_path=str(stdout_file.resolve()),
            stderr_path=str(stderr_file.resolve()),
            verifier_log_path=verifier_log,
            adapter_metadata={
                **meta,
                "cost_cap": "unenforced_estimate",
                "reported_cost_usd": "unavailable",
            },
            counts_toward_pass_at_k=counts,
        ),
    ]


__all__ = [
    "HLE_ADAPTER_ID",
    "HleCliResult",
    "HleInstanceOutcome",
    "HleOfficialScore",
    "HleProcessRunner",
    "HleRunPaths",
    "build_hle_run_commands",
    "hle_output_stem",
    "hle_run_paths",
    "hle_work_dir",
    "materialize_hle_predictions",
    "parse_hle_official_score",
    "prepare_hle_work_dir",
    "remaining_timeout_sec",
    "run_hle_slice",
]
