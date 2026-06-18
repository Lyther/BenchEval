from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

from bencheval.admission import run_workspace_verifier
from tests.selftest_paths import core8_workspace

_ROOT = Path(__file__).resolve().parents[1]
_A1_WS = core8_workspace("be-core-a1-multi-file-repo-fix")
_REF = json.loads((_A1_WS / "reference.patch.json").read_text(encoding="utf-8"))


def _load_a1_verify_module():
    path = _A1_WS / "verify.py"
    spec = importlib.util.spec_from_file_location("a1_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_passes_admission_verifier() -> None:
    report = run_workspace_verifier(_A1_WS, _A1_WS / "reference.patch.json")
    assert report.primary_pass is True


def test_negative_fails_admission_verifier() -> None:
    report = run_workspace_verifier(_A1_WS, _A1_WS / "negative.patch.json")
    assert report.primary_pass is False


def test_wrong_root_cause_fails() -> None:
    mod = _load_a1_verify_module()
    candidate = dict(_REF)
    candidate["root_cause_id"] = "wrong-root-cause"
    result = mod._score(_A1_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["root_cause_identified"] == 0.0


def test_test_modification_rejected() -> None:
    mod = _load_a1_verify_module()
    candidate = dict(_REF)
    candidate["files"] = dict(_REF["files"])
    candidate["files"]["repo/tests/test_extra.py"] = "def test_x() -> None:\n    assert True\n"
    result = mod._score(_A1_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["patch_compiles"] == 0.0


def test_extra_source_file_fails_minimality() -> None:
    mod = _load_a1_verify_module()
    candidate = dict(_REF)
    candidate["files"] = dict(_REF["files"])
    candidate["files"]["repo/src/extra.py"] = "VALUE = 1\n"
    result = mod._score(_A1_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["patch_minimality"] == 0.0


def test_path_traversal_rejected(tmp_path: Path) -> None:
    mod = _load_a1_verify_module()
    dest = tmp_path / "sandbox"
    shutil.copytree(_A1_WS / "repo", dest / "repo")
    outside = tmp_path / "owned.txt"
    assert mod._apply_patch(dest, {"../owned.txt": "owned"}) is False
    assert not outside.exists()


def test_malformed_candidate_json_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.patch.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_A1_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "valid JSON" in proc.stderr
