"""JSONL evidence store for BenchEval vNext runs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from bencheval.backends import LOCAL_BACKEND, ExecutionBackend
from bencheval.exceptions import BenchEvalError, EvidenceValidationError
from bencheval.task_contract import ExecutionProfile


class EvidenceRecord(BaseModel):
    run_id: str
    task_id: str
    model_id: str
    execution_profile: ExecutionProfile
    backend: ExecutionBackend = LOCAL_BACKEND
    primary_pass: bool
    partial_score: float = Field(ge=0.0, le=1.0)
    cost_usd: float = Field(ge=0.0)
    latency_sec: float = Field(ge=0.0)
    failure_labels: list[str] = Field(default_factory=list)
    artifact_paths: list[str] = Field(default_factory=list)
    verifier_log_path: str | None = None
    adapter_metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime


def _parse_line(line: str, source: str, line_no: int) -> EvidenceRecord:
    try:
        return EvidenceRecord.model_validate_json(line)
    except json.JSONDecodeError as e:
        raise EvidenceValidationError(
            f"{source}:line {line_no}: invalid JSON: {e}",
        ) from e
    except ValidationError as e:
        errs = e.errors()
        if len(errs) == 1 and errs[0].get("type") == "json_invalid":
            raise EvidenceValidationError(
                f"{source}:line {line_no}: invalid JSON: {e}",
            ) from e
        raise EvidenceValidationError(f"{source}:line {line_no}: {e}") from e


def read_evidence_jsonl(path: Path | str) -> list[EvidenceRecord]:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise BenchEvalError(f"cannot read evidence jsonl {p}: {e}") from e

    rows: list[EvidenceRecord] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        rows.append(_parse_line(line, p.name, line_no))
    return rows


class JsonlEvidenceSink:
    """Append ``EvidenceRecord`` as JSON lines; single-threaded only."""

    def append_jsonl(self, path: Path, record: EvidenceRecord) -> None:
        target = path.resolve()
        if target.exists() and not target.is_file():
            raise BenchEvalError(f"path exists but is not a regular file: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        line = record.model_dump_json() + "\n"
        with target.open("a", encoding="utf-8") as f:
            f.write(line)
