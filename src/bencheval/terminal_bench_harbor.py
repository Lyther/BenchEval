"""Terminal-Bench 2.0 adapter via Harbor CLI (control-plane P2)."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bencheval.doctor import harbor_revision
from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id

HARBOR_DATASET = "terminal-bench@2.0"
TERMINAL_BENCH_ADAPTER_ID = "terminal-bench-harbor"

_RUNTIME_TO_HARBOR_AGENT: dict[str, str] = {
    "claude-code": "claude-code",
    "codex-cli": "codex-cli",
    "harbor-agent": "openhands",
}


@dataclass(frozen=True, slots=True)
class HarborCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerminalBenchInstanceOutcome:
    instance_id: str
    primary_pass: bool
    partial_score: float
    cost_usd: float
    latency_sec: float
    native_score: dict[str, object]
    failure_class: FailureLabel | None
    stdout_path: str | None
    stderr_path: str | None
    raw_result_path: str | None
    adapter_metadata: dict[str, str]


class HarborProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> HarborCliResult: ...


def harbor_agent_for_runtime(runtime_id: str) -> str:
    agent = _RUNTIME_TO_HARBOR_AGENT.get(runtime_id)
    if agent is None:
        raise BenchEvalError(
            f"runtime {runtime_id!r} has no Harbor --agent mapping; "
            f"known: {sorted(_RUNTIME_TO_HARBOR_AGENT)}",
        )
    return agent


def build_harbor_run_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[str, ...]:
    validate_control_plane_instance_id(instance_id)
    agent = harbor_agent_for_runtime(plan.runtime_id)
    model = plan.model_id
    cmd: list[str] = [
        "harbor",
        "run",
        "--dataset",
        HARBOR_DATASET,
        "--agent",
        agent,
        "--task",
        instance_id,
        "--output-dir",
        str(artifacts_dir.resolve()),
    ]
    if plan.model_binding == "bencheval_injected" and model != "runtime-default":
        cmd.extend(["--model", model])
    return tuple(cmd)


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
) -> HarborCliResult:
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
            f"harbor CLI timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"harbor_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"harbor CLI launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"harbor_command": " ".join(command)},
        ) from e
    return HarborCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def _write_text_artifact(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path.resolve())


def _locate_native_result(artifacts_dir: Path) -> Path | None:
    candidates = [
        artifacts_dir / "result.json",
        artifacts_dir / "results.json",
        artifacts_dir / "harbor_result.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    for path in sorted(artifacts_dir.rglob("result.json")):
        if path.is_file():
            return path
    return None


def parse_harbor_instance_outcome(
    *,
    instance_id: str,
    cli: HarborCliResult,
    artifacts_dir: Path,
    repo_root: Path,
    harness_version: str | None,
) -> TerminalBenchInstanceOutcome:
    stdout_file = artifacts_dir / "stdout.log"
    stderr_file = artifacts_dir / "stderr.log"
    stdout_rel = _write_text_artifact(stdout_file, cli.stdout)
    stderr_rel = _write_text_artifact(stderr_file, cli.stderr)

    raw_path: str | None = None
    native: dict[str, object] = {"harbor_returncode": cli.returncode}
    primary_pass = cli.returncode == 0
    partial_score = 1.0 if primary_pass else 0.0
    failure_class: FailureLabel | None = None
    cost_usd = 0.0

    result_file = _locate_native_result(artifacts_dir)
    if result_file is not None:
        raw_path = str(result_file.resolve())
        try:
            parsed = json.loads(result_file.read_text(encoding="utf-8"))
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
                elif "success" in parsed:
                    primary_pass = bool(parsed["success"])
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

    def _rel(p: str) -> str:
        try:
            return str(Path(p).resolve().relative_to(repo_root))
        except ValueError:
            return p

    metadata = {
        "adapter_id": TERMINAL_BENCH_ADAPTER_ID,
        "harbor_dataset": HARBOR_DATASET,
        "harbor_command": " ".join(cli.command),
    }
    if harness_version:
        metadata["harness_version"] = harness_version

    return TerminalBenchInstanceOutcome(
        instance_id=instance_id,
        primary_pass=primary_pass,
        partial_score=partial_score,
        cost_usd=cost_usd,
        latency_sec=cli.latency_sec,
        native_score=native,
        failure_class=failure_class,
        stdout_path=_rel(stdout_rel),
        stderr_path=_rel(stderr_rel),
        raw_result_path=_rel(raw_path) if raw_path else None,
        adapter_metadata=metadata,
    )


def run_terminal_bench_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: HarborProcessRunner | None = None,
    timeout_sec: int | None = None,
) -> TerminalBenchInstanceOutcome:
    if plan.adapter_id != TERMINAL_BENCH_ADAPTER_ID:
        raise BenchEvalError(
            f"terminal_bench_harbor adapter cannot run adapter_id={plan.adapter_id!r}",
        )
    revision = harbor_revision()
    if revision is None and process_runner is None:
        raise AdapterFailureError(
            "harbor CLI is not available",
            failure_label="runtime_launch_failure",
        )

    validate_control_plane_instance_id(instance_id)
    instance_dir = artifacts_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    command = build_harbor_run_command(
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
    start = time.monotonic()
    try:
        cli = runner(command, cwd=repo_root, timeout_sec=wall)
    except subprocess.TimeoutExpired as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"harbor CLI timed out after {wall}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"harbor_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"harbor CLI launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"harbor_command": " ".join(command)},
        ) from e
    return parse_harbor_instance_outcome(
        instance_id=instance_id,
        cli=cli,
        artifacts_dir=instance_dir,
        repo_root=repo_root,
        harness_version=revision,
    )


__all__ = [
    "HARBOR_DATASET",
    "TERMINAL_BENCH_ADAPTER_ID",
    "HarborCliResult",
    "HarborProcessRunner",
    "TerminalBenchInstanceOutcome",
    "build_harbor_run_command",
    "harbor_agent_for_runtime",
    "parse_harbor_instance_outcome",
    "run_terminal_bench_instance",
]
