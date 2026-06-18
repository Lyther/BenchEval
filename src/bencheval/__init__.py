"""BenchEval: LLM benchmark evaluation tracker."""

from bencheval.benchmark_registry import (
    BenchmarkCatalog,
    BenchmarkEntry,
    load_benchmark_catalog,
)
from bencheval.compare import GuardedComparisonReporter
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
    EvalLogError,
    EvidenceValidationError,
    LiveRunManifestError,
    ManifestError,
    SummaryValidationError,
    TaskContractError,
)
from bencheval.live_run_manifest import (
    LIVE_RUN_SCHEMA_VERSION,
    LiveRunRecord,
    append_live_run,
    default_runs_manifest_path,
    read_live_runs,
)
from bencheval.loader import read_summary_jsonl
from bencheval.models import (
    ComparisonReport,
    DeltaRow,
    ManifestDigest,
    ModelFamily,
    RunStamp,
    SummaryRow,
)
from bencheval.pricing import ModelPrice, PricingSheet, load_pricing
from bencheval.runtime_registry import load_runtime_catalog, load_runtime_profile
from bencheval.sink import JsonlSummarySink
from bencheval.slice_manifest import load_slice_manifest
from bencheval.summary import StrictSummaryBuilder
from bencheval.task_contract import TaskContract

__all__ = [
    "LIVE_RUN_SCHEMA_VERSION",
    "AdapterFailureError",
    "AttemptSummaryDTO",
    "BenchEvalError",
    "BenchmarkCatalog",
    "BenchmarkEntry",
    "ComparisonError",
    "ComparisonReport",
    "DeltaRow",
    "EvalLogError",
    "EvidenceRecord",
    "EvidenceValidationError",
    "GuardedComparisonReporter",
    "JsonlSummarySink",
    "LiveRunManifestError",
    "LiveRunRecord",
    "ManifestDigest",
    "ManifestError",
    "ModelFamily",
    "ModelPrice",
    "PricingSheet",
    "RunPlan",
    "RunStamp",
    "RuntimeCatalog",
    "RuntimeProfile",
    "SliceManifest",
    "StrictSummaryBuilder",
    "SummaryRow",
    "SummaryValidationError",
    "TaskContract",
    "TaskContractError",
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
    "read_summary_jsonl",
]
