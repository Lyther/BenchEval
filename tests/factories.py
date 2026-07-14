"""Shared test factories for control-plane evidence rows."""

from datetime import UTC, datetime
from typing import Literal

from bencheval.evidence import EvidenceRecord

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
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@1",
        runtime_id=runtime_id,
        runtime_kind="cli_agent",
        instance_id=instance_id,
        attempt_validity=attempt_validity,
        counts_toward_pass_at_k=counts_toward_pass_at_k,
    )
