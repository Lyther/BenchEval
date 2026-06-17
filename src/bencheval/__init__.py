"""BenchEval: LLM benchmark evaluation tracker."""

from bencheval.compare import GuardedComparisonReporter
from bencheval.evidence import EvidenceRecord, read_evidence_jsonl
from bencheval.exceptions import (
    AdapterFailureError,
    BenchEvalError,
    ComparisonError,
    EvalLogError,
    EvidenceValidationError,
    ManifestError,
    SummaryValidationError,
    TaskContractError,
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
from bencheval.sink import JsonlSummarySink
from bencheval.summary import StrictSummaryBuilder
from bencheval.task_contract import TaskContract

__all__ = [
    "AdapterFailureError",
    "BenchEvalError",
    "ComparisonError",
    "ComparisonReport",
    "DeltaRow",
    "EvalLogError",
    "EvidenceRecord",
    "EvidenceValidationError",
    "GuardedComparisonReporter",
    "JsonlSummarySink",
    "ManifestDigest",
    "ManifestError",
    "ModelFamily",
    "ModelPrice",
    "PricingSheet",
    "RunStamp",
    "StrictSummaryBuilder",
    "SummaryRow",
    "SummaryValidationError",
    "TaskContract",
    "TaskContractError",
    "load_pricing",
    "read_evidence_jsonl",
    "read_summary_jsonl",
]
