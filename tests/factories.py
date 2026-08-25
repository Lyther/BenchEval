"""Shared test factories for control-plane evidence rows and crafted plans."""

from datetime import UTC, datetime
from typing import Literal

from bencheval.benchmark_plan import plan_control_plane
from bencheval.domain import RunPlan
from bencheval.evidence import EvidenceRecord
from bencheval.lifecycle import CleanupPolicy

_CP_TS = datetime(2026, 6, 1, tzinfo=UTC)


def make_control_plane_evidence_record(
    *,
    instance_id: str,
    model_id: str = "runtime-default",
    runtime_id: str = "claude-code",
    primary_pass: bool = True,
    attempt_validity: Literal["valid", "invalid"] | None = None,
    counts_toward_pass_at_k: bool | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"run-{runtime_id}-{model_id}-{instance_id}",
        task_id=instance_id,
        model_id=model_id,
        execution_profile="E1",
        backend="harbor",
        primary_pass=primary_pass,
        partial_score=1.0 if primary_pass else 0.0,
        cost_usd=0.1,
        latency_sec=10.0,
        created_at=_CP_TS,
        benchmark_id="terminal-bench",
        benchmark_version="terminal-bench@2.1",
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@1",
        runtime_id=runtime_id,
        runtime_kind="cli_agent",
        runtime_version=f"{runtime_id}@1",
        runtime_config_hash=f"sha256:{runtime_id}",
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm-test",
        instance_id=instance_id,
        interpretation_label="runtime_comparison",
        attempt_validity=attempt_validity,
        counts_toward_pass_at_k=counts_toward_pass_at_k,
    )


def make_scaffold_agent_plan(
    *,
    benchmark_id: str = "terminal-bench",
    slice_id: str = "smoke-5",
    model_id: str = "kimi-k2.7-code",
    cleanup_policy: CleanupPolicy = "always",
) -> RunPlan:
    """Craft a MOMO plan without using the product planner.

    The planner rejects scaffold agents. Retained adapter tests still need a
    typed plan that looks like the old admitted path.
    """
    plan = plan_control_plane(
        benchmark_id=benchmark_id,
        slice_id=slice_id,
        runtime_id="claude-code",
        model_id=model_id,
        cleanup_policy=cleanup_policy,
    )
    return plan.model_copy(
        update={
            "runtime_id": None,
            "runtime_kind": None,
            "agent_id": "momo",
            "model_binding": "bencheval_injected",
            "network_policy": "benchmark_required",
        },
    )
