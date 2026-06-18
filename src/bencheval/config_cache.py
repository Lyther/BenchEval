"""Process-local cache invalidation for YAML config loaders."""

from __future__ import annotations


def clear_config_loader_caches() -> None:
    """Drop cached benchmark/runtime/slice/plan indexes (for tests and config edits)."""
    from bencheval import benchmark_plan as _benchmark_plan
    from bencheval import benchmark_registry as _benchmark_registry
    from bencheval import runtime_registry as _runtime_registry
    from bencheval import slice_manifest as _slice_manifest

    _benchmark_registry.clear_benchmark_catalog_cache()
    _runtime_registry.clear_runtime_catalog_cache()
    _slice_manifest.clear_slice_manifest_cache()
    _benchmark_plan.clear_plan_cache()


__all__ = ["clear_config_loader_caches"]
