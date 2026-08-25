"""Append-only JSONL registry of live BenchEval runs (schema ``live_run_v1``).

Each line is one :class:`LiveRunRecord` describing a run's identity axes
(benchmark / slice / runtime / model) plus the paths to its evidence, report,
and bundle artifacts. The registry intentionally carries NO secrets: a
construction-time guard rejects any field whose value looks like a credential.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bencheval.exceptions import LiveRunManifestError
from bencheval.paths import repo_root as _repo_root

LIVE_RUN_SCHEMA_VERSION = "live_run_v1"

LiveRunStatus = Literal[
    "registered",
    "running",
    "completed",
    "passed",
    "failed",
    "archived",
]

_DEFAULT_MANIFEST_REL = Path("results") / "manifests" / "runs.jsonl"

_SECRET_SUBSTRINGS = (
    "api_key",
    "api-key",
    "secret",
    "token",
    "password",
    "authorization",
    "bearer",
)
_SK_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")

_STR_FIELDS: tuple[str, ...] = (
    "run_id",
    "host",
    "benchmark",
    "slice_id",
    "runtime",
    "model_id",
    "evidence_path",
    "report_path",
    "bundle_path",
    "status",
    "notes",
)
_FILL_ONCE_AXES: tuple[str, ...] = ("benchmark", "slice_id", "runtime")
_ALLOWED_TRANSITIONS: dict[LiveRunStatus, frozenset[LiveRunStatus]] = {
    "registered": frozenset(
        {"registered", "running", "completed", "passed", "failed", "archived"},
    ),
    "running": frozenset({"running", "completed", "passed", "failed", "archived"}),
    "completed": frozenset({"completed", "passed", "failed", "archived"}),
    "passed": frozenset({"passed", "archived"}),
    "failed": frozenset({"failed", "archived"}),
    "archived": frozenset({"archived"}),
}


def _looks_secret(value: str) -> bool:
    if _SK_PATTERN.search(value):
        return True
    lowered = value.lower()
    return any(marker in lowered for marker in _SECRET_SUBSTRINGS)


class LiveRunRecord(BaseModel):
    """One row in the live run registry JSONL.

    Identity is required (``run_id``, ``host``, ``model_id``, ``generated_at``);
    the four-axis identity (``benchmark``/``slice_id``/``runtime``) and artifact
    paths are optional because a run may be registered before all artifacts exist.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["live_run_v1"] = LIVE_RUN_SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    host: str = Field(min_length=1)
    benchmark: str | None = None
    slice_id: str | None = None
    runtime: str | None = None
    model_id: str = Field(min_length=1)
    evidence_path: str | None = None
    report_path: str | None = None
    bundle_path: str | None = None
    status: LiveRunStatus = "registered"
    notes: str = ""
    generated_at: datetime

    @model_validator(mode="after")
    def _reject_secrets(self) -> LiveRunRecord:
        for field_name in _STR_FIELDS:
            value = getattr(self, field_name)
            if isinstance(value, str) and _looks_secret(value):
                raise ValueError(
                    f"field {field_name!r} appears to contain a secret; "
                    "refusing to record (live run manifest must stay non-secret)",
                )
        return self


def default_runs_manifest_path() -> Path:
    """Default registry location: ``<repo>/results/manifests/runs.jsonl``."""
    return _repo_root() / _DEFAULT_MANIFEST_REL


def _aware_event_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _first_filled(rows: list[LiveRunRecord], field: str) -> str | None:
    for row in rows:
        value = getattr(row, field)
        if isinstance(value, str):
            return value
    return None


def _latest_filled(rows: list[LiveRunRecord], field: str) -> str | None:
    latest: str | None = None
    for row in rows:
        value = getattr(row, field)
        if isinstance(value, str):
            latest = value
    return latest


def _lock_path(manifest: Path) -> Path:
    return manifest.with_name(f"{manifest.name}.lock")


@contextmanager
def _live_run_lock(manifest: Path, *, exclusive: bool) -> Iterator[None]:
    lock_path = _lock_path(manifest)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as e:
        raise LiveRunManifestError(f"cannot lock runs manifest {manifest}: {e}") from e
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _reject_record_against_prior(prior: list[LiveRunRecord], record: LiveRunRecord) -> None:
    if not prior:
        return
    last = prior[-1]
    if _aware_event_time(record.generated_at) < _aware_event_time(last.generated_at):
        raise LiveRunManifestError(
            f"run {record.run_id!r}: event time moves backward",
        )
    allowed = _ALLOWED_TRANSITIONS[last.status]
    if record.status not in allowed:
        raise LiveRunManifestError(
            f"run {record.run_id!r}: cannot move from {last.status!r} to {record.status!r}",
        )
    if record.model_id != prior[0].model_id:
        raise LiveRunManifestError(f"run {record.run_id!r}: model_id is immutable")
    for field in _FILL_ONCE_AXES:
        filled = _first_filled(prior, field)
        incoming = getattr(record, field)
        if filled is not None and incoming is not None and incoming != filled:
            raise LiveRunManifestError(
                f"run {record.run_id!r}: {field} is immutable once filled",
            )


def _validate_live_run_history(rows: list[LiveRunRecord]) -> None:
    histories: dict[str, list[LiveRunRecord]] = {}
    for record in rows:
        history = histories.setdefault(record.run_id, [])
        _reject_record_against_prior(history, record)
        history.append(record)


def _reject_inconsistent_history(existing: list[LiveRunRecord], record: LiveRunRecord) -> None:
    _validate_live_run_history(existing)
    _reject_record_against_prior(
        [row for row in existing if row.run_id == record.run_id],
        record,
    )


def append_live_run(path: Path | str, record: LiveRunRecord) -> Path:
    """Append ``record`` as one JSON line to ``path``.

    The leaf is opened with ``O_NOFOLLOW`` so a swapped symlink cannot
    redirect the append; the lexical (unresolved) path is used on purpose,
    since resolving would follow that symlink. Read→validate→append→fsync
    is one exclusive ``fcntl.flock`` critical section.
    """
    target = Path(os.path.abspath(Path(path).expanduser()))
    if target.exists() and not target.is_file():
        raise LiveRunManifestError(f"path exists but is not a regular file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    line = record.model_dump_json() + "\n"
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    with _live_run_lock(target, exclusive=True):
        _reject_inconsistent_history(_parse_live_run_rows(target), record)
        try:
            descriptor = os.open(target, flags, 0o600)
        except OSError as e:
            raise LiveRunManifestError(f"cannot append runs manifest {target}: {e}") from e
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
    return target


def _parse_line(line: str, source: str, line_no: int) -> LiveRunRecord:
    try:
        return LiveRunRecord.model_validate_json(line)
    except json.JSONDecodeError as e:
        raise LiveRunManifestError(
            f"{source}:line {line_no}: invalid JSON: {e}",
        ) from e
    except LiveRunManifestError as e:
        raise LiveRunManifestError(f"{source}:line {line_no}: {e}") from e
    except ValidationError as e:
        errs = e.errors()
        if len(errs) == 1 and errs[0].get("type") == "json_invalid":
            raise LiveRunManifestError(
                f"{source}:line {line_no}: invalid JSON: {e}",
            ) from e
        raise LiveRunManifestError(f"{source}:line {line_no}: {e}") from e


def _parse_live_run_text(text: str, source: str) -> list[LiveRunRecord]:
    rows: list[LiveRunRecord] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        rows.append(_parse_line(line, source, line_no))
    return rows


def _parse_live_run_rows(path: Path) -> list[LiveRunRecord]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise LiveRunManifestError(
            f"cannot decode runs manifest {path} as UTF-8: {e}",
        ) from e
    except OSError as e:
        raise LiveRunManifestError(f"cannot read runs manifest {path}: {e}") from e
    return _parse_live_run_text(text, path.name)


def read_live_runs(path: Path | str) -> list[LiveRunRecord]:
    """Read and validate every non-blank line of a runs manifest JSONL file."""
    p = Path(path)
    if not p.is_file():
        raise LiveRunManifestError(f"cannot read runs manifest {p}: file does not exist")
    with _live_run_lock(p, exclusive=False):
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            raise LiveRunManifestError(
                f"cannot decode runs manifest {p} as UTF-8: {e}",
            ) from e
        except OSError as e:
            raise LiveRunManifestError(f"cannot read runs manifest {p}: {e}") from e
        rows = _parse_live_run_text(text, p.name)
        _validate_live_run_history(rows)
        return rows


@dataclass(frozen=True, slots=True)
class LiveRunProjection:
    """Last-valid-event operational view for one run_id. Raw rows stay intact."""

    run_id: str
    model_id: str
    host: str
    status: LiveRunStatus
    benchmark: str | None
    slice_id: str | None
    runtime: str | None
    evidence_path: str | None
    report_path: str | None
    bundle_path: str | None
    notes: str
    event_count: int
    first_generated_at: datetime
    last_generated_at: datetime


def project_live_runs(rows: list[LiveRunRecord]) -> tuple[LiveRunProjection, ...]:
    """Derive one current-state row per run_id from a validated history."""
    _validate_live_run_history(rows)
    projections: list[LiveRunProjection] = []
    seen: dict[str, list[LiveRunRecord]] = {}
    order: list[str] = []
    for record in rows:
        if record.run_id not in seen:
            order.append(record.run_id)
            seen[record.run_id] = []
        seen[record.run_id].append(record)
    for run_id in order:
        history = seen[run_id]
        last = history[-1]
        projections.append(
            LiveRunProjection(
                run_id=run_id,
                model_id=history[0].model_id,
                host=last.host,
                status=last.status,
                benchmark=_first_filled(history, "benchmark"),
                slice_id=_first_filled(history, "slice_id"),
                runtime=_first_filled(history, "runtime"),
                evidence_path=_latest_filled(history, "evidence_path"),
                report_path=_latest_filled(history, "report_path"),
                bundle_path=_latest_filled(history, "bundle_path"),
                notes=last.notes,
                event_count=len(history),
                first_generated_at=_aware_event_time(history[0].generated_at),
                last_generated_at=_aware_event_time(last.generated_at),
            ),
        )
    return tuple(projections)


def read_live_run_projections(path: Path | str) -> tuple[LiveRunProjection, ...]:
    return project_live_runs(read_live_runs(path))


class JsonlLiveRunSink:
    """Append a :class:`LiveRunRecord` as a JSON line under the exclusive lock."""

    def append_jsonl(self, path: Path, record: LiveRunRecord) -> Path:
        return append_live_run(path, record)


__all__ = [
    "LIVE_RUN_SCHEMA_VERSION",
    "JsonlLiveRunSink",
    "LiveRunProjection",
    "LiveRunRecord",
    "LiveRunStatus",
    "append_live_run",
    "default_runs_manifest_path",
    "project_live_runs",
    "read_live_run_projections",
    "read_live_runs",
]
