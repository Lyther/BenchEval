from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from bencheval.admission import run_workspace_verifier
from tests.selftest_paths import core16_workspace

_ROOT = Path(__file__).resolve().parents[1]
_T3_WS = core16_workspace("be-core-t3-tool-necessity-gate")
_REF = json.loads((_T3_WS / "reference.json").read_text(encoding="utf-8"))
_HIDDEN = json.loads((_T3_WS / "hidden_variants.json").read_text(encoding="utf-8"))
_PROMPT_VARIANTS = json.loads((_T3_WS / "prompt_variants.json").read_text(encoding="utf-8"))


def _load_t3_verify_module():
    path = _T3_WS / "verify.py"
    spec = importlib.util.spec_from_file_location("t3_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prompt_variants_cover_hidden_variant_ids_without_gold() -> None:
    hidden_ids = {entry["variant_id"] for entry in _HIDDEN["variants"]}
    prompt_ids = {entry["variant_id"] for entry in _PROMPT_VARIANTS["variants"]}
    assert prompt_ids == hidden_ids
    for entry in _PROMPT_VARIANTS["variants"]:
        assert "gold" not in entry


def test_reference_passes_admission_verifier() -> None:
    report = run_workspace_verifier(_T3_WS, _T3_WS / "reference.json")
    assert report.primary_pass is True


def test_negative_fails_admission_verifier() -> None:
    report = run_workspace_verifier(_T3_WS, _T3_WS / "negative.json")
    assert report.primary_pass is False


def test_hidden_variant_gold_labels_self_match() -> None:
    mod = _load_t3_verify_module()
    for entry in _HIDDEN["variants"]:
        gold = entry["gold"]
        assert mod._matches_gold(gold, gold) is True


def test_hidden_variants_aggregate_perfect_precision_recall() -> None:
    mod = _load_t3_verify_module()
    labels = mod._hidden_gold_labels(_T3_WS)
    pairs = [(gold, gold) for gold in labels]
    precision, recall = mod._aggregate_necessity_metrics(pairs)
    assert precision == 1.0
    assert recall == 1.0


def test_canonical_only_candidate_fails_hidden_variant_scoring() -> None:
    mod = _load_t3_verify_module()
    candidate = {
        "use_tool": True,
        "tool_call": {
            "tool": "mock_lookup",
            "arguments": {"query": "ada@example.com"},
        },
    }
    result = mod._score(_T3_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["schema_valid"] == 0.0
    assert result["partial_metrics"]["variant_coverage"] == 0.0


def test_wrong_tool_when_required_fails() -> None:
    mod = _load_t3_verify_module()
    candidate = json.loads(json.dumps(_REF))
    candidate["variant_responses"]["canonical"]["tool_call"] = {
        "tool": "mock_calendar",
        "arguments": {
            "title": "mistake",
            "date": "2026-06-01",
            "time": "10:00",
            "timezone": "UTC",
            "attendees": ["ada@example.com"],
        },
    }
    result = mod._score(_T3_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["tool_call_match"] == 0.0


def test_unnecessary_tool_call_fails_schema() -> None:
    mod = _load_t3_verify_module()
    candidate = json.loads(json.dumps(_REF))
    candidate["variant_responses"]["direct-arithmetic"] = {
        "use_tool": False,
        "tool_call": {"tool": "mock_lookup", "arguments": {"query": "ada@example.com"}},
        "answer": {"department": "Engineering"},
    }
    result = mod._score(_T3_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["schema_valid"] == 0.0


def test_missing_tool_call_when_required_fails_schema() -> None:
    mod = _load_t3_verify_module()
    candidate = json.loads(json.dumps(_REF))
    candidate["variant_responses"]["calendar-required"] = {
        "use_tool": True,
        "answer": {"scheduled": True},
    }
    result = mod._score(_T3_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["schema_valid"] == 0.0


def test_hidden_variant_matrix_scores_perfect_on_reference() -> None:
    mod = _load_t3_verify_module()
    result = mod._score(_T3_WS, _REF)
    assert result["primary_pass"] is True
    assert result["partial_metrics"]["necessity_precision"] == 1.0
    assert result["partial_metrics"]["necessity_recall"] == 1.0
    assert result["partial_metrics"]["variant_coverage"] == 1.0


def test_malformed_candidate_json_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_T3_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "valid JSON" in proc.stderr
