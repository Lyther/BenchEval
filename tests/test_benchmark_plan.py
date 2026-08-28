"""Four-axis control-plane planner tests."""

from __future__ import annotations

import pytest

from bencheval.benchmark_plan import ControlPlanePlanner, plan_control_plane, resolve_runtime_id
from bencheval.control_plane_executor import _execution_profile_for_plan
from bencheval.exceptions import BenchEvalError


def test_plan_terminal_bench_smoke() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    assert plan.benchmark_id == "terminal-bench"
    assert plan.adapter_id == "terminal-bench-harbor"
    assert plan.harness_kind == "harbor"
    assert plan.comparison_validity == "adapter_smoke"
    assert plan.provider_id == "bytellm"
    assert len(plan.instances) == 5
    assert plan.requires_harbor is True
    assert plan.requires_sandbox is True
    assert _execution_profile_for_plan(plan) == "E2"


def test_plan_swe_smoke_codex_cli() -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )
    assert plan.harness_kind == "swebench-native"
    assert plan.runtime_id == "codex-cli"
    assert len(plan.instances) == 10
    assert plan.requires_harbor is False
    assert plan.requires_sandbox is True
    assert _execution_profile_for_plan(plan) == "E1"


def test_harness_mismatch_rejected() -> None:
    try:
        plan_control_plane(
            benchmark_id="terminal-bench",
            slice_id="smoke-5",
            runtime_id="no-such-runtime",
            model_id="kimi-k2.7-code",
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
        model_id="kimi-k2.7-code",
    )
    assert plan.comparison_validity == "adapter_smoke"
    assert plan.adapter_id == "bfcl"
    assert plan.runtime_id is None
    assert plan.requires_harbor is False
    assert plan.requires_sandbox is False
    assert _execution_profile_for_plan(plan) == "E0"


@pytest.mark.parametrize(
    ("benchmark_id", "slice_id", "model_id"),
    [
        ("gpqa-diamond", "smoke", "kimi-k2.7-code"),
        ("hle", "smoke", "gpt-5.4-2026-03-05"),
    ],
)
def test_plan_model_only_harness_does_not_claim_sandbox(
    benchmark_id: str,
    slice_id: str,
    model_id: str,
) -> None:
    plan = plan_control_plane(
        benchmark_id=benchmark_id,
        slice_id=slice_id,
        runtime_id=None,
        model_id=model_id,
    )

    assert plan.requires_harbor is False
    assert plan.requires_sandbox is False
    assert _execution_profile_for_plan(plan) == "E0"


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
        model_id="kimi-k2.7-code",
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
            model_id="kimi-k2.7-code",
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
            model_id="gpt-5.5-2026-04-24",
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
            model_id="kimi-k2.7-code",
        )
    except BenchEvalError as e:
        assert "scaffold" in str(e)
    else:
        raise AssertionError("expected BenchEvalError")


def test_run_planner_protocol_shape() -> None:
    planner = ControlPlanePlanner()
    plan = planner.plan(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )
    assert plan.runtime_id == "codex-cli"
