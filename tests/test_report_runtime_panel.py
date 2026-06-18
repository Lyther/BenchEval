from __future__ import annotations

from datetime import UTC, datetime

from bencheval.evidence import EvidenceRecord
from bencheval.report import (
    generate_evidence_report_with_runtime_panel,
    generate_runtime_comparison_panel,
)

_TS = datetime(2026, 6, 1, tzinfo=UTC)


def _cp(instance_id: str, runtime_id: str) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"r-{runtime_id}",
        task_id=instance_id,
        model_id="runtime-default",
        execution_profile="E1",
        backend="harbor",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.2,
        latency_sec=5.0,
        created_at=_TS,
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="1",
        runtime_id=runtime_id,
        instance_id=instance_id,
    )


def test_runtime_panel_emitted_for_multi_runtime_file() -> None:
    records = [
        _cp("tb-001", "claude-code"),
        _cp("tb-001", "codex-cli"),
    ]
    panel = generate_runtime_comparison_panel(records)
    assert panel is not None
    assert "# Runtime comparison" in panel

    full = generate_evidence_report_with_runtime_panel(records)
    assert "BenchEval Evidence Report" in full
    assert "# Runtime comparison" in full
