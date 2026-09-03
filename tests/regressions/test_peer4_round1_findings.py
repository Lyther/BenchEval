"""Regressions for accepted peer #4 Round-1 findings F001-F006."""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from bencheval.evidence import EvidenceRecord
from bencheval.live_run_manifest import LiveRunRecord

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS = datetime(2026, 8, 7, tzinfo=UTC)


def _evidence_record() -> EvidenceRecord:
    return EvidenceRecord(
        run_id="immutable-evidence",
        task_id="task-1",
        model_id="model-1",
        execution_profile="E0",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.0,
        latency_sec=0.1,
        created_at=_TS,
    )


def test_f001_evidence_record_rejects_post_validation_reassignment() -> None:
    record = _evidence_record()

    with pytest.raises(ValidationError, match="frozen"):
        record.primary_pass = False


def test_f002_live_run_record_rejects_post_validation_reassignment() -> None:
    record = LiveRunRecord(
        run_id="immutable-live-run",
        host="dev-box",
        model_id="model-1",
        generated_at=_TS,
    )

    with pytest.raises(ValidationError, match="frozen"):
        record.status = "failed"


def test_f003_cli_domain_errors_never_emit_tracebacks(tmp_path: Path) -> None:
    missing = tmp_path / "missing.jsonl"
    commands = (
        ("export", str(missing), "--output", str(tmp_path / "warehouse"), 1),
        (
            "export-run",
            "--evidence",
            str(missing),
            "--output",
            str(tmp_path / "bundle"),
            1,
        ),
        ("doctor", "--backend", "local", "--profile", "E0", 2),
    )

    for *args, expected_status in commands:
        proc = subprocess.run(
            [sys.executable, "-m", "bencheval.cli", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == expected_status, (args, proc.stdout, proc.stderr)
        assert "Traceback" not in proc.stderr
        assert "error:" in proc.stderr.lower()


def test_f005_security_contract_declares_substitute_boundary() -> None:
    contract = _REPO_ROOT / "tests" / "specs" / "test_remaining_security_contracts.py"
    content = contract.read_text(encoding="utf-8")

    for required in (
        "SUBSTITUTE_JUSTIFICATION",
        "- substitute:",
        "- replaces:",
        "- necessity:",
        "- real-option:",
        "- proof-limit:",
        "- real-proof:",
    ):
        assert required in content, required
