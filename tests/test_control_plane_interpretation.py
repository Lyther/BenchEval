"""Table-driven interpretation_label mapping from RunPlan."""

from __future__ import annotations

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import control_plane_interpretation_label


@pytest.mark.parametrize(
    ("benchmark_id", "slice_id", "runtime_id", "model_id", "expected"),
    [
        (
            "bfcl-v4",
            "smoke-5",
            None,
            "kimi-k2.7-code",
            "adapter_smoke",
        ),
        (
            "terminal-bench",
            "smoke-5",
            "claude-code",
            "kimi-k2.7-code",
            "adapter_smoke",
        ),
        (
            "swe-bench-verified",
            "swe-bench-verified-smoke-10",
            "codex-cli",
            "kimi-k2.7-code",
            "contaminated_or_legacy",
        ),
    ],
)
def test_control_plane_interpretation_label_from_catalog_plan(
    benchmark_id: str,
    slice_id: str,
    runtime_id: str | None,
    model_id: str,
    expected: str,
) -> None:
    plan = plan_control_plane(
        benchmark_id=benchmark_id,
        slice_id=slice_id,
        runtime_id=runtime_id,
        model_id=model_id,
    )
    assert control_plane_interpretation_label(plan) == expected


def test_interpretation_label_diagnostic_only_maps_to_benchmark_native_claim() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    diagnostic = plan.model_copy(update={"comparison_validity": "diagnostic_only"})
    assert control_plane_interpretation_label(diagnostic) == "benchmark_native_claim"


def test_interpretation_label_invalid_maps_to_rough_regression() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    invalid = plan.model_copy(update={"comparison_validity": "invalid"})
    assert control_plane_interpretation_label(invalid) == "rough_regression"
