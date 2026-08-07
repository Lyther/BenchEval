"""Fallback harness labels must be named even when sides disagree on harness_version."""

from __future__ import annotations

from bencheval.model_compare import assess_model_comparison_validity
from bencheval.provenance_gates import (
    is_captured_harness_version,
    is_uncaptured_harness_version,
)
from bencheval.runtime_compare import assess_runtime_comparison_validity
from tests.specs.test_review_r3_proof_contracts import _comparison_record


def test_shared_captured_harness_predicate() -> None:
    assert is_uncaptured_harness_version("swebench-native-smoke")
    assert is_uncaptured_harness_version("bfcl-native-smoke")
    assert not is_captured_harness_version("swebench-native-smoke")
    assert is_captured_harness_version("harbor@0.3.1")
    assert not is_captured_harness_version(None)
    assert not is_captured_harness_version("   ")
    assert not is_captured_harness_version("\t")


def test_model_compare_names_fallback_when_harness_versions_differ() -> None:
    baseline = _comparison_record(
        run_id="mixed-model-baseline",
        runtime_id=None,
        model_id="model-a",
        interpretation_label="model_comparison",
    ).model_copy(
        update={
            "benchmark_version": "terminal-bench@2.1",
            "harness_version": "swebench-native-smoke",
            "runtime_id": None,
            "runtime_kind": None,
            "runtime_version": None,
            "runtime_config_hash": None,
        },
    )
    current = baseline.model_copy(
        update={
            "run_id": "mixed-model-current",
            "model_id": "model-b",
            "harness_version": "harbor@0.3.1",
        },
    )

    verdict = assess_model_comparison_validity([baseline], [current])
    reason = " ".join(verdict.reasons).lower()

    assert verdict.valid is False
    assert "fallback" in reason or "uncaptured" in reason


def test_runtime_compare_names_fallback_when_harness_versions_differ() -> None:
    baseline = _comparison_record(
        run_id="mixed-runtime-baseline",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
        interpretation_label="adapter_smoke",
    ).model_copy(
        update={
            "benchmark_version": "terminal-bench@2.1",
            "harness_version": "bfcl-native-smoke",
        },
    )
    current = baseline.model_copy(
        update={
            "run_id": "mixed-runtime-current",
            "runtime_id": "codex-cli",
            "runtime_version": "codex-cli@1",
            "runtime_config_hash": "sha256:codex-cli",
            "harness_version": "harbor@0.3.1",
        },
    )

    verdict = assess_runtime_comparison_validity([baseline], [current])
    reason = " ".join(verdict.reasons).lower()

    assert verdict.valid is False
    assert "fallback" in reason or "uncaptured" in reason
