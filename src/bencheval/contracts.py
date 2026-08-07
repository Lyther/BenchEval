"""Internal capability boundaries (replaceable implementations, stable call sites)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from bencheval.domain import (
    RunPlan,
    RuntimeCatalog,
    RuntimeProfile,
    SliceManifest,
)

if TYPE_CHECKING:
    from bencheval.benchmark_registry import BenchmarkCatalog


class BenchmarkCatalogSource(Protocol):
    """Load the benchmark registry (executable contracts)."""

    def load(self, path: Path | None = None) -> BenchmarkCatalog:
        """Return a validated ``BenchmarkCatalog``; raise ``BenchEvalError`` on failure."""


class RuntimeCatalogSource(Protocol):
    """Load runtime profiles from ``config/runtimes/*.yaml``."""

    def load_catalog(self, dir_path: Path | str | None = None) -> RuntimeCatalog:
        """Return a validated ``RuntimeCatalog``; raise ``BenchEvalError`` on failure."""

    def load_profile(self, path: Path | str) -> RuntimeProfile:
        """Return a validated ``RuntimeProfile``; raise ``BenchEvalError`` on failure."""


class SliceManifestSource(Protocol):
    """Load a typed slice manifest + its referenced instance ids."""

    def load(self, path: Path | str) -> SliceManifest:
        """Return a validated ``SliceManifest``; raise ``BenchEvalError`` on failure."""

    def instance_ids(self, manifest: SliceManifest, slice_yaml_path: Path | str) -> tuple[str, ...]:
        """Return ordered instance ids referenced by ``manifest``."""


class RunPlanner(Protocol):
    """Build a concrete execution plan (no execution, no artifacts)."""

    def plan(
        self,
        *,
        benchmark_id: str,
        slice_id: str,
        runtime_id: str | None,
        model_id: str,
        agent_id: str | None = None,
        provider_id: str | None = None,
    ) -> RunPlan:
        """Return a frozen ``RunPlan`` DTO.

        Pass at most one of ``runtime_id`` / ``agent_id``. Omitting both is
        model-only (bfcl-native). Raises ``BenchEvalError`` when the tuple is
        incoherent. The plan carries NO artifact paths and NO secrets.
        """


class AdapterDispatcher(Protocol):
    """Route a ``RunPlan`` to the matching adapter."""

    def dispatch(self, plan: RunPlan) -> None:
        """Execute the plan, appending ``EvidenceRecord`` rows.

        Preflight/infrastructure failures abort without evidence. Post-preflight
        adapter failures write ``EvidenceRecord`` rows with ``primary_pass=False``.
        Raises ``AdapterFailureError`` for preflight aborts.
        """


class AuthProbe(Protocol):
    """Preflight provider credentials."""

    def verify_baseline_providers(self) -> None:
        """Raise ``BenchEvalError`` if probe fails."""


__all__ = [
    "AdapterDispatcher",
    "AuthProbe",
    "BenchmarkCatalogSource",
    "RunPlanner",
    "RuntimeCatalogSource",
    "SliceManifestSource",
]
