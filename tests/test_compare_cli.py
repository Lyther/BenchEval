from __future__ import annotations

import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from bencheval import JsonlSummarySink
from tests.factories import make_summary_row

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_happy_markdown_stdout(tmp_path: Path) -> None:
    b = tmp_path / "b.jsonl"
    c = tmp_path / "c.jsonl"
    sink = JsonlSummarySink()
    sink.append_jsonl(b, make_summary_row(resolved=10, n_samples=100, resolved_rate=0.1))
    sink.append_jsonl(c, make_summary_row(resolved=20, n_samples=100, resolved_rate=0.2))
    r = _run("--baseline", str(b), "--current", str(c), "--format", "md")
    assert r.returncode == 0, r.stderr
    assert "# resolved_rate delta" in r.stdout
    assert "| Metric | Baseline | Current | Delta | 95% CI |" in r.stdout


def test_happy_json_stdout(tmp_path: Path) -> None:
    b = tmp_path / "b.jsonl"
    c = tmp_path / "c.jsonl"
    sink = JsonlSummarySink()
    sink.append_jsonl(b, make_summary_row(resolved=5, n_samples=50, resolved_rate=0.1))
    sink.append_jsonl(c, make_summary_row(resolved=10, n_samples=50, resolved_rate=0.2))
    r = _run("--baseline", str(b), "--current", str(c), "--format", "json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["title"] == "resolved_rate delta"
    assert len(data["metrics"]) == 1


def test_output_file_empty_stdout(tmp_path: Path) -> None:
    b = tmp_path / "b.jsonl"
    c = tmp_path / "c.jsonl"
    out = tmp_path / "out.md"
    sink = JsonlSummarySink()
    sink.append_jsonl(b, make_summary_row(resolved=1, n_samples=10, resolved_rate=0.1))
    sink.append_jsonl(c, make_summary_row(resolved=2, n_samples=10, resolved_rate=0.2))
    r = _run("--baseline", str(b), "--current", str(c), "--format", "md", "--output", str(out))
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
    text = out.read_text(encoding="utf-8")
    assert "# resolved_rate delta" in text


def test_cross_lane_without_equivalence_note_exits_2(tmp_path: Path) -> None:
    b = tmp_path / "b.jsonl"
    c = tmp_path / "c.jsonl"
    sink = JsonlSummarySink()
    lane_kwargs: dict[str, object] = {
        "solver": "cursor_cli",
        "solver_version": "cursor-agent@1.0.0",
        "inspect_swe_version": None,
    }
    sink.append_jsonl(b, make_summary_row(auth_lane="baseline_api", **lane_kwargs))
    sink.append_jsonl(
        c,
        make_summary_row(
            auth_lane="experimental_cursor",
            actual_cost_usd=None,
            estimated_api_equivalent_usd=Decimal("1.00"),
            **lane_kwargs,
        ),
    )
    r = _run("--baseline", str(b), "--current", str(c))
    assert r.returncode == 2
    err = (r.stderr or "").lower()
    assert "auth_lane" in err or "equivalence" in err


def test_cross_lane_with_equivalence_note_ok(tmp_path: Path) -> None:
    b = tmp_path / "b.jsonl"
    c = tmp_path / "c.jsonl"
    sink = JsonlSummarySink()
    lane_kwargs: dict[str, object] = {
        "solver": "cursor_cli",
        "solver_version": "cursor-agent@1.0.0",
        "inspect_swe_version": None,
    }
    sink.append_jsonl(b, make_summary_row(auth_lane="baseline_api", **lane_kwargs))
    sink.append_jsonl(
        c,
        make_summary_row(
            auth_lane="experimental_cursor",
            actual_cost_usd=None,
            estimated_api_equivalent_usd=Decimal("1.00"),
            **lane_kwargs,
        ),
    )
    r = _run("--baseline", str(b), "--current", str(c), "--equivalence-note", "ok")
    assert r.returncode == 0, r.stderr
    assert "resolved_rate" in r.stdout


def test_missing_baseline_exits_2(tmp_path: Path) -> None:
    c = tmp_path / "c.jsonl"
    JsonlSummarySink().append_jsonl(c, make_summary_row())
    missing = tmp_path / "missing.jsonl"
    r = _run("--baseline", str(missing), "--current", str(c))
    assert r.returncode == 2
    assert "cannot read" in r.stderr.lower()


def test_malformed_jsonl_exits_2(tmp_path: Path) -> None:
    b = tmp_path / "b.jsonl"
    c = tmp_path / "c.jsonl"
    b.write_text("{not-json\n", encoding="utf-8")
    JsonlSummarySink().append_jsonl(c, make_summary_row())
    r = _run("--baseline", str(b), "--current", str(c))
    assert r.returncode == 2
    assert "line 1" in r.stderr


def test_help_exits_zero_and_lists_flags() -> None:
    r = _run("--help")
    assert r.returncode == 0
    out = r.stdout
    for needle in ("--baseline", "--current", "--equivalence-note", "--format", "--output"):
        assert needle in out
