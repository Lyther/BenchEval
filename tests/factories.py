"""Shared test factories (single source for SummaryRow defaults)."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from bencheval.evidence import EvidenceRecord
from bencheval.models import ModelFamily, SummaryRow

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


def make_summary_row(**overrides: object) -> SummaryRow:
    base: dict[str, object] = {
        "timestamp": datetime.now(tz=UTC),
        "benchmark": "swebench-verified",
        "benchmark_revision": "inspect-evals==0.8.0",
        "task_manifest_hash": "a" * 64,
        "model": "anthropic/claude-sonnet-4-5",
        "model_snapshot": "2026-04-15",
        "model_family": ModelFamily.ANTHROPIC,
        "solver": "inspect_swe.claude_code",
        "solver_version": "0.2.47",
        "auth_lane": "baseline_api",
        "reasoning_effort_requested": None,
        "reasoning_tokens_requested": None,
        "reasoning_effort_honored": None,
        "reasoning_tokens_honored": None,
        "provider_model_args": {},
        "n_samples": 500,
        "resolved": 300,
        "resolved_rate": 0.6,
        "total_tokens": 1,
        "wall_time_s": 1.0,
        "actual_cost_usd": Decimal("1.23"),
        "estimated_api_equivalent_usd": None,
        "inspect_version": "0.3.205",
        "inspect_swe_version": "0.2.47",
        "log_file": "raw/example.eval",
    }
    base.update(overrides)
    return SummaryRow(**base)
