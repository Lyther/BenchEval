"""Humanity's Last Exam model-only adapter (official CAIS scripts on host)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id

HLE_ADAPTER_ID = "hle"
_HLE_HOME_ENV = "BENCHEVAL_HLE_HOME"
_MIN_HLE_WORKERS = 2
_ACCURACY_RE = re.compile(r"Accuracy:\s*([0-9]+(?:\.[0-9]+)?)%")


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


class HleProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> HleCliResult: ...


def _hle_root() -> Path:
    raw = os.environ.get(_HLE_HOME_ENV)
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd()


def _hle_eval_dir(root: Path) -> Path:
    return root / "hle_eval"


def _model_slug(model_id: str) -> str:
    return Path(model_id).name.replace(os.sep, "_")


def build_hle_run_commands(
    *,
    plan: RunPlan,
    max_samples: int,
    artifacts_dir: Path,
) -> tuple[tuple[str, ...], ...]:
    del artifacts_dir  # official scripts write under hle_eval cwd
    if plan.runtime_id is not None:
        raise BenchEvalError(
            f"hle adapter expects model-only (runtime_id=None), got {plan.runtime_id!r}",
        )
    if plan.agent_id is not None:
        raise BenchEvalError(
            f"hle adapter expects model-only (agent_id=None), got {plan.agent_id!r}",
        )
    root = _hle_root()
    eval_dir = _hle_eval_dir(root)
    pred_script = eval_dir / "run_model_predictions.py"
    judge_script = eval_dir / "run_judge_results.py"
    if not pred_script.is_file() or not judge_script.is_file():
        raise BenchEvalError(
            f"CAIS HLE scripts not found under {eval_dir}; "
            f"clone https://github.com/centerforaisafety/hle and set {_HLE_HOME_ENV}",
        )
    # Official run_model_predictions.py writes hle_<basename(model)>.json in cwd.
    predictions = eval_dir / f"hle_{_model_slug(plan.model_id)}.json"
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
        str(predictions.resolve()),
        "--num_workers",
        workers,
    )
    return (pred_cmd, judge_cmd)


def parse_hle_official_score(
    *,
    eval_dir: Path,
    model_id: str,
    judge_stdout: str,
    max_samples: int,
) -> HleOfficialScore | None:
    """Parse judge file and/or official metrics stdout into accuracy."""
    judged_path = eval_dir / f"judged_hle_{_model_slug(model_id)}.json"
    if judged_path.is_file():
        try:
            parsed = json.loads(judged_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict) and parsed:
            correct = 0
            total = 0
            for row in parsed.values():
                if not isinstance(row, dict):
                    continue
                judge = row.get("judge_response")
                if not isinstance(judge, dict):
                    continue
                total += 1
                answer = judge.get("correct")
                if isinstance(answer, str) and "yes" in answer.lower():
                    correct += 1
            if total > 0:
                return HleOfficialScore(
                    accuracy=correct / total,
                    correct=correct,
                    total=total,
                    source=str(judged_path),
                )
    match = _ACCURACY_RE.search(judge_stdout)
    if match is not None:
        pct = float(match.group(1))
        accuracy = min(max(pct / 100.0, 0.0), 1.0)
        return HleOfficialScore(
            accuracy=accuracy,
            correct=round(accuracy * max(max_samples, 1)),
            total=max(max_samples, 1),
            source="stdout_metrics",
        )
    return None


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
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
) -> list[HleInstanceOutcome]:
    if plan.adapter_id != HLE_ADAPTER_ID:
        raise BenchEvalError(f"hle adapter cannot run adapter_id={plan.adapter_id!r}")
    for inst in plan.instances:
        validate_control_plane_instance_id(inst.instance_id)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    commands = build_hle_run_commands(
        plan=plan,
        max_samples=len(plan.instances),
        artifacts_dir=artifacts_dir,
    )
    wall = timeout_sec if timeout_sec is not None else max(plan.max_wall_clock_sec, 60)
    runner = process_runner or _default_process_runner
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    total_latency = 0.0
    last_rc = 0
    last_cmd: tuple[str, ...] = ()
    root = _hle_root()
    eval_dir = _hle_eval_dir(root)
    if eval_dir.is_dir():
        cwd = eval_dir
    elif root.is_dir():
        cwd = root
    else:
        cwd = repo_root
    for command in commands:
        cli = runner(command, cwd=cwd, timeout_sec=wall)
        stdout_parts.append(cli.stdout)
        stderr_parts.append(cli.stderr)
        total_latency += cli.latency_sec
        last_rc = cli.returncode
        last_cmd = cli.command
        if cli.returncode != 0:
            break

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
        primary_pass = official.accuracy >= 1.0 and official.total > 0
        counts = True
        failure = None if primary_pass else "model_wrong_solution"

    summary_path.write_text(
        json.dumps(
            {
                "returncode": last_rc,
                "max_samples": len(plan.instances),
                "predictions_path": str(
                    (eval_dir / f"hle_{_model_slug(plan.model_id)}.json").resolve(),
                ),
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
    }
    native: dict[str, object] = {
        "returncode": last_rc,
        "planned_sample_slots": len(plan.instances),
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
            verifier_log_path=str(summary_path.resolve()),
            adapter_metadata=meta,
            counts_toward_pass_at_k=counts,
        ),
    ]


__all__ = [
    "HLE_ADAPTER_ID",
    "HleCliResult",
    "HleInstanceOutcome",
    "HleOfficialScore",
    "HleProcessRunner",
    "build_hle_run_commands",
    "parse_hle_official_score",
    "run_hle_slice",
]
