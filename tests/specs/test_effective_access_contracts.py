"""Behavioral contracts for additive effective-access evidence.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed ``BfclInstanceOutcome`` in
  ``test_model_only_outcome_projects_effective_access``
- replaces: a charged provider-backed BFCL outcome
- necessity: the assertion targets the pure adapter-outcome to EvidenceRecord
  projection; a live run cannot safely and deterministically isolate that mapping
- real-option: a real BFCL diagnostic would include provider and official harness
  behavior unrelated to this schema projection and would incur external cost
- proof-limit: proves only BenchEval's outcome/evidence mapping, not BFCL execution
  or the provider's effective network path
- real-proof: roadmap X2.3 real BFCL Live diagnostic and private proof

"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bencheval.access_evidence import (
    harbor_uncontrolled_access,
    inspect_swe_access_from_retained_config,
    model_only_access,
)
from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import BfclInstanceOutcome
from bencheval.control_plane_executor import _evidence_from_bfcl_outcome
from bencheval.evidence import EvidenceRecord, eligible_for_pass_at_k


def _legacy_record(**updates: object) -> EvidenceRecord:
    values: dict[str, object] = {
        "run_id": "legacy-run",
        "task_id": "task-1",
        "model_id": "gpt-5.2-2025-12-11",
        "execution_profile": "E0",
        "primary_pass": True,
        "partial_score": 1.0,
        "cost_usd": 0.0,
        "latency_sec": 0.1,
        "created_at": datetime(2026, 9, 3, tzinfo=UTC),
    }
    values.update(updates)
    return EvidenceRecord.model_validate(values)


def test_legacy_rows_leave_effective_access_unknown() -> None:
    row = _legacy_record()

    assert row.access_control_source is None
    assert row.egress_control is None
    assert row.repository_history is None
    assert row.retrieval_audit is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("access_control_source", "plan_policy"),
        ("egress_control", "allowed"),
        ("repository_history", "git_present"),
        ("retrieval_audit", "clean"),
    ],
)
def test_effective_access_values_are_closed(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        _legacy_record(**{field: value})


def test_model_only_and_harbor_access_are_distinct_from_plan_intent() -> None:
    model_only = model_only_access()
    harbor = harbor_uncontrolled_access()

    assert model_only.access_control_source == "not_applicable"
    assert model_only.egress_control == "not_applicable"
    assert model_only.repository_history == "not_applicable"
    assert model_only.retrieval_audit == "not_run"
    assert harbor.access_control_source == "none"
    assert harbor.egress_control == "uncontrolled"
    assert harbor.repository_history == "unknown"
    assert harbor.retrieval_audit == "not_run"


def test_inspect_swe_requires_the_retained_effective_compose() -> None:
    compose = b"services:\n  default:\n    network_mode: none\n"

    access = inspect_swe_access_from_retained_config(
        task_registry_name="inspect_evals/swe_bench",
        sandbox_type="docker",
        allow_internet=False,
        allow_internet_overridden=False,
        compose_bytes=compose,
    )

    assert access is not None
    assert access.access_control_source == "official_default"
    assert access.egress_control == "blocked"
    assert access.repository_history == "unknown"


@pytest.mark.parametrize(
    (
        "task_registry_name",
        "sandbox_type",
        "allow_internet",
        "allow_internet_overridden",
        "compose_bytes",
    ),
    [
        ("other/task", "docker", False, False, b"services:\n  default:\n    network_mode: none\n"),
        ("inspect_evals/swe_bench", "local", False, False, b"services: {}\n"),
        ("inspect_evals/swe_bench", "docker", True, False, b"services: {}\n"),
        ("inspect_evals/swe_bench", "docker", False, True, b"services: {}\n"),
        (
            "inspect_evals/swe_bench",
            "docker",
            False,
            False,
            b"services:\n  default:\n    network_mode: bridge\n",
        ),
        ("inspect_evals/swe_bench", "docker", False, False, b"[]\n"),
    ],
)
def test_inspect_swe_never_invents_blocked_access(
    task_registry_name: str,
    sandbox_type: str,
    allow_internet: bool,
    allow_internet_overridden: bool,
    compose_bytes: bytes,
) -> None:
    assert (
        inspect_swe_access_from_retained_config(
            task_registry_name=task_registry_name,
            sandbox_type=sandbox_type,
            allow_internet=allow_internet,
            allow_internet_overridden=allow_internet_overridden,
            compose_bytes=compose_bytes,
        )
        is None
    )


def test_retrieval_audit_does_not_change_scoring_or_eligibility() -> None:
    no_audit = _legacy_record(retrieval_audit="not_run")
    observed = _legacy_record(retrieval_audit="retrieval_observed")

    assert observed.primary_pass == no_audit.primary_pass
    assert observed.partial_score == no_audit.partial_score
    assert eligible_for_pass_at_k(observed) == eligible_for_pass_at_k(no_audit)


def test_model_only_outcome_projects_effective_access() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
    )
    outcome = BfclInstanceOutcome(
        instance_id="irrelevance",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.0,
        latency_sec=0.1,
        native_score={"accuracy": 1.0},
        failure_class=None,
        stdout_path=None,
        stderr_path=None,
        verifier_log_path="official-score.json",
        adapter_metadata={"benchmark_version": plan.benchmark_version},
    )

    row = _evidence_from_bfcl_outcome(
        plan=plan,
        run_id="access-projection",
        outcome=outcome,
        execution_profile="E0",
    )

    assert row.access_control_source == "not_applicable"
    assert row.egress_control == "not_applicable"
    assert row.repository_history == "not_applicable"
    assert row.retrieval_audit == "not_run"
