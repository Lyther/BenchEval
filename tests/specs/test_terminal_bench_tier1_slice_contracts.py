"""RED contract for the smallest honest Terminal-Bench Tier-1 lane.

The real typed planner is used.  No harness, provider, process runner, or other
test substitute is involved; this contract only requires the missing manifest.
"""

from __future__ import annotations

from bencheval.benchmark_plan import plan_control_plane


def test_tier1_one_is_a_single_fix_git_runtime_smoke() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )

    assert [instance.instance_id for instance in plan.instances] == ["fix-git"]
    assert plan.comparison_validity == "adapter_smoke"
    assert plan.max_wall_clock_sec_per_instance == 600
    assert plan.max_wall_clock_sec == 600
    assert plan.max_cost_usd == 5.0
    assert plan.requires_harbor is True
