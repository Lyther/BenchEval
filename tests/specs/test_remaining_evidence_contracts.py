"""RED contracts for evidence identity, comparison validity, and reporting.

The positive controls in this module keep the remediation honest: a valid
runtime comparison and a legacy v0.2 row must continue to work while ambiguous
or over-claimed evidence is rejected or downgraded to diagnostic-only.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bencheval.benchmark_plan import plan_control_plane
from bencheval.evidence import EvidenceRecord
from bencheval.model_compare import (
    assess_model_comparison_validity,
    compare_model_evidence,
    is_model_comparison_evidence,
)
from bencheval.report import generate_evidence_report
from bencheval.runtime_compare import assess_runtime_comparison_validity

_TS = datetime(2026, 8, 6, tzinfo=UTC)


def _runtime_record(
    *,
    instance_id: str,
    runtime_id: str,
    primary_pass: bool = True,
    benchmark_version: str | None = "terminal-bench@2.1",
    harness_version: str | None = "harbor@0.3.1",
    provider_id: str | None = "bytellm",
    runtime_version: str | None = None,
    runtime_config_hash: str | None = None,
    eligible: bool = True,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"runtime-{runtime_id}-{instance_id}",
        task_id=instance_id,
        model_id="kimi-k2.7-code",
        execution_profile="E4",
        backend="harbor",
        primary_pass=primary_pass,
        partial_score=1.0 if primary_pass else 0.0,
        cost_usd=0.25,
        latency_sec=12.0,
        created_at=_TS,
        benchmark_id="terminal-bench",
        benchmark_version=benchmark_version,
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version=harness_version,
        runtime_id=runtime_id,
        runtime_version=runtime_version or f"{runtime_id}@2026.08",
        runtime_kind="cli_agent",
        runtime_config_hash=runtime_config_hash or f"sha256:{runtime_id}-config",
        provider_id=provider_id,
        provider_config_hash="sha256:bytellm-test" if provider_id else None,
        instance_id=instance_id,
        interpretation_label="adapter_smoke",
        contamination_label="public_possible",
        reward_hack_risk_label="known_public_risk",
        verifier_integrity_label="native",
        attempt_validity="valid" if eligible else "invalid",
        counts_toward_pass_at_k=eligible,
    )


def _model_only_record(*, model_id: str, primary_pass: bool) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"gpqa-{model_id}",
        task_id="sample-0",
        model_id=model_id,
        execution_profile="E3",
        backend="inspect",
        primary_pass=primary_pass,
        partial_score=1.0 if primary_pass else 0.0,
        cost_usd=0.1,
        latency_sec=2.0,
        created_at=_TS,
        benchmark_id="gpqa-diamond",
        benchmark_version="gpqa-diamond@inspect-evals-pin",
        slice_id="smoke",
        adapter_id="gpqa",
        harness_kind="inspect-evals",
        harness_version="inspect-evals@0.3",
        runtime_id=None,
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm-test",
        instance_id="sample-0",
        interpretation_label="adapter_smoke",
        counts_toward_pass_at_k=True,
    )


def test_model_comparison_routes_model_only_evidence_without_promoting_smoke_claim() -> None:
    runtime_baseline = [
        _runtime_record(instance_id="tb-001", runtime_id="claude-code").model_copy(
            update={"interpretation_label": "model_comparison"},
        ),
    ]
    runtime_current = [
        _runtime_record(instance_id="tb-001", runtime_id="claude-code").model_copy(
            update={
                "model_id": "kimi-k2.7-code-variant",
                "interpretation_label": "model_comparison",
            },
        ),
    ]
    assert is_model_comparison_evidence(runtime_baseline, runtime_current) is True
    assert assess_model_comparison_validity(runtime_baseline, runtime_current).valid is True

    baseline = [_model_only_record(model_id="provider/model-a", primary_pass=False)]
    current = [_model_only_record(model_id="provider/model-b", primary_pass=True)]

    assert is_model_comparison_evidence(baseline, current) is True
    report = compare_model_evidence(baseline, current)
    assert report.runtime_id is None
    assert report.instance_count == 1
    assert report.pass_rate_delta == pytest.approx(1.0)
    assert report.validity.valid is False
    assert report.interpretation_label == "diagnostic_only"
    assert any("model_comparison" in reason for reason in report.validity.reasons)


def test_runtime_comparison_requires_complete_matching_provenance() -> None:
    baseline = [_runtime_record(instance_id="tb-001", runtime_id="claude-code")]
    current = [_runtime_record(instance_id="tb-001", runtime_id="codex-cli")]
    assert assess_runtime_comparison_validity(baseline, current).valid is True

    drift_cases = {
        "benchmark_version": current[0].model_copy(
            update={"benchmark_version": "terminal-bench@2.0"},
        ),
        "missing_benchmark_version": current[0].model_copy(update={"benchmark_version": None}),
        "missing_harness_version": current[0].model_copy(update={"harness_version": None}),
        "provider_id": current[0].model_copy(update={"provider_id": "other-provider"}),
        "missing_runtime_version": current[0].model_copy(update={"runtime_version": None}),
        "missing_runtime_config_hash": current[0].model_copy(
            update={"runtime_config_hash": None},
        ),
    }

    for axis, drifted in drift_cases.items():
        verdict = assess_runtime_comparison_validity(baseline, [drifted])
        assert verdict.valid is False, axis
        assert verdict.interpretation_label == "diagnostic_only", axis
        assert any(axis.replace("missing_", "") in reason for reason in verdict.reasons), axis


def test_runtime_comparison_rejects_zero_eligible_or_zero_shared_instances() -> None:
    eligible_baseline = [
        _runtime_record(
            instance_id="tb-001",
            runtime_id="claude-code",
            primary_pass=False,
        ),
    ]
    eligible_current = [
        _runtime_record(
            instance_id="tb-001",
            runtime_id="codex-cli",
            primary_pass=False,
        ),
    ]
    assert assess_runtime_comparison_validity(eligible_baseline, eligible_current).valid is True

    ineligible_baseline = [
        _runtime_record(
            instance_id="tb-001",
            runtime_id="claude-code",
            primary_pass=False,
            eligible=False,
        ),
    ]
    ineligible_current = [
        _runtime_record(
            instance_id="tb-001",
            runtime_id="codex-cli",
            primary_pass=False,
            eligible=False,
        ),
    ]
    ineligible = assess_runtime_comparison_validity(ineligible_baseline, ineligible_current)
    assert ineligible.valid is False
    assert ineligible.interpretation_label == "diagnostic_only"
    assert any("eligible" in reason for reason in ineligible.reasons)

    disjoint_current = [
        _runtime_record(instance_id="tb-999", runtime_id="codex-cli"),
    ]
    disjoint = assess_runtime_comparison_validity(eligible_baseline, disjoint_current)
    assert disjoint.valid is False
    assert any("shared" in reason for reason in disjoint.reasons)


def test_evidence_rejects_unknown_fields_without_breaking_v02_rows() -> None:
    legacy = {
        "run_id": "legacy-v02",
        "task_id": "legacy-task",
        "model_id": "legacy-model",
        "execution_profile": "E0",
        "primary_pass": True,
        "partial_score": 1.0,
        "cost_usd": 0.0,
        "latency_sec": 0.1,
        "created_at": _TS,
    }
    parsed = EvidenceRecord.model_validate(legacy)
    assert parsed.run_id == "legacy-v02"
    assert parsed.benchmark_id is None

    with pytest.raises(ValidationError, match="runtime_vesion"):
        EvidenceRecord.model_validate({**legacy, "runtime_vesion": "typo-is-not-provenance"})


def test_report_exposes_interpretation_axes_versions_and_integrity_without_core_warning() -> None:
    record = _runtime_record(instance_id="tb-contract-017", runtime_id="claude-code")
    report = generate_evidence_report([record])

    expected_fragments = (
        "Interpretation: `adapter_smoke`",
        "Benchmark: `terminal-bench`",
        "Benchmark version: `terminal-bench@2.1`",
        "Slice: `smoke-5`",
        "Adapter: `terminal-bench-harbor`",
        "Harness: `harbor`",
        "Harness version: `harbor@0.3.1`",
        "Runtime: `claude-code`",
        "Runtime version: `claude-code@2026.08`",
        "Provider: `bytellm`",
        "Contamination: `public_possible`",
        "Reward-hack risk: `known_public_risk`",
        "Verifier integrity: `native`",
    )
    for fragment in expected_fragments:
        assert fragment in report
    assert "Core-8" not in report
    assert "Core-16" not in report


def test_all_executable_plans_pin_a_benchmark_version() -> None:
    targets = (
        ("terminal-bench", "smoke-5", "claude-code"),
        ("swe-bench-verified", "swe-bench-verified-smoke-10", "claude-code"),
        ("bfcl-v4", "smoke-5", None),
        ("gpqa-diamond", "smoke", None),
        ("hle", "smoke", None),
    )
    versions = {
        benchmark_id: plan_control_plane(
            benchmark_id=benchmark_id,
            slice_id=slice_id,
            runtime_id=runtime_id,
            model_id="kimi-k2.7-code",
        ).benchmark_version
        for benchmark_id, slice_id, runtime_id in targets
    }

    assert set(versions) == {target[0] for target in targets}
    assert all(version and version.strip() for version in versions.values()), versions


def test_runtime_comparison_excludes_diagnostic_rows() -> None:
    baseline = [_runtime_record(instance_id="tb-001", runtime_id="claude-code")]
    current = [_runtime_record(instance_id="tb-001", runtime_id="codex-cli")]
    assert assess_runtime_comparison_validity(baseline, current).valid is True

    diagnostic_current = [current[0].model_copy(update={"interpretation_label": "diagnostic"})]
    verdict = assess_runtime_comparison_validity(baseline, diagnostic_current)
    assert verdict.valid is False
    assert verdict.interpretation_label == "diagnostic_only"
    assert any("diagnostic" in reason for reason in verdict.reasons)
