"""F002: SWE generation must use the selected Inspect runtime solver."""

from __future__ import annotations

from pathlib import Path

from bencheval.benchmark_plan import plan_control_plane
from bencheval.swebench_adapter import build_swebench_run_command


def test_swebench_command_uses_inspect_runtime_solver() -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )
    cmd = build_swebench_run_command(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=Path("/tmp/out"),
    )
    assert cmd[:3] == ("inspect", "eval", "inspect_evals/swe_bench")
    assert cmd[cmd.index("--sample-id") + 1] == "django__django-11099"
    assert cmd[cmd.index("--solver") + 1] == "inspect_swe/codex_cli"
    assert cmd[cmd.index("-S") + 1] == "version=0.148.0"
    assert "mini-extra" not in cmd
