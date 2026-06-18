from __future__ import annotations

import json
from datetime import UTC, datetime

from bencheval.evidence import EvidenceRecord
from bencheval.model_compare import (
    assess_model_comparison_validity,
    compare_model_evidence,
    is_model_comparison_evidence,
    render_model_comparison_json,
)

_TS = datetime(2026, 6, 1, tzinfo=UTC)


def _cp_record(
    *,
    instance_id: str,
    model_id: str,
    runtime_id: str = "native-api",
    primary_pass: bool = True,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"run-{model_id}-{instance_id}",
        task_id=instance_id,
        model_id=model_id,
        execution_profile="E0",
        backend="inspect",
        primary_pass=primary_pass,
        partial_score=1.0 if primary_pass else 0.0,
        cost_usd=0.1,
        latency_sec=1.0,
        created_at=_TS,
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@1",
        runtime_id=runtime_id,
        instance_id=instance_id,
    )


def test_is_model_comparison_evidence() -> None:
    baseline = [_cp_record(instance_id="tb-001", model_id="openai/a")]
    current = [_cp_record(instance_id="tb-001", model_id="openai/b")]
    assert is_model_comparison_evidence(baseline, current) is True


def test_model_comparison_valid_and_compare() -> None:
    baseline = [
        _cp_record(instance_id="tb-001", model_id="openai/a", primary_pass=True),
        _cp_record(instance_id="tb-002", model_id="openai/a", primary_pass=False),
    ]
    current = [
        _cp_record(instance_id="tb-001", model_id="openai/b", primary_pass=True),
        _cp_record(instance_id="tb-002", model_id="openai/b", primary_pass=True),
    ]
    verdict = assess_model_comparison_validity(baseline, current)
    assert verdict.valid is True
    assert verdict.interpretation_label == "model_comparison"
    report = compare_model_evidence(baseline, current)
    assert report.pass_rate_delta > 0
    assert report.runtime_id == "native-api"


def test_model_compare_pass_rates_use_shared_instances_only() -> None:
    baseline = [
        _cp_record(instance_id="tb-001", model_id="openai/a", primary_pass=True),
        _cp_record(instance_id="tb-002", model_id="openai/a", primary_pass=True),
        _cp_record(instance_id="tb-extra", model_id="openai/a", primary_pass=False),
    ]
    current = [
        _cp_record(instance_id="tb-001", model_id="openai/b", primary_pass=True),
        _cp_record(instance_id="tb-002", model_id="openai/b", primary_pass=False),
    ]
    report = compare_model_evidence(baseline, current)
    assert report.instance_count == 2
    assert report.baseline_pass_rate == 1.0
    assert report.current_pass_rate == 0.5


def test_model_compare_json_includes_ci_fields() -> None:
    baseline = [_cp_record(instance_id="tb-001", model_id="openai/a", primary_pass=True)]
    current = [_cp_record(instance_id="tb-001", model_id="openai/b", primary_pass=False)]
    report = compare_model_evidence(baseline, current)
    payload = json.loads(render_model_comparison_json(report))
    for key in (
        "baseline_pass_ci_low",
        "baseline_pass_ci_high",
        "current_pass_ci_low",
        "current_pass_ci_high",
        "pass_rate_delta_ci_low",
        "pass_rate_delta_ci_high",
    ):
        assert key in payload
