from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from bencheval.admission import run_workspace_verifier

_ROOT = Path(__file__).resolve().parents[1]
_S3_WS = _ROOT / "config/tasks/core-16/workspaces/be-core-s3-alert-triage-evidence-json"
_REF = json.loads((_S3_WS / "reference.json").read_text(encoding="utf-8"))


def _load_s3_verify_module():
    path = _S3_WS / "verify.py"
    spec = importlib.util.spec_from_file_location("s3_verify", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load verifier module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_passes_admission_verifier() -> None:
    report = run_workspace_verifier(_S3_WS, _S3_WS / "reference.json")
    assert report.primary_pass is True


def test_negative_fails_admission_verifier() -> None:
    report = run_workspace_verifier(_S3_WS, _S3_WS / "negative.json")
    assert report.primary_pass is False


def test_wrong_severity_fails() -> None:
    mod = _load_s3_verify_module()
    candidate = json.loads(json.dumps(_REF))
    candidate["verdicts"][0]["severity"] = "low"
    result = mod._score(_S3_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["label_accuracy"] < 1.0


def test_hallucinated_evidence_id_fails() -> None:
    mod = _load_s3_verify_module()
    candidate = json.loads(json.dumps(_REF))
    candidate["verdicts"][2]["evidence_ids"] = ["EV-404"]
    result = mod._score(_S3_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["evidence_id_accuracy"] < 1.0


def test_hidden_alert_verdict_fails() -> None:
    mod = _load_s3_verify_module()
    candidate = json.loads(json.dumps(_REF))
    candidate["verdicts"].append(
        {
            "alert_id": "ALERT-005",
            "disposition": "false_positive",
            "severity": "info",
            "evidence_ids": [],
        },
    )
    result = mod._score(_S3_WS, candidate)
    assert result["primary_pass"] is False
    assert result["partial_metrics"]["unsupported_claim_count"] > 0.0


def test_missing_required_field_fails() -> None:
    mod = _load_s3_verify_module()
    candidate = json.loads(json.dumps(_REF))
    del candidate["verdicts"][3]["severity"]
    result = mod._score(_S3_WS, candidate)
    assert result["primary_pass"] is False


def test_malformed_candidate_json_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_S3_WS / "verify.py"), str(bad)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "valid JSON" in proc.stderr
