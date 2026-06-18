"""F002: SWE adapter must invoke mini-extra swebench per production contract."""

from __future__ import annotations

from pathlib import Path

from bencheval.benchmark_plan import plan_control_plane
from bencheval.swebench_adapter import build_swebench_run_command


def test_swebench_command_uses_mini_extra_swebench() -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="mini-swe-agent",
        model_id="openai/gpt-test",
    )
    cmd = build_swebench_run_command(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=Path("/tmp/out"),
    )
    assert cmd[:2] == ("mini-extra", "swebench")
    assert "django__django-11099" in cmd
