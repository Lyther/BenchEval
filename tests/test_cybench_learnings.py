"""Regression tests for CyBench live-run design learnings."""

from __future__ import annotations

from bencheval.benchmark_plan import dry_run_slice_resolution, plan_control_plane
from bencheval.benchmark_registry import execution_support_label, load_benchmark_catalog


def test_cybench_is_metadata_only_execution_support() -> None:
    catalog = load_benchmark_catalog()
    cybench = catalog.by_id_or_alias("cybench")
    assert cybench.adapter_status == "cataloged"
    assert execution_support_label(cybench) == "metadata_only"


def test_terminal_bench_smoke_dry_run_slice_resolution() -> None:
    resolution = dry_run_slice_resolution(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
    )
    assert resolution["expected_instance_count"] == 5
    assert resolution["execution_support"] == "executable_adapter"
    assert len(resolution["instances_manifest_sha256"]) == 64
    assert resolution["resolved_instance_ids"]


def test_swe_verified_is_executable_not_manifest_only() -> None:
    catalog = load_benchmark_catalog()
    swe = catalog.by_id_or_alias("swe-bench-verified")
    assert swe.adapter_status == "manifest_available"
    assert execution_support_label(swe) == "executable_adapter"


def test_dry_run_plan_caveats_no_execution_support_caveat_when_executable() -> None:
    catalog = load_benchmark_catalog()
    entry = catalog.by_id_or_alias("terminal-bench")
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="codex-cli",
        model_id="openai/gpt-test",
    )
    assert "execution_support:executable_adapter" not in plan.caveats
    assert entry.id == "terminal-bench"


def test_evidence_record_attempt_validity_fields_roundtrip() -> None:
    from datetime import UTC, datetime

    from bencheval.evidence import EvidenceRecord

    rec = EvidenceRecord(
        run_id="r1",
        task_id="t1",
        model_id="m1",
        execution_profile="E0",
        primary_pass=False,
        partial_score=0.0,
        cost_usd=0.0,
        latency_sec=1.0,
        created_at=datetime(2026, 6, 18, tzinfo=UTC),
        failure_class="runtime_output_cap_reached",
        attempt_validity="invalid",
        invalid_reason="output_tokens==32000",
        counts_toward_pass_at_k=False,
        runtime_output_cap=32000,
    )
    restored = EvidenceRecord.model_validate_json(rec.model_dump_json())
    assert restored.failure_class == "runtime_output_cap_reached"
    assert restored.attempt_validity == "invalid"
    assert restored.counts_toward_pass_at_k is False
