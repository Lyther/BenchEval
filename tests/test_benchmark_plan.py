"""Four-axis control-plane planner tests."""

from __future__ import annotations

from bencheval.benchmark_plan import ControlPlanePlanner, plan_control_plane
from bencheval.exceptions import BenchEvalError


def test_plan_terminal_bench_smoke() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="runtime-default",
    )
    assert plan.benchmark_id == "terminal-bench"
    assert plan.adapter_id == "terminal-bench-harbor"
    assert plan.harness_kind == "harbor"
    assert plan.comparison_validity == "adapter_smoke"
    assert len(plan.instances) == 5


def test_plan_swe_smoke_mini_swe() -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="mini-swe-agent",
        model_id="openai/gpt-test",
    )
    assert plan.harness_kind == "swebench-native"
    assert len(plan.instances) == 10


def test_harness_mismatch_rejected() -> None:
    try:
        plan_control_plane(
            benchmark_id="terminal-bench",
            slice_id="smoke-5",
            runtime_id="native-api",
            model_id="openai/gpt-test",
        )
    except BenchEvalError as e:
        assert "does not support harness" in str(e)
    else:
        raise AssertionError("expected BenchEvalError")


def test_plan_bfcl_smoke_model_comparison_validity() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id="native-api",
        model_id="openai/gpt-test",
    )
    assert plan.comparison_validity == "model_comparison"
    assert plan.adapter_id == "bfcl"


def test_run_planner_protocol_shape() -> None:
    planner = ControlPlanePlanner()
    plan = planner.plan(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="codex-cli",
        model_id="runtime-default",
    )
    assert plan.runtime_id == "codex-cli"
