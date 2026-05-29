from __future__ import annotations

from bencheval.planner import plan_dry_run


def test_dry_run_smoke_includes_selected_tasks() -> None:
    plan = plan_dry_run(suite="smoke", model_id="anthropic/claude-test")
    ids = [t.task_id for t in plan.tasks]
    assert len(ids) == 8
    assert "be-core-c1-small-logic-patch" in ids
    assert "be-core-s4-local-prompt-injection-resistance" in ids


def test_e2_sets_requires_harbor() -> None:
    plan = plan_dry_run(suite="core-8", model_id="anthropic/claude-test")
    assert plan.requires_harbor is True
    assert plan.requires_sandbox is True


def test_total_cost_is_deterministic() -> None:
    a = plan_dry_run(suite="core-8", model_id="model-a")
    b = plan_dry_run(suite="core-8", model_id="model-b")
    assert a.total_max_cost_usd == b.total_max_cost_usd
    assert a.total_max_cost_usd == 8.8
    assert a.total_max_wall_clock_sec == b.total_max_wall_clock_sec
