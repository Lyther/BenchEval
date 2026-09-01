"""Closed, redacted view models for BenchEval operator interfaces."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ViewDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["ui_v1"] = "ui_v1"


class OperationErrorDTO(ViewDTO):
    code: str
    message: str
    retryable: bool = False
    human_action_required: bool = False


class ActionDTO(ViewDTO):
    id: str
    allowed: bool
    disabled_reason: str | None = None


class CatalogItemDTO(ViewDTO):
    kind: Literal["benchmark", "model", "runtime", "agent", "provider"]
    id: str
    name: str
    status: str
    detail: tuple[str, ...] = ()
    runnable: bool = False
    default_slice: str | None = None


class CatalogSnapshotDTO(ViewDTO):
    items: tuple[CatalogItemDTO, ...]
    benchmark_count: int
    executable_count: int
    diagnostic_count: int


class CatalogPageDTO(ViewDTO):
    items: tuple[CatalogItemDTO, ...]
    source_revision: str
    next_cursor: str | None


class PlanRequestDTO(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark_id: str = Field(min_length=1)
    slice_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    runtime_id: str | None = None
    agent_id: str | None = None
    provider_id: str = "bytellm"
    diagnostic: bool = False
    output_path: str | None = Field(default=None, min_length=1)
    artifacts_dir: str | None = Field(default=None, min_length=1)


class PlanPreviewDTO(ViewDTO):
    request: PlanRequestDTO
    fingerprint: str
    benchmark_version: str
    adapter_id: str
    harness_kind: str
    backend: str
    execution_profile: str
    instance_count: int
    runtime_id: str | None
    agent_id: str | None
    provider_id: str
    model_id: str
    max_cost_usd: float
    max_wall_clock_sec: int
    network_policy: str
    diagnostic: bool
    executable: bool
    caveats: tuple[str, ...]


class DoctorCheckDTO(ViewDTO):
    name: str
    status: Literal["pass", "fail", "skip"]
    message: str


class DoctorViewDTO(ViewDTO):
    backend: str
    ok: bool
    checks: tuple[DoctorCheckDTO, ...]


class RunSummaryDTO(ViewDTO):
    run_id: str
    model_id: str
    host: str
    status: str
    benchmark_id: str | None
    slice_id: str | None
    runtime_id: str | None
    evidence_path: str | None
    report_path: str | None
    bundle_path: str | None
    event_count: int
    last_generated_at: str


class RunExecutionDTO(ViewDTO):
    run_id: str
    benchmark_id: str
    slice_id: str
    runtime_id: str | None
    model_id: str
    evidence_path: str
    passed_count: int
    failed_count: int
    outcome: Literal["finished"] = "finished"


class EvidenceSummaryDTO(ViewDTO):
    task_id: str
    instance_id: str | None
    primary_pass: bool
    partial_score: float
    failure_class: str | None
    attempt_validity: str | None
    interpretation_label: str | None
    cost_usd: float
    cost_basis: str | None
    artifacts: tuple[str, ...]


class QualificationViewDTO(ViewDTO):
    ok: bool
    eligible_count: int
    reasons: tuple[str, ...]


class RunDetailDTO(ViewDTO):
    summary: RunSummaryDTO
    history: tuple[dict[str, str | None], ...]
    evidence: tuple[EvidenceSummaryDTO, ...]
    evidence_total: int
    evidence_truncated: bool
    qualification: QualificationViewDTO | None
    actions: tuple[ActionDTO, ...]


class ArtifactResultDTO(ViewDTO):
    role: str
    path: str
    size: int
    sha256: str
    visibility: str | None = None
    valid: bool | None = None
    detail: tuple[str, ...] = ()


class ProofViewDTO(ViewDTO):
    proof_id: str
    run_id: str
    path: str
    classification: str
    classification_reason: str | None
    verified: bool
    benchmark_id: str | None = None


class ReadinessItemDTO(ViewDTO):
    benchmark_id: str
    executable: bool
    software_state: str
    tier1_state: str
    tier2_state: str
    ledger: str | None
    blockers: tuple[str, ...]
