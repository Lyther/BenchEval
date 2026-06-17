from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from bencheval.admission import run_workspace_verifier

_ROOT = Path(__file__).resolve().parents[1]
_C3_WS = _ROOT / "config/tasks/core-16/workspaces/be-core-c3-backward-compatible-config-migration"


def _load_c3_verify_module():
    path = _C3_WS / "verify.py"
    spec = importlib.util.spec_from_file_location("c3_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_apply_candidate_rejects_sibling_prefix_path_escape(tmp_path: Path) -> None:
    mod = _load_c3_verify_module()
    dest = tmp_path / "sandbox"
    dest.mkdir()
    sibling = tmp_path / "sandbox-escape"
    sibling.mkdir()
    outside = sibling / "owned.txt"
    assert mod._apply_candidate({"files": {"../sandbox-escape/owned.txt": "owned"}}, dest) is False
    assert not outside.exists()


def test_apply_candidate_rejects_absolute_paths(tmp_path: Path) -> None:
    mod = _load_c3_verify_module()
    dest = tmp_path / "sandbox"
    dest.mkdir()
    outside = tmp_path / "owned.txt"
    assert mod._apply_candidate({"files": {str(outside): "owned"}}, dest) is False
    assert not outside.exists()


def test_apply_candidate_rejects_dot_segment_tests_path(tmp_path: Path) -> None:
    mod = _load_c3_verify_module()
    dest = tmp_path / "sandbox"
    shutil.copytree(_C3_WS / "repo", dest / "repo")
    evil = dest / "repo" / "tests" / "evil.py"
    assert mod._apply_candidate({"files": {"repo/./tests/evil.py": "x = 1\n"}}, dest) is False
    assert not evil.exists()


def _reference_files() -> dict[str, str]:
    payload = json.loads((_C3_WS / "reference.patch.json").read_text(encoding="utf-8"))
    files = payload["files"]
    assert isinstance(files, dict)
    return files


def test_score_rejects_added_test_file() -> None:
    mod = _load_c3_verify_module()
    candidate = {
        "files": {
            **_reference_files(),
            "repo/tests/test_extra.py": "def test_extra() -> None:\n    assert True\n",
        },
    }
    result = mod._score(_C3_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["patch_applies"] == 0.0


def test_score_rejects_changed_test_file() -> None:
    mod = _load_c3_verify_module()
    ref_files = _reference_files()
    candidate = {
        "files": {
            **ref_files,
            "repo/tests/test_visible.py": "def test_broken() -> None:\n    assert False\n",
        },
    }
    result = mod._score(_C3_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["patch_applies"] == 0.0


def test_tests_unchanged_rejects_changed_test_file() -> None:
    mod = _load_c3_verify_module()
    with tempfile.TemporaryDirectory(prefix="bencheval-c3-test-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(_C3_WS / "repo", sandbox / "repo")
        ref_files = _reference_files()
        assert mod._apply_candidate({"files": ref_files}, sandbox) is True
        (sandbox / "repo" / "tests" / "test_visible.py").write_text(
            "def test_broken() -> None:\n    assert False\n",
            encoding="utf-8",
        )
        assert mod._tests_unchanged(_C3_WS, sandbox) is False


def test_tests_unchanged_rejects_added_test_file() -> None:
    mod = _load_c3_verify_module()
    with tempfile.TemporaryDirectory(prefix="bencheval-c3-test-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(_C3_WS / "repo", sandbox / "repo")
        ref_files = _reference_files()
        assert mod._apply_candidate({"files": ref_files}, sandbox) is True
        (sandbox / "repo" / "tests" / "test_extra.py").write_text(
            "def test_extra() -> None:\n    assert True\n",
            encoding="utf-8",
        )
        assert mod._tests_unchanged(_C3_WS, sandbox) is False


def test_tests_unchanged_rejects_removed_test_file() -> None:
    mod = _load_c3_verify_module()
    with tempfile.TemporaryDirectory(prefix="bencheval-c3-test-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(_C3_WS / "repo", sandbox / "repo")
        ref_files = _reference_files()
        assert mod._apply_candidate({"files": ref_files}, sandbox) is True
        (sandbox / "repo" / "tests" / "test_visible.py").unlink()
        assert mod._tests_unchanged(_C3_WS, sandbox) is False


def test_tests_unchanged_ignores_runtime_pycache() -> None:
    mod = _load_c3_verify_module()
    with tempfile.TemporaryDirectory(prefix="bencheval-c3-test-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(_C3_WS / "repo", sandbox / "repo")
        pycache = sandbox / "repo" / "tests" / "__pycache__"
        pycache.mkdir()
        (pycache / "test_visible.cpython-314-pytest-9.0.3.pyc").write_bytes(b"cache")
        assert mod._tests_unchanged(_C3_WS, sandbox) is True


def test_reference_passes_admission_verifier() -> None:
    report = run_workspace_verifier(_C3_WS, _C3_WS / "reference.patch.json")
    assert report.primary_pass is True


def test_negative_fails_admission_verifier() -> None:
    report = run_workspace_verifier(_C3_WS, _C3_WS / "negative.patch.json")
    assert report.primary_pass is False
    assert report.partial_metrics["old_configs_parse"] == 0.0


def test_malformed_candidate_json_exits_nonzero(tmp_path: Path) -> None:
    bad = tmp_path / "bad.patch.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_C3_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "valid JSON" in proc.stderr


def test_malformed_candidate_shape_exits_nonzero(tmp_path: Path) -> None:
    bad = tmp_path / "bad.patch.json"
    bad.write_text("[]", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_C3_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "JSON object" in proc.stderr
