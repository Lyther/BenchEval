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
_C4_WS = _ROOT / "config/tasks/core-16/workspaces/be-core-c4-minimal-refactor-under-invariants"
_REF = json.loads((_C4_WS / "reference.patch.json").read_text(encoding="utf-8"))


def _load_c4_verify_module():
    path = _C4_WS / "verify.py"
    spec = importlib.util.spec_from_file_location("c4_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_passes_admission_verifier() -> None:
    report = run_workspace_verifier(_C4_WS, _C4_WS / "reference.patch.json")
    assert report.primary_pass is True


def test_negative_fails_admission_verifier() -> None:
    report = run_workspace_verifier(_C4_WS, _C4_WS / "negative.patch.json")
    assert report.primary_pass is False


def test_apply_candidate_rejects_disallowed_file() -> None:
    mod = _load_c4_verify_module()
    candidate = {
        "files": {
            "repo/src/shipkit/models.py": "class ShipKitError(Exception):\n    pass\n",
        },
    }
    with tempfile.TemporaryDirectory(prefix="bencheval-c4-test-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(_C4_WS / "repo", sandbox / "repo")
        assert mod._apply_candidate(candidate, sandbox) is False


def test_apply_candidate_rejects_test_modification() -> None:
    mod = _load_c4_verify_module()
    candidate = {
        "files": {
            "repo/tests/test_visible.py": "def test_broken() -> None:\n    assert False\n",
        },
    }
    with tempfile.TemporaryDirectory(prefix="bencheval-c4-test-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(_C4_WS / "repo", sandbox / "repo")
        assert mod._apply_candidate(candidate, sandbox) is False


def test_score_rejects_changed_test_file() -> None:
    mod = _load_c4_verify_module()
    candidate = dict(_REF)
    candidate["files"] = dict(_REF["files"])
    broken_test = "def test_broken() -> None:\n    assert False\n"
    candidate["files"]["repo/tests/test_visible.py"] = broken_test
    result = mod._score(_C4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["patch_applies"] == 0.0


def test_score_rejects_public_api_signature_change() -> None:
    mod = _load_c4_verify_module()
    negative = json.loads((_C4_WS / "negative.patch.json").read_text(encoding="utf-8"))
    result = mod._score(_C4_WS, negative)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["public_api_unchanged"] == 0.0


def test_score_rejects_diff_locality_violation() -> None:
    mod = _load_c4_verify_module()
    candidate = dict(_REF)
    candidate["files"] = dict(_REF["files"])
    candidate["files"]["repo/src/shipkit/models.py"] = (
        "from dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass Parcel:\n"
        "    weight_oz: int\n    length_in: int\n    width_in: int\n    height_in: int\n"
        "    fragile: bool = False\n"
    )
    result = mod._score(_C4_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["patch_applies"] == 0.0


def test_invariants_reject_excessive_line_count() -> None:
    mod = _load_c4_verify_module()
    candidate = {
        "files": {
            "repo/src/shipkit/rating.py": "\n".join(["# padding"] * 90),
        },
    }
    with tempfile.TemporaryDirectory(prefix="bencheval-c4-test-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(_C4_WS / "repo", sandbox / "repo")
        assert mod._invariants_ok(sandbox, candidate) is False


def test_hidden_integration_passes_for_reference() -> None:
    mod = _load_c4_verify_module()
    with tempfile.TemporaryDirectory(prefix="bencheval-c4-test-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(_C4_WS / "repo", sandbox / "repo")
        assert mod._apply_candidate(_REF, sandbox) is True
        assert mod._hidden_integration_pass(sandbox / "repo") is True


def test_malformed_candidate_json_exits_nonzero(tmp_path: Path) -> None:
    bad = tmp_path / "bad.patch.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_C4_WS / "verify.py"), str(bad)],
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
        [sys.executable, str(_C4_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "JSON object" in proc.stderr
