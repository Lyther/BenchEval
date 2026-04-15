"""Shared test factories (single source for SummaryRow defaults)."""

from datetime import UTC, datetime
from decimal import Decimal

from bencheval.models import ModelFamily, SummaryRow


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
