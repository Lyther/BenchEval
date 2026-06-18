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


def test_default_benchmark_catalog_has_at_least_fifty_entries() -> None:
    catalog = load_benchmark_catalog()
    assert len(catalog.benchmarks) >= 50


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
