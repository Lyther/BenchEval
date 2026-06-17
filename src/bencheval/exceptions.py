class BenchEvalError(Exception):
    """Base error for BenchEval boundaries."""


class SummaryValidationError(BenchEvalError):
    """Raised when a summary row fails schema or business rules."""


class ManifestError(BenchEvalError):
    """Raised when a task manifest cannot be loaded or hashed."""


class EvalLogError(BenchEvalError):
    """Raised when an Inspect `.eval` log cannot be read or parsed."""


class ComparisonError(BenchEvalError):
    """Raised when a delta comparison violates guardrails."""


class TaskContractError(BenchEvalError):
    """Raised when a task contract cannot be loaded or validated."""


class EvidenceValidationError(BenchEvalError):
    """Raised when an evidence JSONL row fails schema or business rules."""


class AdapterFailureError(BenchEvalError):
    """Adapter produced no scorable candidate; maps to evidence failure_labels."""

    def __init__(
        self,
        message: str,
        *,
        failure_label: str,
        cost_usd: float = 0.0,
        latency_sec: float = 0.0,
        adapter_metadata: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_label = failure_label
        self.cost_usd = cost_usd
        self.latency_sec = latency_sec
        self.adapter_metadata = dict(adapter_metadata or {})
