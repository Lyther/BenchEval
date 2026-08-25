"""SWE-bench Verified adapter (control-plane P4, swebench-native harness)."""

from __future__ import annotations

import os
import stat
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bencheval.backends import INSPECT_BACKEND
from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.run_isolation import (
    AUTHORITATIVE_ARTIFACT_NAMES,
    dir_identity_error,
    open_owned_dir_fd,
    prepare_instance_artifacts_dir,
    read_json_at_nofollow,
    write_text_at_exclusive,
)

SWEBENCH_ADAPTER_ID = "swebench"
_INSTANCE_DIR_ROLE = "swebench instance directory"
_OFFICIAL_REPORT_NAME = "report.json"
_WORKSPACE_DIFF_NAME = "workspace.diff"


def _as_bool_verdict(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class SwebenchCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SwebenchInstanceOutcome:
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
    workspace_diff_path: str | None
    adapter_metadata: dict[str, str]


class SwebenchProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> SwebenchCliResult: ...


def build_swebench_run_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[str, ...]:
    """Command shape for ``mini-extra swebench`` (mini-SWE-agent SWE-bench helper)."""
    validate_control_plane_instance_id(instance_id)
    admitted = ("claude-code", "codex-cli")
    if plan.runtime_id not in admitted:
        raise BenchEvalError(
            f"swebench adapter expects runtime_id in {admitted}, got {plan.runtime_id!r}",
        )
    cmd: list[str] = [
        "mini-extra",
        "swebench",
        "--instance",
        instance_id,
        "--output-dir",
        str(artifacts_dir.resolve()),
    ]
    if plan.model_binding == "bencheval_injected" and plan.model_id != "runtime-default":
        cmd.extend(["--model", plan.model_id])
    return tuple(cmd)


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
) -> SwebenchCliResult:
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
            f"swebench harness timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"swebench_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"swebench harness launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"swebench_command": " ".join(command)},
        ) from e
    return SwebenchCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def _rel_path(path: str, repo_root: Path) -> str:
    absolute = Path(os.path.abspath(path))
    root = Path(os.path.abspath(repo_root))
    try:
        return str(absolute.relative_to(root))
    except ValueError:
        return str(absolute)


def _reject_instance_swap(
    *,
    instance_dir: Path,
    instance_fd: int,
    cli: SwebenchCliResult,
) -> None:
    identity_error = dir_identity_error(instance_fd, instance_dir, role=_INSTANCE_DIR_ROLE)
    if identity_error is not None:
        raise AdapterFailureError(
            identity_error,
            failure_label="evidence_corrupt",
            latency_sec=cli.latency_sec,
            adapter_metadata={"swebench_command": " ".join(cli.command)},
        )


def _write_owned_logs(
    *,
    instance_dir: Path,
    instance_fd: int,
    cli: SwebenchCliResult,
) -> tuple[str, str]:
    _reject_instance_swap(instance_dir=instance_dir, instance_fd=instance_fd, cli=cli)
    write_text_at_exclusive(instance_fd, "stdout.log", cli.stdout)
    write_text_at_exclusive(instance_fd, "stderr.log", cli.stderr)
    _reject_instance_swap(instance_dir=instance_dir, instance_fd=instance_fd, cli=cli)
    return str((instance_dir / "stdout.log").resolve()), str(
        (instance_dir / "stderr.log").resolve(),
    )


def _read_official_report_json(instance_fd: int) -> dict[str, object] | None:
    _, parsed = read_json_at_nofollow(instance_fd, _OFFICIAL_REPORT_NAME)
    return parsed if isinstance(parsed, dict) else None


def _owned_regular_file_path(
    instance_fd: int,
    name: str,
    artifacts_dir: Path,
) -> str | None:
    try:
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=instance_fd)
    except OSError:
        return None
    try:
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode):
            return None
    finally:
        os.close(file_fd)
    return os.path.abspath(artifacts_dir / name)


def _official_instance_report(
    instance_fd: int,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[bool, dict[str, object], str] | None:
    parsed = _read_official_report_json(instance_fd)
    if parsed is None or instance_id not in parsed:
        return None
    instance = parsed[instance_id]
    if not isinstance(instance, dict):
        return None
    resolved = _as_bool_verdict(instance.get("resolved"))
    if resolved is None:
        return None
    return resolved, instance, os.path.abspath(artifacts_dir / _OFFICIAL_REPORT_NAME)


def _score_from_official(
    *,
    cli: SwebenchCliResult,
    official: tuple[bool, dict[str, object], str] | None,
) -> tuple[bool, float, FailureLabel | None, dict[str, object], str | None, float]:
    native: dict[str, object] = {"returncode": cli.returncode, "backend": INSPECT_BACKEND}
    if official is None:
        failure: FailureLabel = (
            "harness_failure" if cli.returncode != 0 else "runtime_output_unparseable"
        )
        return False, 0.0, failure, native, None, 0.0
    resolved, instance, verifier_path = official
    native = {**native, **instance}
    cost = instance.get("cost_usd")
    cost_usd = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else 0.0
    if cli.returncode != 0:
        return False, 0.0, "harness_failure", native, verifier_path, cost_usd
    if resolved:
        return True, 1.0, None, native, verifier_path, cost_usd
    return False, 0.0, "model_wrong_solution", native, verifier_path, cost_usd


def parse_swebench_instance_outcome(
    *,
    instance_id: str,
    cli: SwebenchCliResult,
    artifacts_dir: Path,
    repo_root: Path,
    harness_version: str | None,
    artifacts_fd: int | None = None,
) -> SwebenchInstanceOutcome:
    owned_fd = artifacts_fd is None
    instance_fd = artifacts_fd
    if instance_fd is None:
        instance_fd = open_owned_dir_fd(artifacts_dir, role=_INSTANCE_DIR_ROLE)
    try:
        stdout_abs, stderr_abs = _write_owned_logs(
            instance_dir=artifacts_dir,
            instance_fd=instance_fd,
            cli=cli,
        )
        official = _official_instance_report(instance_fd, instance_id, artifacts_dir)
        _reject_instance_swap(instance_dir=artifacts_dir, instance_fd=instance_fd, cli=cli)
        diff_path = _owned_regular_file_path(
            instance_fd,
            _WORKSPACE_DIFF_NAME,
            artifacts_dir,
        )
        _reject_instance_swap(instance_dir=artifacts_dir, instance_fd=instance_fd, cli=cli)
        primary_pass, partial_score, failure_class, native, verifier_path, cost_usd = (
            _score_from_official(cli=cli, official=official)
        )
        metadata = {
            "adapter_id": SWEBENCH_ADAPTER_ID,
            "harness_kind": "swebench-native",
            "swebench_command": " ".join(cli.command),
        }
        if harness_version:
            metadata["harness_version"] = harness_version
        outcome = SwebenchInstanceOutcome(
            instance_id=instance_id,
            primary_pass=primary_pass,
            partial_score=partial_score,
            cost_usd=cost_usd,
            latency_sec=cli.latency_sec,
            native_score=native,
            failure_class=failure_class,
            stdout_path=_rel_path(stdout_abs, repo_root),
            stderr_path=_rel_path(stderr_abs, repo_root),
            verifier_log_path=_rel_path(verifier_path, repo_root) if verifier_path else None,
            workspace_diff_path=_rel_path(diff_path, repo_root) if diff_path else None,
            adapter_metadata=metadata,
        )
        _reject_instance_swap(instance_dir=artifacts_dir, instance_fd=instance_fd, cli=cli)
        return outcome
    finally:
        if owned_fd:
            os.close(instance_fd)


def run_swebench_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: SwebenchProcessRunner | None = None,
    timeout_sec: int | None = None,
    harness_version: str | None = None,
) -> SwebenchInstanceOutcome:
    if plan.adapter_id != SWEBENCH_ADAPTER_ID:
        raise BenchEvalError(f"swebench adapter cannot run adapter_id={plan.adapter_id!r}")
    validate_control_plane_instance_id(instance_id)
    instance_dir = prepare_instance_artifacts_dir(
        artifacts_dir / instance_id,
        clear_names=AUTHORITATIVE_ARTIFACT_NAMES
        | frozenset({_OFFICIAL_REPORT_NAME, _WORKSPACE_DIFF_NAME}),
    )
    instance_fd = open_owned_dir_fd(instance_dir, role=_INSTANCE_DIR_ROLE)
    try:
        command = build_swebench_run_command(
            plan=plan,
            instance_id=instance_id,
            artifacts_dir=instance_dir,
        )
        wall = (
            timeout_sec if timeout_sec is not None else max(1, plan.max_wall_clock_sec_per_instance)
        )
        runner = process_runner or _default_process_runner
        cli = runner(command, cwd=repo_root, timeout_sec=wall)
        return parse_swebench_instance_outcome(
            instance_id=instance_id,
            cli=cli,
            artifacts_dir=instance_dir,
            repo_root=repo_root,
            harness_version=harness_version,
            artifacts_fd=instance_fd,
        )
    finally:
        os.close(instance_fd)


__all__ = [
    "SWEBENCH_ADAPTER_ID",
    "SwebenchCliResult",
    "SwebenchInstanceOutcome",
    "SwebenchProcessRunner",
    "build_swebench_run_command",
    "parse_swebench_instance_outcome",
    "run_swebench_instance",
]
