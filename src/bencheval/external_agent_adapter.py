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
from bencheval.domain import CleanupResult, ExecutionProfile, FailureLabel, RunPlan
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.ids import new_run_id
from bencheval.lifecycle import cleanup_transient_artifacts
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.paths import repo_root as _repo_root
from bencheval.provider_registry import resolve_openai_compatible_launch

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
    timeout_sec: int | None = None,
) -> ExternalAgentInstanceOutcome:
    validate_control_plane_instance_id(instance_id)
    instance_dir = artifacts_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    command = build_external_agent_command(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=instance_dir,
    )
    runner = process_runner or _default_process_runner
    wall = timeout_sec if timeout_sec is not None else max(1, plan.max_wall_clock_sec)
    cli = runner(command, cwd=repo_root, timeout_sec=wall)
    stdout_path = instance_dir / "stdout.log"
    stderr_path = instance_dir / "stderr.log"
    stdout_path.write_text(cli.stdout, encoding="utf-8")
    stderr_path.write_text(cli.stderr, encoding="utf-8")

    # Exit 0 means the agent command completed — not a benchmark pass.
    # Anything under --output-dir is agent-writable and cannot be scoring
    # authority; official verifier wiring remains pending.
    primary_pass = False
    partial_score = 0.0
    failure: FailureLabel | None = None
    metadata: dict[str, str] = {
        "agent_id": plan.agent_id or "",
        "agent_command": " ".join(cli.command),
        "returncode": str(cli.returncode),
    }

    if cli.returncode != 0:
        failure = "runtime_tool_failure"
    else:
        failure = "harness_failure"
        metadata["scoring"] = "missing_verifier_artifact"

    return ExternalAgentInstanceOutcome(
        instance_id=instance_id,
        primary_pass=primary_pass,
        partial_score=partial_score,
        cost_usd=0.0,
        latency_sec=cli.latency_sec,
        failure_class=failure,
        stdout_path=str(stdout_path.resolve()),
        stderr_path=str(stderr_path.resolve()),
        adapter_metadata=metadata,
    )


def _agent_cleanup_result(
    *,
    plan: RunPlan,
    instance_artifacts: Path,
    primary_pass: bool,
) -> CleanupResult:
    report = cleanup_transient_artifacts(
        instance_artifacts,
        policy=plan.cleanup_policy,
        primary_pass=primary_pass,
    )
    if not report.attempted:
        return "skipped"
    return "success" if report.removed_paths else "skipped"


def _agent_budget_skip_record(
    *,
    plan: RunPlan,
    run_id: str,
    instance_id: str,
    profile: ExecutionProfile,
    adapter_id: str,
    provider_config_hash: str,
    spent_cost_usd: float,
    spent_wall_sec: float,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=run_id,
        task_id=instance_id,
        model_id=plan.model_id,
        execution_profile=profile,
        backend=LOCAL_BACKEND,
        primary_pass=False,
        partial_score=0.0,
        cost_usd=0.0,
        latency_sec=0.0,
        failure_labels=["runtime_budget_exceeded"],
        artifact_paths=[],
        adapter_metadata={
            "adapter_id": adapter_id,
            "agent_id": plan.agent_id or "",
            "spent_cost_usd": f"{spent_cost_usd:.6f}",
            "spent_wall_sec": f"{spent_wall_sec:.3f}",
        },
        created_at=datetime.now(tz=UTC),
        benchmark_id=plan.benchmark_id,
        benchmark_version=plan.benchmark_version,
        slice_id=plan.slice_id,
        adapter_id=adapter_id,
        harness_kind=plan.harness_kind,
        runtime_id=None,
        runtime_kind=None,
        agent_id=plan.agent_id,
        provider_id=plan.provider_id,
        provider_config_hash=provider_config_hash,
        judge_model_id=plan.judge_model_id,
        instance_id=instance_id,
        failure_class="runtime_budget_exceeded",
        cleanup_result="skipped",
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
    from bencheval.run_isolation import claim_exclusive_run_outputs

    root = _repo_root()
    rid = run_id or new_run_id()
    run_artifacts = artifacts_dir or (root / "results" / "raw" / rid)
    claim_exclusive_run_outputs(evidence_path=output_path, artifacts_path=run_artifacts)
    sink = JsonlEvidenceSink()
    profile: ExecutionProfile = "E1"
    provider_config_hash = resolve_openai_compatible_launch(
        plan.provider_id,
        require_api_key=False,
    ).config_hash
    # Keep benchmark adapter identity; agent_id is a separate scaffold axis.
    adapter_id = plan.adapter_id
    passed = 0
    spent_cost_usd = 0.0
    spent_wall_sec = 0.0
    for inst in plan.instances:
        instance_id = inst.instance_id
        cost_hit = plan.max_cost_usd > 0 and spent_cost_usd >= plan.max_cost_usd
        wall_hit = plan.max_wall_clock_sec > 0 and spent_wall_sec >= plan.max_wall_clock_sec
        if cost_hit or wall_hit:
            record = _agent_budget_skip_record(
                plan=plan,
                run_id=rid,
                instance_id=instance_id,
                profile=profile,
                adapter_id=adapter_id,
                provider_config_hash=provider_config_hash,
                spent_cost_usd=spent_cost_usd,
                spent_wall_sec=spent_wall_sec,
            )
            sink.append_jsonl(output_path, record)
            continue
        try:
            remaining = max(1, int(plan.max_wall_clock_sec - spent_wall_sec))
            outcome = run_external_agent_instance(
                plan=plan,
                instance_id=instance_id,
                artifacts_dir=run_artifacts,
                repo_root=root,
                process_runner=process_runner,
                timeout_sec=remaining,
            )
            cleanup_result = _agent_cleanup_result(
                plan=plan,
                instance_artifacts=run_artifacts / instance_id,
                primary_pass=outcome.primary_pass,
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
                benchmark_version=plan.benchmark_version,
                slice_id=plan.slice_id,
                adapter_id=adapter_id,
                harness_kind=plan.harness_kind,
                runtime_id=None,
                runtime_kind=None,
                agent_id=plan.agent_id,
                provider_id=plan.provider_id,
                provider_config_hash=provider_config_hash,
                judge_model_id=plan.judge_model_id,
                instance_id=outcome.instance_id,
                failure_class=outcome.failure_class,
                cleanup_result=cleanup_result,
            )
        except AdapterFailureError as e:
            instance_dir = run_artifacts / instance_id
            instance_dir.mkdir(parents=True, exist_ok=True)
            failure_log = instance_dir / "adapter_failure.json"
            failure_log.write_text(
                json.dumps(
                    {
                        "instance_id": instance_id,
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
            cleanup_result = _agent_cleanup_result(
                plan=plan,
                instance_artifacts=instance_dir,
                primary_pass=False,
            )
            record = EvidenceRecord(
                run_id=rid,
                task_id=instance_id,
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
                benchmark_version=plan.benchmark_version,
                slice_id=plan.slice_id,
                adapter_id=adapter_id,
                harness_kind=plan.harness_kind,
                runtime_id=None,
                runtime_kind=None,
                agent_id=plan.agent_id,
                provider_id=plan.provider_id,
                provider_config_hash=provider_config_hash,
                judge_model_id=plan.judge_model_id,
                instance_id=instance_id,
                failure_class=failure_class,
                cleanup_result=cleanup_result,
            )
        spent_cost_usd += record.cost_usd
        spent_wall_sec += record.latency_sec
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
