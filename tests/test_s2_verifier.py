from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

from bencheval.admission import run_workspace_verifier

_ROOT = Path(__file__).resolve().parents[1]
_S2_WS = _ROOT / "config/tasks/core-16/workspaces/be-core-s2-authorization-matrix-regression"
_REF = json.loads((_S2_WS / "reference.patch.json").read_text(encoding="utf-8"))


def _load_s2_verify_module():
    path = _S2_WS / "verify.py"
    spec = importlib.util.spec_from_file_location("s2_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_passes_admission_verifier() -> None:
    report = run_workspace_verifier(_S2_WS, _S2_WS / "reference.patch.json")
    assert report.primary_pass is True


def test_negative_fails_admission_verifier() -> None:
    report = run_workspace_verifier(_S2_WS, _S2_WS / "negative.patch.json")
    assert report.primary_pass is False


def test_valid_behavior_preserved_on_reference() -> None:
    mod = _load_s2_verify_module()
    result = mod._score(_S2_WS, _REF)
    assert result["partial_metrics"]["valid_behavior_preserved"] == 1.0


def test_negative_fails_authorization_matrix() -> None:
    mod = _load_s2_verify_module()
    result = mod._score(
        _S2_WS,
        json.loads((_S2_WS / "negative.patch.json").read_text(encoding="utf-8")),
    )
    assert result["partial_metrics"]["authorization_matrix_match"] == 0.0


def test_privilege_escalation_rejected() -> None:
    mod = _load_s2_verify_module()
    candidate = {
        "files": {
            "repo/src/authz.py": (
                '"""Role-based authorization for internal resources."""\n\n'
                "from __future__ import annotations\n\n"
                '_ROLES = frozenset({"viewer", "editor", "admin"})\n'
                '_RESOURCES = frozenset({"document", "settings", "audit_log"})\n'
                '_ACTIONS = frozenset({"read", "write", "delete"})\n\n'
                "_PERMS: dict[tuple[str, str, str], bool] = {\n"
                '    ("viewer", "read", "document"): True,\n'
                '    ("viewer", "delete", "document"): True,\n'
                "}\n\n\n"
                "def can(role: str, action: str, resource: str) -> bool:\n"
                "    if role not in _ROLES or action not in _ACTIONS "
                "or resource not in _RESOURCES:\n"
                "        return False\n"
                "    return _PERMS.get((role, action, resource), False)\n"
            ),
        },
    }
    result = mod._score(_S2_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["authorization_matrix_match"] == 0.0


def test_test_modification_rejected() -> None:
    mod = _load_s2_verify_module()
    candidate = dict(_REF)
    candidate["files"] = dict(_REF["files"])
    candidate["files"]["repo/tests/test_extra.py"] = "def test_x() -> None:\n    assert True\n"
    result = mod._score(_S2_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["valid_behavior_preserved"] == 0.0


def test_path_traversal_rejected(tmp_path: Path) -> None:
    mod = _load_s2_verify_module()
    dest = tmp_path / "sandbox"
    shutil.copytree(_S2_WS / "repo", dest / "repo")
    outside = tmp_path / "owned.txt"
    assert mod._apply_patch(dest, {"../owned.txt": "owned"}) is False
    assert not outside.exists()


def test_malformed_candidate_json_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.patch.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_S2_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "valid JSON" in proc.stderr
