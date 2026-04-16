from __future__ import annotations

import inspect
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import get_type_hints

import pytest

from bencheval import BenchEvalError, JsonlSummarySink
from bencheval.models import SummaryRow
from tests.factories import make_summary_row


def test_append_once_writes_single_json_line(tmp_path: Path) -> None:
    path = tmp_path / "out.jsonl"
    row = make_summary_row()
    JsonlSummarySink().append_jsonl(path, row)
    assert path.is_file()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["benchmark"] == row.benchmark


def test_append_twice_writes_two_standalone_objects(tmp_path: Path) -> None:
    path = tmp_path / "out.jsonl"
    sink = JsonlSummarySink()
    sink.append_jsonl(path, make_summary_row(benchmark="a"))
    sink.append_jsonl(path, make_summary_row(benchmark="b"))
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["benchmark"] == "a"
    assert json.loads(lines[1])["benchmark"] == "b"


def test_decimal_actual_cost_round_trips_as_string_in_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "out.jsonl"
    row = make_summary_row(actual_cost_usd=Decimal("9.99"))
    JsonlSummarySink().append_jsonl(path, row)
    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert isinstance(payload["actual_cost_usd"], str)
    assert Decimal(payload["actual_cost_usd"]) == Decimal("9.99")


def test_creates_parent_directories(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "deep" / "out.jsonl"
    JsonlSummarySink().append_jsonl(path, make_summary_row())
    assert path.is_file()


def test_existing_directory_path_raises_bench_eval_error(tmp_path: Path) -> None:
    bad = tmp_path / "dir"
    bad.mkdir()
    with pytest.raises(BenchEvalError, match="not a regular file"):
        JsonlSummarySink().append_jsonl(bad, make_summary_row())


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="requires os.symlink")
def test_symlink_to_directory_raises_bench_eval_error(tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    link = tmp_path / "link"
    link.symlink_to(d, target_is_directory=True)
    with pytest.raises(BenchEvalError, match="not a regular file"):
        JsonlSummarySink().append_jsonl(link, make_summary_row())


def test_append_jsonl_signature_matches_protocol() -> None:
    sig = inspect.signature(JsonlSummarySink.append_jsonl)
    params = list(sig.parameters.values())
    assert [p.name for p in params] == ["self", "path", "row"]
    hints = get_type_hints(JsonlSummarySink.append_jsonl)
    assert hints["path"] is Path
    assert hints["row"] is SummaryRow
    assert hints["return"] is type(None)
