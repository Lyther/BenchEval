"""External agent adapter — invoke agent CLI from ``config/agents/*.yaml``."""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

from bencheval.agent_registry import load_agent_catalog
from bencheval.backends import LOCAL_BACKEND
from bencheval.domain import ExecutionProfile, FailureLabel, RunPlan
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.ids import new_run_id
from bencheval.paths import repo_root as _repo_root

ExternalAgentProcessRunner = Callable[..., "ExternalAgentCliResult"]
_FAILURE_LABELS = frozenset(get_args(FailureLabel))


@dataclass(frozen=True, slots=True)
class ExternalAgentCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExternalAgentInstanceOutcome:
    instance_id: str
    primary_pass: bool
    partial_score: float
    cost_usd: float
    latency_sec: float
    failure_class: FailureLabel | None
    stdout_path: str | None
    stderr_path: str | None
    adapter_metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class ExternalAgentRunSummary:
    run_id: str
    instance_count: int
    passed_count: int
    failed_count: int
    output_path: Path


def adapter_id_for_agent(agent_id: str) -> str:
    return f"{agent_id}-agent"


def build_external_agent_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[str, ...]:
    if not plan.agent_id:
        raise BenchEvalError("external agent adapter requires plan.agent_id")
    profile = load_agent_catalog().by_id(plan.agent_id)
    cmd = list(profile.agent.command)
    cmd.extend(
        [
            "run",
            "--benchmark",
            plan.benchmark_id,
            "--instance",
            instance_id,
            "--model",
            plan.model_id,
            "--provider",
            plan.provider_id,
            "--output-dir",
            str(artifacts_dir.resolve()),
        ],
    )
    return tuple(cmd)


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
) -> ExternalAgentCliResult:
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
            f"agent timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"agent_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"agent launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"agent_command": " ".join(command)},
        ) from e
    return ExternalAgentCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def run_external_agent_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: ExternalAgentProcessRunner | None = None,
    timeout_sec: int = 300,
) -> ExternalAgentInstanceOutcome:
    instance_dir = artifacts_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    command = build_external_agent_command(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=instance_dir,
    )
    runner = process_runner or _default_process_runner
    cli = runner(command, cwd=repo_root, timeout_sec=timeout_sec)
    stdout_path = instance_dir / "stdout.log"
    stderr_path = instance_dir / "stderr.log"
    stdout_path.write_text(cli.stdout, encoding="utf-8")
    stderr_path.write_text(cli.stderr, encoding="utf-8")
    primary_pass = cli.returncode == 0
    failure: FailureLabel | None = None if primary_pass else "runtime_tool_failure"
    return ExternalAgentInstanceOutcome(
        instance_id=instance_id,
        primary_pass=primary_pass,
        partial_score=1.0 if primary_pass else 0.0,
        cost_usd=0.0,
        latency_sec=cli.latency_sec,
        failure_class=failure,
        stdout_path=str(stdout_path.resolve()),
        stderr_path=str(stderr_path.resolve()),
        adapter_metadata={
            "agent_id": plan.agent_id or "",
            "agent_command": " ".join(cli.command),
            "returncode": str(cli.returncode),
        },
    )


def execute_external_agent_run(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None = None,
    process_runner: ExternalAgentProcessRunner | None = None,
    run_id: str | None = None,
) -> ExternalAgentRunSummary:
    if not plan.agent_id:
        raise BenchEvalError("external agent run requires plan.agent_id")
    root = _repo_root()
    rid = run_id or new_run_id()
    run_artifacts = artifacts_dir or (root / "results" / "raw" / rid)
    run_artifacts.mkdir(parents=True, exist_ok=True)
    sink = JsonlEvidenceSink()
    profile: ExecutionProfile = "E1"
    adapter_id = adapter_id_for_agent(plan.agent_id)
    passed = 0
    for inst in plan.instances:
        try:
            outcome = run_external_agent_instance(
                plan=plan,
                instance_id=inst.instance_id,
                artifacts_dir=run_artifacts,
                repo_root=root,
                process_runner=process_runner,
            )
            artifact_paths = [p for p in (outcome.stdout_path, outcome.stderr_path) if p]
            failure_labels = [outcome.failure_class] if outcome.failure_class else []
            record = EvidenceRecord(
                run_id=rid,
                task_id=outcome.instance_id,
                model_id=plan.model_id,
                execution_profile=profile,
                backend=LOCAL_BACKEND,
                primary_pass=outcome.primary_pass,
                partial_score=outcome.partial_score,
                cost_usd=outcome.cost_usd,
                latency_sec=outcome.latency_sec,
                failure_labels=list(failure_labels),
                artifact_paths=artifact_paths,
                adapter_metadata=outcome.adapter_metadata,
                created_at=datetime.now(tz=UTC),
                benchmark_id=plan.benchmark_id,
                slice_id=plan.slice_id,
                adapter_id=adapter_id,
                harness_kind=plan.harness_kind,
                runtime_id=None,
                runtime_kind=None,
                agent_id=plan.agent_id,
                provider_id=plan.provider_id,
                instance_id=outcome.instance_id,
                failure_class=outcome.failure_class,
            )
        except AdapterFailureError as e:
            instance_dir = run_artifacts / inst.instance_id
            instance_dir.mkdir(parents=True, exist_ok=True)
            failure_log = instance_dir / "adapter_failure.json"
            failure_log.write_text(
                json.dumps(
                    {
                        "instance_id": inst.instance_id,
                        "failure_label": e.failure_label,
                        "message": str(e),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            failure_class = cast(
                FailureLabel,
                e.failure_label if e.failure_label in _FAILURE_LABELS else "adapter_error",
            )
            metadata = dict(e.adapter_metadata)
            metadata.setdefault("adapter_id", adapter_id)
            metadata.setdefault("agent_id", plan.agent_id or "")
            record = EvidenceRecord(
                run_id=rid,
                task_id=inst.instance_id,
                model_id=plan.model_id,
                execution_profile=profile,
                backend=LOCAL_BACKEND,
                primary_pass=False,
                partial_score=0.0,
                cost_usd=e.cost_usd,
                latency_sec=e.latency_sec,
                failure_labels=[failure_class],
                artifact_paths=[str(failure_log.resolve())],
                adapter_metadata=metadata,
                created_at=datetime.now(tz=UTC),
                benchmark_id=plan.benchmark_id,
                slice_id=plan.slice_id,
                adapter_id=adapter_id,
                harness_kind=plan.harness_kind,
                runtime_id=None,
                runtime_kind=None,
                agent_id=plan.agent_id,
                provider_id=plan.provider_id,
                instance_id=inst.instance_id,
                failure_class=failure_class,
            )
        if record.primary_pass:
            passed += 1
        sink.append_jsonl(output_path, record)
    total = len(plan.instances)
    return ExternalAgentRunSummary(
        run_id=rid,
        instance_count=total,
        passed_count=passed,
        failed_count=total - passed,
        output_path=output_path.resolve(),
    )


# MOMO naming lives in momo_agent_adapter.py (compat module).

__all__ = [
    "ExternalAgentCliResult",
    "ExternalAgentInstanceOutcome",
    "ExternalAgentProcessRunner",
    "ExternalAgentRunSummary",
    "adapter_id_for_agent",
    "build_external_agent_command",
    "execute_external_agent_run",
    "run_external_agent_instance",
]
