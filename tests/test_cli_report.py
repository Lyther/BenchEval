from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bencheval.cli import main
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink


def _write_evidence(path: Path) -> None:
    record = EvidenceRecord(
        run_id="run-report-001",
        task_id="be-core-t1-single-structured-call",
        model_id="local/harness",
        execution_profile="E0",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.0,
        latency_sec=0.0,
        failure_labels=[],
        artifact_paths=[],
        verifier_log_path=None,
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
    )
    JsonlEvidenceSink().append_jsonl(path, record)


def test_report_cli_generates_markdown(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    output = tmp_path / "reports" / "run.md"
    _write_evidence(evidence)
    code = main(["report", str(evidence), "--output", str(output)])
    assert code == 0
    text = output.read_text(encoding="utf-8")
    assert "# BenchEval Evidence Report" in text
    assert "Pass rate: 100.00%" in text


def test_report_cli_rejects_malformed_evidence(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json}\n", encoding="utf-8")
    code = main(["report", str(bad), "--output", str(tmp_path / "out.md")])
    assert code == 1
