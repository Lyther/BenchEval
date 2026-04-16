"""Pure-Python comparison reporter with Newcombe-Wilson CI; no scipy."""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime

from bencheval.exceptions import ComparisonError
from bencheval.models import ComparisonReport, DeltaRow, SummaryRow

Z_95 = 1.96


def _require_constant(rows: Sequence[SummaryRow], attr: str, side_label: str) -> object:
    first = getattr(rows[0], attr)
    for i, row in enumerate(rows[1:], start=1):
        if getattr(row, attr) != first:
            msg = f"{attr} drifted within {side_label}: row 0 and row {i} differ"
            raise ComparisonError(msg)
    return first


def _wilson(k: int, n: int) -> tuple[float, float, float]:
    """Return (p_hat, lo, hi) with p_hat = k/n and (lo, hi) the Wilson score interval (R3)."""
    z = Z_95
    z2 = z * z
    denom = n + z2
    center = (k + z2 / 2) / denom
    inner = k * (n - k) / n + z2 / 4 if n else 0.0
    halfwidth = z * math.sqrt(inner) / denom
    lo = center - halfwidth
    hi = center + halfwidth
    p_hat = k / n if n else float("nan")
    return (p_hat, lo, hi)


def _newcombe_diff(
    p_b: float,
    lo_b: float,
    hi_b: float,
    p_c: float,
    lo_c: float,
    hi_c: float,
    delta: float,
) -> tuple[float, float]:
    ci_low = delta - math.sqrt((p_b - lo_b) ** 2 + (hi_c - p_c) ** 2)
    ci_high = delta + math.sqrt((hi_b - p_b) ** 2 + (p_c - lo_c) ** 2)
    return (ci_low, ci_high)


class GuardedComparisonReporter:
    """§7 comparison with guardrails and Newcombe-Wilson interval on resolved_rate delta."""

    def compare(
        self,
        baseline: Sequence[SummaryRow],
        current: Sequence[SummaryRow],
        *,
        equivalence_note: str | None,
    ) -> ComparisonReport:
        if not baseline:
            raise ComparisonError("baseline must be non-empty")
        if not current:
            raise ComparisonError("current must be non-empty")

        _require_constant(baseline, "task_manifest_hash", "baseline")
        _require_constant(baseline, "benchmark_revision", "baseline")
        _require_constant(baseline, "solver", "baseline")
        _require_constant(baseline, "solver_version", "baseline")
        _require_constant(baseline, "auth_lane", "baseline")

        _require_constant(current, "task_manifest_hash", "current")
        _require_constant(current, "benchmark_revision", "current")
        _require_constant(current, "solver", "current")
        _require_constant(current, "solver_version", "current")
        _require_constant(current, "auth_lane", "current")

        b0, c0 = baseline[0], current[0]
        if b0.task_manifest_hash != c0.task_manifest_hash:
            raise ComparisonError("task_manifest_hash differs between baseline and current")
        if b0.benchmark_revision != c0.benchmark_revision:
            raise ComparisonError("benchmark_revision differs between baseline and current")
        if b0.solver != c0.solver:
            raise ComparisonError("solver differs between baseline and current")
        if b0.solver_version != c0.solver_version:
            raise ComparisonError("solver_version differs between baseline and current")

        if b0.auth_lane != c0.auth_lane:
            if equivalence_note is None or not equivalence_note.strip():
                raise ComparisonError(
                    "auth_lane differs between baseline and current; "
                    "equivalence_note must be a non-empty string",
                )

        k_b = sum(r.resolved for r in baseline)
        n_b = sum(r.n_samples for r in baseline)
        k_c = sum(r.resolved for r in current)
        n_c = sum(r.n_samples for r in current)

        if n_b == 0 or n_c == 0:
            raise ComparisonError("total n_samples must be positive on each side")

        p_b, lo_b, hi_b = _wilson(k_b, n_b)
        p_c, lo_c, hi_c = _wilson(k_c, n_c)
        delta = p_c - p_b
        ci_low, ci_high = _newcombe_diff(p_b, lo_b, hi_b, p_c, lo_c, hi_c, delta)

        metric = DeltaRow(
            label="resolved_rate",
            baseline=float(p_b),
            compare=float(p_c),
            delta=float(delta),
            ci_low=float(ci_low),
            ci_high=float(ci_high),
        )
        return ComparisonReport(
            title="resolved_rate delta",
            generated_at=datetime.now(tz=UTC),
            equivalence_note=equivalence_note,
            metrics=(metric,),
        )
