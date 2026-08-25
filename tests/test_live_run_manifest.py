"""Live run manifest (``live_run_v1``) write/read path and CLI registration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from bencheval.cli import main
from bencheval.evidence import EvidenceRecord
from bencheval.exceptions import LiveRunManifestError
from bencheval.live_run_manifest import (
    LIVE_RUN_SCHEMA_VERSION,
    LiveRunRecord,
    append_live_run,
    default_runs_manifest_path,
    project_live_runs,
    read_live_run_projections,
    read_live_runs,
)

_TS = datetime(2026, 6, 18, 15, 5, 0, tzinfo=UTC)


def _record(**overrides: object) -> LiveRunRecord:
    base: dict[str, object] = {
        "run_id": "tb-claude-code-haiku-one-20260618T150500Z",
        "host": "peer-host-01",
        "benchmark": "terminal-bench",
        "slice_id": "one",
        "runtime": "claude-code",
        "model_id": "claude-3-5-haiku",
        "evidence_path": "/repo/results/evidence/tb-haiku.jsonl",
        "report_path": "/repo/results/reports/tb-haiku.md",
        "bundle_path": "/repo/results/bundles/tb-haiku.tar.gz",
        "status": "registered",
        "notes": "peer control-plane run",
        "generated_at": _TS,
    }
    base.update(overrides)
    return LiveRunRecord(**base)


def _write_evidence(
    path: Path,
    *,
    run_id: str = "tb-claude-code-haiku-one-20260618T150500Z",
) -> None:
    record = EvidenceRecord(
        run_id=run_id,
        task_id="terminal-bench/fix-git",
        model_id="claude-3-5-haiku",
        execution_profile="E2",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.01,
        latency_sec=12.0,
        created_at=_TS,
    )
    path.write_text(record.model_dump_json() + "\n", encoding="utf-8")


def test_schema_version_is_live_run_v1() -> None:
    assert LIVE_RUN_SCHEMA_VERSION == "live_run_v1"
    assert _record().schema_version == "live_run_v1"


def test_round_trip_write_then_read(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    target = append_live_run(manifest, _record())
    assert target == manifest.resolve()
    rows = read_live_runs(manifest)
    assert len(rows) == 1
    record = rows[0]
    assert record.run_id == "tb-claude-code-haiku-one-20260618T150500Z"
    assert record.benchmark == "terminal-bench"
    assert record.slice_id == "one"
    assert record.runtime == "claude-code"
    assert record.status == "registered"
    assert record.generated_at == _TS


def test_append_is_additive_and_preserves_order(tmp_path: Path) -> None:
    manifest = tmp_path / "nested" / "dir" / "runs.jsonl"
    append_live_run(manifest, _record(run_id="run-a"))
    append_live_run(manifest, _record(run_id="run-b"))
    rows = read_live_runs(manifest)
    assert [r.run_id for r in rows] == ["run-a", "run-b"]
    assert manifest.parent.is_dir()


def test_read_skips_blank_lines(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(manifest, _record(run_id="run-a"))
    with manifest.open("a", encoding="utf-8") as handle:
        handle.write("\n   \n")
    append_live_run(manifest, _record(run_id="run-b"))
    rows = read_live_runs(manifest)
    assert [r.run_id for r in rows] == ["run-a", "run-b"]


def test_optional_axes_default_to_none(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    record = LiveRunRecord(
        run_id="run-min",
        host="h",
        model_id="local/harness",
        generated_at=_TS,
    )
    append_live_run(manifest, record)
    rows = read_live_runs(manifest)
    assert rows[0].benchmark is None
    assert rows[0].slice_id is None
    assert rows[0].runtime is None
    assert rows[0].evidence_path is None
    assert rows[0].status == "registered"
    assert rows[0].notes == ""


def test_extra_field_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    data = _record().model_dump(mode="json")
    data["api_key"] = "nope"
    manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
    with pytest.raises(LiveRunManifestError, match="line 1"):
        read_live_runs(manifest)


def test_missing_required_field_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="run_id"):
        LiveRunRecord(host="h", model_id="m", generated_at=_TS)


def test_invalid_status_rejected(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    data = _record().model_dump(mode="json")
    data["status"] = "deleted"
    manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
    with pytest.raises(LiveRunManifestError, match="line 1"):
        read_live_runs(manifest)


def test_malformed_json_line_reports_line_number(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(manifest, _record(run_id="run-a"))
    with manifest.open("a", encoding="utf-8") as handle:
        handle.write("{not json}\n")
    with pytest.raises(LiveRunManifestError, match="line 2"):
        read_live_runs(manifest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("notes", "token=sk-abcdef123456"),
        ("model_id", "x-sk-abcdef123456y"),
        ("host", "h;Authorization: Bearer abc"),
        ("run_id", "run;password=1234"),
    ],
)
def test_secret_like_content_rejected(field: str, value: str, tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="secret"):
        _record(**{field: value})


def test_secret_in_stored_line_rejected_on_read(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    data = _record().model_dump(mode="json")
    data["notes"] = "leaked api_key=ABC123"
    manifest.write_text(json.dumps(data) + "\n", encoding="utf-8")
    with pytest.raises(LiveRunManifestError, match="secret"):
        read_live_runs(manifest)


def test_directory_target_rejected(tmp_path: Path) -> None:
    target = tmp_path / "isadir"
    target.mkdir()
    with pytest.raises(LiveRunManifestError, match="not a regular file"):
        append_live_run(target, _record())


def test_read_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(LiveRunManifestError, match="cannot read"):
        read_live_runs(tmp_path / "nope.jsonl")
    assert not (tmp_path / "nope.jsonl.lock").exists()


def test_project_live_runs_uses_last_valid_event(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(manifest, _record(status="registered", notes="start"))
    append_live_run(
        manifest,
        _record(
            status="completed",
            notes="done",
            generated_at=datetime(2026, 6, 18, 15, 6, 0, tzinfo=UTC),
            evidence_path="/later/evidence.jsonl",
        ),
    )
    views = read_live_run_projections(manifest)
    assert len(views) == 1
    view = views[0]
    assert view.status == "completed"
    assert view.event_count == 2
    assert view.notes == "done"
    assert view.evidence_path == "/later/evidence.jsonl"
    assert view.first_generated_at == _TS
    assert project_live_runs(read_live_runs(manifest)) == views


def test_cli_evidence_list_current_projects_latest_state(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = tmp_path / "runs.jsonl"
    append_live_run(manifest, _record(status="registered", notes="start"))
    append_live_run(
        manifest,
        _record(
            status="completed",
            notes="done",
            generated_at=datetime(2026, 6, 18, 15, 6, 0, tzinfo=UTC),
        ),
    )
    code = main(["evidence", "list", "--current", "--manifest-path", str(manifest)])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["runs"][0]["status"] == "completed"
    assert payload["runs"][0]["event_count"] == 2
    assert payload["runs"][0]["notes"] == "done"


def test_default_runs_manifest_path_under_repo_results() -> None:
    path = default_runs_manifest_path()
    assert path.name == "runs.jsonl"
    assert path.parent.as_posix().endswith("results/manifests")


def test_cli_register_appends_record(tmp_path: Path) -> None:
    manifest = tmp_path / "manifests" / "runs.jsonl"
    evidence = tmp_path / "evidence" / "tb-haiku.jsonl"
    evidence.parent.mkdir(parents=True)
    _write_evidence(evidence)

    code = main(
        [
            "evidence",
            "register",
            "--run-id",
            "tb-claude-code-haiku-one-20260618T150500Z",
            "--model",
            "claude-3-5-haiku",
            "--benchmark",
            "terminal-bench",
            "--slice",
            "one",
            "--runtime",
            "claude-code",
            "--evidence",
            str(evidence),
            "--status",
            "completed",
            "--notes",
            "peer control-plane run",
            "--host",
            "peer-host-01",
            "--manifest-path",
            str(manifest),
        ],
    )
    assert code == 0

    rows = read_live_runs(manifest)
    assert len(rows) == 1
    record = rows[0]
    assert record.run_id == "tb-claude-code-haiku-one-20260618T150500Z"
    assert record.model_id == "claude-3-5-haiku"
    assert record.benchmark == "terminal-bench"
    assert record.slice_id == "one"
    assert record.runtime == "claude-code"
    assert record.status == "completed"
    assert record.evidence_path == str(evidence.resolve())
    assert record.generated_at.tzinfo is not None


def test_cli_archive_may_omit_filled_axes_but_not_replace_them(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    common = [
        "evidence",
        "register",
        "--run-id",
        "run-fill-once-cli",
        "--model",
        "gpt-5.2-2025-12-11",
        "--host",
        "dev-box-cpu",
        "--manifest-path",
        str(manifest),
        "--allow-missing-artifacts",
    ]

    completed = main(
        [
            *common,
            "--benchmark",
            "terminal-bench",
            "--slice",
            "core-8",
            "--runtime",
            "claude-code",
            "--status",
            "completed",
        ],
    )
    archived_without_axes = main([*common, "--status", "archived"])
    archived_with_drift = main(
        [
            *common,
            "--benchmark",
            "hle",
            "--status",
            "archived",
        ],
    )

    assert completed == 0
    assert archived_without_axes == 0
    assert archived_with_drift == 1
    rows = read_live_runs(manifest)
    assert len(rows) == 2
    assert (rows[0].benchmark, rows[0].slice_id, rows[0].runtime) == (
        "terminal-bench",
        "core-8",
        "claude-code",
    )
    assert (rows[1].benchmark, rows[1].slice_id, rows[1].runtime) == (None, None, None)


def test_cli_register_rejects_secret(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    code = main(
        [
            "evidence",
            "register",
            "--run-id",
            "run-secret",
            "--model",
            "claude-3-5-haiku",
            "--status",
            "registered",
            "--notes",
            "token=sk-abcdef123456",
            "--host",
            "h",
            "--manifest-path",
            str(manifest),
        ],
    )
    assert code == 1
    assert not manifest.exists()


def test_cli_register_requires_run_id(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "evidence",
                "register",
                "--model",
                "claude-3-5-haiku",
                "--manifest-path",
                str(tmp_path / "runs.jsonl"),
            ],
        )
