"""General-purpose run record/replay for BenchEval.

A *run record* is a JSONL file where each line is a structured record: a header,
a stream of events, and a footer. Any adapter (external-command, Terminal-Bench,
SWE-bench, a future native adapter) captures its live terminal stream + timeline
+ structured data into such a file. This module loads, validates, replays, and
verifies that file.

## Canonical vs derived (production integrity policy)

There are two lanes, and they must never be confused:

- **Canonical run record** (``events.jsonl``): **raw, private, integrity-preserving**.
  It is the scoring/audit source of truth. It MAY contain flags, secrets, prompts,
  model outputs, tool calls, stack traces, filesystem paths, and challenge content.
  Redaction is forbidden here by default. Replay operates on this lane.

- **Derived public artifacts** (public reports, demo videos, shareable transcripts):
  MAY redact sensitive material via :mod:`bencheval.presentation`, but
  they are never used as scoring truth and must carry provenance (source path/hash,
  redaction mode, generated time).

This module implements the canonical lane. Redaction helpers live in
``bencheval.presentation`` and are NOT called by ``replay()`` or
``load_run_record()``.

## Schema versions

- ``bencheval_run_record_v1`` — production schema with header/event/footer records,
  integrity binding (run_id, benchmark_id, evidence_sha256), and per-event ``seq``.
- ``momo_event_v1`` — legacy MOMO capture schema (flat event stream, no header).
  Accepted for backward compatibility; treated as ``legacy_unbound`` (no integrity
  binding) so old recordings stay usable without pretending they have audit-grade
  binding.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from bencheval.evidence import EvidenceRecord, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError, EvidenceValidationError

# ---------------------------------------------------------------------------
# Schema versioning
# ---------------------------------------------------------------------------

RunRecordSchemaVersion = Literal["bencheval_run_record_v1", "momo_event_v1"]

#: Accepted schema versions. The first seen schema becomes the file's schema;
#: a mid-stream schema change is rejected.
_ACCEPTED_SCHEMAS: frozenset[str] = frozenset({"bencheval_run_record_v1", "momo_event_v1"})

#: Legacy schemas that lack integrity binding. They are readable but flagged.
_LEGACY_UNBOUND_SCHEMAS: frozenset[str] = frozenset({"momo_event_v1"})


# ---------------------------------------------------------------------------
# Event kinds and record types
# ---------------------------------------------------------------------------

ReplayEventKind = Literal[
    "system",
    "target",
    "model",
    "queue",
    "start",
    "llm",
    "tool",
    "debug",
    "break",
    "pass",
    "fail",
    "invalid",
    "artifact",
    "summary",
]

RecordType = Literal["header", "event", "footer"]

ANSI_RESET = "\033[0m"
_ANSI_COLORS: dict[str, str] = {
    "system": "\033[36m",
    "target": "\033[35m",
    "model": "\033[34m",
    "queue": "\033[36m",
    "start": "\033[1;34m",
    "llm": "\033[37m",
    "tool": "\033[34m",
    "debug": "\033[90m",
    "break": "\033[1;33m",
    "pass": "\033[1;32m",
    "fail": "\033[1;31m",
    "invalid": "\033[1;33m",
    "artifact": "\033[36m",
    "summary": "\033[1;36m",
}

# ---------------------------------------------------------------------------
# v1 record models (header / event / footer)
# ---------------------------------------------------------------------------


class RecordHeader(BaseModel):
    """Integrity-binding header for a v1 run record.

    The first line of a ``bencheval_run_record_v1`` file. Binds the record to
    its run/evidence so replay and evidence cannot drift silently.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["bencheval_run_record_v1"]
    record_type: Literal["header"] = "header"
    run_id: str = Field(min_length=1)
    benchmark_id: str | None = None
    slice_id: str | None = None
    suite_id: str | None = None
    runtime_id: str | None = None
    model_id: str | None = None
    backend: str | None = None
    adapter_id: str | None = None
    redaction_policy: Literal["none"] = "none"
    contains_sensitive: bool = True
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    producer_command: str | None = None
    producer_version: str | None = None
    host_label: str | None = None


class RecordEvent(BaseModel):
    """One event in a v1 run record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["bencheval_run_record_v1"]
    record_type: Literal["event"] = "event"
    seq: int = Field(ge=1)
    time: datetime | None = None
    elapsed_sec: float = Field(default=0.0, ge=0.0)
    kind: str = "system"
    run_id: str | None = None
    benchmark_id: str | None = None
    task_id: str | None = None
    instance_id: str | None = None
    attempt: int | None = None
    challenge_id: str | None = None
    message: str = ""
    data: dict[str, JsonValue] = Field(default_factory=dict)
    display: str = ""

    @field_validator("elapsed_sec", mode="before")
    @classmethod
    def _coerce_elapsed(cls, value: object) -> object:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        return value

    @property
    def rendered_display(self) -> str:
        return self.display or self.message


class RecordFooter(BaseModel):
    """Footer for a v1 run record (exit code + summary)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["bencheval_run_record_v1"]
    record_type: Literal["footer"] = "footer"
    exit_code: int = 0
    summary: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Legacy MOMO event model (backward compat)
# ---------------------------------------------------------------------------


class LegacyMomoEvent(BaseModel):
    """One line of a legacy ``momo_event_v1`` run record.

    Has no header/footer/seq/integrity binding. Treated as ``legacy_unbound``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["momo_event_v1"]
    time: datetime | None = None
    elapsed_sec: float = Field(default=0.0, ge=0.0)
    kind: str = "system"
    challenge_id: str | None = None
    attempt: int | None = None
    message: str = ""
    data: dict[str, JsonValue] = Field(default_factory=dict)
    display: str = ""

    @field_validator("elapsed_sec", mode="before")
    @classmethod
    def _coerce_elapsed(cls, value: object) -> object:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        return value

    @property
    def rendered_display(self) -> str:
        return self.display or self.message


# ---------------------------------------------------------------------------
# Unified run record (in-memory)
# ---------------------------------------------------------------------------


class RunRecord:
    """Validated, in-memory run record.

    A v1 record has a header, event stream, and optional footer.
    A legacy record has only events and is flagged ``legacy_unbound``.
    """

    __slots__ = ("_events", "_footer", "_header", "_path", "_schema_version")

    def __init__(
        self,
        path: Path,
        events: tuple[RecordEvent | LegacyMomoEvent, ...],
        header: RecordHeader | None = None,
        footer: RecordFooter | None = None,
    ) -> None:
        self._path = path
        self._events = events
        self._header = header
        self._footer = footer
        if header is not None:
            self._schema_version = header.schema_version
        elif events:
            self._schema_version = events[0].schema_version
        else:
            self._schema_version = "bencheval_run_record_v1"

    @property
    def path(self) -> Path:
        return self._path

    @property
    def schema_version(self) -> str:
        return self._schema_version

    @property
    def is_legacy_unbound(self) -> bool:
        """True when the record lacks integrity binding (legacy momo_event_v1)."""
        return self._schema_version in _LEGACY_UNBOUND_SCHEMAS

    @property
    def header(self) -> RecordHeader | None:
        return self._header

    @property
    def footer(self) -> RecordFooter | None:
        return self._footer

    @property
    def events(self) -> tuple[RecordEvent | LegacyMomoEvent, ...]:
        return self._events

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Iterator[RecordEvent | LegacyMomoEvent]:
        return iter(self._events)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_run_record(path: Path | str) -> RunRecord:
    """Load and validate a run-record JSONL file (events.jsonl).

    Raises ``EvidenceValidationError`` on the first malformed line, and
    ``BenchEvalError`` if the file cannot be read or has no records.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise BenchEvalError(f"cannot read run record {p}: {e}") from e

    raw_records: list[dict[str, object]] = []
    pinned_schema: str | None = None
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            raise EvidenceValidationError(
                f"{p.name}:line {line_no}: invalid JSON: {e}",
            ) from e
        if not isinstance(record, dict):
            raise EvidenceValidationError(
                f"{p.name}:line {line_no}: each line must be a JSON object",
            )
        schema = record.get("schema_version")
        if not isinstance(schema, str):
            # Legacy tolerance: schema-less lines default to momo_event_v1.
            schema = "momo_event_v1"
            record["schema_version"] = schema
        if schema not in _ACCEPTED_SCHEMAS:
            raise EvidenceValidationError(
                f"{p.name}:line {line_no}: unsupported schema_version: {schema!r}",
            )
        if pinned_schema is None:
            pinned_schema = schema
        elif schema != pinned_schema:
            raise EvidenceValidationError(
                f"{p.name}:line {line_no}: schema_version changed mid-file "
                f"({pinned_schema!r} -> {schema!r}); refusing mixed-schema replay",
            )
        raw_records.append(record)

    if not raw_records:
        raise BenchEvalError(f"run record {p} has no event lines")

    return _build_run_record(p, raw_records, pinned_schema or "bencheval_run_record_v1")


def _build_run_record(path: Path, raw_records: list[dict[str, object]], schema: str) -> RunRecord:
    if schema == "bencheval_run_record_v1":
        return _build_v1_record(path, raw_records)
    return _build_legacy_record(path, raw_records)


def _build_v1_record(path: Path, raw_records: list[dict[str, object]]) -> RunRecord:
    header: RecordHeader | None = None
    footer: RecordFooter | None = None
    events: list[RecordEvent] = []
    expected_seq = 0
    header_seen = False
    footer_seen = False
    for idx, raw in enumerate(raw_records, start=1):
        rtype = raw.get("record_type", "event")
        if rtype == "header":
            if header_seen:
                raise EvidenceValidationError(
                    f"{path.name}:record {idx}: duplicate header; "
                    f"a v1 record must have exactly one header",
                )
            if events or footer_seen:
                raise EvidenceValidationError(
                    f"{path.name}:record {idx}: header must be the first record; "
                    f"found after {len(events)} event(s) and {int(footer_seen)} footer(s)",
                )
            try:
                header = RecordHeader.model_validate(raw)
            except ValidationError as e:
                raise EvidenceValidationError(f"{path.name}:record {idx}: {e}") from e
            header_seen = True
        elif rtype == "footer":
            if footer_seen:
                raise EvidenceValidationError(
                    f"{path.name}:record {idx}: duplicate footer; "
                    f"a v1 record may have at most one footer",
                )
            if not header_seen:
                raise EvidenceValidationError(
                    f"{path.name}:record {idx}: footer before header; header must come first",
                )
            try:
                footer = RecordFooter.model_validate(raw)
            except ValidationError as e:
                raise EvidenceValidationError(f"{path.name}:record {idx}: {e}") from e
            footer_seen = True
        else:
            if not header_seen:
                raise EvidenceValidationError(
                    f"{path.name}:record {idx}: event before header; "
                    f"v1 records must start with a header record",
                )
            if footer_seen:
                raise EvidenceValidationError(
                    f"{path.name}:record {idx}: event after footer; "
                    f"all events must precede the footer",
                )
            try:
                event = RecordEvent.model_validate(raw)
            except ValidationError as e:
                raise EvidenceValidationError(f"{path.name}:record {idx}: {e}") from e
            expected_seq += 1
            if event.seq != expected_seq:
                raise EvidenceValidationError(
                    f"{path.name}:record {idx}: event seq={event.seq} expected {expected_seq}; "
                    f"events must be monotonically increasing from 1",
                )
            events.append(event)

    if not header_seen:
        raise EvidenceValidationError(
            f"{path.name}: v1 record is missing a header; "
            f"bencheval_run_record_v1 requires exactly one header as the first record",
        )
    if not events:
        raise BenchEvalError(f"run record {path} has header but no event records")
    return RunRecord(path, tuple(events), header=header, footer=footer)


def _build_legacy_record(path: Path, raw_records: list[dict[str, object]]) -> RunRecord:
    events: list[LegacyMomoEvent] = []
    for idx, raw in enumerate(raw_records, start=1):
        try:
            events.append(LegacyMomoEvent.model_validate(raw))
        except ValidationError as e:
            raise EvidenceValidationError(f"{path.name}:line {idx}: {e}") from e
    return RunRecord(path, tuple(events))


# ---------------------------------------------------------------------------
# Terminal replay (canonical = raw, no redaction)
# ---------------------------------------------------------------------------


def replay(
    path: Path | str,
    *,
    color: bool = True,
    speed: float = 1.0,
    max_delay_sec: float = 2.0,
) -> int:
    """Replay a canonical run record to the terminal with original timing and colors.

    The canonical replay is **raw**: it prints exactly what was recorded, including
    flags, secrets, and sensitive content. This is the private/audit lane. For a
    redacted public presentation, generate a derived artifact with
    ``--redaction public`` or presentation-layer helpers.

    Side-effect-free except for stdout. Returns 0 on success.
    """
    if speed <= 0:
        raise BenchEvalError("--speed must be > 0")
    if max_delay_sec < 0:
        raise BenchEvalError("--max-delay must be >= 0")
    record = load_run_record(path)
    _emit_to_stdout(record, color=color, speed=speed, max_delay_sec=max_delay_sec)
    return 0


def _emit_to_stdout(
    record: RunRecord,
    *,
    color: bool,
    speed: float,
    max_delay_sec: float,
) -> None:
    previous_elapsed = 0.0
    out = sys.stdout
    for event in record:
        delay = max(0.0, event.elapsed_sec - previous_elapsed) / speed
        if delay > 0:
            time.sleep(min(delay, max_delay_sec))
        previous_elapsed = event.elapsed_sec
        display = event.rendered_display
        out.write(_colorize(display, event.kind, enabled=color) + "\n")
    out.flush()


def _colorize(text: str, kind: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    color = _ANSI_COLORS.get(kind, "")
    if not color:
        return text
    return f"{color}{text}{ANSI_RESET}"


# ---------------------------------------------------------------------------
# Evidence verification (F005: renamed from reproduce_evidence)
# ---------------------------------------------------------------------------


def verify_bound_evidence(
    run_record_path: Path | str,
    *,
    evidence_path: Path | str | None = None,
    allow_missing_evidence: bool = False,
) -> list[EvidenceRecord]:
    """Load and verify the evidence rows bound to a run record.

    This **loads** existing evidence rows and cross-checks them against the run
    record. It does NOT rerun verifiers or regenerate evidence. The name reflects
    the real behavior: verify that evidence belongs to this run.

    Cross-checks (best-effort for legacy; strict for v1):
    - v1 header ``run_id`` matches evidence ``run_id`` (when both present).
    - v1 header ``benchmark_id`` matches evidence ``benchmark_id`` (when both present).
    - Event ``instance_id`` / ``challenge_id`` sets match evidence ``instance_id``.
    - v1 header ``evidence_sha256`` matches the SHA-256 of the evidence file (when set).

    If ``evidence_path`` is omitted, it is derived from the run record's sibling
    ``<results_root>/evidence/<run_id>.jsonl`` convention. By default, missing
    evidence raises ``BenchEvalError`` (production: verification must fail when
    the evidence to verify is absent). Pass ``allow_missing_evidence=True`` for
    dry inspection that returns an empty list with a warning.
    """
    record = load_run_record(run_record_path)
    ev_path = _resolve_evidence_path(run_record_path, record, evidence_path)
    if ev_path is None or not ev_path.is_file():
        msg = f"no evidence file found for run record {record.path}; expected {ev_path}"
        if allow_missing_evidence:
            sys.stderr.write(f"warning: {msg}\n")
            return []
        raise BenchEvalError(msg)
    rows = read_evidence_jsonl(ev_path)
    if not rows:
        raise BenchEvalError(f"evidence file {ev_path} has no evidence rows")
    _assert_run_consistency(record, rows, ev_path)
    return rows


def _resolve_evidence_path(
    run_record_path: Path | str,
    record: RunRecord,
    evidence_path: Path | str | None,
) -> Path | None:
    if evidence_path is not None:
        return Path(evidence_path)
    p = Path(run_record_path)
    # v1: header.run_id is authoritative. Legacy: derive from parent dir name.
    run_id = record.header.run_id if record.header else p.parent.name
    # Convention: <results_root>/raw/<run_id>/events.jsonl -> <results_root>/evidence/<run_id>.jsonl
    results_root = p.parent.parent.parent
    return results_root / "evidence" / f"{run_id}.jsonl"


def _assert_run_consistency(
    record: RunRecord,
    rows: list[EvidenceRecord],
    evidence_path: Path,
) -> None:
    """Cross-check that evidence rows belong to this run record.

    F003 fix: always collect top-level ``challenge_id`` / ``instance_id``, even
    when ``data`` is empty (legacy MOMO events carry challenge_id at top level).
    """
    if not rows:
        return

    # v1 header binding: run_id and benchmark_id.
    if record.header is not None:
        header = record.header
        if header.run_id:
            mismatched = [r for r in rows if r.run_id != header.run_id]
            if mismatched:
                raise BenchEvalError(
                    f"evidence row run_id={mismatched[0].run_id!r} does not match "
                    f"header run_id={header.run_id!r}",
                )
        if header.benchmark_id:
            mismatched = [
                r for r in rows if r.benchmark_id and r.benchmark_id != header.benchmark_id
            ]
            if mismatched:
                raise BenchEvalError(
                    f"evidence row benchmark_id={mismatched[0].benchmark_id!r} does not match "
                    f"header benchmark_id={header.benchmark_id!r}",
                )
        expected_sha256 = header.evidence_sha256
        if record.footer is not None and record.footer.evidence_sha256:
            if expected_sha256 and expected_sha256 != record.footer.evidence_sha256:
                raise BenchEvalError(
                    f"header evidence_sha256={expected_sha256} does not match footer "
                    f"evidence_sha256={record.footer.evidence_sha256}",
                )
            expected_sha256 = record.footer.evidence_sha256
        if expected_sha256:
            actual = _sha256_file(evidence_path)
            if actual != expected_sha256:
                raise BenchEvalError(
                    f"evidence file sha256={actual} does not match record "
                    f"evidence_sha256={expected_sha256}",
                )

    # Event-level instance/challenge sets (always collected, F003 fix).
    record_instances: set[str] = set()
    for event in record:
        # Prefer explicit instance_id, then challenge_id (legacy MOMO top-level).
        instance = _event_instance_id(event)
        if instance is not None:
            record_instances.add(instance)
    if not record_instances:
        return

    for row in rows:
        if row.instance_id and row.instance_id not in record_instances:
            raise BenchEvalError(
                f"evidence row instance_id={row.instance_id!r} not present in run record",
            )


def _event_instance_id(event: RecordEvent | LegacyMomoEvent) -> str | None:
    """Extract the instance identifier from an event, preferring explicit fields."""
    # RecordEvent has instance_id + task_id; LegacyMomoEvent has challenge_id.
    instance = getattr(event, "instance_id", None)
    if isinstance(instance, str) and instance:
        return instance
    challenge = getattr(event, "challenge_id", None)
    if isinstance(challenge, str) and challenge:
        return challenge
    return None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Run record writer (generic v1; adapters use this to write canonical records)
# ---------------------------------------------------------------------------


class RunRecordWriter:
    """Generic v1 run-record writer for BenchEval adapters.

    Adapters (external-command, Terminal-Bench, SWE-bench, future native) use this writer
    instead of hand-rolling record JSON. The writer emits:

    1. A ``RecordHeader`` as the first line (integrity binding).
    2. ``RecordEvent`` lines with monotonically increasing ``seq``.
    3. An optional ``RecordFooter`` at the end (exit code + summary + evidence digest).

    The canonical file is **raw** (no redaction). If a derived/public display is
    needed, the adapter applies presentation-layer redaction to console output
    only, never to the file.

    The writer is single-threaded (one file, one writer). For concurrent runs,
    each challenge/attempt gets its own writer/file.
    """

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        benchmark_id: str | None = None,
        slice_id: str | None = None,
        suite_id: str | None = None,
        runtime_id: str | None = None,
        model_id: str | None = None,
        backend: str | None = None,
        adapter_id: str | None = None,
        producer_command: str | None = None,
        producer_version: str | None = None,
        host_label: str | None = None,
    ) -> None:
        self._path = path
        self._seq = 0
        self._closed = False
        self._footer_written = False
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("w", encoding="utf-8")
        header = RecordHeader(
            schema_version="bencheval_run_record_v1",
            record_type="header",
            run_id=run_id,
            benchmark_id=benchmark_id,
            slice_id=slice_id,
            suite_id=suite_id,
            runtime_id=runtime_id,
            model_id=model_id,
            backend=backend,
            adapter_id=adapter_id,
            redaction_policy="none",
            contains_sensitive=True,
            producer_command=producer_command,
            producer_version=producer_version,
            host_label=host_label,
        )
        self._file.write(header.model_dump_json() + "\n")
        self._file.flush()

    def write_event(
        self,
        kind: str,
        message: str,
        *,
        elapsed_sec: float = 0.0,
        time: datetime | None = None,
        instance_id: str | None = None,
        challenge_id: str | None = None,
        attempt: int | None = None,
        data: dict[str, JsonValue] | None = None,
        display: str = "",
    ) -> None:
        if self._closed:
            raise BenchEvalError(f"run record writer for {self._path} is already closed")
        if self._footer_written:
            raise BenchEvalError(f"run record writer for {self._path} already has a footer")
        self._seq += 1
        event = RecordEvent(
            schema_version="bencheval_run_record_v1",
            record_type="event",
            seq=self._seq,
            time=time,
            elapsed_sec=elapsed_sec,
            kind=kind,
            instance_id=instance_id,
            challenge_id=challenge_id,
            attempt=attempt,
            message=message,
            data=data or {},
            display=display,
        )
        self._file.write(event.model_dump_json() + "\n")
        self._file.flush()

    def write_footer(
        self,
        *,
        exit_code: int = 0,
        summary: dict[str, JsonValue] | None = None,
        evidence_sha256: str | None = None,
    ) -> None:
        if self._closed:
            raise BenchEvalError(f"run record writer for {self._path} is already closed")
        if self._footer_written:
            raise BenchEvalError(f"run record writer for {self._path} already has a footer")
        footer = RecordFooter(
            schema_version="bencheval_run_record_v1",
            record_type="footer",
            exit_code=exit_code,
            summary=summary or {},
            evidence_sha256=evidence_sha256,
        )
        self._file.write(footer.model_dump_json() + "\n")
        self._file.flush()
        self._footer_written = True

    def close(self) -> None:
        if not self._closed:
            self._file.close()
            self._closed = True

    def __enter__(self) -> RunRecordWriter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Deprecated redaction alias (moved to bencheval.presentation)
# ---------------------------------------------------------------------------
# redact_for_public_presentation() and strip_ansi() now live in
# bencheval.presentation. This deprecated alias keeps old imports working
# while callers migrate. New code should import from presentation.py.


def sanitize_for_replay(text: str, *, redact: bool = True) -> str:
    """Deprecated alias for :func:`bencheval.presentation.redact_for_public_presentation`."""
    from bencheval.presentation import redact_for_public_presentation

    return redact_for_public_presentation(text, redact=redact)


__all__ = [
    "LegacyMomoEvent",
    "RecordEvent",
    "RecordFooter",
    "RecordHeader",
    "RecordType",
    "ReplayEventKind",
    "RunRecord",
    "RunRecordSchemaVersion",
    "RunRecordWriter",
    "load_run_record",
    "replay",
    "sanitize_for_replay",
    "verify_bound_evidence",
]
