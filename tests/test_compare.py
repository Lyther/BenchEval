from __future__ import annotations

import math
from decimal import Decimal

import pytest

from bencheval import ComparisonError, GuardedComparisonReporter
from bencheval.models import SummaryRow
from tests.factories import make_summary_row

H = "a" * 64


def _row(**overrides: object) -> SummaryRow:
    return make_summary_row(**overrides)


def test_happy_two_by_two_structure() -> None:
    base = [
        _row(n_samples=250, resolved=150, resolved_rate=0.6),
        _row(n_samples=250, resolved=150, resolved_rate=0.6),
    ]
    cur = [
        _row(n_samples=250, resolved=160, resolved_rate=0.64),
        _row(n_samples=250, resolved=160, resolved_rate=0.64),
    ]
    rep = GuardedComparisonReporter().compare(base, cur, equivalence_note=None)
    assert rep.title == "resolved_rate delta"
    assert rep.equivalence_note is None
    assert len(rep.metrics) == 1
    assert rep.metrics[0].label == "resolved_rate"


def test_happy_delta_aggregate_rates() -> None:
    base = [
        _row(n_samples=250, resolved=150, resolved_rate=0.6),
        _row(n_samples=250, resolved=150, resolved_rate=0.6),
    ]
    cur = [
        _row(n_samples=250, resolved=200, resolved_rate=0.8),
        _row(n_samples=250, resolved=200, resolved_rate=0.8),
    ]
    m = GuardedComparisonReporter().compare(base, cur, equivalence_note=None).metrics[0]
    assert math.isclose(m.baseline, 0.6)
    assert math.isclose(m.compare, 0.8)
    assert math.isclose(m.delta, 0.2)
    assert m.ci_low <= m.delta <= m.ci_high


def test_identity_zero_delta() -> None:
    base = [
        _row(n_samples=100, resolved=40, resolved_rate=0.4),
        _row(n_samples=100, resolved=40, resolved_rate=0.4),
    ]
    cur = list(base)
    m = GuardedComparisonReporter().compare(base, cur, equivalence_note=None).metrics[0]
    assert math.isclose(m.delta, 0.0)
    assert m.ci_low <= 0.0 <= m.ci_high


def test_newcombe_bounds_significant_positive() -> None:
    base = [_row(n_samples=100, resolved=50, resolved_rate=0.5)]
    cur = [_row(n_samples=100, resolved=70, resolved_rate=0.7)]
    m = GuardedComparisonReporter().compare(base, cur, equivalence_note=None).metrics[0]
    assert math.isclose(m.delta, 0.2)
    assert m.ci_low > 0.0
    assert m.ci_high < 1.0
    assert (m.ci_high - m.ci_low) > 0.1


def test_wilson_zero_events_sanity() -> None:
    base = [_row(n_samples=100, resolved=0, resolved_rate=0.0)]
    cur = [_row(n_samples=100, resolved=0, resolved_rate=0.0)]
    m = GuardedComparisonReporter().compare(base, cur, equivalence_note=None).metrics[0]
    assert math.isclose(m.baseline, 0.0)
    assert math.isclose(m.compare, 0.0)
    assert math.isclose(m.delta, 0.0)
    assert m.ci_low <= 0.0 <= m.ci_high
    assert math.isfinite(m.ci_low)
    assert math.isfinite(m.ci_high)


def test_guardrail_empty_baseline() -> None:
    with pytest.raises(ComparisonError, match="baseline"):
        GuardedComparisonReporter().compare([], [_row()], equivalence_note=None)


def test_guardrail_empty_current() -> None:
    with pytest.raises(ComparisonError, match="current"):
        GuardedComparisonReporter().compare([_row()], [], equivalence_note=None)


def test_guardrail_baseline_task_manifest_hash_drift() -> None:
    base = [
        _row(task_manifest_hash=H),
        _row(task_manifest_hash="b" * 64),
    ]
    with pytest.raises(ComparisonError, match="task_manifest_hash"):
        GuardedComparisonReporter().compare(base, [_row()], equivalence_note=None)


def test_guardrail_benchmark_revision_between_sides() -> None:
    base = [_row(benchmark_revision="rev-a")]
    cur = [_row(benchmark_revision="rev-b")]
    with pytest.raises(ComparisonError, match="benchmark_revision"):
        GuardedComparisonReporter().compare(base, cur, equivalence_note=None)


def test_guardrail_solver_between_sides() -> None:
    v = "0.2.47"
    base = [_row(solver="inspect_swe.claude_code", solver_version=v, inspect_swe_version=v)]
    cur = [_row(solver="inspect_swe.openai", solver_version=v, inspect_swe_version=v)]
    with pytest.raises(ComparisonError, match="solver"):
        GuardedComparisonReporter().compare(base, cur, equivalence_note=None)


def test_guardrail_solver_version_between_sides() -> None:
    base = [_row(solver_version="0.2.47", inspect_swe_version="0.2.47")]
    cur = [_row(solver_version="0.2.48", inspect_swe_version="0.2.48")]
    with pytest.raises(ComparisonError, match="solver_version"):
        GuardedComparisonReporter().compare(base, cur, equivalence_note=None)


def test_guardrail_auth_lane_mismatch_requires_note() -> None:
    base = [
        _row(
            auth_lane="baseline_api",
            solver="cursor_cli",
            solver_version="cursor-agent@1.0.0",
            inspect_swe_version=None,
        ),
    ]
    cur = [
        _row(
            auth_lane="experimental_cursor",
            actual_cost_usd=None,
            estimated_api_equivalent_usd=Decimal("1.00"),
            solver="cursor_cli",
            solver_version="cursor-agent@1.0.0",
            inspect_swe_version=None,
        ),
    ]
    with pytest.raises(ComparisonError, match="auth_lane"):
        GuardedComparisonReporter().compare(base, cur, equivalence_note=None)


def test_guardrail_auth_lane_mismatch_with_note_passes_through() -> None:
    note = "gateway routes to API; tokens billed identically"
    base = [
        _row(
            auth_lane="baseline_api",
            solver="cursor_cli",
            solver_version="cursor-agent@1.0.0",
            inspect_swe_version=None,
        ),
    ]
    cur = [
        _row(
            auth_lane="experimental_cursor",
            actual_cost_usd=None,
            estimated_api_equivalent_usd=Decimal("1.00"),
            solver="cursor_cli",
            solver_version="cursor-agent@1.0.0",
            inspect_swe_version=None,
        ),
    ]
    rep = GuardedComparisonReporter().compare(base, cur, equivalence_note=note)
    assert rep.equivalence_note == note


def test_guardrail_zero_total_n_samples() -> None:
    base = [_row(n_samples=0, resolved=0, resolved_rate=0.0)]
    cur = [_row(n_samples=100, resolved=10, resolved_rate=0.1)]
    with pytest.raises(ComparisonError, match="n_samples"):
        GuardedComparisonReporter().compare(base, cur, equivalence_note=None)
