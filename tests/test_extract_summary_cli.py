from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bencheval import read_summary_jsonl
from bencheval.manifest import load_manifest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "extract_summary.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def _default_header(**overrides: object) -> dict[str, object]:
    h: dict[str, object] = {
        "model": "anthropic/claude-sonnet-4-5",
        "model_snapshot": "2026-04-15",
        "solver": "inspect_swe.claude_code",
        "solver_version": "0.2.47",
        "inspect_version": "0.3.205",
        "inspect_swe_version": "0.2.47",
        "reasoning_effort_requested": None,
        "reasoning_tokens_requested": None,
        "reasoning_effort_honored": None,
        "reasoning_tokens_honored": None,
        "provider_model_args": {},
        "n_samples": 3,
        "resolved": 2,
        "resolved_rate": 2 / 3,
        "total_tokens": 10,
        "wall_time_s": 1.0,
        "actual_cost_usd": "0.50",
        "estimated_api_equivalent_usd": None,
        "timestamp": "2026-04-17T12:00:00+00:00",
    }
    h.update(overrides)
    return h


def _default_stamp(task_manifest_hash: str) -> dict[str, object]:
    return {
        "auth_lane": "baseline_api",
        "task_manifest_hash": task_manifest_hash,
        "benchmark_revision": "inspect-evals==0.8.0",
        "model_family": "anthropic",
    }


def _write_inputs(
    tmp_path: Path,
    *,
    stamp_overrides: dict[str, object] | None = None,
    header_overrides: dict[str, object] | None = None,
    manifest_text: str = "alpha\nbeta\ngamma\n",
) -> tuple[Path, Path, Path, Path, Path]:
    eval_log = tmp_path / "raw" / "example.eval"
    manifest_path = tmp_path / "tasks.txt"
    manifest_path.write_text(manifest_text, encoding="utf-8")
    digest = load_manifest(manifest_path)
    stamp = _default_stamp(digest.content_sha256)
    if stamp_overrides:
        stamp.update(stamp_overrides)
    header = _default_header()
    if header_overrides:
        header.update(header_overrides)
    stamp_path = tmp_path / "stamp.json"
    header_path = tmp_path / "header.json"
    stamp_path.write_text(json.dumps(stamp), encoding="utf-8")
    header_path.write_text(json.dumps(header), encoding="utf-8")
    output_path = tmp_path / "out.jsonl"
    return eval_log, manifest_path, stamp_path, header_path, output_path


def test_happy_path_one_row(tmp_path: Path) -> None:
    ev, mf, sp, hp, op = _write_inputs(tmp_path)
    r = _run(
        "--eval-log",
        str(ev),
        "--manifest",
        str(mf),
        "--stamp-json",
        str(sp),
        "--header-json",
        str(hp),
        "--output",
        str(op),
    )
    assert r.returncode == 0, r.stderr
    assert op.is_file()
    rows = read_summary_jsonl(op)
    assert len(rows) == 1
    assert rows[0].model == "anthropic/claude-sonnet-4-5"
    assert rows[0].benchmark == "tasks"


def test_two_appends_two_lines(tmp_path: Path) -> None:
    ev, mf, sp, hp, op = _write_inputs(tmp_path)
    base = [
        "--eval-log",
        str(ev),
        "--manifest",
        str(mf),
        "--stamp-json",
        str(sp),
        "--header-json",
        str(hp),
        "--output",
        str(op),
    ]
    assert _run(*base).returncode == 0
    hp2 = tmp_path / "header2.json"
    hp2.write_text(json.dumps(_default_header(resolved=3, resolved_rate=1.0)), encoding="utf-8")
    r2 = _run(
        "--eval-log",
        str(ev),
        "--manifest",
        str(mf),
        "--stamp-json",
        str(sp),
        "--header-json",
        str(hp2),
        "--output",
        str(op),
    )
    assert r2.returncode == 0, r2.stderr
    rows = read_summary_jsonl(op)
    assert len(rows) == 2
    assert rows[0].resolved == 2
    assert rows[1].resolved == 3


def test_hash_mismatch_exits_2(tmp_path: Path) -> None:
    ev, mf, sp, hp, op = _write_inputs(
        tmp_path,
        stamp_overrides={"task_manifest_hash": "a" * 64},
    )
    r = _run(
        "--eval-log",
        str(ev),
        "--manifest",
        str(mf),
        "--stamp-json",
        str(sp),
        "--header-json",
        str(hp),
        "--output",
        str(op),
    )
    assert r.returncode == 2
    err = (r.stderr or "").lower()
    assert "task_manifest_hash" in err or "manifest" in err


def test_family_mismatch_exits_2(tmp_path: Path) -> None:
    ev, mf, sp, hp, op = _write_inputs(
        tmp_path,
        header_overrides={"model": "openai/gpt-4o"},
    )
    r = _run(
        "--eval-log",
        str(ev),
        "--manifest",
        str(mf),
        "--stamp-json",
        str(sp),
        "--header-json",
        str(hp),
        "--output",
        str(op),
    )
    assert r.returncode == 2
    err = (r.stderr or "").lower()
    assert "family" in err or "model" in err


def test_missing_timestamp_in_header_exits_2(tmp_path: Path) -> None:
    ev, mf, sp, _, op = _write_inputs(tmp_path)
    bad_header = _default_header()
    del bad_header["timestamp"]
    hp = tmp_path / "bad_header.json"
    hp.write_text(json.dumps(bad_header), encoding="utf-8")
    r = _run(
        "--eval-log",
        str(ev),
        "--manifest",
        str(mf),
        "--stamp-json",
        str(sp),
        "--header-json",
        str(hp),
        "--output",
        str(op),
    )
    assert r.returncode == 2
    assert "timestamp" in r.stderr.lower()


def test_missing_manifest_exits_2(tmp_path: Path) -> None:
    ev, _, sp, hp, op = _write_inputs(tmp_path)
    missing = tmp_path / "nope.txt"
    r = _run(
        "--eval-log",
        str(ev),
        "--manifest",
        str(missing),
        "--stamp-json",
        str(sp),
        "--header-json",
        str(hp),
        "--output",
        str(op),
    )
    assert r.returncode == 2
    assert "manifest" in r.stderr.lower()


def test_malformed_stamp_json_exits_2(tmp_path: Path) -> None:
    ev, mf, _, hp, op = _write_inputs(tmp_path)
    bad_stamp = tmp_path / "bad_stamp.json"
    bad_stamp.write_text("{not-json", encoding="utf-8")
    r = _run(
        "--eval-log",
        str(ev),
        "--manifest",
        str(mf),
        "--stamp-json",
        str(bad_stamp),
        "--header-json",
        str(hp),
        "--output",
        str(op),
    )
    assert r.returncode == 2


def test_help_lists_required_flags() -> None:
    r = _run("--help")
    assert r.returncode == 0
    out = r.stdout
    for needle in ("--eval-log", "--manifest", "--stamp-json", "--header-json", "--output"):
        assert needle in out
