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
    assert len(catalog.benchmarks) == 8


def test_public_docs_match_current_catalog_count() -> None:
    catalog_count = len(load_benchmark_catalog().benchmarks)
    repo_root = Path(__file__).resolve().parents[1]
    docs = (
        repo_root / "README.md",
        repo_root / "docs" / "architecture.md",
    )
    stale_markers = ("~50", "64 entries", "64-entry", "80 entries", "80-entry", "81 entries")
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert str(catalog_count) in text, f"{path} should mention {catalog_count}"
        for marker in stale_markers:
            assert marker not in text, f"{path} contains stale marker {marker!r}"


def test_product_catalog_ids() -> None:
    catalog = load_benchmark_catalog()
    ids = {b.id for b in catalog.benchmarks}
    assert ids == {
        "terminal-bench",
        "swe-bench-verified",
        "bfcl-v4",
        "swe-bench-pro",
        "gpqa-diamond",
        "hle",
        "cybergym",
        "exploitgym",
    }
    for entry in catalog.benchmarks:
        if not entry.executable:
            continue
        assert entry.default_slice is not None


def test_harness_kind_is_not_benchmark_yaml_configuration() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    text = (repo_root / "config" / "benchmarks.yaml").read_text(encoding="utf-8")
    assert "harness_kind:" not in text
    assert not hasattr(load_benchmark_catalog().benchmarks[0], "harness_kind")


def test_alias_lookup_terminal_bench() -> None:
    catalog = load_benchmark_catalog()
    assert catalog.by_id_or_alias("t-bench").id == "terminal-bench"
    assert catalog.by_id_or_alias("Terminal-Bench").id == "terminal-bench"


def test_catalog_filters_executable_only() -> None:
    catalog = load_benchmark_catalog()
    entries = filter_benchmarks(
        catalog,
        BenchmarkFilter(execution_support="executable_adapter"),
    )
    assert len(entries) == 5
    assert {e.id for e in entries} == {
        "terminal-bench",
        "swe-bench-verified",
        "bfcl-v4",
        "gpqa-diamond",
        "hle",
    }


def test_catalog_rejects_duplicate_aliases(tmp_path: Path) -> None:
    catalog = tmp_path / "benchmarks.yaml"
    catalog.write_text(
        """
schema_version: 1
benchmarks:
  - id: a
    name: A
    aliases: [shared]
    category: coding
    tier: stretch
    adapter_status: cataloged
    recommended_backend: inspect
    recommended_profile: E3
    task_count: 1
    public_indexed: true
    contamination_risk: low
    single_mode_required: false
    source_url: https://example.com/a
    notes: a
  - id: b
    name: B
    aliases: [shared]
    category: coding
    tier: stretch
    adapter_status: cataloged
    recommended_backend: inspect
    recommended_profile: E3
    task_count: 1
    public_indexed: true
    contamination_risk: low
    single_mode_required: false
    source_url: https://example.com/b
    notes: b
""",
        encoding="utf-8",
    )
    with pytest.raises(BenchEvalError, match="duplicate"):
        load_benchmark_catalog(catalog)
