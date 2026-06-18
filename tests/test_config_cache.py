"""Config loader caches and planner hot-path reuse."""

from __future__ import annotations

import time
from pathlib import Path

from bencheval.benchmark_plan import _slice_lookup_index, clear_plan_cache, plan_control_plane
from bencheval.benchmark_registry import load_benchmark_catalog
from bencheval.config_cache import clear_config_loader_caches


def test_plan_control_plane_reuses_cache_across_calls() -> None:
    clear_config_loader_caches()
    load_benchmark_catalog()
    samples: list[float] = []
    for _ in range(30):
        t0 = time.perf_counter()
        plan_control_plane(
            benchmark_id="bfcl-v4",
            slice_id="smoke-5",
            runtime_id="native-api",
            model_id="openai/gpt-test",
        )
        samples.append((time.perf_counter() - t0) * 1000.0)
    p50 = sorted(samples)[len(samples) // 2]
    assert p50 < 15.0, f"expected cached plan p50 < 15ms, got {p50:.2f}ms"


def test_clear_config_loader_caches_invalidates() -> None:
    clear_config_loader_caches()
    a = load_benchmark_catalog()
    clear_config_loader_caches()
    b = load_benchmark_catalog()
    assert a.schema_version == b.schema_version
    assert len(a.benchmarks) == len(b.benchmarks)


def test_slice_lookup_index_cached_per_slices_dir(tmp_path: Path) -> None:
    clear_plan_cache()
    dir_a = tmp_path / "slices-a"
    dir_b = tmp_path / "slices-b"
    dir_a.mkdir()
    dir_b.mkdir()
    _slice_lookup_index(str(dir_a.resolve()))
    _slice_lookup_index(str(dir_b.resolve()))
    assert _slice_lookup_index.cache_info().currsize == 2
