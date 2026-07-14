"""Four-axis control-plane planner tests."""

from __future__ import annotations

from bencheval.benchmark_plan import ControlPlanePlanner, plan_control_plane, resolve_runtime_id
from bencheval.exceptions import BenchEvalError


def test_plan_terminal_bench_smoke() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="gpt-test",
    )
    assert plan.benchmark_id == "terminal-bench"
    assert plan.adapter_id == "terminal-bench-harbor"
    assert plan.harness_kind == "harbor"
    assert plan.comparison_validity == "adapter_smoke"
    assert plan.provider_id == "bytellm"
    assert len(plan.instances) == 5


def test_plan_swe_smoke_claude_code() -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="claude-code",
        model_id="gpt-test",
    )
    assert plan.harness_kind == "swebench-native"
    assert plan.runtime_id == "claude-code"
    assert len(plan.instances) == 10


def test_harness_mismatch_rejected() -> None:
    try:
        plan_control_plane(
            benchmark_id="terminal-bench",
            slice_id="smoke-5",
            runtime_id="no-such-runtime",
            model_id="gpt-test",
        )
    except BenchEvalError as e:
        assert "unknown runtime" in str(e) or "does not support" in str(e)
    else:
        raise AssertionError("expected BenchEvalError")


def test_plan_bfcl_smoke_adapter_smoke_validity() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-test",
    )
    assert plan.comparison_validity == "adapter_smoke"
    assert plan.adapter_id == "bfcl"
    assert plan.runtime_id is None


def test_resolve_runtime_null_for_bfcl() -> None:
    assert resolve_runtime_id(benchmark_id="bfcl-v4", runtime_id=None) is None


def test_resolve_runtime_requires_choice_for_swe() -> None:
    try:
        resolve_runtime_id(benchmark_id="swe-bench-verified", runtime_id=None)
    except BenchEvalError as e:
        assert "--runtime is required" in str(e)
    else:
        raise AssertionError("expected BenchEvalError")


def test_resolve_runtime_requires_choice_for_harbor() -> None:
    try:
        resolve_runtime_id(benchmark_id="terminal-bench", runtime_id=None)
    except BenchEvalError as e:
        assert "--runtime is required" in str(e)
        assert "claude-code" in str(e)
    else:
        raise AssertionError("expected BenchEvalError")


def test_plan_omitted_runtime_is_model_only_for_bfcl() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-test",
    )
    assert plan.runtime_id is None
    assert plan.agent_id is None


def test_plan_rejects_runtime_and_agent() -> None:
    try:
        plan_control_plane(
            benchmark_id="bfcl-v4",
            slice_id="smoke-5",
            runtime_id="claude-code",
            agent_id="momo",
            model_id="gpt-test",
        )
    except BenchEvalError as e:
        assert "mutually exclusive" in str(e)
    else:
        raise AssertionError("expected BenchEvalError")


def test_plan_rejects_unknown_model() -> None:
    try:
        plan_control_plane(
            benchmark_id="bfcl-v4",
            slice_id="smoke-5",
            runtime_id=None,
            model_id="no-such-model",
        )
    except BenchEvalError as e:
        assert "unknown model" in str(e)
    else:
        raise AssertionError("expected BenchEvalError")


def test_plan_rejects_provider_route_mismatch() -> None:
    try:
        plan_control_plane(
            benchmark_id="bfcl-v4",
            slice_id="smoke-5",
            runtime_id=None,
            model_id="claude-sonnet-5",
            provider_id="ollama-cloud",
        )
    except BenchEvalError as e:
        assert "routed to provider" in str(e)
    else:
        raise AssertionError("expected BenchEvalError")


def test_plan_rejects_agent_unsupported_harness() -> None:
    try:
        plan_control_plane(
            benchmark_id="bfcl-v4",
            slice_id="smoke-5",
            runtime_id=None,
            agent_id="momo",
            model_id="gpt-test",
        )
    except BenchEvalError as e:
        assert "does not support harness" in str(e)
    else:
        raise AssertionError("expected BenchEvalError")


def test_run_planner_protocol_shape() -> None:
    planner = ControlPlanePlanner()
    plan = planner.plan(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="codex-cli",
        model_id="gpt-test",
    )
    assert plan.runtime_id == "codex-cli"
