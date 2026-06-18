"""BFCL v4 model-only adapter (control-plane P5.1, bfcl-native harness)."""

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

BFCL_ADAPTER_ID = "bfcl"
_HARNESS_VERSION_FALLBACK = "bfcl-native-smoke"


@dataclass(frozen=True, slots=True)
class BfclCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BfclInstanceOutcome:
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


class BfclProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> BfclCliResult: ...


def build_bfcl_run_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[str, ...]:
    validate_control_plane_instance_id(instance_id)
    if plan.runtime_id not in ("native-api", "inspect-api"):
        raise BenchEvalError(
            f"bfcl adapter expects runtime native-api or inspect-api, got {plan.runtime_id!r}",
        )
    cmd: list[str] = [
        "bfcl-eval",
        "run",
        "--instance-id",
        instance_id,
        "--output-dir",
        str(artifacts_dir.resolve()),
    ]
    if plan.model_id != "runtime-default":
        cmd.extend(["--model", plan.model_id])
    return tuple(cmd)


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
) -> BfclCliResult:
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
            f"bfcl harness timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"bfcl_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"bfcl harness launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"bfcl_command": " ".join(command)},
        ) from e
    return BfclCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def _rel_path(path: str, repo_root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(repo_root))
    except ValueError:
        return path


def parse_bfcl_instance_outcome(
    *,
    instance_id: str,
    cli: BfclCliResult,
    artifacts_dir: Path,
    repo_root: Path,
    harness_version: str | None,
) -> BfclInstanceOutcome:
    stdout_file = artifacts_dir / "stdout.log"
    stderr_file = artifacts_dir / "stderr.log"
    stdout_file.parent.mkdir(parents=True, exist_ok=True)
    stdout_file.write_text(cli.stdout, encoding="utf-8")
    stderr_file.write_text(cli.stderr, encoding="utf-8")
    stdout_rel = str(stdout_file.resolve())
    stderr_rel = str(stderr_file.resolve())

    verifier_path: str | None = None
    native: dict[str, object] = {"returncode": cli.returncode, "backend": INSPECT_BACKEND}
    primary_pass = cli.returncode == 0
    partial_score = 1.0 if primary_pass else 0.0
    failure_class: FailureLabel | None = None
    cost_usd = 0.0

    verdict_file = artifacts_dir / "verdict.json"
    if not verdict_file.is_file():
        verdict_file = artifacts_dir / "result.json"
    if verdict_file.is_file():
        verifier_path = str(verdict_file.resolve())
        try:
            parsed = json.loads(verdict_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failure_class = "runtime_output_unparseable"
            primary_pass = False
            partial_score = 0.0
        else:
            if isinstance(parsed, dict):
                native = {**native, **parsed}
                if "primary_pass" in parsed:
                    primary_pass = bool(parsed["primary_pass"])
                elif "correct" in parsed:
                    primary_pass = bool(parsed["correct"])
                elif "resolved" in parsed:
                    primary_pass = bool(parsed["resolved"])
                partial_score = 1.0 if primary_pass else 0.0
                if "cost_usd" in parsed and isinstance(parsed["cost_usd"], (int, float)):
                    cost_usd = float(parsed["cost_usd"])
    elif cli.returncode != 0:
        failure_class = "harness_failure"
    elif cli.returncode == 0:
        failure_class = "harness_failure"
        primary_pass = False
        partial_score = 0.0

    if not primary_pass and failure_class is None:
        failure_class = "model_wrong_solution"

    metadata = {
        "adapter_id": BFCL_ADAPTER_ID,
        "harness_kind": "bfcl-native",
        "bfcl_command": " ".join(cli.command),
        "harness_version": harness_version or _HARNESS_VERSION_FALLBACK,
    }

    return BfclInstanceOutcome(
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
        adapter_metadata=metadata,
    )


def run_bfcl_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: BfclProcessRunner | None = None,
    timeout_sec: int | None = None,
    harness_version: str | None = None,
) -> BfclInstanceOutcome:
    if plan.adapter_id != BFCL_ADAPTER_ID:
        raise BenchEvalError(f"bfcl adapter cannot run adapter_id={plan.adapter_id!r}")
    validate_control_plane_instance_id(instance_id)
    instance_dir = artifacts_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    command = build_bfcl_run_command(
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
    return parse_bfcl_instance_outcome(
        instance_id=instance_id,
        cli=cli,
        artifacts_dir=instance_dir,
        repo_root=repo_root,
        harness_version=harness_version,
    )


__all__ = [
    "BFCL_ADAPTER_ID",
    "BfclCliResult",
    "BfclInstanceOutcome",
    "BfclProcessRunner",
    "build_bfcl_run_command",
    "parse_bfcl_instance_outcome",
    "run_bfcl_instance",
]
