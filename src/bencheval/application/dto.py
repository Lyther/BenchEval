"""Closed, redacted view models for BenchEval operator interfaces."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bencheval.exceptions import BenchEvalError


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
    # None defers to the model's declared provider_route (planner rule).
    provider_id: str | None = None
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
    # Plan-aware preflight only (CF3.1): resolved selection, recipe, host roots.
    selection: dict[str, object] | None = None
    recipe: dict[str, object] | None = None
    host: dict[str, object] | None = None


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


class StudyValidationDTO(ViewDTO):
    """What ``bencheval study validate`` established, projected unchanged."""

    study_id: str
    study_sha256: str
    kind: str
    relation: str
    comparison_mode: str
    payload: dict[str, object]


class StudyReportDTO(ViewDTO):
    """One exposure report, projected from the domain payload without re-deriving it.

    Every number, caveat, and non-claim below is read out of ``payload``; the
    projection never recomputes a rate, an interval, or an interpretation.
    """

    study_id: str
    analysis_mode: str
    population_scale: str
    population_binding: tuple[str, ...] | None
    relation: str
    comparison_mode: str
    report_sha256: str
    lock_sha256: str | None = None
    report_path: str | None = None
    lock_path: str | None = None
    permitted_interpretation: str
    non_claims: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    pairs: dict[str, object] | None = None
    payload: dict[str, object]

    def table_rows(self) -> tuple[dict[str, str], ...]:
        """Label/value rows for a keyboard-reachable table fallback."""
        return _study_table_rows(self.payload)


class StudyLockVerificationDTO(ViewDTO):
    """A reproduction of a retained lock: never an upgrade of its claim.

    ``payload`` is the domain verification result. ``analysis_mode``,
    ``non_claims``, and ``caveats`` are read from the reproduced report when the
    operator asked for one; they are the locked report's own words, not a second
    interpretation of the lock.
    """

    ok: bool
    study_id: str
    report_sha256: str
    lock_sha256: str
    canonical_proof_id: str | None = None
    candidate_proof_id: str | None = None
    analysis_mode: str | None = None
    non_claims: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    report_path: str | None = None
    report_payload: dict[str, object] | None = None
    payload: dict[str, object]

    def table_rows(self) -> tuple[dict[str, str], ...]:
        """Label/value rows for the reproduction, including the report it rebuilt."""
        # ``field`` is the table's row key, so the verification's own rows must not
        # collide with the rebuilt report's rows appended below.
        rows = [
            {"field": "reproduced", "value": "yes" if self.ok else "no"},
            {"field": "locked study", "value": self.study_id},
            {"field": "report digest", "value": self.report_sha256},
            {"field": "lock digest", "value": self.lock_sha256},
        ]
        if self.report_payload is None:
            # Verification alone proves the reproduction. The locked report's own
            # numbers and non-claims are shown only when one was written, so the
            # short table is deliberate rather than a failure.
            rows.append(
                {
                    "field": "report",
                    "value": (
                        "digests match the lock; ask for a JSON reproduction output to see the "
                        "locked report's scores, caveats, and non-claims"
                    ),
                },
            )
            return tuple(rows)
        rows.extend(_study_table_rows(self.report_payload))
        return tuple(rows)


def _required(payload: dict[str, object], key: str) -> object:
    """Read a field the exposure report always emits.

    A renamed or dropped domain field must fail loudly rather than reach the
    operator as a blank cell, and it must fail as the operator-facing error type
    every frontend already handles.
    """
    try:
        return payload[key]
    except KeyError as exc:
        raise BenchEvalError(f"exposure report is missing the {key!r} field") from exc


def _side_row(payload: dict[str, object], side: str) -> str:
    value = _required(payload, side)
    if not isinstance(value, dict):
        raise BenchEvalError(f"exposure report side {side!r} is not an object")
    overall = value.get("overall")
    rate = overall.get("rate") if isinstance(overall, dict) else None
    counts = ""
    if isinstance(overall, dict):
        counts = f"{overall.get('passed')}/{overall.get('eligible')}"
    interval = ""
    if isinstance(rate, dict):
        interval = f" rate {rate['point']:.3f} [{rate['low']:.3f}, {rate['high']:.3f}]"
    return f"{value.get('benchmark_id')} ({value.get('slice_id')}) {counts}{interval}".strip()


def _study_table_rows(payload: dict[str, object]) -> tuple[dict[str, str], ...]:
    """Render an exposure report payload as label/value rows.

    The required keys are indexed, not defaulted: a renamed report field must
    fail loudly here rather than reach the operator as a blank cell.
    """
    binding = payload.get("population_binding")
    rows: list[dict[str, str]] = [
        {"field": "study", "value": str(_required(payload, "study_id"))},
        {"field": "relation", "value": str(_required(payload, "relation"))},
        {"field": "comparison mode", "value": str(_required(payload, "comparison_mode"))},
        {"field": "analysis mode", "value": str(_required(payload, "analysis_mode"))},
        {"field": "population scale", "value": str(_required(payload, "population_scale"))},
        {
            "field": "population binding",
            "value": ", ".join(binding) if isinstance(binding, list) else "none (raw-only ceiling)",
        },
        {"field": "canonical", "value": _side_row(payload, "canonical")},
        {"field": "candidate", "value": _side_row(payload, "candidate")},
        {"field": "retrieval observed", "value": str(_required(payload, "retrieval_observed"))},
    ]
    pairs = payload.get("pairs")
    if isinstance(pairs, dict):
        rows.append(
            {"field": "pairs", "value": ", ".join(f"{k}={v}" for k, v in pairs.items())},
        )
    delta = payload.get("paired_delta")
    test = payload.get("paired_test")
    if delta is not None and isinstance(test, dict):
        rows.append(
            {
                "field": "paired delta",
                "value": (
                    f"{float(delta):+.3f} ({test.get('method')}: discordant "
                    f"{test.get('discordant_pairs')}, p {test.get('p_value')})"
                ),
            },
        )
    difference = payload.get("difference")
    if isinstance(difference, dict):
        rows.append(
            {"field": "difference", "value": ", ".join(f"{k}={v}" for k, v in difference.items())},
        )
    rows.append(
        {
            "field": "permitted interpretation",
            "value": str(_required(payload, "permitted_interpretation")),
        },
    )
    forbidden = payload.get("forbidden_claims")
    if isinstance(forbidden, list):
        rows.append({"field": "non-claims", "value": "; ".join(str(c) for c in forbidden)})
    caveats = payload.get("caveats")
    if isinstance(caveats, list):
        rows.append({"field": "caveats", "value": "; ".join(str(c) for c in caveats)})
    return tuple(rows)
