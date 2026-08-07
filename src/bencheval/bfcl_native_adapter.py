"""BFCL v4 model-only adapter (generation smoke via ``bfcl generate``).

Official native scoring requires ``bfcl evaluate`` and is not wired yet.
Evidence interpretation for the admitted smoke slice is ``adapter_smoke``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Protocol

from bencheval.backends import INSPECT_BACKEND
from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id

BFCL_ADAPTER_ID = "bfcl"
BFCL_COMMAND = "bfcl"
_BFCL_DIST_CANDIDATES = ("bfcl-eval", "bfcl")
_VERSION_TIMEOUT_SEC = 15


def _as_bool_verdict(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def bfcl_harness_version() -> str | None:
    """Capture installed BFCL CLI/package revision; None when capture fails."""
    if shutil.which(BFCL_COMMAND) is not None:
        try:
            proc = subprocess.run(
                [BFCL_COMMAND, "version"],
                capture_output=True,
                text=True,
                check=False,
                timeout=_VERSION_TIMEOUT_SEC,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0:
            line = (proc.stdout or proc.stderr).strip().splitlines()
            if line and line[0].strip():
                return line[0].strip()
    for dist in _BFCL_DIST_CANDIDATES:
        try:
            return f"{dist}@{distribution_version(dist)}"
        except PackageNotFoundError:
            continue
    return None


def bfcl_benchmark_version() -> str | None:
    """BFCL dataset/category revision — not capturable from package version alone.

    Package/CLI output belongs in ``harness_version``. Until an upstream git
    commit plus dataset/category-map revision is captured, return None so the
    planner's provisional benchmark label is retained.
    """
    return None


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
    if plan.runtime_id is not None:
        raise BenchEvalError(
            f"bfcl adapter expects model-only (runtime_id=None), got {plan.runtime_id!r}",
        )
    if plan.agent_id is not None:
        raise BenchEvalError(
            f"bfcl adapter expects model-only (agent_id=None), got {plan.agent_id!r}",
        )
    cmd: list[str] = [
        BFCL_COMMAND,
        "generate",
        "--test-category",
        instance_id,
        "--result-dir",
        str(artifacts_dir.resolve()),
        "--allow-overwrite",
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
                verdict: bool | None = None
                if "primary_pass" in parsed:
                    verdict = _as_bool_verdict(parsed["primary_pass"])
                elif "correct" in parsed:
                    verdict = _as_bool_verdict(parsed["correct"])
                elif "resolved" in parsed:
                    verdict = _as_bool_verdict(parsed["resolved"])
                if "primary_pass" in parsed or "correct" in parsed or "resolved" in parsed:
                    if verdict is None:
                        failure_class = "runtime_output_unparseable"
                        primary_pass = False
                        partial_score = 0.0
                    else:
                        primary_pass = verdict
                        partial_score = 1.0 if primary_pass else 0.0
                else:
                    # Result file present without an explicit bool verdict → fail closed.
                    failure_class = "runtime_output_unparseable"
                    primary_pass = False
                    partial_score = 0.0
                if "cost_usd" in parsed and isinstance(parsed["cost_usd"], (int, float)):
                    cost_usd = float(parsed["cost_usd"])
            else:
                failure_class = "runtime_output_unparseable"
                primary_pass = False
                partial_score = 0.0
    elif cli.returncode != 0:
        failure_class = "harness_failure"
    elif cli.returncode == 0:
        failure_class = "harness_failure"
        primary_pass = False
        partial_score = 0.0

    if cli.returncode != 0:
        primary_pass = False
        partial_score = 0.0
        if failure_class is None:
            failure_class = "harness_failure"

    if not primary_pass and failure_class is None:
        failure_class = "model_wrong_solution"

    metadata = {
        "adapter_id": BFCL_ADAPTER_ID,
        "harness_kind": "bfcl-native",
        "bfcl_command": " ".join(cli.command),
    }
    if harness_version:
        metadata["harness_version"] = harness_version

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
    from bencheval.run_isolation import prepare_instance_artifacts_dir

    instance_dir = prepare_instance_artifacts_dir(artifacts_dir / instance_id)
    command = build_bfcl_run_command(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=instance_dir,
    )
    if timeout_sec is not None:
        wall = timeout_sec
    else:
        n = max(len(plan.instances), 1)
        wall = max(1, plan.max_wall_clock_sec // n)
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
    "BFCL_COMMAND",
    "BfclCliResult",
    "BfclInstanceOutcome",
    "BfclProcessRunner",
    "bfcl_benchmark_version",
    "bfcl_harness_version",
    "build_bfcl_run_command",
    "parse_bfcl_instance_outcome",
    "run_bfcl_instance",
]
