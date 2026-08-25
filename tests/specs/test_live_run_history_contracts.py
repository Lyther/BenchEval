"""RED contracts for append-only live-run lifecycle consistency.

The registry keeps raw events, while rows sharing a ``run_id`` form one
operational lifecycle. These contracts preserve the observed same-status host
correction use case without allowing identity drift, backward state movement,
or time reversal.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed ``LiveRunRecord`` lifecycle rows in this module
- replaces: operator-generated registration events for a real benchmark run
- necessity: conflicting identity, backward transition, and decreasing-time
  events must be forced deterministically without corrupting the operator's
  real append-only registry; the production append/read implementation and a
  real mode-0600 JSONL file are still exercised in a disposable directory
- real-option: the CLI can create ordinary lifecycle rows but, once fixed,
  cannot safely create the invalid histories these negative assertions require
- proof-limit: diagnostic proof of local manifest event validation and raw
  ordering only; it does not prove CLI live qualification, artifact integrity,
  portable bundle export/import, backup, or benchmark execution
- real-proof: the operator registry contains a real BFCL same-status correction
  history; portable cross-host proof remains BLOCKED until roadmap R2 lands
- covered tests: every test in this module
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bencheval.exceptions import LiveRunManifestError
from bencheval.live_run_manifest import LiveRunRecord, append_live_run, read_live_runs

_T0 = datetime(2026, 8, 25, 1, 0, tzinfo=UTC)


def _event(
    *,
    status: str,
    minute: int,
    benchmark: str | None = "bfcl-v4",
    slice_id: str | None = "smoke-5",
    runtime: str | None = None,
    model_id: str = "gpt-5.2-2025-12-11",
    host: str = "dev-box-cpu",
) -> LiveRunRecord:
    return LiveRunRecord(
        run_id="run-history-contract",
        host=host,
        benchmark=benchmark,
        slice_id=slice_id,
        runtime=runtime,
        model_id=model_id,
        status=status,
        generated_at=_T0 + timedelta(minutes=minute),
    )


def test_valid_history_preserves_raw_events_and_latest_operational_event(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(manifest, _event(status="registered", minute=0, host="workstation"))
    append_live_run(manifest, _event(status="passed", minute=1))
    # A same-status correction is valid and preserves the earlier row.
    append_live_run(manifest, _event(status="passed", minute=2, host="dev-box-cpu-corrected"))

    history = read_live_runs(manifest)

    assert [row.status for row in history] == ["registered", "passed", "passed"]
    assert history[-1].host == "dev-box-cpu-corrected"


def test_optional_identity_axes_may_be_filled_once(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(
        manifest,
        _event(
            status="registered",
            minute=0,
            benchmark=None,
            slice_id=None,
            runtime=None,
        ),
    )
    append_live_run(
        manifest,
        _event(
            status="passed",
            minute=1,
            benchmark="bfcl-v4",
            slice_id="smoke-5",
            runtime=None,
        ),
    )

    history = read_live_runs(manifest)

    assert history[-1].benchmark == "bfcl-v4"
    assert history[-1].slice_id == "smoke-5"


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("registered", "registered"),
        ("registered", "running"),
        ("registered", "completed"),
        ("registered", "passed"),
        ("registered", "failed"),
        ("registered", "archived"),
        ("running", "running"),
        ("running", "completed"),
        ("running", "passed"),
        ("running", "failed"),
        ("running", "archived"),
        ("completed", "completed"),
        ("completed", "passed"),
        ("completed", "failed"),
        ("completed", "archived"),
        ("passed", "passed"),
        ("passed", "archived"),
        ("failed", "failed"),
        ("failed", "archived"),
        ("archived", "archived"),
    ],
)
def test_every_documented_forward_or_same_status_transition_is_allowed(
    before: str,
    after: str,
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(manifest, _event(status=before, minute=0))
    append_live_run(manifest, _event(status=after, minute=1))

    assert [row.status for row in read_live_runs(manifest)] == [before, after]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("running", "registered"),
        ("completed", "registered"),
        ("completed", "running"),
        ("passed", "registered"),
        ("passed", "running"),
        ("passed", "completed"),
        ("passed", "failed"),
        ("failed", "registered"),
        ("failed", "running"),
        ("failed", "completed"),
        ("failed", "passed"),
        ("archived", "registered"),
        ("archived", "running"),
        ("archived", "completed"),
        ("archived", "passed"),
        ("archived", "failed"),
    ],
)
def test_every_backward_or_cross_terminal_transition_is_rejected(
    before: str,
    after: str,
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(manifest, _event(status=before, minute=0))

    with pytest.raises(LiveRunManifestError):
        append_live_run(manifest, _event(status=after, minute=1))

    assert [row.status for row in read_live_runs(manifest)] == [before]


@pytest.mark.parametrize(
    "changed",
    [
        {"benchmark": "hle"},
        {"slice_id": "full"},
        {"runtime": "codex-cli"},
        {"model_id": "gpt-5.4-2026-03-05"},
    ],
)
def test_same_status_correction_rejects_identity_drift_within_one_run_id(
    changed: dict[str, str],
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(manifest, _event(status="passed", minute=0, runtime="claude-code"))

    fields: dict[str, object] = {
        "status": "passed",
        "minute": 1,
        "runtime": "claude-code",
    }
    fields.update(changed)
    with pytest.raises(LiveRunManifestError):
        append_live_run(manifest, _event(**fields))

    assert len(read_live_runs(manifest)) == 1


def test_equal_event_timestamps_are_allowed(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(manifest, _event(status="registered", minute=0))
    append_live_run(manifest, _event(status="running", minute=0))

    assert [row.status for row in read_live_runs(manifest)] == ["registered", "running"]


def test_append_rejects_decreasing_event_time(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(manifest, _event(status="registered", minute=1))

    with pytest.raises(LiveRunManifestError):
        append_live_run(manifest, _event(status="running", minute=0))

    assert read_live_runs(manifest)[-1].generated_at == _T0 + timedelta(minutes=1)
