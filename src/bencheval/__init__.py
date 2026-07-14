"""BenchEval: LLM benchmark evaluation control plane."""

from bencheval.benchmark_registry import (
    BenchmarkCatalog,
    BenchmarkEntry,
    load_benchmark_catalog,
)
from bencheval.domain import (
    AttemptSummaryDTO,
    RunPlan,
    RuntimeCatalog,
    RuntimeProfile,
    SliceManifest,
    TokenUsage,
)
from bencheval.evidence import EvidenceRecord, read_evidence_jsonl
from bencheval.exceptions import (
    AdapterFailureError,
    BenchEvalError,
    ComparisonError,
    EvidenceValidationError,
    LiveRunManifestError,
    ManifestError,
)
from bencheval.live_run_manifest import (
    LIVE_RUN_SCHEMA_VERSION,
    LiveRunRecord,
    append_live_run,
    default_runs_manifest_path,
    read_live_runs,
)
from bencheval.models import ManifestDigest, ModelFamily
from bencheval.pricing import ModelPrice, PricingSheet, load_pricing
from bencheval.runtime_registry import load_runtime_catalog, load_runtime_profile
from bencheval.slice_manifest import load_slice_manifest

__all__ = [
    "LIVE_RUN_SCHEMA_VERSION",
    "AdapterFailureError",
    "AttemptSummaryDTO",
    "BenchEvalError",
    "BenchmarkCatalog",
    "BenchmarkEntry",
    "ComparisonError",
    "EvidenceRecord",
    "EvidenceValidationError",
    "LiveRunManifestError",
    "LiveRunRecord",
    "ManifestDigest",
    "ManifestError",
    "ModelFamily",
    "ModelPrice",
    "PricingSheet",
    "RunPlan",
    "RuntimeCatalog",
    "RuntimeProfile",
    "SliceManifest",
    "TokenUsage",
    "append_live_run",
    "default_runs_manifest_path",
    "load_benchmark_catalog",
    "load_pricing",
    "load_runtime_catalog",
    "load_runtime_profile",
    "load_slice_manifest",
    "read_evidence_jsonl",
    "read_live_runs",
]
