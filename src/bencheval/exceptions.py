class BenchEvalError(Exception):
    """Base error for BenchEval boundaries."""


class ManifestError(BenchEvalError):
    """Raised when a task manifest cannot be loaded or hashed."""


class ComparisonError(BenchEvalError):
    """Raised when a delta comparison violates guardrails."""


class EvidenceValidationError(BenchEvalError):
    """Raised when an evidence JSONL row fails schema or business rules."""


class LiveRunManifestError(BenchEvalError):
    """Raised when a live run manifest record fails schema or business rules."""


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
