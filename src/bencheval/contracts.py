"""Internal capability boundaries (replaceable implementations, stable call sites)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from pydantic import JsonValue

from bencheval.models import ComparisonReport, ManifestDigest, RunStamp, SummaryRow


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
