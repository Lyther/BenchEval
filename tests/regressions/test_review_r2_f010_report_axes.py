"""Review round 2 F010: report axes aggregate across rows, not first-row only."""

from __future__ import annotations

from datetime import UTC, datetime

from bencheval.evidence import EvidenceRecord
from bencheval.report import generate_evidence_report

_TS = datetime(2026, 8, 6, tzinfo=UTC)


def _row(
    *,
    task_id: str,
    runtime_version: str,
    provider_id: str,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"run-{task_id}",
        task_id=task_id,
        model_id="model-a",
        execution_profile="E1",
        backend="harbor",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.1,
        latency_sec=1.0,
        created_at=_TS,
        benchmark_id="terminal-bench",
        benchmark_version="2.0",
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@1",
        runtime_id="claude-code",
        runtime_version=runtime_version,
        provider_id=provider_id,
        interpretation_label="adapter_smoke",
    )


def test_report_shows_mixed_axes_not_first_row_only() -> None:
    records = [
        _row(task_id="t1", runtime_version="claude-code@a", provider_id="bytellm"),
        _row(task_id="t2", runtime_version="claude-code@b", provider_id="other"),
    ]
    md = generate_evidence_report(records)
    assert "Runtime version: mixed (" in md
    assert "`claude-code@a`" in md
    assert "`claude-code@b`" in md
    assert "Provider: mixed (" in md
    assert "`bytellm`" in md
    assert "`other`" in md
    # Must not silently report only the first row's values.
    assert "Runtime version: `claude-code@a`" not in md
    assert "Provider: `bytellm`" not in md


def test_report_singleton_axis_unchanged() -> None:
    records = [
        _row(task_id="t1", runtime_version="claude-code@a", provider_id="bytellm"),
        _row(task_id="t2", runtime_version="claude-code@a", provider_id="bytellm"),
    ]
    md = generate_evidence_report(records)
    assert "Runtime version: `claude-code@a`" in md
    assert "Provider: `bytellm`" in md
    assert "mixed" not in md
