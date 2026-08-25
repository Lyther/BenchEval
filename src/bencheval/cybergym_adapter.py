"""CyberGym adapter — thin wrapper around the official host-installed harness."""

from __future__ import annotations

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
from bencheval.run_isolation import (
    dir_identity_error,
    open_owned_dir_fd,
    read_json_at_nofollow,
    write_text_at_exclusive,
)

CYBERGYM_ADAPTER_ID = "cybergym"
_CYBERGYM_HOME_ENV = "BENCHEVAL_CYBERGYM_HOME"


@dataclass(frozen=True, slots=True)
class CybergymCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CybergymInstanceOutcome:
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


class CybergymProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> CybergymCliResult: ...


def _cybergym_root() -> Path:
    raw = os.environ.get(_CYBERGYM_HOME_ENV)
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd()


def build_cybergym_run_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[str, ...]:
    validate_control_plane_instance_id(instance_id)
    if plan.agent_id is None and plan.runtime_id is None:
        raise BenchEvalError("cybergym requires --agent (or --runtime)")
    out_dir = artifacts_dir / "task"
    # Official entrypoint: generate/prepare one task, then agent solves + PoC submit.
    # Data/images stay on host under BENCHEVAL_CYBERGYM_HOME.
    return (
        "python",
        "-m",
        "cybergym.task.gen_task",
        "--task-id",
        instance_id,
        "--out-dir",
        str(out_dir.resolve()),
        "--agent",
        plan.agent_id or plan.runtime_id or "unknown",
        "--model",
        plan.model_id,
    )


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
) -> CybergymCliResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"cybergym harness timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"cybergym_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"cybergym harness launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"cybergym_command": " ".join(command)},
        ) from e
    return CybergymCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def _write_owned_logs(
    *,
    instance_dir: Path,
    instance_fd: int,
    cli: CybergymCliResult,
) -> tuple[Path, Path]:
    role = "cybergym instance directory"
    identity_error = dir_identity_error(instance_fd, instance_dir, role=role)
    if identity_error is not None:
        raise AdapterFailureError(
            identity_error,
            failure_label="evidence_corrupt",
            latency_sec=cli.latency_sec,
            adapter_metadata={"cybergym_command": " ".join(cli.command)},
        )
    write_text_at_exclusive(instance_fd, "stdout.log", cli.stdout)
    write_text_at_exclusive(instance_fd, "stderr.log", cli.stderr)
    identity_error = dir_identity_error(instance_fd, instance_dir, role=role)
    if identity_error is not None:
        raise AdapterFailureError(
            identity_error,
            failure_label="evidence_corrupt",
            latency_sec=cli.latency_sec,
            adapter_metadata={"cybergym_command": " ".join(cli.command)},
        )
    return instance_dir / "stdout.log", instance_dir / "stderr.log"


def run_cybergym_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: CybergymProcessRunner | None = None,
    timeout_sec: int | None = None,
) -> CybergymInstanceOutcome:
    if plan.adapter_id != CYBERGYM_ADAPTER_ID:
        raise BenchEvalError(f"cybergym adapter cannot run adapter_id={plan.adapter_id!r}")
    validate_control_plane_instance_id(instance_id)
    instance_dir = artifacts_dir / instance_id
    instance_fd = open_owned_dir_fd(instance_dir, role="cybergym instance directory")
    try:
        command = build_cybergym_run_command(
            plan=plan,
            instance_id=instance_id,
            artifacts_dir=instance_dir,
        )
        wall = (
            timeout_sec if timeout_sec is not None else max(1, plan.max_wall_clock_sec_per_instance)
        )
        root = _cybergym_root()
        has_pkg = (root / "src" / "cybergym").is_dir() or (root / "cybergym").is_dir()
        cwd = root if has_pkg else repo_root
        runner = process_runner or _default_process_runner
        cli = runner(command, cwd=cwd, timeout_sec=wall)
        stdout_file, stderr_file = _write_owned_logs(
            instance_dir=instance_dir,
            instance_fd=instance_fd,
            cli=cli,
        )
        verdict = instance_dir / "verdict.json"
        verdict_present, parsed = read_json_at_nofollow(instance_fd, verdict.name)
        # gen_task exit 0 is not official CyberGym scoring — require explicit verdict.
        primary_pass = False
        if isinstance(parsed, dict) and "primary_pass" in parsed:
            value = parsed["primary_pass"]
            # Fail closed: only an actual JSON boolean is scoring authority;
            # strings like "false" must never coerce to a pass.
            primary_pass = value if isinstance(value, bool) else False
        if cli.returncode != 0:
            failure: FailureLabel | None = "harness_failure"
        elif not verdict_present:
            failure = "runtime_output_unparseable"
        else:
            failure = None if primary_pass else "model_wrong_solution"
        outcome = CybergymInstanceOutcome(
            instance_id=instance_id,
            primary_pass=primary_pass,
            partial_score=1.0 if primary_pass else 0.0,
            cost_usd=0.0,
            latency_sec=cli.latency_sec,
            native_score={"returncode": cli.returncode, "score_source": "verdict_or_missing"},
            failure_class=failure,
            stdout_path=os.path.abspath(stdout_file),
            stderr_path=os.path.abspath(stderr_file),
            verifier_log_path=os.path.abspath(verdict) if verdict_present else None,
            adapter_metadata={
                "adapter_id": CYBERGYM_ADAPTER_ID,
                "harness_kind": "cybergym-native",
                "cybergym_command": " ".join(cli.command),
                "interpretation": "adapter_smoke",
            },
        )
        identity_error = dir_identity_error(
            instance_fd,
            instance_dir,
            role="cybergym instance directory",
        )
        if identity_error is not None:
            raise AdapterFailureError(
                identity_error,
                failure_label="evidence_corrupt",
                latency_sec=cli.latency_sec,
                adapter_metadata={"cybergym_command": " ".join(cli.command)},
            )
        return outcome
    finally:
        os.close(instance_fd)


__all__ = [
    "CYBERGYM_ADAPTER_ID",
    "CybergymCliResult",
    "CybergymInstanceOutcome",
    "CybergymProcessRunner",
    "build_cybergym_run_command",
    "run_cybergym_instance",
]
