"""RED contracts for validating an already-written live-run event history.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed ``LiveRunRecord`` event rows in every test here
- replaces: operator-generated lifecycle events in the real machine-local
  ``runs.jsonl`` registry
- necessity: illegal transitions and identity drift must be written directly
  to a disposable real JSONL file to prove the reader does not trust history
  solely because individual rows parse; corrupting the operator registry is
  unsafe and the production append API correctly refuses these rows
- real-option: a real CLI path cannot create the invalid on-disk history once
  append-time validation is active
- proof-limit: diagnostic reader-validation proof only; it does not prove
  concurrent locking, backup, or benchmark execution
- real-proof: operator-host Terminal-Bench Codex
  ``run-20260825-171829-685914-aa08dd1d`` proof
  ``sha256:fca2295d6844e4dda99799527561985885a90b59e01c865082510eaa63d90c06``
  and GPQA ``run-20260825-160511-036214-304c2cee`` proof
  ``sha256:aa19d02b7d1457d0f43d9588b3d08c042e967a981ed8537068412e1797ff0eda``
  remain externally retained on the operator host, not in this checkout
- covered tests: every test in this module
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bencheval.exceptions import LiveRunManifestError
from bencheval.live_run_manifest import LiveRunRecord, read_live_runs

_T0 = datetime(2026, 8, 25, 8, 0, tzinfo=UTC)


def _event(*, status: str, minute: int, model_id: str = "gpt-5.2-2025-12-11") -> LiveRunRecord:
    return LiveRunRecord(
        run_id="run-reader-validation",
        host="dev-box-cpu",
        benchmark="bfcl-v4",
        slice_id="smoke-5",
        model_id=model_id,
        status=status,
        generated_at=_T0 + timedelta(minutes=minute),
    )


def _write_raw(path: Path, *rows: LiveRunRecord) -> None:
    path.write_text("".join(row.model_dump_json() + "\n" for row in rows), encoding="utf-8")


def test_reader_rejects_backward_transition_written_outside_append_api(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    _write_raw(
        manifest,
        _event(status="passed", minute=0),
        _event(status="running", minute=1),
    )

    with pytest.raises(LiveRunManifestError, match=r"transition|passed|running"):
        read_live_runs(manifest)


def test_reader_rejects_identity_drift_written_outside_append_api(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    _write_raw(
        manifest,
        _event(status="completed", minute=0),
        _event(status="archived", minute=1, model_id="gpt-5.4-2026-03-05"),
    )

    with pytest.raises(LiveRunManifestError, match=r"model_id|immutable"):
        read_live_runs(manifest)


def test_reader_preserves_a_legal_raw_history(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    _write_raw(
        manifest,
        _event(status="registered", minute=0),
        _event(status="completed", minute=1),
        _event(status="archived", minute=2),
    )

    rows = read_live_runs(manifest)

    assert [row.status for row in rows] == ["registered", "completed", "archived"]
