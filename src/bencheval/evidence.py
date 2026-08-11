"""JSONL evidence store for BenchEval vNext runs."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from bencheval.backends import LOCAL_BACKEND, ExecutionBackend
from bencheval.domain import (
    ContaminationLabel,
    ExecutionProfile,
    FailureLabel,
    InterpretationLabel,
    RewardHackRiskLabel,
    RuntimeKind,
    VerifierIntegrityLabel,
)
from bencheval.exceptions import BenchEvalError, EvidenceValidationError
from bencheval.run_isolation import append_reserved_evidence


class EvidenceRecord(BaseModel):
    """One attempt row in the JSONL evidence store.

    v0.2 fields (run_id .. created_at) are a frozen public contract: they MUST stay
    unchanged and all v0.2 rows must keep parsing. v0.3 adds optional fields below
    with safe defaults so a v0.2 row validates with all v0.3 fields absent.
    Unknown keys are rejected so provenance typos cannot be silently discarded.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- v0.2 (unchanged; do not reorder or drop) ---
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

    @field_validator("partial_score", "cost_usd", "latency_sec", mode="before")
    @classmethod
    def _require_finite_float(cls, value: object) -> object:
        if isinstance(value, (int, float)) and not math.isfinite(float(value)):
            raise ValueError("numeric field must be finite")
        return value

    # --- v0.3 additive (optional; absent => behaves as v0.2) ---
    # Four-axis identity.
    benchmark_id: str | None = None
    benchmark_version: str | None = None
    slice_id: str | None = None
    adapter_id: str | None = None
    harness_kind: str | None = None
    harness_version: str | None = None
    runtime_id: str | None = None
    runtime_version: str | None = None
    runtime_kind: RuntimeKind | None = None
    runtime_config_hash: str | None = None
    agent_id: str | None = None
    provider_id: str | None = None
    provider_config_hash: str | None = None
    judge_model_id: str | None = None
    # Attempt operational metadata.
    instance_id: str | None = None
    steps: int | None = Field(default=None, ge=0)
    token_usage: dict[str, int] | None = None
    native_score: dict[str, JsonValue] | None = None
    normalized_score: float | None = Field(default=None, ge=0.0, le=1.0)
    # Integrity / caveat labels.
    interpretation_label: InterpretationLabel | None = None
    contamination_label: ContaminationLabel | None = None
    reward_hack_risk_label: RewardHackRiskLabel | None = None
    verifier_integrity_label: VerifierIntegrityLabel | None = None
    cleanup_result: str | None = None
    # Optional structured failure class (one of the canonical taxonomy). The free-form
    # failure_labels list above is preserved for backward compat and multi-label cases.
    failure_class: FailureLabel | None = None
    # Attempt validity (live-run learnings): physical launches vs Pass@k budget.
    attempt_validity: Literal["valid", "invalid"] | None = None
    invalid_reason: str | None = None
    counts_toward_pass_at_k: bool | None = None
    physical_launch_id: str | None = None
    logical_attempt_number: int | None = Field(default=None, ge=1)
    runtime_output_cap: int | None = Field(default=None, ge=1)


# Failure classes that prove the attempt never produced a native harness/scorer
# result: launch/setup/auth/permission failures, infra stalls and timeouts,
# adapter/harness errors, and policy interruptions (see the FailureLabel
# taxonomy in domain.py). They never enter pass@k denominators or shared-instance
# accounting, regardless of what the explicit validity fields say.
INFRASTRUCTURE_FAILURE_CLASSES: frozenset[str] = frozenset(
    {
        "harness_failure",
        "runtime_launch_failure",
        "runtime_auth_failure",
        "runtime_permission_block",
        "runtime_output_unparseable",
        "runtime_context_overflow",
        "runtime_tool_failure",
        "runtime_config_drift",
        "runtime_budget_exceeded",
        "runtime_output_cap_reached",
        "runtime_no_progress_stall",
        "runtime_wall_clock_timeout",
        "materialization_failure",
        "adapter_error",
        "budget_exceeded",
        "operator_interrupted",
        "interrupted_by_harness",
        "config_failed",
        "remote_infra_failure",
        "evidence_corrupt",
        "duplicate_launch",
    }
)


def eligible_for_pass_at_k(record: EvidenceRecord) -> bool:
    """Whether a row should enter pass@k rate / Wilson CI denominators.

    Canonical rule, used by live proof, model/runtime comparison, and reports:
    an infrastructure-failure row is never eligible. The veto reads both the
    v0.3 ``failure_class`` and the frozen v0.2 ``failure_labels`` list (legacy
    rows carry only the latter), applies even when both explicit validity
    fields are absent, and cannot be overridden by an explicit
    ``counts_toward_pass_at_k=True`` stamp. Otherwise the explicit stamp wins,
    then ``attempt_validity``.
    """
    if record.failure_class is not None and record.failure_class in INFRASTRUCTURE_FAILURE_CLASSES:
        return False
    if any(label in INFRASTRUCTURE_FAILURE_CLASSES for label in record.failure_labels):
        return False
    if record.counts_toward_pass_at_k is not None:
        return record.counts_toward_pass_at_k
    return record.attempt_validity != "invalid"


def count_ineligible_pass_at_k(records: list[EvidenceRecord]) -> int:
    """Rows excluded from Pass@k denominators (invalid / output-cap policy)."""
    return sum(1 for r in records if not eligible_for_pass_at_k(r))


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
    except UnicodeDecodeError as e:
        raise BenchEvalError(f"cannot decode evidence jsonl {p} as UTF-8: {e}") from e
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
        line = record.model_dump_json() + "\n"
        if append_reserved_evidence(path, line.encode("utf-8")):
            return
        target = path.resolve()
        if target.exists() and not target.is_file():
            raise BenchEvalError(f"path exists but is not a regular file: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as f:
            f.write(line)
