"""SWE-bench Verified adapter (control-plane P4, swebench-native harness)."""

from __future__ import annotations

import json
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

SWEBENCH_ADAPTER_ID = "swebench"
_HARNESS_VERSION_FALLBACK = "swebench-native-smoke"


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
    if plan.runtime_id != "mini-swe-agent":
        raise BenchEvalError(
            f"swebench adapter expects runtime_id='mini-swe-agent', got {plan.runtime_id!r}",
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


def _write_text(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path.resolve())


def _rel_path(path: str, repo_root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(repo_root))
    except ValueError:
        return path


def parse_swebench_instance_outcome(
    *,
    instance_id: str,
    cli: SwebenchCliResult,
    artifacts_dir: Path,
    repo_root: Path,
    harness_version: str | None,
) -> SwebenchInstanceOutcome:
    stdout_file = artifacts_dir / "stdout.log"
    stderr_file = artifacts_dir / "stderr.log"
    stdout_rel = _write_text(stdout_file, cli.stdout)
    stderr_rel = _write_text(stderr_file, cli.stderr)

    verifier_path: str | None = None
    diff_path: str | None = None
    native: dict[str, object] = {"returncode": cli.returncode, "backend": INSPECT_BACKEND}
    primary_pass = cli.returncode == 0
    partial_score = 1.0 if primary_pass else 0.0
    failure_class: FailureLabel | None = None
    cost_usd = 0.0

    verifier_file = artifacts_dir / "verifier.json"
    if not verifier_file.is_file():
        verifier_file = artifacts_dir / "result.json"
    if verifier_file.is_file():
        verifier_path = str(verifier_file.resolve())
        try:
            parsed = json.loads(verifier_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failure_class = "runtime_output_unparseable"
            primary_pass = False
            partial_score = 0.0
        else:
            if isinstance(parsed, dict):
                native = {**native, **parsed}
                if "resolved" in parsed:
                    primary_pass = bool(parsed["resolved"])
                    partial_score = 1.0 if primary_pass else 0.0
                elif "tests_passed" in parsed:
                    primary_pass = bool(parsed["tests_passed"])
                    partial_score = 1.0 if primary_pass else 0.0
                if "cost_usd" in parsed and isinstance(parsed["cost_usd"], (int, float)):
                    cost_usd = float(parsed["cost_usd"])
    elif cli.returncode != 0:
        failure_class = "harness_failure"
    elif cli.returncode == 0:
        failure_class = "harness_failure"
        primary_pass = False
        partial_score = 0.0

    diff_file = artifacts_dir / "workspace.diff"
    if diff_file.is_file():
        diff_path = str(diff_file.resolve())

    if not primary_pass and failure_class is None:
        failure_class = "model_wrong_solution"

    metadata = {
        "adapter_id": SWEBENCH_ADAPTER_ID,
        "harness_kind": "swebench-native",
        "swebench_command": " ".join(cli.command),
        "harness_version": harness_version or _HARNESS_VERSION_FALLBACK,
    }

    return SwebenchInstanceOutcome(
        instance_id=instance_id,
        primary_pass=primary_pass,
        partial_score=partial_score,
        cost_usd=cost_usd,
        latency_sec=cli.latency_sec,
        native_score=native,
        failure_class=failure_class,
        stdout_path=_rel_path(stdout_rel, repo_root),
        stderr_path=_rel_path(stderr_rel, repo_root),
        verifier_log_path=_rel_path(verifier_path, repo_root) if verifier_path else None,
        workspace_diff_path=_rel_path(diff_path, repo_root) if diff_path else None,
        adapter_metadata=metadata,
    )


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
    instance_dir = artifacts_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    command = build_swebench_run_command(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=instance_dir,
    )
    if timeout_sec is not None:
        wall = timeout_sec
    else:
        n = max(len(plan.instances), 1)
        wall = max(plan.max_wall_clock_sec // n, 60)
    runner = process_runner or _default_process_runner
    cli = runner(command, cwd=repo_root, timeout_sec=wall)
    return parse_swebench_instance_outcome(
        instance_id=instance_id,
        cli=cli,
        artifacts_dir=instance_dir,
        repo_root=repo_root,
        harness_version=harness_version,
    )


__all__ = [
    "SWEBENCH_ADAPTER_ID",
    "SwebenchCliResult",
    "SwebenchInstanceOutcome",
    "SwebenchProcessRunner",
    "build_swebench_run_command",
    "parse_swebench_instance_outcome",
    "run_swebench_instance",
]
