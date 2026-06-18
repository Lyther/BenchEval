"""BFCL v4 adapter unit tests (injected process runner)."""

from __future__ import annotations

import json
from pathlib import Path

from bencheval.adapter_admission import assess_bfcl_v4_admission
from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import (
    BFCL_ADAPTER_ID,
    BfclCliResult,
    build_bfcl_run_command,
    parse_bfcl_instance_outcome,
)
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError


def test_bfcl_admission_passes() -> None:
    report = assess_bfcl_v4_admission()
    assert report.passed is True


def test_build_bfcl_run_command() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id="native-api",
        model_id="openai/gpt-test",
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


def test_execute_bfcl_smoke_writes_evidence(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id="native-api",
        model_id="openai/gpt-test",
    )
    evidence_path = tmp_path / "evidence.jsonl"

    def fake_runner(command, *, cwd: Path | None, timeout_sec: int) -> BfclCliResult:
        out_dir = Path(command[command.index("--result-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "verdict.json").write_text(
            json.dumps({"primary_pass": True}),
            encoding="utf-8",
        )
        return BfclCliResult(0, "", "", 0.1, tuple(command))

    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "art",
        bfcl_process_runner=fake_runner,
        run_id="bfcl-run",
    )
    assert summary.instance_count == 5
    rows = read_evidence_jsonl(evidence_path)
    assert len(rows) == 5
    assert rows[0].interpretation_label == "model_comparison"


def test_adapter_failure_row_includes_benchmark_version(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id="native-api",
        model_id="openai/gpt-test",
    )
    evidence_path = tmp_path / "evidence.jsonl"

    def failing_runner(command, *, cwd: Path | None, timeout_sec: int) -> BfclCliResult:
        raise AdapterFailureError("injected", failure_label="harness_failure")

    execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "art",
        bfcl_process_runner=failing_runner,
        run_id="bfcl-fail-run",
    )
    row = read_evidence_jsonl(evidence_path)[0]
    assert row.benchmark_version == plan.benchmark_version
    assert row.primary_pass is False
