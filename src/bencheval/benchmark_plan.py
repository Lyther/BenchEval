"""Control-plane planner: benchmark × slice × (runtime XOR agent)? × model × provider.

Implements :class:`~bencheval.contracts.RunPlanner`. No execution, no artifact paths.
Omit both runtime and agent for model-only harnesses (e.g. bfcl-native).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal, cast, get_args

from bencheval.actor_binding import ActorBinding, actor_binding_for_agent, actor_binding_for_runtime
from bencheval.agent_registry import AgentCatalog, load_agent_catalog, resolve_launchable_agent
from bencheval.benchmark_registry import (
    BenchmarkEntry,
    execution_support_label,
    load_benchmark_catalog,
)
from bencheval.budget_defaults import BUDGET_CLASS_DEFAULTS
from bencheval.domain import (
    BudgetClass,
    HarnessKindLiteral,
    RunPlan,
    RunPlanInstance,
    RuntimeCatalog,
    SlicePurpose,
)
from bencheval.exceptions import BenchEvalError
from bencheval.lifecycle import CleanupPolicy
from bencheval.model_binding import resolve_model_binding
from bencheval.model_registry import ModelRegistry, load_model_registry
from bencheval.provider_registry import DEFAULT_PROVIDER_ID, ProviderCatalog, load_provider_catalog
from bencheval.runtime_registry import load_runtime_catalog
from bencheval.slice_manifest import (
    default_slices_dir,
    list_slice_manifest_paths,
    load_slice_manifest,
    slice_instance_ids,
)

ComparisonValidity = Literal[
    "model_comparison",
    "runtime_comparison",
    "adapter_smoke",
    "rough_regression",
    "diagnostic_only",
    "invalid",
]

_VALID_HARNESS_KINDS = frozenset(get_args(HarnessKindLiteral))
_MODEL_ONLY_HARNESSES = frozenset({"bfcl-native", "inspect-evals", "hle-native"})

_BACKEND_TO_HARNESS: dict[str, str] = {
    "harbor": "harbor",
    "inspect": "inspect",
    "external": "local-harness",
}

_ADAPTER_TO_OFFICIAL_RUNNER: dict[str, str] = {
    "terminal-bench-harbor": "harbor",
    "swebench": "swebench-native",
    "swebench-pro-harbor": "harbor",
    "bfcl": "bfcl-native",
    "gpqa": "inspect-evals",
    "hle": "hle-native",
    "cybergym": "cybergym-native",
    "exploitgym": "exploitgym-native",
}

# Provisional planning labels only — not immutable dataset/harness digests.
# Live evidence must overwrite with captured harness/package/git revisions
# (see control_plane_executor runtime/harness version capture). The ``provisional:``
# prefix prevents these labels from being mistaken for frozen provenance pins.
_BENCHMARK_VERSION_LABELS: dict[str, str] = {
    "terminal-bench": "provisional:terminal-bench/2.1",
    "swe-bench-verified": "provisional:swe-bench-verified/public",
    "bfcl-v4": "provisional:bfcl-v4/generate-smoke",
    "gpqa-diamond": "provisional:gpqa-diamond/inspect-evals",
    "hle": "provisional:hle/cais",
}


def _benchmark_version_pin(benchmark: BenchmarkEntry) -> str:
    labeled = _BENCHMARK_VERSION_LABELS.get(benchmark.id)
    if labeled is not None:
        return labeled
    return f"provisional:{benchmark.id}/catalog"


@dataclass(frozen=True, slots=True)
class AdapterDescriptor:
    adapter_id: str
    harness_kind: str
    benchmark_ids: tuple[str, ...]


def list_adapter_descriptors() -> tuple[AdapterDescriptor, ...]:
    """Adapter families derived from the catalog's per-benchmark ``adapter_id`` bindings.

    Config-driven: adding a benchmark to an existing adapter family is a
    ``config/benchmarks.yaml`` edit. New adapter families must register their
    official runner kind in code so config cannot choose an arbitrary harness.
    """
    catalog = load_benchmark_catalog()
    harness_by_adapter: dict[str, str] = {}
    benchmarks_by_adapter: dict[str, set[str]] = {}
    for entry in catalog.benchmarks:
        if entry.adapter_id is None:
            continue
        harness_by_adapter.setdefault(entry.adapter_id, _harness_for_adapter(entry.adapter_id))
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


def _inline_instances_fingerprint(instance_ids: tuple[str, ...]) -> dict[str, object]:
    raw = ("\n".join(instance_ids) + "\n").encode("utf-8")
    return {
        "instances_source": "inline",
        "instances_manifest_sha256": hashlib.sha256(raw).hexdigest(),
        "instances_manifest_bytes": len(raw),
    }


def _as_harness_kind(harness: str) -> HarnessKindLiteral:
    if harness not in _VALID_HARNESS_KINDS:
        raise BenchEvalError(f"unknown harness kind {harness!r}")
    return cast("HarnessKindLiteral", harness)


def _harness_for_adapter(adapter_id: str) -> HarnessKindLiteral:
    try:
        return _as_harness_kind(_ADAPTER_TO_OFFICIAL_RUNNER[adapter_id])
    except KeyError as e:
        raise BenchEvalError(
            f"adapter {adapter_id!r} has no declared official runner kind",
        ) from e


def _harness_for_benchmark(benchmark: BenchmarkEntry) -> HarnessKindLiteral:
    if benchmark.adapter_id is not None:
        return _harness_for_adapter(benchmark.adapter_id)
    raw = _BACKEND_TO_HARNESS.get(benchmark.recommended_backend, "local-harness")
    return _as_harness_kind(raw)


def official_harness_kind(benchmark: BenchmarkEntry) -> HarnessKindLiteral:
    """The adapter-declared official runner kind a plan for ``benchmark`` stamps."""
    return _harness_for_benchmark(benchmark)


def _adapter_for_benchmark(benchmark: BenchmarkEntry) -> str:
    if benchmark.adapter_id is not None:
        return benchmark.adapter_id
    folded = benchmark.id.replace("_", "-")
    return f"{folded}-adapter"


def _comparison_validity(purpose: SlicePurpose) -> ComparisonValidity:
    if purpose in ("runtime_comparison", "model_comparison", "adapter_smoke", "rough_regression"):
        return purpose
    if purpose == "benchmark_native_claim":
        return "diagnostic_only"
    return "adapter_smoke"


def _budget_class_for_slice(max_cost: Decimal, max_wall_per_instance: int) -> BudgetClass:
    # Thresholds mirror the BUDGET_CLASS_DEFAULTS envelopes.
    cost_f = float(max_cost)
    if cost_f <= 0.05 and max_wall_per_instance <= 60:
        return "B0"
    if cost_f <= 0.25 and max_wall_per_instance <= 180:
        return "B1"
    if cost_f <= 2.0 and max_wall_per_instance <= 300:
        return "B2"
    return "B3"


def resolve_runtime_id(*, benchmark_id: str, runtime_id: str | None) -> str | None:
    """Resolve runtime for a benchmark, or None for model-only harnesses.

    Explicit ``runtime_id`` wins. Model-only harnesses (bfcl-native) return None when
    omitted. Otherwise require an explicit admitted runtime when multiple are compatible.
    """
    catalog = load_benchmark_catalog()
    benchmark = catalog.by_id_or_alias(benchmark_id)
    harness = _harness_for_benchmark(benchmark)
    if runtime_id is not None and runtime_id.strip():
        return runtime_id.strip()
    if harness in _MODEL_ONLY_HARNESSES:
        return None
    runtimes = load_runtime_catalog()
    compatible = tuple(
        sorted(
            rp.runtime.id for rp in runtimes.runtimes if harness in rp.runtime.supported_harnesses
        ),
    )
    if len(compatible) == 1:
        return compatible[0]
    if not compatible:
        raise BenchEvalError(
            f"no runtime supports harness {harness!r} for benchmark {benchmark.id!r}",
        )
    joined = ", ".join(compatible)
    raise BenchEvalError(
        f"--runtime is required for harness {harness!r} (compatible: {joined})",
    )


def plan_control_plane(
    *,
    benchmark_id: str,
    slice_id: str,
    runtime_id: str | None,
    model_id: str,
    agent_id: str | None = None,
    provider_id: str | None = None,
    cleanup_policy: CleanupPolicy = "always",
    diagnostic: bool = False,
    model_registry: ModelRegistry | None = None,
    provider_catalog: ProviderCatalog | None = None,
    agent_catalog: AgentCatalog | None = None,
    runtime_catalog: RuntimeCatalog | None = None,
) -> RunPlan:
    """Build a frozen :class:`~bencheval.domain.RunPlan` for ``run`` phase 1.

    ``model_registry`` / ``provider_catalog`` / ``agent_catalog`` /
    ``runtime_catalog`` inject the declarative inputs (tests and tooling); the
    CLI uses the shipped config.
    """
    runtime_arg = runtime_id.strip() if runtime_id and runtime_id.strip() else None
    agent_arg = agent_id.strip() if agent_id and agent_id.strip() else None
    if runtime_arg is not None and agent_arg is not None:
        raise BenchEvalError("--runtime and --agent are mutually exclusive")

    catalog = load_benchmark_catalog()
    benchmark = catalog.by_id_or_alias(benchmark_id)
    harness_kind = _harness_for_benchmark(benchmark)

    model_key = model_id.strip()
    if not model_key:
        raise BenchEvalError("--model is required")
    model_registry = model_registry if model_registry is not None else load_model_registry()
    provider_catalog = provider_catalog if provider_catalog is not None else load_provider_catalog()
    try:
        model_entry = model_registry.by_id(model_key)
    except KeyError as e:
        raise BenchEvalError(f"unknown model {model_key!r}") from e

    # The model's declared route is its default provider; --provider may only
    # confirm it (a mismatch fails below), and unrouted rows fall back to the
    # shipped default.
    resolved_provider = (
        provider_id or model_entry.provider_route or DEFAULT_PROVIDER_ID
    ).strip() or DEFAULT_PROVIDER_ID
    try:
        provider_catalog.by_id(resolved_provider)
    except KeyError as e:
        raise BenchEvalError(f"unknown provider {resolved_provider!r}") from e
    if model_entry.provider_route is not None and model_entry.provider_route != resolved_provider:
        raise BenchEvalError(
            f"model {model_key!r} is routed to provider {model_entry.provider_route!r}, "
            f"not {resolved_provider!r}",
        )

    resolved_runtime_id: str | None = None
    resolved_runtime_kind = None
    model_binding: Literal["runtime_configured", "bencheval_injected", "not_applicable"]
    network: Literal["deny", "allow", "benchmark_required"] = "deny"

    agent_profile = None
    runtime = None
    if agent_arg is not None:
        try:
            agent_profile = resolve_launchable_agent(
                agent_arg, catalog=agent_catalog, diagnostic=diagnostic
            )
        except KeyError as e:
            raise BenchEvalError(f"unknown agent {agent_arg!r}") from e
        if harness_kind not in agent_profile.agent.supported_harnesses:
            raise BenchEvalError(
                f"agent {agent_arg!r} does not support harness {harness_kind!r}; "
                f"supported: {list(agent_profile.agent.supported_harnesses)}",
            )
        if harness_kind in _MODEL_ONLY_HARNESSES:
            # A profile may claim any harness; model-only harnesses call the
            # provider directly and never dispatch an agent (§23.6).
            raise BenchEvalError(
                f"harness {harness_kind!r} is model-only; agent {agent_arg!r} cannot be "
                "dispatched there whatever its profile declares",
            )
        model_binding = "bencheval_injected"
        # External agents typically need provider egress; Harbor proxy forward
        # remains gated by network_policy + BENCHEVAL_HARBOR_FORWARD_PROXY.
        network = "benchmark_required"
    else:
        resolved_runtime_id = resolve_runtime_id(
            benchmark_id=benchmark.id,
            runtime_id=runtime_arg,
        )
        if resolved_runtime_id is not None:
            runtimes = runtime_catalog if runtime_catalog is not None else load_runtime_catalog()
            try:
                runtime = runtimes.by_id(resolved_runtime_id)
            except KeyError as e:
                raise BenchEvalError(f"unknown runtime {resolved_runtime_id!r}") from e
            if harness_kind not in runtime.runtime.supported_harnesses:
                raise BenchEvalError(
                    f"runtime {resolved_runtime_id!r} does not support harness {harness_kind!r}; "
                    f"supported: {list(runtime.runtime.supported_harnesses)}",
                )
            resolved_runtime_kind = runtime.runtime.kind
            model_binding = runtime.runtime.model_binding
            network = runtime.safety.network_default
            if benchmark.id == "swe-bench-verified" and resolved_runtime_id == "claude-code":
                raise BenchEvalError(
                    "swe-bench-verified diagnostic is Codex-only for v1; "
                    "claude-code is rejected until a pinned Inspect SWE + Claude "
                    "lifecycle is proven",
                )
        else:
            if harness_kind not in _MODEL_ONLY_HARNESSES:
                raise BenchEvalError(
                    f"--runtime or --agent is required for harness {harness_kind!r}",
                )
            model_binding = "bencheval_injected"
            # Model-only harnesses call providers on the host; deny is not a
            # sandbox claim here.
            network = "allow"

    adapter_id = _adapter_for_benchmark(benchmark)
    # Model-only harnesses launch the provider from the host; snapshot the
    # resolved, non-secret binding now so confirmation covers it (§23.3).
    # Scaffolded runs keep their runtime/agent-owned model configuration; a
    # native Harbor agent runs its LLM host-side on the confirmed binding, so
    # it snapshots both the model and the actor (§23.6).
    model_snapshot = None
    actor_snapshot: ActorBinding | None = None
    if resolved_runtime_id is None and agent_arg is None:
        model_snapshot = resolve_model_binding(
            model_key, resolved_provider, models=model_registry, providers=provider_catalog
        )
    elif agent_profile is not None and agent_profile.agent.kind == "harbor":
        model_snapshot = resolve_model_binding(
            model_key, resolved_provider, models=model_registry, providers=provider_catalog
        )
        actor_snapshot = actor_binding_for_agent(agent_profile)
    elif runtime is not None and harness_kind == "harbor":
        actor_snapshot = actor_binding_for_runtime(runtime)
    if adapter_id == "bfcl" and model_snapshot is not None:
        bfcl_binding = model_snapshot.bfcl
        if bfcl_binding is not None and bfcl_binding.mode == "configured" and not diagnostic:
            raise BenchEvalError(
                f"model {model_key!r} reaches BFCL through a configured registration; "
                "such runs are diagnostic only until separately qualified (pass --diagnostic)",
            )
    slice_path = _resolve_slice_yaml(slice_id, benchmark.id)
    slice_manifest = load_slice_manifest(slice_path)
    judge_model_id = slice_manifest.slice.judge_model_id
    judge_snapshot = None
    if adapter_id == "hle":
        if judge_model_id is None:
            raise BenchEvalError(f"HLE slice {slice_id!r} must pin judge_model_id")
        try:
            judge_entry = model_registry.by_id(judge_model_id)
        except KeyError as e:
            raise BenchEvalError(
                f"HLE slice {slice_id!r} references unknown judge model {judge_model_id!r}",
            ) from e
        # The judge resolves its own route; it is never silently sent to the
        # candidate's provider.
        judge_snapshot = resolve_model_binding(
            judge_model_id,
            judge_entry.provider_route or resolved_provider,
            models=model_registry,
            providers=provider_catalog,
        )
    elif judge_model_id is not None:
        raise BenchEvalError(
            f"slice {slice_id!r} sets judge_model_id but adapter {adapter_id!r} has no judge",
        )
    instance_ids = slice_instance_ids(slice_manifest, slice_path)
    if not instance_ids:
        raise BenchEvalError(f"slice {slice_id!r} has no instances")

    budget_class = _budget_class_for_slice(
        slice_manifest.budget.max_total_cost_usd,
        slice_manifest.budget.max_wall_clock_sec_per_instance,
    )
    defaults = BUDGET_CLASS_DEFAULTS[budget_class]
    # Envelope semantics (docs/architecture.md §9): class values are per-instance
    # wall / run-total cost ceilings used for classification; because the bands
    # mirror the defaults, the slice's own envelope is always the tighter one and
    # is preserved verbatim. Per-instance and run-total wall limits are separate
    # fields — adapters must never derive one from the other by dividing.
    default_cost = float(defaults["max_cost_usd"])
    default_wall = int(defaults["max_wall_clock_sec"])
    slice_cost = float(slice_manifest.budget.max_total_cost_usd)
    slice_wall_per_instance = slice_manifest.budget.max_wall_clock_sec_per_instance
    max_cost = min(slice_cost, default_cost) if default_cost > 0 else slice_cost
    max_wall_per_instance = (
        min(slice_wall_per_instance, default_wall) if default_wall > 0 else slice_wall_per_instance
    )
    max_wall_total = max_wall_per_instance * len(instance_ids)
    requires_harbor = harness_kind == "harbor"
    profile = benchmark.recommended_profile
    # E3 is catalog planning vocabulary for external calibration; it does not
    # claim that the concrete launch is sandboxed. E4 does, as do the harnesses
    # whose execution contract explicitly owns a sandbox.
    requires_sandbox = harness_kind in ("harbor", "swebench-native") or profile == "E4"

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
    # Aggregate Inspect/HLE adapters report cost_usd=0; envelope max_cost is not a hard cap.
    if adapter_id in {"gpqa", "hle", "bfcl"}:
        caveats.append("max_cost_usd_unenforced_estimate")

    validity = _comparison_validity(slice_manifest.slice.purpose)
    if agent_profile is not None and agent_profile.admission == "draft":
        # A draft native agent is diagnostic evidence until its own proof
        # admits exactly this profile/combination (roadmap CF2.3).
        validity = "diagnostic_only"
    if adapter_id == "bfcl" and model_snapshot is not None and model_snapshot.bfcl is not None:
        if model_snapshot.bfcl.mode == "configured":
            # A configured registration identifies an extension of the pinned
            # harness, never plain upstream support: diagnostic only. The BFCL
            # binding says nothing about other adapters' classification.
            validity = "diagnostic_only"

    return RunPlan(
        schema_version="0.3",
        benchmark_id=benchmark.id,
        benchmark_version=_benchmark_version_pin(benchmark),
        slice_id=slice_manifest.slice.id,
        adapter_id=adapter_id,
        harness_kind=harness_kind,
        runtime_id=resolved_runtime_id,
        runtime_kind=resolved_runtime_kind,
        agent_id=agent_arg,
        provider_id=resolved_provider,
        model_id=model_key,
        judge_model_id=judge_model_id,
        model_binding=model_binding,
        model_binding_snapshot=model_snapshot,
        judge_binding_snapshot=judge_snapshot,
        actor_binding_snapshot=actor_snapshot,
        instances=tuple(RunPlanInstance(instance_id=i) for i in instance_ids),
        budget_class=budget_class,
        max_cost_usd=round(max_cost, 6),
        max_wall_clock_sec=max_wall_total,
        max_wall_clock_sec_per_instance=max_wall_per_instance,
        requires_harbor=requires_harbor,
        requires_sandbox=requires_sandbox,
        network_policy=network,
        cleanup_policy=cleanup_policy,
        caveats=tuple(caveats),
        comparison_validity=validity,
        diagnostic=diagnostic,
    )


class ControlPlanePlanner:
    """Concrete :class:`~bencheval.contracts.RunPlanner` implementation."""

    def plan(
        self,
        *,
        benchmark_id: str,
        slice_id: str,
        runtime_id: str | None,
        model_id: str,
        agent_id: str | None = None,
        provider_id: str | None = None,
        diagnostic: bool = False,
    ) -> RunPlan:
        return plan_control_plane(
            benchmark_id=benchmark_id,
            slice_id=slice_id,
            runtime_id=runtime_id,
            model_id=model_id,
            agent_id=agent_id,
            provider_id=provider_id,
            diagnostic=diagnostic,
        )


def draft_native_agent(agent_id: str | None) -> bool:
    """True when ``agent_id`` is a draft ``kind: harbor`` profile (diagnostic-only launch)."""
    if not agent_id or not agent_id.strip():
        return False
    try:
        profile = load_agent_catalog().by_id(agent_id.strip())
    except KeyError:
        return False
    return profile.admission == "draft" and profile.agent.kind == "harbor"


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
    if slice_manifest.slice.instances_source is None:
        fingerprint = _inline_instances_fingerprint(instance_ids)
    else:
        from bencheval.slice_manifest import resolve_instances_source_path

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
    "draft_native_agent",
    "dry_run_slice_resolution",
    "list_adapter_descriptors",
    "plan_control_plane",
    "resolve_runtime_id",
    "run_plan_to_dry_run_dict",
]
