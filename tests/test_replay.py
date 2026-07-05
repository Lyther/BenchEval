"""Tests for the general-purpose run record/replay feature.

Test policy: canonical run records are RAW (no redaction). Redaction tests
belong to the public-presentation layer only.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.cli import main
from bencheval.evidence import EvidenceRecord
from bencheval.exceptions import BenchEvalError, EvidenceValidationError
from bencheval.presentation import redact_for_public_presentation, strip_ansi
from bencheval.replay import (
    LegacyMomoEvent,
    RecordEvent,
    RecordFooter,
    RecordHeader,
    RunRecord,
    load_run_record,
    replay,
    sanitize_for_replay,
    verify_bound_evidence,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FLAG_MARKER = "FLAG{synthetic_secret_123}"
_SECRET_MARKER = "sk-abcd1234567890efgh"


def _v1_header(
    *,
    run_id: str = "run-1",
    benchmark_id: str = "cybench",
    evidence_sha256: str | None = None,
) -> dict[str, object]:
    h: dict[str, object] = {
        "schema_version": "bencheval_run_record_v1",
        "record_type": "header",
        "run_id": run_id,
        "benchmark_id": benchmark_id,
        "runtime_id": "kilo",
        "model_id": "glm-5.2",
        "redaction_policy": "none",
        "contains_sensitive": True,
    }
    if evidence_sha256 is not None:
        h["evidence_sha256"] = evidence_sha256
    return h


def _v1_event(
    *,
    seq: int = 1,
    kind: str = "system",
    message: str = "hello",
    elapsed: float = 0.0,
    instance_id: str | None = None,
    challenge_id: str | None = None,
    attempt: int | None = None,
    data: dict[str, object] | None = None,
    display: str = "",
) -> dict[str, object]:
    return {
        "schema_version": "bencheval_run_record_v1",
        "record_type": "event",
        "seq": seq,
        "time": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "elapsed_sec": elapsed,
        "kind": kind,
        "instance_id": instance_id,
        "challenge_id": challenge_id,
        "attempt": attempt,
        "message": message,
        "data": data or {},
        "display": display,
    }


def _v1_footer(*, exit_code: int = 0, evidence_sha256: str | None = None) -> dict[str, object]:
    footer: dict[str, object] = {
        "schema_version": "bencheval_run_record_v1",
        "record_type": "footer",
        "exit_code": exit_code,
        "summary": {"passed": 1, "failed": 0},
    }
    if evidence_sha256 is not None:
        footer["evidence_sha256"] = evidence_sha256
    return footer


def _momo_event(
    *,
    kind: str = "pass",
    display: str = "[00:00:00] PASS     lootstash  flag verified",
    elapsed: float = 0.0,
    challenge_id: str = "lootstash",
    message: str = "flag verified",
    data: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": "momo_event_v1",
        "time": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "elapsed_sec": elapsed,
        "kind": kind,
        "challenge_id": challenge_id,
        "attempt": 1,
        "message": message,
        "data": data or {},
        "display": display,
    }


def _write_records(path: Path, *records: dict[str, object]) -> Path:
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _evidence_row(
    *,
    run_id: str = "run-1",
    task_id: str = "cybench/lootstash",
    primary_pass: bool = True,
    instance_id: str = "lootstash",
    benchmark_id: str = "cybench",
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=run_id,
        task_id=task_id,
        model_id="ollama-cloud/glm-5.2",
        execution_profile="E2",
        primary_pass=primary_pass,
        partial_score=1.0 if primary_pass else 0.0,
        cost_usd=0.0,
        latency_sec=10.0,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        benchmark_id=benchmark_id,
        instance_id=instance_id,
    )


def _write_evidence(path: Path, *rows: EvidenceRecord) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(r.model_dump_json() for r in rows) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# v1 schema validation
# ---------------------------------------------------------------------------


class TestV1Schema:
    def test_header_validates(self) -> None:
        h = RecordHeader.model_validate(_v1_header())
        assert h.run_id == "run-1"
        assert h.redaction_policy == "none"
        assert h.contains_sensitive is True

    def test_event_validates(self) -> None:
        ev = RecordEvent.model_validate(_v1_event(seq=1))
        assert ev.seq == 1
        assert ev.record_type == "event"

    def test_footer_validates(self) -> None:
        f = RecordFooter.model_validate(_v1_footer(exit_code=0))
        assert f.exit_code == 0

    def test_header_extra_field_forbidden(self) -> None:
        with pytest.raises(Exception):
            RecordHeader.model_validate(_v1_header() | {"not_a_field": 1})

    def test_event_negative_seq_rejected(self) -> None:
        with pytest.raises(Exception):
            RecordEvent.model_validate(_v1_event(seq=0))

    def test_event_frozen(self) -> None:
        ev = RecordEvent.model_validate(_v1_event())
        with pytest.raises(Exception):
            ev.message = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


class TestLoadRunRecord:
    def test_loads_v1_with_header_events_footer(self, tmp_path: Path) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1, kind="start", message="launching"),
            _v1_event(seq=2, kind="pass", message="done", elapsed=1.5),
            _v1_footer(),
        )
        record = load_run_record(p)
        assert isinstance(record, RunRecord)
        assert len(record) == 2
        assert record.schema_version == "bencheval_run_record_v1"
        assert record.header is not None
        assert record.header.run_id == "run-1"
        assert record.footer is not None
        assert record.footer.exit_code == 0
        assert not record.is_legacy_unbound

    def test_loads_v1_without_footer(self, tmp_path: Path) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1, kind="start"),
        )
        record = load_run_record(p)
        assert record.footer is None
        assert record.header is not None

    def test_v1_seq_gap_rejected(self, tmp_path: Path) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1),
            _v1_event(seq=3),  # gap: expected 2
        )
        with pytest.raises(EvidenceValidationError, match="seq=3 expected 2"):
            load_run_record(p)

    def test_loads_legacy_momo_events(self, tmp_path: Path) -> None:
        p = _write_records(tmp_path / "events.jsonl", _momo_event())
        record = load_run_record(p)
        assert record.schema_version == "momo_event_v1"
        assert record.is_legacy_unbound
        assert record.header is None
        assert isinstance(record.events[0], LegacyMomoEvent)

    def test_mixed_schema_rejected(self, tmp_path: Path) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1),
            _momo_event(),
        )
        with pytest.raises(EvidenceValidationError, match="schema_version changed mid-file"):
            load_run_record(p)

    def test_schema_less_lines_accepted_as_legacy_momo(self, tmp_path: Path) -> None:
        p = tmp_path / "events.jsonl"
        p.write_text(json.dumps({"kind": "pass", "display": "x"}) + "\n", encoding="utf-8")
        record = load_run_record(p)
        assert record.schema_version == "momo_event_v1"

    def test_unsupported_schema_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "events.jsonl"
        p.write_text(
            json.dumps({"schema_version": "bogus_v9", "kind": "pass", "display": "x"}) + "\n",
            encoding="utf-8",
        )
        with pytest.raises(EvidenceValidationError, match="unsupported schema_version"):
            load_run_record(p)

    def test_invalid_json_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "events.jsonl"
        p.write_text("{not json}\n", encoding="utf-8")
        with pytest.raises(EvidenceValidationError, match="invalid JSON"):
            load_run_record(p)

    def test_empty_file_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "events.jsonl"
        p.write_text("\n\n  \n", encoding="utf-8")
        with pytest.raises(BenchEvalError, match="no event lines"):
            load_run_record(p)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(BenchEvalError, match="cannot read"):
            load_run_record(tmp_path / "nope.jsonl")

    # --- F002: v1 binding enforcement ---

    def test_v1_without_header_rejected(self, tmp_path: Path) -> None:
        """F002: v1 record without a header is invalid, not v1_bound."""
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_event(seq=1, kind="start"),
        )
        with pytest.raises(EvidenceValidationError, match="event before header"):
            load_run_record(p)

    def test_v1_duplicate_header_rejected(self, tmp_path: Path) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_header(run_id="run-2"),
        )
        with pytest.raises(EvidenceValidationError, match="duplicate header"):
            load_run_record(p)

    def test_v1_event_before_header_rejected(self, tmp_path: Path) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_event(seq=1, kind="start"),
            _v1_header(),
        )
        with pytest.raises(EvidenceValidationError, match="event before header"):
            load_run_record(p)

    def test_v1_duplicate_footer_rejected(self, tmp_path: Path) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1),
            _v1_footer(),
            _v1_footer(),
        )
        with pytest.raises(EvidenceValidationError, match="duplicate footer"):
            load_run_record(p)

    def test_v1_event_after_footer_rejected(self, tmp_path: Path) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1),
            _v1_footer(),
            _v1_event(seq=2),
        )
        with pytest.raises(EvidenceValidationError, match="event after footer"):
            load_run_record(p)

    def test_v1_footer_before_header_rejected(self, tmp_path: Path) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_footer(),
            _v1_header(),
            _v1_event(seq=1),
        )
        with pytest.raises(EvidenceValidationError, match="footer before header"):
            load_run_record(p)


# ---------------------------------------------------------------------------
# Canonical raw integrity (F001/F002/F007)
# ---------------------------------------------------------------------------


class TestCanonicalRawIntegrity:
    def test_replay_preserves_raw_flag_in_display(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Canonical replay prints the exact recorded text, including flags."""
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(
                seq=1,
                kind="break",
                message=f"FLAG: {_FLAG_MARKER}",
                display=f"FLAG: {_FLAG_MARKER}",
            ),
        )
        assert replay(p, color=False, speed=100.0) == 0
        out = capsys.readouterr().out
        assert _FLAG_MARKER in out
        assert "[redacted]" not in out

    def test_replay_preserves_raw_secret(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Canonical replay does not redact secrets."""
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1, kind="debug", message=f"key={_SECRET_MARKER}"),
        )
        assert replay(p, color=False, speed=100.0) == 0
        out = capsys.readouterr().out
        assert _SECRET_MARKER in out

    def test_replay_does_not_modify_message_or_display(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Replay prints exactly what was in the record — no sanitization applied."""
        raw_text = f"FLAG: {_FLAG_MARKER} secret={_SECRET_MARKER}"
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1, kind="break", display=raw_text),
        )
        replay(p, color=False, speed=100.0)
        out = capsys.readouterr().out.strip()
        assert raw_text in out

    def test_legacy_momo_replay_preserves_raw_flag(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Legacy MOMO records are also raw — no redaction on replay."""
        p = _write_records(
            tmp_path / "events.jsonl",
            _momo_event(
                message=f"FLAG: {_FLAG_MARKER}",
                display=f"[00:00:00] BREAK  lootstash  FLAG: {_FLAG_MARKER}",
            ),
        )
        assert replay(p, color=False, speed=100.0) == 0
        out = capsys.readouterr().out
        assert _FLAG_MARKER in out


# ---------------------------------------------------------------------------
# Terminal replay
# ---------------------------------------------------------------------------


class TestReplay:
    def test_replay_prints_display(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1, kind="pass", display="[00:00:00] PASS     ok", elapsed=0.0),
        )
        assert replay(p, color=False, speed=100.0) == 0
        assert "PASS" in capsys.readouterr().out

    def test_replay_color_off_strips_ansi(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1, kind="pass", display="DONE", elapsed=0.0),
        )
        replay(p, color=False, speed=100.0)
        assert "\033[" not in capsys.readouterr().out

    def test_replay_color_on_adds_ansi(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1, kind="fail", display="NOPE", elapsed=0.0),
        )
        replay(p, color=True, speed=100.0)
        assert "\033[1;31m" in capsys.readouterr().out

    def test_replay_speed_zero_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(BenchEvalError, match="--speed"):
            replay(tmp_path / "x.jsonl", speed=0.0)

    def test_replay_unknown_kind_falls_back_to_system(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1, kind="not_a_real_kind", display="mystery"),
        )
        assert replay(p, color=False, speed=100.0) == 0
        assert "mystery" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------


class TestReplayCLI:
    def test_cli_replay_text(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        p = _write_records(
            tmp_path / "events.jsonl",
            _v1_header(),
            _v1_event(seq=1, kind="pass", display="[00:00:00] PASS ok", elapsed=0.0),
        )
        rc = main(["replay", str(p), "--no-color", "--speed", "100"])
        assert rc == 0
        assert "PASS" in capsys.readouterr().out

    def test_cli_verify_evidence_text(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = "run-1"
        run_dir = tmp_path / "raw" / run_id
        run_dir.mkdir(parents=True)
        events = run_dir / "events.jsonl"
        _write_records(
            events,
            _v1_header(run_id=run_id, benchmark_id="cybench"),
            _v1_event(seq=1, kind="summary", instance_id="lootstash"),
        )
        evidence = _write_evidence(
            tmp_path / "evidence" / f"{run_id}.jsonl",
            _evidence_row(run_id=run_id),
        )
        rc = main(["replay", str(events), "--verify-evidence", str(evidence)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Verified 1 evidence row" in out
        assert "cybench/lootstash" in out

    def test_cli_verify_evidence_json(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        run_id = "run-1"
        run_dir = tmp_path / "raw" / run_id
        run_dir.mkdir(parents=True)
        events = run_dir / "events.jsonl"
        _write_records(
            events,
            _v1_header(run_id=run_id),
            _v1_event(seq=1, kind="summary", instance_id="lootstash"),
        )
        evidence = _write_evidence(tmp_path / "e.jsonl", _evidence_row(run_id=run_id))
        rc = main(
            [
                "replay",
                str(events),
                "--verify-evidence",
                str(evidence),
                "--format",
                "json",
            ]
        )
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["row_count"] == 1
        assert payload["rows"][0]["instance_id"] == "lootstash"

    def test_cli_verify_evidence_derives_sibling_path(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--verify-evidence without a path derives the sibling evidence path."""
        run_id = "run-2026"
        run_dir = tmp_path / "raw" / run_id
        run_dir.mkdir(parents=True)
        events = run_dir / "events.jsonl"
        _write_records(
            events,
            _v1_header(run_id=run_id),
            _v1_event(seq=1, kind="summary", instance_id="lootstash"),
        )
        _write_evidence(tmp_path / "evidence" / f"{run_id}.jsonl", _evidence_row(run_id=run_id))
        rc = main(["replay", str(events), "--verify-evidence"])
        assert rc == 0
        assert "Verified 1 evidence row" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Evidence verification (F005: renamed from reproduce_evidence)
# ---------------------------------------------------------------------------


class TestVerifyBoundEvidence:
    def test_verify_from_explicit_path(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run-1"
        run_dir.mkdir()
        events = run_dir / "events.jsonl"
        _write_records(
            events,
            _v1_header(benchmark_id="cybench"),
            _v1_event(seq=1, kind="summary", instance_id="lootstash"),
        )
        evidence = _write_evidence(tmp_path / "e.jsonl", _evidence_row())
        rows = verify_bound_evidence(events, evidence_path=evidence)
        assert len(rows) == 1

    def test_verify_sibling_evidence_path(self, tmp_path: Path) -> None:
        run_id = "run-2026"
        raw_dir = tmp_path / "raw" / run_id
        raw_dir.mkdir(parents=True)
        events = raw_dir / "events.jsonl"
        _write_records(
            events,
            _v1_header(run_id=run_id),
            _v1_event(seq=1, kind="summary", instance_id="lootstash"),
        )
        _write_evidence(tmp_path / "evidence" / f"{run_id}.jsonl", _evidence_row(run_id=run_id))
        rows = verify_bound_evidence(events)
        assert len(rows) == 1

    def test_verify_missing_evidence_raises_by_default(self, tmp_path: Path) -> None:
        """F003: missing evidence raises BenchEvalError by default (not return [])."""
        run_dir = tmp_path / "run-x"
        run_dir.mkdir()
        events = run_dir / "events.jsonl"
        _write_records(events, _v1_header(run_id="run-x"), _v1_event(seq=1))
        with pytest.raises(BenchEvalError, match="no evidence file found"):
            verify_bound_evidence(events)

    def test_verify_missing_evidence_allowed_with_flag(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """F003: allow_missing_evidence=True returns [] with warning."""
        run_dir = tmp_path / "run-x"
        run_dir.mkdir()
        events = run_dir / "events.jsonl"
        _write_records(events, _v1_header(run_id="run-x"), _v1_event(seq=1))
        rows = verify_bound_evidence(events, allow_missing_evidence=True)
        assert rows == []
        assert "no evidence file found" in capsys.readouterr().err.lower()

    def test_verify_empty_evidence_rejected(self, tmp_path: Path) -> None:
        """An existing but empty evidence file is not a verified bound run."""
        run_id = "run-empty"
        raw_dir = tmp_path / "raw" / run_id
        raw_dir.mkdir(parents=True)
        events = raw_dir / "events.jsonl"
        _write_records(events, _v1_header(run_id=run_id), _v1_event(seq=1))
        evidence = tmp_path / "evidence" / f"{run_id}.jsonl"
        evidence.parent.mkdir(parents=True)
        evidence.write_text("", encoding="utf-8")
        with pytest.raises(BenchEvalError, match="has no evidence rows"):
            verify_bound_evidence(events)

    def test_cli_verify_evidence_missing_fails_nonzero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """F003: CLI --verify-evidence exits non-zero when evidence is missing."""
        run_dir = tmp_path / "run-x"
        run_dir.mkdir()
        events = run_dir / "events.jsonl"
        _write_records(events, _v1_header(run_id="run-x"), _v1_event(seq=1))
        rc = main(["replay", str(events), "--verify-evidence"])
        assert rc != 0
        assert "error" in capsys.readouterr().err.lower()

    def test_verify_inconsistent_instance_rejected(self, tmp_path: Path) -> None:
        events = tmp_path / "events.jsonl"
        _write_records(
            events,
            _v1_header(),
            _v1_event(seq=1, kind="summary", instance_id="lootstash"),
        )
        evidence = _write_evidence(tmp_path / "e.jsonl", _evidence_row(instance_id="DIFFERENT"))
        with pytest.raises(BenchEvalError, match="not present in run record"):
            verify_bound_evidence(events, evidence_path=evidence)

    def test_verify_v1_header_run_id_mismatch_rejected(self, tmp_path: Path) -> None:
        events = tmp_path / "events.jsonl"
        _write_records(
            events,
            _v1_header(run_id="run-A"),
            _v1_event(seq=1, instance_id="lootstash"),
        )
        evidence = _write_evidence(tmp_path / "e.jsonl", _evidence_row(run_id="run-B"))
        with pytest.raises(BenchEvalError, match="does not match header run_id"):
            verify_bound_evidence(events, evidence_path=evidence)

    def test_verify_v1_evidence_sha256_matches(self, tmp_path: Path) -> None:
        evidence = _write_evidence(tmp_path / "e.jsonl", _evidence_row())
        sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
        events = tmp_path / "events.jsonl"
        _write_records(
            events,
            _v1_header(evidence_sha256=sha),
            _v1_event(seq=1, instance_id="lootstash"),
        )
        rows = verify_bound_evidence(events, evidence_path=evidence)
        assert len(rows) == 1

    def test_verify_v1_evidence_sha256_mismatch_rejected(self, tmp_path: Path) -> None:
        evidence = _write_evidence(tmp_path / "e.jsonl", _evidence_row())
        events = tmp_path / "events.jsonl"
        _write_records(
            events,
            _v1_header(evidence_sha256="0" * 64),
            _v1_event(seq=1, instance_id="lootstash"),
        )
        with pytest.raises(BenchEvalError, match="evidence file sha256"):
            verify_bound_evidence(events, evidence_path=evidence)

    def test_verify_v1_footer_evidence_sha256_matches(self, tmp_path: Path) -> None:
        """Footer evidence_sha256 supports streamed records whose header is written first."""
        evidence = _write_evidence(tmp_path / "e.jsonl", _evidence_row())
        sha = hashlib.sha256(evidence.read_bytes()).hexdigest()
        events = tmp_path / "events.jsonl"
        _write_records(
            events,
            _v1_header(),
            _v1_event(seq=1, instance_id="lootstash"),
            _v1_footer(evidence_sha256=sha),
        )
        rows = verify_bound_evidence(events, evidence_path=evidence)
        assert len(rows) == 1

    def test_verify_v1_footer_evidence_sha256_mismatch_rejected(self, tmp_path: Path) -> None:
        evidence = _write_evidence(tmp_path / "e.jsonl", _evidence_row())
        events = tmp_path / "events.jsonl"
        _write_records(
            events,
            _v1_header(),
            _v1_event(seq=1, instance_id="lootstash"),
            _v1_footer(evidence_sha256="0" * 64),
        )
        with pytest.raises(BenchEvalError, match="evidence file sha256"):
            verify_bound_evidence(events, evidence_path=evidence)


# ---------------------------------------------------------------------------
# F003 regression: legacy MOMO challenge_id consistency
# ---------------------------------------------------------------------------


class TestF003LegacyChallengeIdConsistency:
    def test_legacy_momo_challenge_id_checked_even_with_empty_data(self, tmp_path: Path) -> None:
        """F003: top-level challenge_id must be checked even when data={}."""
        events = tmp_path / "events.jsonl"
        _write_records(
            events,
            _momo_event(challenge_id="lootstash", data={}),  # data explicitly empty
        )
        evidence = _write_evidence(tmp_path / "e.jsonl", _evidence_row(instance_id="DIFFERENT"))
        with pytest.raises(BenchEvalError, match="not present in run record"):
            verify_bound_evidence(events, evidence_path=evidence)

    def test_legacy_momo_matching_challenge_id_passes(self, tmp_path: Path) -> None:
        events = tmp_path / "events.jsonl"
        _write_records(
            events,
            _momo_event(challenge_id="lootstash", data={}),
        )
        evidence = _write_evidence(tmp_path / "e.jsonl", _evidence_row(instance_id="lootstash"))
        rows = verify_bound_evidence(events, evidence_path=evidence)
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# Public presentation redaction (F002: NOT canonical replay)
# ---------------------------------------------------------------------------


class TestPublicPresentationRedaction:
    def test_redact_flag(self) -> None:
        assert (
            redact_for_public_presentation(f"FLAG: {_FLAG_MARKER}", redact=True)
            == "FLAG: [redacted]"
        )

    def test_redact_embedded_flag(self) -> None:
        assert (
            redact_for_public_presentation(f"found {_FLAG_MARKER} here", redact=True)
            == "found [redacted-flag] here"
        )

    def test_redact_secret(self) -> None:
        assert _SECRET_MARKER not in redact_for_public_presentation(
            f"key={_SECRET_MARKER}",
            redact=True,
        )

    def test_no_redact_keeps_text(self) -> None:
        text = f"FLAG: {_FLAG_MARKER}"
        assert redact_for_public_presentation(text, redact=False) == text

    def test_deprecated_alias_still_works(self) -> None:
        """sanitize_for_replay is a deprecated alias for redact_for_public_presentation."""
        assert sanitize_for_replay(f"FLAG: {_FLAG_MARKER}", redact=True) == "FLAG: [redacted]"

    def test_strip_ansi(self) -> None:
        assert strip_ansi("\033[1;31mred\033[0m") == "red"


# ---------------------------------------------------------------------------
# RunRecordWriter (F004: generic v1 writer for adapters)
# ---------------------------------------------------------------------------


class TestRunRecordWriter:
    def test_writer_produces_valid_v1_record(self, tmp_path: Path) -> None:
        from bencheval.replay import RunRecordWriter

        path = tmp_path / "events.jsonl"
        with RunRecordWriter(
            path,
            run_id="run-test",
            benchmark_id="cybench",
            runtime_id="kilo",
            model_id="glm-5.2",
        ) as w:
            w.write_event("start", "launching", elapsed_sec=0.0)
            w.write_event(
                "break",
                f"FLAG: {_FLAG_MARKER}",
                elapsed_sec=1.0,
                instance_id="lootstash",
                display=f"FLAG: {_FLAG_MARKER}",
            )
            w.write_footer(exit_code=0, summary={"passed": 1}, evidence_sha256="1" * 64)

        record = load_run_record(path)
        assert record.schema_version == "bencheval_run_record_v1"
        assert record.header is not None
        assert record.header.run_id == "run-test"
        assert record.header.redaction_policy == "none"
        assert not record.is_legacy_unbound
        assert len(record) == 2
        # F001/F002: canonical record preserves raw flag.
        assert _FLAG_MARKER in record.events[1].message
        assert record.footer is not None
        assert record.footer.exit_code == 0
        assert record.footer.evidence_sha256 == "1" * 64

    def test_writer_writes_raw_canonical(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The writer does NOT redact — canonical is raw."""
        from bencheval.replay import RunRecordWriter

        path = tmp_path / "events.jsonl"
        with RunRecordWriter(path, run_id="r") as w:
            w.write_event("debug", f"secret={_SECRET_MARKER}", elapsed_sec=0.0)

        text = path.read_text(encoding="utf-8")
        assert _SECRET_MARKER in text
        assert "[redacted]" not in text

    def test_writer_rejects_duplicate_footer(self, tmp_path: Path) -> None:
        from bencheval.replay import RunRecordWriter

        with RunRecordWriter(tmp_path / "events.jsonl", run_id="r") as w:
            w.write_event("start", "launching")
            w.write_footer(exit_code=0)
            with pytest.raises(BenchEvalError, match="already has a footer"):
                w.write_footer(exit_code=0)

    def test_writer_rejects_event_after_footer(self, tmp_path: Path) -> None:
        from bencheval.replay import RunRecordWriter

        with RunRecordWriter(tmp_path / "events.jsonl", run_id="r") as w:
            w.write_event("start", "launching")
            w.write_footer(exit_code=0)
            with pytest.raises(BenchEvalError, match="already has a footer"):
                w.write_event("debug", "too late")
