class BenchEvalError(Exception):
    """Base error for BenchEval boundaries."""


class SummaryValidationError(BenchEvalError):
    """Raised when a summary row fails schema or business rules."""


class ManifestError(BenchEvalError):
    """Raised when a task manifest cannot be loaded or hashed."""


class EvalLogError(BenchEvalError):
    """Raised when an Inspect `.eval` log cannot be read or parsed."""


class ComparisonError(BenchEvalError):
    """Raised when a delta comparison violates §7 guardrails."""
