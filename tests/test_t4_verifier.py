from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from bencheval.admission import run_workspace_verifier
from tests.selftest_paths import core16_workspace

_ROOT = Path(__file__).resolve().parents[1]
_T4_WS = core16_workspace("be-core-t4-stateful-policy-workflow")
_REF = json.loads((_T4_WS / "reference.json").read_text(encoding="utf-8"))
_ALT = json.loads((_T4_WS / "hidden" / "alternate_gold.json").read_text(encoding="utf-8"))


def _load_t4_verify_module():
    path = _T4_WS / "verify.py"
    spec = importlib.util.spec_from_file_location("t4_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_passes_admission_verifier() -> None:
    report = run_workspace_verifier(_T4_WS, _T4_WS / "reference.json")
    assert report.primary_pass is True


def test_negative_fails_admission_verifier() -> None:
    report = run_workspace_verifier(_T4_WS, _T4_WS / "negative.json")
    assert report.primary_pass is False


def test_forbidden_delete_as_editor_fails() -> None:
    mod = _load_t4_verify_module()
    candidate = json.loads((_T4_WS / "negative.json").read_text(encoding="utf-8"))
    result = mod._score(_T4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["forbidden_action_absent"] == 0.0


def test_missing_audit_entry_fails() -> None:
    mod = _load_t4_verify_module()
    candidate = dict(_REF)
    audit = list(_REF["audit_log"])
    audit.pop()
    candidate["audit_log"] = audit
    result = mod._score(_T4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["audit_sequence_match"] == 0.0


def test_wrong_final_entity_fails() -> None:
    mod = _load_t4_verify_module()
    candidate = dict(_REF)
    final_state = dict(_REF["final_state"])
    policies = [dict(item) for item in _REF["final_state"]["policies"]]
    policies[-1]["id"] = "pol-999"
    final_state["policies"] = policies
    candidate["final_state"] = final_state
    result = mod._score(_T4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["final_state_match"] == 0.0


def test_audit_timestamps_are_normalized_for_match() -> None:
    mod = _load_t4_verify_module()
    candidate = dict(_REF)
    audit = []
    for entry in _REF["audit_log"]:
        item = dict(entry)
        item["timestamp"] = "2099-12-31T23:59:59Z"
        audit.append(item)
    candidate["audit_log"] = audit
    result = mod._score(_T4_WS, candidate)
    assert result["partial_metrics"]["audit_sequence_match"] == 1.0


def test_alternate_starting_state_hidden_fixture_passes() -> None:
    mod = _load_t4_verify_module()
    candidate = {
        "starting_state_id": "alt-v1",
        "tool_sequence": _ALT["tool_sequence"],
        "final_state": _ALT["final_state"],
        "audit_log": _ALT["audit_log"],
    }
    result = mod._score(_T4_WS, candidate)
    assert result["primary_pass"] is True
    assert result["partial_metrics"]["final_state_match"] == 1.0
    assert result["partial_metrics"]["audit_sequence_match"] == 1.0


def test_alternate_starting_state_wrong_final_state_fails() -> None:
    mod = _load_t4_verify_module()
    candidate = {
        "starting_state_id": "alt-v1",
        "tool_sequence": _ALT["tool_sequence"],
        "final_state": _REF["final_state"],
        "audit_log": _ALT["audit_log"],
    }
    result = mod._score(_T4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["final_state_match"] == 0.0


def test_workspace_verifier_replay_is_deterministic() -> None:
    ref = _T4_WS / "reference.json"
    first = run_workspace_verifier(_T4_WS, ref)
    second = run_workspace_verifier(_T4_WS, ref)
    assert first == second


def test_malformed_candidate_json_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_T4_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "valid JSON" in proc.stderr


def test_malformed_candidate_shape_exits_nonzero(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_T4_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "JSON object" in proc.stderr
