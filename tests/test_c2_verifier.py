from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

from bencheval.admission import run_workspace_verifier

_ROOT = Path(__file__).resolve().parents[1]
_C2_WS = _ROOT / "config/tasks/core-8/workspaces/be-core-c2-regression-test-authoring"


def _load_c2_verify_module():
    path = _C2_WS / "verify.py"
    spec = importlib.util.spec_from_file_location("c2_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_passes_admission_verifier() -> None:
    report = run_workspace_verifier(_C2_WS, _C2_WS / "reference.test.json")
    assert report.primary_pass is True


def test_negative_fails_admission_verifier() -> None:
    report = run_workspace_verifier(_C2_WS, _C2_WS / "negative.test.json")
    assert report.primary_pass is False


def test_malformed_candidate_json_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.test.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_C2_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "valid JSON" in proc.stderr


def test_malformed_candidate_shape_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.test.json"
    bad.write_text("[]", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_C2_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "JSON object" in proc.stderr


def test_gold_apply_failure_returns_metric_dict(tmp_path: Path) -> None:
    mod = _load_c2_verify_module()
    workspace = tmp_path / "ws"
    shutil.copytree(_C2_WS, workspace)
    (workspace / "gold.patch.json").write_text(
        '{"files": {"repo/tests/evil.py": "x = 1\\n"}}',
        encoding="utf-8",
    )
    candidate = json.loads((_C2_WS / "reference.test.json").read_text(encoding="utf-8"))
    result = mod._score(workspace, candidate)
    assert isinstance(result["partial_metrics"], dict)
    assert "test_fails_before_gold_patch" in result["partial_metrics"]


def test_source_file_write_rejected() -> None:
    mod = _load_c2_verify_module()
    candidate = {
        "files": {
            "repo/src/mathops.py": "def divide(a: int, b: int) -> float:\n    return a / b\n",
        },
    }
    result = mod._score(_C2_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["test_fails_before_gold_patch"] == 0.0


def test_path_traversal_rejected(tmp_path: Path) -> None:
    mod = _load_c2_verify_module()
    dest = tmp_path / "sandbox"
    shutil.copytree(_C2_WS / "repo", dest / "repo")
    outside = tmp_path / "escape.py"
    assert (
        mod._apply_files(
            dest,
            {"../escape.py": "x = 1\n"},
            require_under=mod._TESTS_PREFIX,
        )
        is False
    )
    assert not outside.exists()


def test_regression_passing_before_gold_fails() -> None:
    mod = _load_c2_verify_module()
    candidate = {
        "files": {
            "repo/tests/test_regression_divide.py": (
                "from mathops import divide\n\n\n"
                "def test_divide_regression_trivial() -> None:\n"
                "    assert divide(4, 2) == 2\n"
            ),
        },
    }
    result = mod._score(_C2_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["test_fails_before_gold_patch"] == 0.0


def test_regression_failing_after_gold_fails() -> None:
    mod = _load_c2_verify_module()
    candidate = {
        "files": {
            "repo/tests/test_regression_divide.py": (
                "from mathops import divide\n\n\n"
                "def test_divide_regression_wrong() -> None:\n"
                "    assert divide(7, 2) == 99\n"
            ),
        },
    }
    result = mod._score(_C2_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["test_fails_before_gold_patch"] == 1.0
    assert result["partial_metrics"]["test_passes_after_gold_patch"] == 0.0
