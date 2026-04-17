from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from bencheval import BenchEvalError, JsonlSummarySink, read_summary_jsonl
from bencheval.exceptions import SummaryValidationError
from bencheval.models import SummaryRow
from tests.factories import make_summary_row


def test_round_trip_single_row_via_sink(tmp_path: Path) -> None:
    p = tmp_path / "one.jsonl"
    row = make_summary_row()
    JsonlSummarySink().append_jsonl(p, row)
    got = read_summary_jsonl(p)
    assert len(got) == 1
    assert got[0] == row


def test_round_trip_three_distinct_rows_order_preserved(tmp_path: Path) -> None:
    p = tmp_path / "three.jsonl"
    sink = JsonlSummarySink()
    rows = [
        make_summary_row(benchmark="x", resolved=1, n_samples=10, resolved_rate=0.1),
        make_summary_row(benchmark="y", resolved=2, n_samples=10, resolved_rate=0.2),
        make_summary_row(benchmark="z", resolved=3, n_samples=10, resolved_rate=0.3),
    ]
    for r in rows:
        sink.append_jsonl(p, r)
    got = read_summary_jsonl(p)
    assert got == rows


def test_decimal_round_trip_exact(tmp_path: Path) -> None:
    p = tmp_path / "dec.jsonl"
    row = make_summary_row(actual_cost_usd=Decimal("0.0123"))
    JsonlSummarySink().append_jsonl(p, row)
    got = read_summary_jsonl(p)[0]
    assert got.actual_cost_usd == Decimal("0.0123")


def test_datetime_tz_round_trip_utc(tmp_path: Path) -> None:
    p = tmp_path / "tz.jsonl"
    ts = datetime(2026, 4, 16, 12, 30, tzinfo=UTC)
    row = make_summary_row(timestamp=ts)
    JsonlSummarySink().append_jsonl(p, row)
    got = read_summary_jsonl(p)[0]
    assert got.timestamp.tzinfo == UTC
    assert got.timestamp == ts


def test_blank_lines_between_rows_skipped(tmp_path: Path) -> None:
    p = tmp_path / "blank.jsonl"
    r1 = make_summary_row(benchmark="row-a")
    r2 = make_summary_row(benchmark="row-b")
    p.write_text(
        r1.model_dump_json() + "\n\n\n" + r2.model_dump_json() + "\n",
        encoding="utf-8",
    )
    got = read_summary_jsonl(p)
    assert len(got) == 2
    assert got[0] == r1
    assert got[1] == r2


def test_trailing_newline_loads_cleanly(tmp_path: Path) -> None:
    p = tmp_path / "trail.jsonl"
    row = make_summary_row()
    p.write_text(row.model_dump_json() + "\n", encoding="utf-8")
    got = read_summary_jsonl(p)
    assert len(got) == 1
    assert got[0] == row


def test_empty_file_returns_empty_list(tmp_path: Path) -> None:
    p = tmp_path / "empty.jsonl"
    p.write_text("", encoding="utf-8")
    assert read_summary_jsonl(p) == []


def test_whitespace_only_file_returns_empty_list(tmp_path: Path) -> None:
    p = tmp_path / "ws.jsonl"
    p.write_text("\n   \n", encoding="utf-8")
    assert read_summary_jsonl(p) == []


def test_missing_file_raises_bench_eval_error(tmp_path: Path) -> None:
    with pytest.raises(BenchEvalError, match="cannot read summary jsonl"):
        read_summary_jsonl(tmp_path / "nope.jsonl")


def test_malformed_json_second_line_names_line_two(tmp_path: Path) -> None:
    p = tmp_path / "bad.jsonl"
    ok = make_summary_row()
    p.write_text(ok.model_dump_json() + "\n{not-json\n", encoding="utf-8")
    with pytest.raises(SummaryValidationError, match="line 2"):
        read_summary_jsonl(p)


def test_validation_failure_names_line_number(tmp_path: Path) -> None:
    p = tmp_path / "val.jsonl"
    p.write_text('{"not_a_summary": true}\n', encoding="utf-8")
    with pytest.raises(SummaryValidationError, match="line 1"):
        read_summary_jsonl(p)


def test_errors_are_summary_validation_not_pydantic_or_json_decode(tmp_path: Path) -> None:
    p = tmp_path / "leak.jsonl"
    p.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(SummaryValidationError) as ctx:
        read_summary_jsonl(p)
    err = ctx.value
    assert not isinstance(err, ValidationError)
    assert not isinstance(err, json.JSONDecodeError)


def test_path_and_str_identical(tmp_path: Path) -> None:
    p = tmp_path / "both.jsonl"
    row = make_summary_row()
    JsonlSummarySink().append_jsonl(p, row)
    a = read_summary_jsonl(p)
    b = read_summary_jsonl(str(p))
    assert a == b
    assert len(a) == 1
    assert isinstance(a[0], SummaryRow)
