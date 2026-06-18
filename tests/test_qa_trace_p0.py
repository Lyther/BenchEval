"""Regression tests for QA trace P0 findings (2026-05-29)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import JsonlEvidenceSink, eligible_for_pass_at_k
from bencheval.evidence_compare import compare_evidence_runs
from bencheval.exceptions import BenchEvalError, ComparisonError
from bencheval.runtime_compare import (
    _pass_rate_ci,
    compare_runtime_evidence,
    is_dual_axis_comparison_drift,
)
from tests.factories import make_control_plane_evidence_record as _cp_record


def test_dual_axis_drift_detected() -> None:
    baseline = [_cp_record(instance_id="tb-001", model_id="openai/a", runtime_id="claude-code")]
    current = [_cp_record(instance_id="tb-001", model_id="openai/b", runtime_id="codex-cli")]
    assert is_dual_axis_comparison_drift(baseline, current) is True


def test_compare_cli_rejects_dual_axis_drift(tmp_path: Path) -> None:
    from bencheval.cli import main

    baseline = tmp_path / "baseline.jsonl"
    current = tmp_path / "current.jsonl"
    out = tmp_path / "report.md"
    sink = JsonlEvidenceSink()
    sink.append_jsonl(
        baseline,
        _cp_record(instance_id="tb-001", model_id="openai/a", runtime_id="claude-code"),
    )
    sink.append_jsonl(
        current,
        _cp_record(instance_id="tb-001", model_id="openai/b", runtime_id="codex-cli"),
    )
    code = main(
        [
            "compare",
            str(baseline),
            str(current),
            "--format",
            "md",
            "--output",
            str(out),
        ],
    )
    assert code == 2
    assert not out.exists()


def test_compare_evidence_runs_rejects_dual_axis_drift() -> None:
    baseline = [_cp_record(instance_id="tb-001", model_id="openai/a", runtime_id="claude-code")]
    current = [_cp_record(instance_id="tb-001", model_id="openai/b", runtime_id="codex-cli")]
    with pytest.raises(ComparisonError, match="dual-axis drift"):
        compare_evidence_runs(baseline, current, mode="auto")


def test_cli_compare_routes_runtime_before_legacy_on_runtime_drift(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from bencheval.cli import main

    baseline = tmp_path / "baseline.jsonl"
    current = tmp_path / "current.jsonl"
    out = tmp_path / "report.md"
    sink = JsonlEvidenceSink()
    sink.append_jsonl(baseline, _cp_record(instance_id="tb-001", runtime_id="claude-code"))
    sink.append_jsonl(current, _cp_record(instance_id="tb-001", runtime_id="codex-cli"))
    code = main(
        [
            "compare",
            str(baseline),
            str(current),
            "--format",
            "md",
            "--output",
            str(out),
        ],
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["mode"] == "runtime"
    assert "# Runtime comparison" in out.read_text(encoding="utf-8")


def test_pass_rate_ci_excludes_invalid_pass_at_k_rows() -> None:
    rows = [
        _cp_record(instance_id="tb-001", primary_pass=True),
        _cp_record(
            instance_id="tb-002",
            primary_pass=False,
            attempt_validity="invalid",
            counts_toward_pass_at_k=False,
        ),
    ]
    ci = _pass_rate_ci(rows)
    assert ci.attempt_count == 1
    assert ci.pass_count == 1
    assert ci.pass_rate == 1.0


def test_runtime_compare_ci_excludes_invalid_rows() -> None:
    baseline = [
        _cp_record(instance_id="tb-001", runtime_id="claude-code", primary_pass=True),
        _cp_record(
            instance_id="tb-002",
            runtime_id="claude-code",
            primary_pass=False,
            attempt_validity="invalid",
            counts_toward_pass_at_k=False,
        ),
    ]
    current = [
        _cp_record(instance_id="tb-001", runtime_id="codex-cli", primary_pass=True),
        _cp_record(instance_id="tb-002", runtime_id="codex-cli", primary_pass=True),
    ]
    report = compare_runtime_evidence(baseline, current)
    assert report.baseline_pass_ci.attempt_count == 1
    assert report.baseline_pass_rate == 1.0
    assert report.baseline_invalid_excluded == 1
    assert any("pass@k invalid rows excluded" in c for c in report.caveats)


def test_eligible_for_pass_at_k_defaults() -> None:
    valid = _cp_record(instance_id="tb-001")
    invalid = _cp_record(
        instance_id="tb-002",
        attempt_validity="invalid",
        counts_toward_pass_at_k=False,
    )
    assert eligible_for_pass_at_k(valid) is True
    assert eligible_for_pass_at_k(invalid) is False


def test_execute_rejects_metadata_only_benchmark(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-rebench",
        slice_id="swe-rebench-smoke-10",
        runtime_id="native-api",
        model_id="openai/gpt-test",
    )
    assert any(c.startswith("execution_support:metadata_only") for c in plan.caveats)
    with pytest.raises(BenchEvalError, match="execution_support='metadata_only'"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "out.jsonl",
            artifacts_dir=tmp_path / "art",
        )
