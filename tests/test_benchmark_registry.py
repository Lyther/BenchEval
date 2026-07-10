from __future__ import annotations

from pathlib import Path

import pytest

from bencheval.benchmark_registry import (
    BenchmarkFilter,
    filter_benchmarks,
    load_benchmark_catalog,
)
from bencheval.exceptions import BenchEvalError


def test_benchmark_registry_exports_from_package() -> None:
    from bencheval import BenchmarkCatalog, BenchmarkEntry, load_benchmark_catalog

    catalog = load_benchmark_catalog()
    assert isinstance(catalog, BenchmarkCatalog)
    assert isinstance(catalog.benchmarks[0], BenchmarkEntry)


def test_default_benchmark_catalog_has_current_expected_count() -> None:
    catalog = load_benchmark_catalog()
    assert len(catalog.benchmarks) == 81


def test_public_docs_match_current_catalog_count() -> None:
    catalog_count = len(load_benchmark_catalog().benchmarks)
    repo_root = Path(__file__).resolve().parents[1]
    docs = (
        repo_root / "README.md",
        repo_root / "docs" / "architecture.md",
        repo_root / "docs" / "roadmap.md",
        repo_root / "docs" / "context" / "concept-hld.md",
        repo_root / "docs" / "context" / "production-v1-pilot.md",
    )
    stale_markers = ("~50", "64 entries", "64-entry", "80 entries", "80-entry", "605")
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert str(catalog_count) in text, f"{path} should mention {catalog_count}"
        for marker in stale_markers:
            assert marker not in text, f"{path} contains stale marker {marker!r}"


def test_catalog_tracks_deepswe_as_unverified_alias() -> None:
    catalog = load_benchmark_catalog()
    benchmark = catalog.by_id_or_alias("DeepSWE")
    assert benchmark.id == "deepswe"
    assert benchmark.adapter_status == "unverified"
    assert "no distinct public benchmark verified" in benchmark.notes


def test_catalog_tracks_exploitgym_as_restricted_stretch() -> None:
    catalog = load_benchmark_catalog()
    benchmark = catalog.by_id_or_alias("Exploit Gym")
    assert benchmark.id == "exploitgym"
    assert benchmark.tier == "stretch"
    assert benchmark.safety_review == "offensive_restricted"
    assert benchmark.single_mode_required is True


def test_alias_lookup_normalizes_spacing_and_underscores() -> None:
    catalog = load_benchmark_catalog()
    assert catalog.by_id_or_alias("Deep_SWE").id == "deepswe"
    assert catalog.by_id_or_alias("Exploit   Gym").id == "exploitgym"


def test_catalog_filters_security_restricted_benchmarks() -> None:
    catalog = load_benchmark_catalog()
    entries = filter_benchmarks(
        catalog,
        BenchmarkFilter(category="cybersecurity", safety_review="offensive_restricted"),
    )
    ids = {entry.id for entry in entries}
    assert {"cybergym", "exploitgym", "bountybench"}.issubset(ids)


def test_catalog_rejects_duplicate_aliases(tmp_path: Path) -> None:
    catalog = tmp_path / "benchmarks.yaml"
    catalog.write_text(
        "\n".join(
            (
                "schema_version: 1",
                "benchmarks:",
                "  - id: alpha",
                "    name: Alpha",
                '    aliases: ["same"]',
                "    category: coding",
                "    tier: calibration",
                "    adapter_status: cataloged",
                "    recommended_backend: inspect",
                "    recommended_profile: E3",
                "    task_count: 1",
                "    public_indexed: true",
                "    contamination_risk: high",
                "    single_mode_required: false",
                "    safety_review: standard",
                '    source_url: "https://example.com/a"',
                '    notes: "A"',
                "  - id: beta",
                "    name: Beta",
                '    aliases: ["same"]',
                "    category: coding",
                "    tier: calibration",
                "    adapter_status: cataloged",
                "    recommended_backend: inspect",
                "    recommended_profile: E3",
                "    task_count: 1",
                "    public_indexed: true",
                "    contamination_risk: high",
                "    single_mode_required: false",
                "    safety_review: standard",
                '    source_url: "https://example.com/b"',
                '    notes: "B"',
                "",
            ),
        ),
        encoding="utf-8",
    )
    with pytest.raises(BenchEvalError, match="duplicate benchmark alias"):
        load_benchmark_catalog(catalog)


def test_catalog_rejects_alias_that_conflicts_with_later_id(tmp_path: Path) -> None:
    catalog = tmp_path / "benchmarks.yaml"
    catalog.write_text(
        "\n".join(
            (
                "schema_version: 1",
                "benchmarks:",
                "  - id: alpha",
                "    name: Alpha",
                '    aliases: ["Beta"]',
                "    category: coding",
                "    tier: calibration",
                "    adapter_status: cataloged",
                "    recommended_backend: inspect",
                "    recommended_profile: E3",
                "    task_count: 1",
                "    public_indexed: true",
                "    contamination_risk: high",
                "    single_mode_required: false",
                "    safety_review: standard",
                '    source_url: "https://example.com/a"',
                '    notes: "A"',
                "  - id: beta",
                "    name: Beta",
                "    aliases: []",
                "    category: coding",
                "    tier: calibration",
                "    adapter_status: cataloged",
                "    recommended_backend: inspect",
                "    recommended_profile: E3",
                "    task_count: 1",
                "    public_indexed: true",
                "    contamination_risk: high",
                "    single_mode_required: false",
                "    safety_review: standard",
                '    source_url: "https://example.com/b"',
                '    notes: "B"',
                "",
            ),
        ),
        encoding="utf-8",
    )
    with pytest.raises(BenchEvalError, match="conflicts with id beta"):
        load_benchmark_catalog(catalog)


def _entry(**overrides: object):
    from bencheval.benchmark_registry import BenchmarkEntry

    base: dict[str, object] = {
        "id": "new-swe-suite",
        "name": "New SWE Suite",
        "category": "coding",
        "tier": "calibration",
        "adapter_status": "manifest_available",
        "recommended_backend": "inspect",
        "recommended_profile": "E3",
        "public_indexed": True,
        "contamination_risk": "low",
        "single_mode_required": True,
        "safety_review": "standard",
        "notes": "n",
    }
    base.update(overrides)
    return BenchmarkEntry(**base)


def test_config_only_binding_makes_a_new_benchmark_executable() -> None:
    """F001: a new benchmark reusing an existing adapter family is executable via
    config alone — no Python change to the executable set or adapter map."""
    from bencheval.benchmark_registry import execution_support_label

    entry = _entry(adapter_id="swebench", harness_kind="swebench-native", executable=True)
    assert execution_support_label(entry) == "executable_adapter"

    # A metadata-only entry with no binding stays non-executable.
    plain = _entry(adapter_status="cataloged")
    assert execution_support_label(plain) == "metadata_only"


def test_executable_entry_requires_adapter_binding() -> None:
    """F001 guardrail: config cannot claim executable without an adapter binding."""
    with pytest.raises(ValueError, match="executable but is missing"):
        _entry(executable=True)  # no adapter_id / harness_kind


def test_adapter_descriptors_are_derived_from_catalog() -> None:
    """list_adapter_descriptors reflects the catalog's config bindings, not a code map."""
    from bencheval.benchmark_plan import list_adapter_descriptors

    descriptors = {d.adapter_id: d for d in list_adapter_descriptors()}
    assert "swebench" in descriptors
    assert "swe-bench-verified" in descriptors["swebench"].benchmark_ids
    assert descriptors["swebench"].harness_kind == "swebench-native"
