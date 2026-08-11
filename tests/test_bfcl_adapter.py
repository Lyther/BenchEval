"""BFCL v4 adapter unit tests (parse/build; execute demoted until evaluate)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.adapter_admission import assess_bfcl_v4_admission
from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import (
    BFCL_ADAPTER_ID,
    BfclCliResult,
    build_bfcl_run_command,
    parse_bfcl_instance_outcome,
)
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.exceptions import BenchEvalError


def test_bfcl_admission_fails_closed_while_demoted() -> None:
    # Round-1 F008 contract: BFCL is demoted (executable: false) until official
    # evaluate is wired, so the Tier-0 wiring gate must not report passed.
    report = assess_bfcl_v4_admission()
    assert report.passed is False
    assert {name: ok for name, ok, _ in report.checks}.get("catalog_executable") is False


def test_build_bfcl_run_command() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    cmd = build_bfcl_run_command(
        plan=plan,
        instance_id="simple",
        artifacts_dir=Path("/tmp/out"),
    )
    assert cmd[:2] == ("bfcl", "generate")
    assert "--test-category" in cmd
    assert "simple" in cmd
    assert "--result-dir" in cmd


def test_parse_verdict_json(tmp_path: Path) -> None:
    art = tmp_path / "inst"
    art.mkdir()
    (art / "verdict.json").write_text(
        json.dumps({"correct": True, "cost_usd": 0.01}),
        encoding="utf-8",
    )
    cli = BfclCliResult(0, "", "", 0.2, ("bfcl", "generate"))
    out = parse_bfcl_instance_outcome(
        instance_id="bfcl_smoke_001",
        cli=cli,
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="bfcl-test",
    )
    assert out.primary_pass is True
    assert out.adapter_metadata["adapter_id"] == BFCL_ADAPTER_ID


def test_execute_bfcl_refuses_until_evaluate_wired(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    with pytest.raises(BenchEvalError, match="executable_adapter"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "evidence.jsonl",
            artifacts_dir=tmp_path / "art",
            run_id="bfcl-run",
        )
