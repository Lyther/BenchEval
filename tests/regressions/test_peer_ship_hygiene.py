"""Peer ship-hygiene regressions for product-spine closeout."""

from __future__ import annotations

from pathlib import Path

from bencheval.benchmark_plan import plan_control_plane
from bencheval.external_agent_adapter import __all__ as external_agent_all

REPO = Path(__file__).resolve().parents[2]


def test_pilot_matrix_defaults_to_registry_model() -> None:
    text = (REPO / "scripts" / "run-live-pilot-matrix.sh").read_text(encoding="utf-8")
    assert "BENCHEVAL_PILOT_MODEL:-gpt-test" in text
    assert "openai/gpt-test" not in text
    assert "config/models.yaml" in text


def test_swe_rebench_orphan_slice_removed() -> None:
    assert not (REPO / "config" / "slices" / "swe-rebench-smoke-10.yaml").exists()
    assert not (REPO / "config" / "manifests" / "swe-rebench-smoke-10.txt").exists()


def test_harbor_agent_runtime_mapping_removed() -> None:
    text = (REPO / "src" / "bencheval" / "terminal_bench_harbor.py").read_text(encoding="utf-8")
    assert '"harbor-agent"' not in text


def test_bfcl_smoke_is_adapter_smoke_not_native_claim() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-test",
    )
    assert plan.comparison_validity == "adapter_smoke"
    assert "benchmark_native_claim" not in plan.comparison_validity


def test_product_yaml_has_no_utf8_bom() -> None:
    roots = [
        REPO / "config" / "benchmarks.yaml",
        REPO / "config" / "models.yaml",
        REPO / "config" / "agents",
        REPO / "config" / "providers",
        REPO / "config" / "runtimes",
        REPO / "config" / "slices",
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.glob("*.yaml")))
            files.extend(sorted(root.glob("*.yml")))
    assert files
    for path in files:
        assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), path


def test_roadmap_separates_current_from_historical_ledger() -> None:
    text = (REPO / "docs" / "roadmap.md").read_text(encoding="utf-8")
    assert "## Current roadmap" in text
    assert "## Historical ledger (do not execute)" in text
    current, _, _historical = text.partition("## Historical ledger (do not execute)")
    assert "inspect-api" not in current
    assert "harbor-agent" not in current
    assert "planner.py" not in current
    assert "run --config" not in current


def test_architecture_has_no_deleted_workspace_staging() -> None:
    text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "workspace_staging.py" not in text


def test_external_catalog_is_research_only_without_dead_cli() -> None:
    text = (REPO / "docs" / "context" / "external-benchmark-catalog.md").read_text(encoding="utf-8")
    assert "Research only" in text or "research only" in text
    assert "doctor --backend inspect" not in text
    assert "harbor_adapter.py" not in text
    assert "run --manifest" not in text


def test_concept_hld_marks_obsolete_cli_historical() -> None:
    text = (REPO / "docs" / "context" / "concept-hld.md").read_text(encoding="utf-8")
    assert "Historical command blocks (do not execute)" in text
    assert "bencheval run bfcl-v4/smoke-5" in text


def test_runtime_profile_docstring_has_no_inspect_api() -> None:
    text = (REPO / "src" / "bencheval" / "domain.py").read_text(encoding="utf-8")
    assert "inspect-api" not in text


def test_external_agent_public_api_has_no_momo_aliases() -> None:
    momo_names = {
        "MOMO_ADAPTER_ID",
        "MomoCliResult",
        "MomoInstanceOutcome",
        "MomoProcessRunner",
        "MomoRunSummary",
        "build_momo_run_command",
        "execute_momo_agent_run",
        "run_momo_instance",
    }
    assert momo_names.isdisjoint(set(external_agent_all))
