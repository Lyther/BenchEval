"""Internal capability boundaries (replaceable implementations, stable call sites)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from pydantic import JsonValue

from bencheval.domain import (
    RunPlan,
    RuntimeCatalog,
    RuntimeProfile,
    SliceManifest,
)
from bencheval.models import ComparisonReport, ManifestDigest, RunStamp, SummaryRow

if TYPE_CHECKING:
    # Avoid an import cycle at runtime: benchmark_registry imports exceptions only,
    # but keep the boundary explicit by importing under TYPE_CHECKING.
    from bencheval.benchmark_registry import BenchmarkCatalog

# ---------------------------------------------------------------------------
# Legacy v0.2 Protocols (selftest / Core / summary pipeline)
# ---------------------------------------------------------------------------


class ManifestLoader(Protocol):
    """Load a committed manifest file and return ids + digest."""

    def load(self, path: Path) -> ManifestDigest:
        """Raise ``ManifestError`` on missing file or hash mismatch."""


class EvalLogSource(Protocol):
    """Read structured slices from an Inspect ``.eval`` log without leaking parser details."""

    def read_header(self, path: Path) -> Mapping[str, JsonValue]:
        """Subset of eval metadata needed for §6 provenance (raise ``EvalLogError`` on failure)."""


class SummaryBuilder(Protocol):
    """Map log + wrapper context → strict ``SummaryRow``."""

    def build(
        self,
        eval_log_path: Path,
        stamp: RunStamp,
        manifest: ManifestDigest,
        header: Mapping[str, JsonValue],
    ) -> SummaryRow:
        """Valid ``SummaryRow`` or raise ``SummaryValidationError``.

        Stamp hash must match ``manifest.content_sha256``. Full-manifest runs need
        ``n_samples == len(manifest.task_ids)``.
        """


class SummarySink(Protocol):
    """Append-only JSONL persistence."""

    def append_jsonl(self, path: Path, row: SummaryRow) -> None:
        """Serialize with stable key order; create parent dirs if needed."""


class ComparisonReporter(Protocol):
    """§7 delta analysis — validates comparability before emitting a report."""

    def compare(
        self,
        baseline: Sequence[SummaryRow],
        current: Sequence[SummaryRow],
        *,
        equivalence_note: str | None,
    ) -> ComparisonReport:
        """Raise ``ComparisonError`` when guardrails fail."""


class AuthProbe(Protocol):
    """Preflight provider credentials (baseline lane)."""

    def verify_baseline_providers(self) -> None:
        """Raise ``bencheval.exceptions.BenchEvalError`` if probe fails."""


# ---------------------------------------------------------------------------
# v0.3 Control-plane Protocols (public benchmark × model × runtime)
# ---------------------------------------------------------------------------
# These are the replaceable boundaries for the v0.3 pivot. Callers depend on
# the Protocol + the domain DTOs, never on a concrete registry/planner/adapter.
# Implementations live in runtime_registry.py, slice_manifest.py, planner.py,
# executor.py, and the adapter modules. See docs/api/internal-contracts.md.


class BenchmarkCatalogSource(Protocol):
    """Load the benchmark registry (executable contracts)."""

    def load(self, path: Path | None = None) -> BenchmarkCatalog:
        """Return a validated ``BenchmarkCatalog``; raise ``BenchEvalError`` on failure.

        Callers depend on this Protocol + the ``BenchmarkCatalog`` DTO, never on the
        concrete loader module.
        """


class RuntimeCatalogSource(Protocol):
    """Load runtime profiles from ``config/runtimes/*.yaml``."""

    def load_catalog(self, dir_path: Path | str | None = None) -> RuntimeCatalog:
        """Return a validated ``RuntimeCatalog``; raise ``BenchEvalError`` on failure."""

    def load_profile(self, path: Path | str) -> RuntimeProfile:
        """Return a validated ``RuntimeProfile``; raise ``BenchEvalError`` on failure."""


class SliceManifestSource(Protocol):
    """Load a typed slice manifest + its referenced instance ids."""

    def load(self, path: Path | str) -> SliceManifest:
        """Return a validated ``SliceManifest``; raise ``BenchEvalError`` on failure.

        Implementations must verify ``instances_source`` resolves and that the
        instance count fits ``budget.max_instances``.
        """

    def instance_ids(self, manifest: SliceManifest, slice_yaml_path: Path | str) -> tuple[str, ...]:
        """Return ordered instance ids referenced by ``manifest``."""


class RunPlanner(Protocol):
    """Build a concrete four-axis execution plan (no execution, no artifacts)."""

    def plan(
        self,
        *,
        benchmark_id: str,
        slice_id: str,
        runtime_id: str,
        model_id: str,
    ) -> RunPlan:
        """Return a frozen ``RunPlan`` DTO.

        Raises ``BenchEvalError`` when the (benchmark, slice, runtime, model) tuple is
        incoherent: unknown benchmark/runtime, empty slice, unsupported harness, or
        safety-lane conflict (offensive task outside Stretch without explicit allow).
        The plan carries NO artifact paths and NO secrets.
        """


class AdapterDispatcher(Protocol):
    """Route a ``RunPlan`` to the matching native/Inspect/Harbor/runtime adapter."""

    def dispatch(self, plan: RunPlan) -> None:
        """Execute the plan, appending ``EvidenceRecord`` rows to the evidence store.

        Preflight/infrastructure failures abort without evidence. Post-preflight adapter
        failures write ``EvidenceRecord`` rows with ``primary_pass=False`` and the
        canonical ``FailureLabel``. Raises ``AdapterFailureError`` for preflight aborts.
        """


__all__ = [
    "AdapterDispatcher",
    "AuthProbe",
    "BenchmarkCatalogSource",
    "ComparisonReporter",
    "EvalLogSource",
    "ManifestLoader",
    "RunPlanner",
    "RuntimeCatalogSource",
    "SliceManifestSource",
    "SummaryBuilder",
    "SummarySink",
]
