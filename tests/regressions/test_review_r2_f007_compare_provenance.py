"""Review round 2 F007: comparison must reject provenance drift."""

from __future__ import annotations

from datetime import UTC, datetime

from bencheval.evidence import EvidenceRecord
from bencheval.model_compare import assess_model_comparison_validity
from bencheval.runtime_compare import assess_runtime_comparison_validity

_TS = datetime(2026, 8, 6, tzinfo=UTC)


def _runtime_row(
    *,
    instance_id: str,
    runtime_id: str,
    runtime_version: str | None = None,
    runtime_config_hash: str | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"run-{runtime_id}-{instance_id}",
        task_id=instance_id,
        model_id="runtime-default",
        execution_profile="E1",
        backend="harbor",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.1,
        latency_sec=10.0,
        created_at=_TS,
        benchmark_id="terminal-bench",
        benchmark_version="2.0",
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@1",
        runtime_id=runtime_id,
        runtime_version=runtime_version or f"{runtime_id}@test",
        runtime_kind="cli_agent",
        runtime_config_hash=runtime_config_hash or f"sha256:{runtime_id}-config",
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm-test",
        instance_id=instance_id,
        interpretation_label="adapter_smoke",
        counts_toward_pass_at_k=True,
    )


def _model_row(
    *,
    instance_id: str,
    model_id: str,
    benchmark_version: str = "terminal-bench@2.0",
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"run-{model_id}-{instance_id}",
        task_id=instance_id,
        model_id=model_id,
        execution_profile="E0",
        backend="inspect",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.1,
        latency_sec=1.0,
        created_at=_TS,
        benchmark_id="terminal-bench",
        benchmark_version=benchmark_version,
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@1",
        runtime_id="claude-code",
        runtime_version="claude-code@test",
        runtime_kind="cli_agent",
        runtime_config_hash="sha256:claude-code-config",
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm-test",
        instance_id=instance_id,
        interpretation_label="model_comparison",
        counts_toward_pass_at_k=True,
    )


def test_mixed_runtime_version_within_baseline_is_invalid() -> None:
    baseline = [
        _runtime_row(instance_id="tb-001", runtime_id="claude-code", runtime_version="v1"),
        _runtime_row(instance_id="tb-002", runtime_id="claude-code", runtime_version="v2"),
    ]
    current = [
        _runtime_row(instance_id="tb-001", runtime_id="codex-cli"),
        _runtime_row(instance_id="tb-002", runtime_id="codex-cli"),
    ]
    verdict = assess_runtime_comparison_validity(baseline, current)
    assert verdict.valid is False
    assert verdict.interpretation_label == "diagnostic_only"
    assert any("runtime_version" in r and "baseline" in r for r in verdict.reasons)


def test_mixed_runtime_config_hash_within_current_is_invalid() -> None:
    baseline = [
        _runtime_row(instance_id="tb-001", runtime_id="claude-code"),
        _runtime_row(instance_id="tb-002", runtime_id="claude-code"),
    ]
    current = [
        _runtime_row(
            instance_id="tb-001",
            runtime_id="codex-cli",
            runtime_config_hash="sha256:a",
        ),
        _runtime_row(
            instance_id="tb-002",
            runtime_id="codex-cli",
            runtime_config_hash="sha256:b",
        ),
    ]
    verdict = assess_runtime_comparison_validity(baseline, current)
    assert verdict.valid is False
    assert any("runtime_config_hash" in r and "current" in r for r in verdict.reasons)


def test_model_compare_different_benchmark_version_is_invalid() -> None:
    baseline = [_model_row(instance_id="tb-001", model_id="openai/a")]
    current = [
        _model_row(
            instance_id="tb-001",
            model_id="openai/b",
            benchmark_version="terminal-bench@1.0",
        ),
    ]
    verdict = assess_model_comparison_validity(baseline, current)
    assert verdict.valid is False
    assert verdict.interpretation_label == "diagnostic_only"
    assert any("benchmark_version" in r for r in verdict.reasons)
