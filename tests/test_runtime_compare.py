from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bencheval.evidence import EvidenceRecord
from bencheval.exceptions import ComparisonError
from bencheval.runtime_compare import (
    assess_runtime_comparison_validity,
    compare_runtime_evidence,
    is_runtime_comparison_evidence,
    render_runtime_comparison_markdown,
)

_TS = datetime(2026, 6, 1, tzinfo=UTC)


def _cp_record(
    *,
    instance_id: str,
    runtime_id: str,
    primary_pass: bool = True,
    cost_usd: float = 0.1,
    latency_sec: float = 10.0,
    harness_version: str = "harbor@1",
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"run-{runtime_id}-{instance_id}",
        task_id=instance_id,
        model_id="runtime-default",
        execution_profile="E1",
        backend="harbor",
        primary_pass=primary_pass,
        partial_score=1.0 if primary_pass else 0.0,
        cost_usd=cost_usd,
        latency_sec=latency_sec,
        created_at=_TS,
        benchmark_id="terminal-bench",
        benchmark_version="2.0",
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version=harness_version,
        runtime_id=runtime_id,
        runtime_kind="cli_agent",
        instance_id=instance_id,
        interpretation_label="adapter_smoke",
    )


def test_is_runtime_comparison_evidence_two_file_routing() -> None:
    baseline = [_cp_record(instance_id="tb-001", runtime_id="claude-code")]
    current = [_cp_record(instance_id="tb-001", runtime_id="codex-cli")]
    assert is_runtime_comparison_evidence(baseline, current) is True


def test_is_runtime_comparison_evidence_rejects_same_runtime() -> None:
    baseline = [_cp_record(instance_id="tb-001", runtime_id="claude-code")]
    current = [_cp_record(instance_id="tb-001", runtime_id="claude-code")]
    assert is_runtime_comparison_evidence(baseline, current) is False


def test_is_runtime_comparison_evidence_single_list_for_report_axes() -> None:
    rows = [
        _cp_record(instance_id="tb-001", runtime_id="claude-code"),
        _cp_record(instance_id="tb-002", runtime_id="codex-cli"),
    ]
    assert is_runtime_comparison_evidence(rows) is True


def test_valid_runtime_comparison_passes_gates() -> None:
    baseline = [_cp_record(instance_id="tb-001", runtime_id="claude-code", primary_pass=True)]
    current = [_cp_record(instance_id="tb-001", runtime_id="codex-cli", primary_pass=False)]
    verdict = assess_runtime_comparison_validity(baseline, current)
    assert verdict.valid is True
    assert verdict.interpretation_label == "runtime_comparison"
    assert "failed attempts" in verdict.caveats[0]


def test_same_runtime_invalid() -> None:
    baseline = [_cp_record(instance_id="tb-001", runtime_id="claude-code")]
    current = [_cp_record(instance_id="tb-001", runtime_id="claude-code")]
    verdict = assess_runtime_comparison_validity(baseline, current)
    assert verdict.valid is False
    assert any("runtime_id must differ" in r for r in verdict.reasons)


def test_harness_version_drift_invalid() -> None:
    baseline = [_cp_record(instance_id="tb-001", runtime_id="claude-code", harness_version="a")]
    current = [_cp_record(instance_id="tb-001", runtime_id="codex-cli", harness_version="b")]
    verdict = assess_runtime_comparison_validity(baseline, current)
    assert verdict.valid is False
    assert any("harness_version" in r for r in verdict.reasons)


def test_compare_runtime_evidence_ci_and_delta() -> None:
    baseline = [
        _cp_record(instance_id="tb-001", runtime_id="claude-code", primary_pass=True),
        _cp_record(instance_id="tb-002", runtime_id="claude-code", primary_pass=False),
    ]
    current = [
        _cp_record(instance_id="tb-001", runtime_id="codex-cli", primary_pass=True),
        _cp_record(instance_id="tb-002", runtime_id="codex-cli", primary_pass=True),
    ]
    report = compare_runtime_evidence(baseline, current)
    assert report.baseline_pass_rate == 0.5
    assert report.current_pass_rate == 1.0
    assert report.pass_rate_delta == pytest.approx(0.5)
    assert report.baseline_failed_attempts == 1
    assert report.current_failed_attempts == 0
    md = render_runtime_comparison_markdown(report)
    assert "# Runtime comparison" in md
    assert "claude-code" in md
    assert "codex-cli" in md
    assert "Per-runtime summary" in md


def test_runtime_compare_pass_rates_use_shared_instances_only() -> None:
    baseline = [
        _cp_record(instance_id="tb-001", runtime_id="claude-code", primary_pass=True),
        _cp_record(instance_id="tb-002", runtime_id="claude-code", primary_pass=True),
        _cp_record(instance_id="tb-only-base", runtime_id="claude-code", primary_pass=False),
    ]
    current = [
        _cp_record(instance_id="tb-001", runtime_id="codex-cli", primary_pass=True),
        _cp_record(instance_id="tb-002", runtime_id="codex-cli", primary_pass=False),
    ]
    report = compare_runtime_evidence(baseline, current)
    assert report.instance_count == 2
    assert report.baseline_pass_rate == 1.0
    assert report.current_pass_rate == 0.5


def test_duplicate_instance_rejected() -> None:
    baseline = [
        _cp_record(instance_id="tb-001", runtime_id="claude-code"),
        _cp_record(instance_id="tb-001", runtime_id="claude-code"),
    ]
    current = [_cp_record(instance_id="tb-001", runtime_id="codex-cli")]
    with pytest.raises(ComparisonError, match="duplicate instance"):
        compare_runtime_evidence(baseline, current)


def test_compare_rejects_missing_v03_axes() -> None:
    legacy = EvidenceRecord(
        run_id="r",
        task_id="t",
        model_id="m",
        execution_profile="E0",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.0,
        latency_sec=0.0,
        created_at=_TS,
    )
    verdict = assess_runtime_comparison_validity([legacy], [legacy])
    assert verdict.valid is False
    with pytest.raises(ComparisonError):
        compare_runtime_evidence([legacy], [legacy])
