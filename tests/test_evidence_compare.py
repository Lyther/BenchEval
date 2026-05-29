from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.evidence_compare import compare_evidence_runs, render_comparison_markdown
from bencheval.exceptions import ComparisonError


def _record(
    *,
    task_id: str,
    backend: str = "local",
    primary_pass: bool = True,
    partial_score: float = 1.0,
    cost_usd: float = 0.0,
    latency_sec: float = 0.1,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"run-{task_id}",
        task_id=task_id,
        model_id="mockllm/model",
        execution_profile="E0",
        backend=backend,
        primary_pass=primary_pass,
        partial_score=partial_score,
        cost_usd=cost_usd,
        latency_sec=latency_sec,
        failure_labels=[] if primary_pass else ["wrong_solution"],
        artifact_paths=[],
        verifier_log_path=None,
        adapter_metadata={},
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
    )


def test_compare_pass_rate_delta() -> None:
    baseline = [
        _record(task_id="be-core-t1-single-structured-call", primary_pass=True),
        _record(task_id="be-core-t2-multi-tool-join", primary_pass=False, partial_score=0.0),
    ]
    current = [
        _record(task_id="be-core-t1-single-structured-call", primary_pass=True),
        _record(task_id="be-core-t2-multi-tool-join", primary_pass=True),
    ]
    report = compare_evidence_runs(baseline, current)
    assert report.baseline_pass_rate == 0.5
    assert report.current_pass_rate == 1.0
    assert report.pass_rate_delta == pytest.approx(0.5)


def test_compare_missing_and_new_tasks() -> None:
    baseline = [_record(task_id="be-core-t1-single-structured-call")]
    current = [_record(task_id="be-core-t2-multi-tool-join")]
    report = compare_evidence_runs(baseline, current)
    assert report.missing_in_current == ("be-core-t1-single-structured-call",)
    assert report.new_in_current == ("be-core-t2-multi-tool-join",)


def test_compare_backend_split() -> None:
    baseline = [
        _record(task_id="be-core-t1-single-structured-call", backend="local", primary_pass=True),
        _record(task_id="be-core-t2-multi-tool-join", backend="inspect", primary_pass=False),
    ]
    current = [
        _record(task_id="be-core-t1-single-structured-call", backend="local", primary_pass=True),
        _record(task_id="be-core-t2-multi-tool-join", backend="inspect", primary_pass=True),
    ]
    report = compare_evidence_runs(baseline, current)
    inspect_row = next(row for row in report.backend_pass_rates if row.backend == "inspect")
    assert inspect_row.baseline_pass_rate == 0.0
    assert inspect_row.current_pass_rate == 1.0
    assert inspect_row.pass_rate_delta == pytest.approx(1.0)


def test_compare_markdown_output() -> None:
    baseline = [_record(task_id="be-core-t1-single-structured-call")]
    current = [_record(task_id="be-core-t1-single-structured-call", cost_usd=0.02)]
    report = compare_evidence_runs(baseline, current)
    md = render_comparison_markdown(report)
    assert "# Evidence comparison" in md
    assert "Backend pass rates" in md
    assert "be-core-t1-single-structured-call" in md


def test_compare_rejects_empty_baseline() -> None:
    with pytest.raises(ComparisonError, match="baseline evidence must be non-empty"):
        compare_evidence_runs([], [_record(task_id="be-core-t1-single-structured-call")])


def test_cli_compare_writes_markdown(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    current = tmp_path / "current.jsonl"
    out = tmp_path / "delta.md"
    sink = JsonlEvidenceSink()
    sink.append_jsonl(baseline, _record(task_id="be-core-t1-single-structured-call"))
    sink.append_jsonl(
        current,
        _record(task_id="be-core-t1-single-structured-call", partial_score=0.5, primary_pass=False),
    )
    from bencheval.cli import main

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
    assert "# Evidence comparison" in out.read_text(encoding="utf-8")
