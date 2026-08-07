"""SWE-bench adapter unit tests (parse/build; execute demoted until evaluate)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.exceptions import BenchEvalError
from bencheval.swebench_adapter import (
    SWEBENCH_ADAPTER_ID,
    SwebenchCliResult,
    build_swebench_run_command,
    parse_swebench_instance_outcome,
    run_swebench_instance,
)

# SUBSTITUTE_JUSTIFICATION
# - substitute: injected mini-SWE runner and disposable result files in
#   test_run_instance_single
# - replaces: live mini-SWE generation and official SWE-Bench evaluation
# - necessity: deterministic local failure/result parsing is required while the official
#   evaluate path is deliberately absent and the adapter is non-executable
# - real-option: official generation plus evaluation must be implemented first
# - proof-limit: diagnostic parser coverage only; cannot qualify SWE-Bench execution
# - real-proof: BLOCKED until the official evaluate path is implemented and run live


def test_build_swebench_run_command() -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    cmd = build_swebench_run_command(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=Path("/tmp/out"),
    )
    assert cmd[:2] == ("mini-extra", "swebench")
    assert "django__django-11099" in cmd
    assert plan.model_binding == "runtime_configured"


def test_parse_verifier_and_diff(tmp_path: Path) -> None:
    art = tmp_path / "inst"
    art.mkdir()
    (art / "verifier.json").write_text(
        json.dumps({"resolved": True, "tests_passed": True, "cost_usd": 0.25}),
        encoding="utf-8",
    )
    (art / "workspace.diff").write_text("diff --git a/foo b/foo\n", encoding="utf-8")
    cli = SwebenchCliResult(0, "ok", "", 1.0, ("claude-code", "run"))
    out = parse_swebench_instance_outcome(
        instance_id="django__django-11099",
        cli=cli,
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="swebench-test",
    )
    assert out.primary_pass is True
    assert out.workspace_diff_path is not None
    assert out.verifier_log_path is not None
    assert out.native_score.get("resolved") is True


def test_execute_swebench_refuses_until_evaluate_wired(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    assert plan.adapter_id == SWEBENCH_ADAPTER_ID
    with pytest.raises(BenchEvalError, match="executable_adapter"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "evidence.jsonl",
            artifacts_dir=tmp_path / "artifacts",
            run_id="test-run-swe",
        )


def test_run_instance_single(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )

    def fake_runner(command, *, cwd, timeout_sec):
        out_dir = Path(command[command.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text('{"resolved": false}', encoding="utf-8")
        return SwebenchCliResult(0, "", "", 0.1, tuple(command))

    out = run_swebench_instance(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=fake_runner,
    )
    assert out.primary_pass is False
    assert out.failure_class == "model_wrong_solution"


def test_parse_missing_verifier_on_success_rc_fails(tmp_path: Path) -> None:
    art = tmp_path / "empty"
    art.mkdir()
    cli = SwebenchCliResult(0, "", "", 0.1, ("claude-code",))
    out = parse_swebench_instance_outcome(
        instance_id="x",
        cli=cli,
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="v",
    )
    assert out.primary_pass is False
    assert out.failure_class == "harness_failure"
