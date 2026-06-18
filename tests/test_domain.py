"""Domain type + v0.3 additive EvidenceRecord contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from bencheval.domain import (
    AttemptSummaryDTO,
    RunPlan,
    RuntimeCatalog,
    RuntimeProfile,
    SliceManifest,
    TokenUsage,
)
from bencheval.evidence import EvidenceRecord
from bencheval.runtime_registry import load_runtime_catalog, load_runtime_profile
from bencheval.slice_manifest import load_slice_manifest

# Reusable v0.2-style minimal record (no v0.3 fields present).
V02_BASE = {
    "run_id": "r1",
    "task_id": "t1",
    "model_id": "m1",
    "execution_profile": "E0",
    "primary_pass": True,
    "partial_score": 0.5,
    "cost_usd": 0.01,
    "latency_sec": 1.0,
    "created_at": datetime(2026, 1, 1, tzinfo=UTC),
}


def _v03_extra() -> dict[str, object]:
    return {
        "benchmark_id": "terminal-bench",
        "slice_id": "smoke-5",
        "adapter_id": "terminal-bench-harbor",
        "harness_kind": "harbor",
        "runtime_id": "claude-code",
        "runtime_kind": "cli_agent",
        "instance_id": "tb-001",
        "steps": 17,
        "token_usage": {"input_tokens": 1000, "output_tokens": 500},
        "native_score": {"resolved": True},
        "normalized_score": 1.0,
        "interpretation_label": "runtime_comparison",
        "contamination_label": "public_possible",
        "failure_class": None,
    }


# ---------------------------------------------------------------------------
# EvidenceRecord v0.2 backward compatibility (additive-only contract)
# ---------------------------------------------------------------------------


class TestEvidenceRecordBackwardCompat:
    def test_minimal_v02_record_parses_without_v03_fields(self) -> None:
        rec = EvidenceRecord(**V02_BASE)
        assert rec.benchmark_id is None
        assert rec.slice_id is None
        assert rec.runtime_id is None
        assert rec.token_usage is None
        assert rec.failure_class is None
        assert rec.backend == "local"

    def test_v02_serialization_roundtrips(self) -> None:
        rec = EvidenceRecord(**V02_BASE)
        as_json = rec.model_dump_json()
        restored = EvidenceRecord.model_validate_json(as_json)
        assert restored == rec

    def test_v02_jsonl_line_still_parses(self) -> None:
        # A hand-written v0.2 JSON line (no v0.3 keys) must validate.
        line = (
            '{"run_id":"r","task_id":"t","model_id":"m","execution_profile":"E0",'
            '"primary_pass":true,"partial_score":0.0,"cost_usd":0.0,"latency_sec":0.0,'
            f'"created_at":"{datetime(2026, 1, 1, tzinfo=UTC).isoformat()}"}}'
        )
        rec = EvidenceRecord.model_validate_json(line)
        assert rec.run_id == "r"
        assert rec.benchmark_id is None

    def test_v03_fields_accepted_additively(self) -> None:
        rec = EvidenceRecord(**{**V02_BASE, **_v03_extra()})
        assert rec.benchmark_id == "terminal-bench"
        assert rec.runtime_kind == "cli_agent"
        assert rec.token_usage == {"input_tokens": 1000, "output_tokens": 500}
        assert rec.native_score == {"resolved": True}
        assert rec.interpretation_label == "runtime_comparison"

    def test_partial_score_range_enforced(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceRecord(**{**V02_BASE, "partial_score": 1.5})

    def test_v02_evidence_record_is_permissive_on_extras(self) -> None:
        # The v0.2 EvidenceRecord has no extra="forbid" config (frozen contract);
        # it must keep accepting rows carrying keys it does not know about, so
        # historical JSONL with extra adapter_metadata siblings still loads.
        rec = EvidenceRecord(**{**V02_BASE, "future_field": 1})
        assert rec.run_id == "r1"

    def test_new_domain_models_forbid_extras(self) -> None:
        # New v0.3 domain models ARE strict: extra keys are a validation error.
        with pytest.raises(ValidationError):
            TokenUsage(input_tokens=1, unknown_key=2)


# ---------------------------------------------------------------------------
# Runtime registry
# ---------------------------------------------------------------------------


class TestRuntimeRegistry:
    def test_load_seed_catalog(self) -> None:
        cat = load_runtime_catalog()
        assert isinstance(cat, RuntimeCatalog)
        ids = {rp.runtime.id for rp in cat.runtimes}
        assert {"claude-code", "codex-cli", "native-api"} <= ids

    def test_load_single_profile(self) -> None:
        rp = load_runtime_profile(Path("config/runtimes/claude-code.yaml"))
        assert isinstance(rp, RuntimeProfile)
        assert rp.runtime.id == "claude-code"
        assert rp.runtime.kind == "cli_agent"
        assert rp.safety.network_default == "deny"

    def test_duplicate_ids_rejected(self, tmp_path: Path) -> None:
        (tmp_path / "a.yaml").write_text(
            Path("config/runtimes/claude-code.yaml").read_text(),
            encoding="utf-8",
        )
        (tmp_path / "b.yaml").write_text(
            Path("config/runtimes/claude-code.yaml").read_text(),
            encoding="utf-8",
        )
        from bencheval.exceptions import BenchEvalError

        with pytest.raises(BenchEvalError, match="duplicate runtime id"):
            load_runtime_catalog(tmp_path)

    def test_invalid_kind_rejected(self, tmp_path: Path) -> None:
        bad = (
            Path("config/runtimes/claude-code.yaml").read_text().replace("cli_agent", "not_a_kind")
        )
        (tmp_path / "x.yaml").write_text(bad, encoding="utf-8")
        from bencheval.exceptions import BenchEvalError

        with pytest.raises(BenchEvalError):
            load_runtime_catalog(tmp_path)

    def test_catalog_by_id(self) -> None:
        cat = load_runtime_catalog()
        rp = cat.by_id("native-api")
        assert rp.runtime.kind == "api_client"


# ---------------------------------------------------------------------------
# Slice manifest
# ---------------------------------------------------------------------------


class TestSliceManifest:
    def test_load_seed_slice(self) -> None:
        m = load_slice_manifest(Path("config/slices/swe-bench-verified-smoke-10.yaml"))
        assert isinstance(m, SliceManifest)
        assert m.slice.benchmark_id == "swe-bench-verified"
        assert m.slice.purpose == "adapter_smoke"
        assert m.budget.max_instances == 10

    def test_instance_count_fits_budget(self) -> None:
        from bencheval.slice_manifest import slice_instance_ids

        m = load_slice_manifest(Path("config/slices/swe-bench-verified-smoke-10.yaml"))
        ids = slice_instance_ids(m, Path("config/slices/swe-bench-verified-smoke-10.yaml"))
        assert len(ids) == 10
        assert len(ids) <= m.budget.max_instances

    def test_over_budget_rejected(self, tmp_path: Path) -> None:
        # Budget max_instances=5 but manifest has 10 -> must fail.
        text = Path("config/slices/swe-bench-verified-smoke-10.yaml").read_text()
        text = text.replace("max_instances: 10", "max_instances: 5")
        (tmp_path / "s.yaml").write_text(text, encoding="utf-8")
        from bencheval.exceptions import BenchEvalError

        with pytest.raises(BenchEvalError, match="exceeds budget"):
            load_slice_manifest(tmp_path / "s.yaml")

    def test_missing_instances_source_rejected(self, tmp_path: Path) -> None:
        text = (
            Path("config/slices/swe-bench-verified-smoke-10.yaml")
            .read_text()
            .replace("swebench-verified-smoke-10.txt", "does-not-exist.txt")
        )
        (tmp_path / "s.yaml").write_text(text, encoding="utf-8")
        from bencheval.exceptions import BenchEvalError

        with pytest.raises(BenchEvalError, match="not found"):
            load_slice_manifest(tmp_path / "s.yaml")


# ---------------------------------------------------------------------------
# RunPlan DTO + AttemptSummaryDTO
# ---------------------------------------------------------------------------


class TestRunPlanDTO:
    def _valid_plan(self) -> dict[str, object]:
        return {
            "schema_version": "0.3",
            "benchmark_id": "terminal-bench",
            "slice_id": "smoke-5",
            "adapter_id": "terminal-bench-harbor",
            "harness_kind": "harbor",
            "runtime_id": "claude-code",
            "runtime_kind": "cli_agent",
            "model_id": "runtime-default",
            "model_binding": "runtime_configured",
            "instances": [{"instance_id": "tb-001"}],
            "budget_class": "B2",
            "max_cost_usd": 1.0,
            "max_wall_clock_sec": 300,
            "requires_harbor": True,
            "requires_sandbox": True,
            "network_policy": "deny",
            "cleanup_policy": "always",
            "comparison_validity": "runtime_comparison",
        }

    def test_valid_plan(self) -> None:
        plan = RunPlan(**self._valid_plan())
        assert plan.benchmark_id == "terminal-bench"
        assert plan.comparison_validity == "runtime_comparison"

    def test_invalid_budget_class_rejected(self) -> None:
        data = self._valid_plan() | {"budget_class": "B9"}
        with pytest.raises(ValidationError):
            RunPlan(**data)

    def test_plan_has_no_artifact_paths(self) -> None:
        plan = RunPlan(**self._valid_plan())
        # DTO must not expose artifact paths.
        assert not hasattr(plan, "artifact_paths")
        assert not hasattr(plan, "verifier_log_path")

    def test_attempt_summary_dto_excludes_paths(self) -> None:
        rec = EvidenceRecord(**{**V02_BASE, **_v03_extra()})
        dto = AttemptSummaryDTO(
            run_id=rec.run_id,
            benchmark_id=rec.benchmark_id,
            slice_id=rec.slice_id,
            runtime_id=rec.runtime_id,
            model_id=rec.model_id,
            instance_id=rec.instance_id,
            primary_pass=rec.primary_pass,
            partial_score=rec.partial_score,
            cost_usd=rec.cost_usd,
            latency_sec=rec.latency_sec,
            failure_class=rec.failure_class,
            interpretation_label=rec.interpretation_label,
            contamination_label=rec.contamination_label,
        )
        assert not hasattr(dto, "artifact_paths")
        assert not hasattr(dto, "verifier_log_path")
        assert dto.runtime_id == "claude-code"


# ---------------------------------------------------------------------------
# Token usage + money discipline
# ---------------------------------------------------------------------------


class TestTokenUsageAndMoney:
    def test_token_usage_non_negative(self) -> None:
        tu = TokenUsage(input_tokens=100, output_tokens=50)
        assert tu.input_tokens == 100
        with pytest.raises(ValidationError):
            TokenUsage(input_tokens=-1)

    def test_money_uses_decimal_in_slice_budget(self) -> None:
        m = load_slice_manifest(Path("config/slices/swe-bench-verified-smoke-10.yaml"))
        # Slice budget max_total_cost_usd is Decimal, not float.
        from decimal import Decimal

        assert isinstance(m.budget.max_total_cost_usd, Decimal)


# ---------------------------------------------------------------------------
# Branded ID distinction (static-only; runtime smoke check that aliases exist)
# ---------------------------------------------------------------------------


class TestBrandedIds:
    def test_newtype_aliases_distinct(self) -> None:
        from bencheval.domain import BenchmarkId, RuntimeId, SliceId

        # NewType aliases are distinct at the type-system level even though they
        # are all str at runtime. This guards against passing the wrong id kind.
        assert BenchmarkId is not RuntimeId
        assert SliceId is not RuntimeId
        assert BenchmarkId is not SliceId
