from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError, EvidenceValidationError


def _record(**overrides: object) -> EvidenceRecord:
    base: dict[str, object] = {
        "run_id": "run-001",
        "task_id": "be-core-c1-small-logic-patch",
        "model_id": "anthropic/claude-test",
        "execution_profile": "E1",
        "primary_pass": True,
        "partial_score": 0.9,
        "cost_usd": 0.12,
        "latency_sec": 42.0,
        "failure_labels": [],
        "artifact_paths": ["artifacts/patch.diff"],
        "verifier_log_path": "verifier/run.log",
        "created_at": datetime(2026, 5, 29, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return EvidenceRecord(**base)


def test_append_read_jsonl_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "evidence.jsonl"
    row = _record()
    JsonlEvidenceSink().append_jsonl(p, row)
    got = read_evidence_jsonl(p)
    assert len(got) == 1
    assert got[0] == row


def test_append_twice_preserves_order(tmp_path: Path) -> None:
    p = tmp_path / "evidence.jsonl"
    sink = JsonlEvidenceSink()
    r1 = _record(task_id="be-core-c1-small-logic-patch")
    r2 = _record(task_id="be-core-c2-regression-test-authoring", primary_pass=False)
    sink.append_jsonl(p, r1)
    sink.append_jsonl(p, r2)
    got = read_evidence_jsonl(p)
    assert got == [r1, r2]


def test_blank_lines_between_rows_skipped(tmp_path: Path) -> None:
    p = tmp_path / "blank.jsonl"
    r1 = _record(task_id="row-a")
    r2 = _record(task_id="row-b")
    p.write_text(r1.model_dump_json() + "\n\n\n" + r2.model_dump_json() + "\n", encoding="utf-8")
    got = read_evidence_jsonl(p)
    assert len(got) == 2
    assert got[0] == r1
    assert got[1] == r2


def test_empty_file_returns_empty_list(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    assert read_evidence_jsonl(p) == []


def test_missing_file_raises_bench_eval_error(tmp_path: Path) -> None:
    with pytest.raises(BenchEvalError, match="cannot read evidence jsonl"):
        read_evidence_jsonl(tmp_path / "nope.jsonl")


def test_malformed_json_second_line_names_line_two(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    ok = _record()
    p.write_text(ok.model_dump_json() + "\n{not-json\n", encoding="utf-8")
    with pytest.raises(EvidenceValidationError, match="line 2"):
        read_evidence_jsonl(p)


def test_validation_failure_names_line_number(tmp_path: Path) -> None:
    p = tmp_path / "val.jsonl"
    p.write_text('{"not_evidence": true}\n', encoding="utf-8")
    with pytest.raises(EvidenceValidationError, match="line 1"):
        read_evidence_jsonl(p)


def test_errors_are_evidence_validation_not_pydantic_or_json_decode(tmp_path: Path) -> None:
    p = tmp_path / "leak.jsonl"
    p.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(EvidenceValidationError) as ctx:
        read_evidence_jsonl(p)
    err = ctx.value
    assert not isinstance(err, ValidationError)
    assert not isinstance(err, json.JSONDecodeError)


def test_path_and_str_identical(tmp_path: Path) -> None:
    p = tmp_path / "both.jsonl"
    row = _record()
    JsonlEvidenceSink().append_jsonl(p, row)
    a = read_evidence_jsonl(p)
    b = read_evidence_jsonl(str(p))
    assert a == b
    assert len(a) == 1
    assert isinstance(a[0], EvidenceRecord)


def test_existing_directory_path_raises_bench_eval_error(tmp_path: Path) -> None:
    bad = tmp_path / "dir"
    bad.mkdir()
    with pytest.raises(BenchEvalError, match="not a regular file"):
        JsonlEvidenceSink().append_jsonl(bad, _record())


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires os.symlink")
def test_symlink_to_directory_raises_bench_eval_error(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    link = tmp_path / "link"
    link.symlink_to(d, target_is_directory=True)
    with pytest.raises(BenchEvalError, match="not a regular file"):
        JsonlEvidenceSink().append_jsonl(link, _record())
