"""Append-only JSONL registry of live BenchEval runs (schema ``live_run_v1``).

Each line is one :class:`LiveRunRecord` describing a run's identity axes
(benchmark / slice / runtime / model) plus the paths to its evidence, report,
and bundle artifacts. The registry intentionally carries NO secrets: a
construction-time guard rejects any field whose value looks like a credential.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
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

    model_config = ConfigDict(extra="forbid")

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


def append_live_run(path: Path | str, record: LiveRunRecord) -> Path:
    """Append ``record`` as one JSON line to ``path`` (single-threaded).

    Creates parent directories as needed. Returns the resolved target path.
    """
    target = Path(path).resolve()
    if target.exists() and not target.is_file():
        raise LiveRunManifestError(f"path exists but is not a regular file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    line = record.model_dump_json() + "\n"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line)
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


def read_live_runs(path: Path | str) -> list[LiveRunRecord]:
    """Read every non-blank line of a runs manifest JSONL file in order."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise LiveRunManifestError(
            f"cannot decode runs manifest {p} as UTF-8: {e}",
        ) from e
    except OSError as e:
        raise LiveRunManifestError(f"cannot read runs manifest {p}: {e}") from e

    rows: list[LiveRunRecord] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        rows.append(_parse_line(line, p.name, line_no))
    return rows


class JsonlLiveRunSink:
    """Append a :class:`LiveRunRecord` as a JSON line; single-threaded only."""

    def append_jsonl(self, path: Path, record: LiveRunRecord) -> Path:
        return append_live_run(path, record)


__all__ = [
    "LIVE_RUN_SCHEMA_VERSION",
    "JsonlLiveRunSink",
    "LiveRunRecord",
    "LiveRunStatus",
    "append_live_run",
    "default_runs_manifest_path",
    "read_live_runs",
]
