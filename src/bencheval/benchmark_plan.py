"""Four-axis control-plane planner (benchmark × slice × runtime × model).

Implements :class:`~bencheval.contracts.RunPlanner`. No execution, no artifact paths.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast, get_args

from bencheval.benchmark_registry import (
    BenchmarkEntry,
    execution_support_label,
    load_benchmark_catalog,
)
from bencheval.domain import HarnessKindLiteral, RunPlan, RunPlanInstance, SlicePurpose
from bencheval.exceptions import BenchEvalError
from bencheval.lifecycle import CleanupPolicy
from bencheval.planner import BUDGET_CLASS_DEFAULTS
from bencheval.runtime_registry import load_runtime_catalog
from bencheval.slice_manifest import (
    default_slices_dir,
    list_slice_manifest_paths,
    load_slice_manifest,
    resolve_instances_source_path,
    slice_instance_ids,
)
from bencheval.task_contract import BudgetClass

ComparisonValidity = Literal[
    "model_comparison",
    "runtime_comparison",
    "adapter_smoke",
    "diagnostic_only",
    "invalid",
]

_VALID_HARNESS_KINDS = frozenset(get_args(HarnessKindLiteral))

_BACKEND_TO_HARNESS: dict[str, str] = {
    "harbor": "harbor",
    "inspect": "inspect",
    "external": "local-harness",
}


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    adapter_id: str
    harness_kind: str
    benchmark_ids: tuple[str, ...]


def list_adapter_descriptors() -> tuple[AdapterDescriptor, ...]:
    """Adapter families derived from the catalog's per-benchmark ``adapter_id`` bindings.

    Config-driven: adding a benchmark to an existing adapter family is a
    ``config/benchmarks.yaml`` edit, not a code change.
    """
    catalog = load_benchmark_catalog()
    harness_by_adapter: dict[str, str] = {}
    benchmarks_by_adapter: dict[str, set[str]] = {}
    for entry in catalog.benchmarks:
        if entry.adapter_id is None or entry.harness_kind is None:
            continue
        harness_by_adapter.setdefault(entry.adapter_id, entry.harness_kind)
        benchmarks_by_adapter.setdefault(entry.adapter_id, set()).add(entry.id)
    return tuple(
        AdapterDescriptor(
            adapter_id=aid,
            harness_kind=harness_by_adapter[aid],
            benchmark_ids=tuple(sorted(benchmarks_by_adapter[aid])),
        )
        for aid in sorted(harness_by_adapter)
    )


@lru_cache(maxsize=4)
def _slice_lookup_index(slices_dir_str: str) -> tuple[tuple[str, str, str], ...]:
    """(slice_id, benchmark_id, path_str) for each slice YAML under ``slices_dir_str``."""
    rows: list[tuple[str, str, str]] = []
    for path in list_slice_manifest_paths(slices_dir_str):
        manifest = load_slice_manifest(path)
        rows.append((manifest.slice.id, manifest.slice.benchmark_id, str(path)))
    return tuple(rows)


def clear_plan_cache() -> None:
    _slice_lookup_index.cache_clear()


def _resolve_slice_yaml(slice_id: str, benchmark_id: str) -> Path:
    slices_dir = str(default_slices_dir().resolve())
    for sid, bid, path_str in _slice_lookup_index(slices_dir):
        if sid == slice_id and bid == benchmark_id:
            return Path(path_str)
    raise BenchEvalError(
        f"slice {slice_id!r} not found for benchmark {benchmark_id!r} under {default_slices_dir()}",
    )


def _instances_source_fingerprint(
    instances_source: str,
    instances_path: Path,
) -> dict[str, object]:
    try:
        raw = instances_path.read_bytes()
    except OSError as e:
        raise BenchEvalError(f"cannot read instances manifest {instances_path}: {e}") from e
    return {
        "instances_source": instances_source,
        "instances_source_path": str(instances_path.resolve()),
        "instances_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "instances_manifest_bytes": len(raw),
    }


def _as_harness_kind(harness: str) -> HarnessKindLiteral:
    if harness not in _VALID_HARNESS_KINDS:
        raise BenchEvalError(f"unknown harness kind {harness!r}")
    return cast("HarnessKindLiteral", harness)


def _harness_for_benchmark(benchmark: BenchmarkEntry) -> HarnessKindLiteral:
    if benchmark.harness_kind is not None:
        return _as_harness_kind(benchmark.harness_kind)
    raw = _BACKEND_TO_HARNESS.get(benchmark.recommended_backend, "local-harness")
    return _as_harness_kind(raw)


def _adapter_for_benchmark(benchmark: BenchmarkEntry) -> str:
    if benchmark.adapter_id is not None:
        return benchmark.adapter_id
    folded = benchmark.id.replace("_", "-")
    return f"{folded}-adapter"


def _comparison_validity(purpose: SlicePurpose) -> ComparisonValidity:
    if purpose in ("runtime_comparison", "model_comparison", "adapter_smoke"):
        return purpose
    if purpose == "benchmark_native_claim":
        return "diagnostic_only"
    return "adapter_smoke"


def _budget_class_for_slice(max_cost: Decimal, max_wall_per_instance: int) -> BudgetClass:
    cost_f = float(max_cost)
    if cost_f <= 0.25 and max_wall_per_instance <= 180:
        return "B1"
    if cost_f <= 2.0 and max_wall_per_instance <= 300:
        return "B2"
    return "B3"


def plan_control_plane(
    *,
    benchmark_id: str,
    slice_id: str,
    runtime_id: str,
    model_id: str,
    cleanup_policy: CleanupPolicy = "always",
) -> RunPlan:
    """Build a frozen :class:`~bencheval.domain.RunPlan` for ``run --dry-run``."""
    catalog = load_benchmark_catalog()
    benchmark = catalog.by_id_or_alias(benchmark_id)
    runtimes = load_runtime_catalog()
    runtime = runtimes.by_id(runtime_id)
    slice_path = _resolve_slice_yaml(slice_id, benchmark.id)
    slice_manifest = load_slice_manifest(slice_path)
    instance_ids = slice_instance_ids(slice_manifest, slice_path)
    if not instance_ids:
        raise BenchEvalError(f"slice {slice_id!r} has no instances")

    harness_kind = _harness_for_benchmark(benchmark)
    if harness_kind not in runtime.runtime.supported_harnesses:
        raise BenchEvalError(
            f"runtime {runtime_id!r} does not support harness {harness_kind!r}; "
            f"supported: {list(runtime.runtime.supported_harnesses)}",
        )

    if benchmark.safety_review == "offensive_restricted":
        raise BenchEvalError(
            f"benchmark {benchmark.id!r} is offensive_restricted; "
            "use Stretch lane with explicit safety review (not implemented in CLI)",
        )

    adapter_id = _adapter_for_benchmark(benchmark)
    budget_class = _budget_class_for_slice(
        slice_manifest.budget.max_total_cost_usd,
        slice_manifest.budget.max_wall_clock_sec_per_instance,
    )
    defaults = BUDGET_CLASS_DEFAULTS[budget_class]
    max_cost = max(float(slice_manifest.budget.max_total_cost_usd), float(defaults["max_cost_usd"]))
    max_wall = max(
        slice_manifest.budget.max_wall_clock_sec_per_instance * len(instance_ids),
        int(defaults["max_wall_clock_sec"]),
    )
    requires_harbor = harness_kind == "harbor"
    profile = benchmark.recommended_profile
    requires_sandbox = harness_kind in ("harbor", "swebench-native") or profile in ("E3", "E4")

    caveats: list[str] = []
    if slice_manifest.labels.contamination_warning:
        caveats.append("contamination_warning")
    if benchmark.contamination_risk in ("high", "medium"):
        caveats.append(f"contamination_risk:{benchmark.contamination_risk}")
    if benchmark.adapter_status != "manifest_available":
        caveats.append(f"adapter_status:{benchmark.adapter_status}")
    support = execution_support_label(benchmark)
    if support != "executable_adapter":
        caveats.append(f"execution_support:{support}")

    network = runtime.safety.network_default
    validity = _comparison_validity(slice_manifest.slice.purpose)

    return RunPlan(
        schema_version="0.3",
        benchmark_id=benchmark.id,
        benchmark_version=None,
        slice_id=slice_manifest.slice.id,
        adapter_id=adapter_id,
        harness_kind=harness_kind,
        runtime_id=runtime.runtime.id,
        runtime_kind=runtime.runtime.kind,
        model_id=model_id,
        model_binding=runtime.runtime.model_binding,
        instances=tuple(RunPlanInstance(instance_id=i) for i in instance_ids),
        budget_class=budget_class,
        max_cost_usd=round(max_cost, 6),
        max_wall_clock_sec=max_wall,
        requires_harbor=requires_harbor,
        requires_sandbox=requires_sandbox,
        network_policy=network,
        cleanup_policy=cleanup_policy,
        caveats=tuple(caveats),
        comparison_validity=validity,
    )


class ControlPlanePlanner:
    """Concrete :class:`~bencheval.contracts.RunPlanner` implementation."""

    def plan(
        self,
        *,
        benchmark_id: str,
        slice_id: str,
        runtime_id: str,
        model_id: str,
    ) -> RunPlan:
        return plan_control_plane(
            benchmark_id=benchmark_id,
            slice_id=slice_id,
            runtime_id=runtime_id,
            model_id=model_id,
        )


def run_plan_to_dry_run_dict(
    plan: RunPlan,
    *,
    slice_resolution: dict[str, object] | None = None,
) -> dict[str, object]:
    """Serialize a ``RunPlan`` for ``run --dry-run --format json`` (frozen field set)."""
    data = plan.model_dump(mode="json")
    data["instance_count"] = len(plan.instances)
    data["instances"] = [{"instance_id": i.instance_id} for i in plan.instances]
    if slice_resolution:
        data["slice_resolution"] = slice_resolution
    return data


def dry_run_slice_resolution(
    *,
    benchmark_id: str,
    slice_id: str,
) -> dict[str, object]:
    """Pre-flight slice identity: counts, manifest fingerprint, execution_support."""
    catalog = load_benchmark_catalog()
    benchmark = catalog.by_id_or_alias(benchmark_id)
    slice_path = _resolve_slice_yaml(slice_id, benchmark.id)
    slice_manifest = load_slice_manifest(slice_path)
    instance_ids = slice_instance_ids(slice_manifest, slice_path)
    instances_path = resolve_instances_source_path(
        slice_path,
        slice_manifest.slice.instances_source,
    )
    fingerprint = _instances_source_fingerprint(
        slice_manifest.slice.instances_source,
        instances_path,
    )
    return {
        "benchmark_id": benchmark.id,
        "slice_id": slice_manifest.slice.id,
        "slice_yaml": str(slice_path.resolve()),
        "expected_instance_count": len(instance_ids),
        "resolved_instance_ids": list(instance_ids),
        "excluded_instance_ids": [],
        "execution_support": execution_support_label(benchmark),
        "adapter_status": benchmark.adapter_status,
        **fingerprint,
    }


__all__ = [
    "AdapterDescriptor",
    "ControlPlanePlanner",
    "dry_run_slice_resolution",
    "list_adapter_descriptors",
    "plan_control_plane",
    "run_plan_to_dry_run_dict",
]
