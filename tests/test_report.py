from __future__ import annotations

from datetime import UTC, datetime

from bencheval.evidence import EvidenceRecord
from bencheval.report import generate_evidence_report


def _record(**overrides: object) -> EvidenceRecord:
    base: dict[str, object] = {
        "run_id": "run-001",
        "task_id": "be-core-c1-small-logic-patch",
        "model_id": "anthropic/claude-test",
        "execution_profile": "E1",
        "primary_pass": True,
        "partial_score": 0.8,
        "cost_usd": 0.5,
        "latency_sec": 30.0,
        "failure_labels": [],
        "artifact_paths": [],
        "verifier_log_path": None,
        "created_at": datetime(2026, 5, 29, tzinfo=UTC),
    }
    base.update(overrides)
    return EvidenceRecord(**base)


def test_report_contains_pass_rate_cost_failure_labels_and_warning() -> None:
    records = [
        _record(primary_pass=True),
        _record(
            task_id="be-core-a1-multi-file-repo-fix",
            primary_pass=False,
            failure_labels=["wrong_solution", "partial_solution"],
            cost_usd=1.0,
        ),
    ]
    md = generate_evidence_report(records)
    assert "Pass rate: 50.00%" in md
    assert "Total cost (USD): 1.5000" in md
    assert "| wrong_solution | 1 |" in md
    assert "| be-core-c1-small-logic-patch |" in md
    assert "| local |" in md
    assert "directional regression signals" in md
