from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

from bencheval.admission import run_workspace_verifier

_ROOT = Path(__file__).resolve().parents[1]
_A4_WS = _ROOT / "config/tasks/core-16/workspaces/be-core-a4-feature-with-invariants"
_REF = json.loads((_A4_WS / "reference.patch.json").read_text(encoding="utf-8"))


def _load_a4_verify_module():
    path = _A4_WS / "verify.py"
    spec = importlib.util.spec_from_file_location("a4_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_passes_admission_verifier() -> None:
    report = run_workspace_verifier(_A4_WS, _A4_WS / "reference.patch.json")
    assert report.primary_pass is True


def test_negative_fails_admission_verifier() -> None:
    report = run_workspace_verifier(_A4_WS, _A4_WS / "negative.patch.json")
    assert report.primary_pass is False


def test_wrong_feature_flag_fails() -> None:
    mod = _load_a4_verify_module()
    candidate = dict(_REF)
    candidate["feature_flag_id"] = "wrong-flag"
    result = mod._score(_A4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["feature_flag_identified"] == 0.0


def test_test_modification_rejected() -> None:
    mod = _load_a4_verify_module()
    candidate = dict(_REF)
    candidate["files"] = dict(_REF["files"])
    candidate["files"]["repo/tests/test_extra.py"] = "def test_x() -> None:\n    assert True\n"
    result = mod._score(_A4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["patch_compiles"] == 0.0


def test_incomplete_feature_fails_functional_pass() -> None:
    mod = _load_a4_verify_module()
    candidate = json.loads((_A4_WS / "negative.patch.json").read_text(encoding="utf-8"))
    result = mod._score(_A4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["feature_functional_pass"] == 0.0


def test_breaking_legacy_invariant_fails() -> None:
    mod = _load_a4_verify_module()
    candidate = dict(_REF)
    candidate["files"] = dict(_REF["files"])
    candidate["files"]["repo/src/normalize.py"] = (
        "import flags\n\n\n"
        "def parse_tokens(line: str) -> list[int]:\n"
        "    parts = line.split()\n"
        "    return [int(part.replace(',', '')) for part in parts if part]\n"
    )
    result = mod._score(_A4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["legacy_invariants_pass"] == 0.0


def test_extra_source_file_fails_minimality() -> None:
    mod = _load_a4_verify_module()
    candidate = dict(_REF)
    candidate["files"] = dict(_REF["files"])
    candidate["files"]["repo/src/extra.py"] = "VALUE = 1\n"
    result = mod._score(_A4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["patch_minimality"] == 0.0


def test_path_traversal_rejected(tmp_path: Path) -> None:
    mod = _load_a4_verify_module()
    dest = tmp_path / "sandbox"
    shutil.copytree(_A4_WS / "repo", dest / "repo")
    outside = tmp_path / "owned.txt"
    assert mod._apply_patch(dest, {"../owned.txt": "owned"}) is False
    assert not outside.exists()


def test_malformed_candidate_json_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.patch.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_A4_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "valid JSON" in proc.stderr
