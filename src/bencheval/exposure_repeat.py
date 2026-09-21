"""Repeat-protocol analysis: three-arm estimand, exact randomization test, interval.

Two things this module is not free to choose:

* the reference distribution is computed by **exact integer counting** over
  balanced allocations, never by sampling and never by visiting every
  allocation (``C(40,20)`` is 137,846,528,820, and a subset-sum count retains
  every allocation's multiplicity in milliseconds);
* the interval consumes the **observable** slot differences returned to the
  assigned frame, never a latent per-block quantity the analyst cannot see.

Specification: ``docs/context/bfcl-repeat-spec.md``.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from bencheval.exceptions import BenchEvalError

REPEAT_CONTRACT_VERSION = "exposure-repeat-v1"

#: Only one method is permitted for this design. The literal exists so a report
#: cannot describe a sampled distribution as an enumerated one.
ReferenceMethod = Literal["exact-counting"]

_ARMS = ("anchor", "treatment", "repeat")
_ALPHA = 0.05

#: Verbatim wordings the design owns. They are constants, not phrasing choices.
_TESTED_NULL = "sharp: no order effect on any case"
_ESTIMATED_QUANTITY = "the cohort average excess disagreement, in percentage points"
_HYPOTHESIS_BOUNDARY = (
    "an exact test of the sharp null is not validity for the average effect; "
    "the two are different claims and only the first is exact here"
)
_PRECISION_NOTE = (
    "five points is a median planning half-width in the evaluated scenarios, "
    "not a promise about this interval"
)
_INCONCLUSIVE_NOTE = (
    "an imprecise or nonsignificant result is reportable and inconclusive, and "
    "never authorizes replacement attempts"
)
_DIAGNOSTIC_NOTE = (
    "the primary population is invalid, so this record explains the absence of a "
    "result: it carries no p-value, no headline, and never registers a pass"
)


@dataclass(frozen=True, slots=True)
class CaseOutcome:
    """One source case seen through all three arms of its block."""

    instance_id: str
    block_id: str
    anchor_pass: bool
    treatment_pass: bool
    repeat_pass: bool


@dataclass(frozen=True, slots=True)
class RepeatEstimand:
    """Shared-anchor arithmetic. ``V`` and ``R`` both compare against the anchor."""

    v_count: int
    r_count: int
    mean_d: float
    outcome_table: dict[tuple[bool, bool, bool], int]


@dataclass(frozen=True, slots=True)
class RandomizationResult:
    """An exact randomization p-value and the provenance of its reference set."""

    statistic: int
    reference_method: ReferenceMethod
    allocation_space_size: int
    at_or_beyond: int
    p_value: float


@dataclass(frozen=True, slots=True)
class BlockInterval:
    """A t-interval over observable per-block effect estimates, in points."""

    centre_points: float
    half_width_points: float
    block_count: int
    degenerate: bool


@dataclass(frozen=True, slots=True)
class ProtocolReport:
    """Deterministic report authority: ``payload`` is the only source of truth."""

    payload: dict[str, object]

    def to_json(self) -> str:
        return json.dumps(self.payload, sort_keys=True, indent=2) + "\n"

    @property
    def sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.to_json().encode('utf-8')).hexdigest()}"


# --- Student-t critical value ------------------------------------------------------
#
# ``stats.py`` is reused unchanged for the existing Wilson/Newcombe/binomial
# helpers; it has no t quantile to reuse, and this one exists solely for the
# frozen block interval below, so it lives here rather than forking that module.


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Lentz evaluation of the continued fraction for the incomplete beta."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 300):
        m2 = 2 * m
        numerator = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        numerator = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-16:
            break
    return h


def _regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def _student_t_two_sided_tail(t: float, df: int) -> float:
    """P(|T| >= t) for a Student-t with ``df`` degrees of freedom."""
    return _regularized_incomplete_beta(df / 2.0, 0.5, df / (df + t * t))


def _student_t_critical(df: int, *, alpha: float = _ALPHA) -> float:
    """The two-sided ``1 - alpha`` critical value, by bisection on the exact tail."""
    if df < 1:
        raise BenchEvalError("a t critical value needs at least one degree of freedom")
    low, high = 0.0, 1.0e4
    for _ in range(200):
        mid = 0.5 * (low + high)
        if _student_t_two_sided_tail(mid, df) > alpha:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


# --- the shared-anchor estimand ----------------------------------------------------


def build_protocol_report(
    estimand: RepeatEstimand,
    test: RandomizationResult,
    interval: BlockInterval,
    *,
    population_valid: bool,
) -> ProtocolReport:
    """Render the report, keeping the tested null and the estimated quantity apart.

    The payload states the **tested null** (sharp: no order effect on any case)
    separately from the **estimated quantity** (the cohort average effect), and
    says that exactness for the first is not validity for the second. It carries
    the precision wording verbatim: five points is a median planning half-width
    in the evaluated scenarios, not a promise about this interval.

    When ``population_valid`` is false the report is a diagnostic availability
    record: it explains why no inferential result exists, carries no p-value and
    no headline, and never registers a pass.
    """
    payload: dict[str, object] = {
        "contract_version": REPEAT_CONTRACT_VERSION,
        "tested_null": _TESTED_NULL,
        "estimated_quantity": _ESTIMATED_QUANTITY,
        "hypothesis_boundary": _HYPOTHESIS_BOUNDARY,
        "precision_note": _PRECISION_NOTE,
        "inconclusive_note": _INCONCLUSIVE_NOTE,
        "population_valid": population_valid,
        # A report is a record, never a test outcome: it never registers a pass.
        "registers_pass": False,
        "estimand": {
            "v_count": estimand.v_count,
            "r_count": estimand.r_count,
            "mean_d": estimand.mean_d,
            "mean_excess_points": estimand.mean_d * 100,
            "outcome_table": _outcome_rows(estimand.outcome_table),
        },
        "interval": {
            "centre_points": interval.centre_points,
            "half_width_points": interval.half_width_points,
            "block_count": interval.block_count,
            "degenerate": interval.degenerate,
        },
    }
    if not population_valid:
        # No p-value anywhere: an invalidated population has no inferential result
        # to withhold selectively.
        payload["interpretation_label"] = "diagnostic"
        payload["diagnostic_note"] = _DIAGNOSTIC_NOTE
        payload["randomization_test"] = "withheld: the primary population is invalid"
        return ProtocolReport(payload=payload)
    payload["interpretation_label"] = "inferential"
    payload["alpha"] = _ALPHA
    payload["p_value"] = test.p_value
    payload["randomization_test"] = {
        "statistic": test.statistic,
        "reference_method": test.reference_method,
        "allocation_space_size": test.allocation_space_size,
        "at_or_beyond": test.at_or_beyond,
    }
    return ProtocolReport(payload=payload)


def _outcome_rows(table: dict[tuple[bool, bool, bool], int]) -> list[dict[str, object]]:
    """All eight A/B/C cells in a stable, JSON-expressible order."""
    return [
        {"anchor_pass": a, "treatment_pass": b, "repeat_pass": c, "count": table[(a, b, c)]}
        for a in (True, False)
        for b in (True, False)
        for c in (True, False)
    ]


def build_estimand(outcomes: tuple[CaseOutcome, ...]) -> RepeatEstimand:
    """``D_i = V_i - R_i`` with ``V_i = 1[A != B]`` and ``R_i = 1[A != C]``.

    Both comparisons share the anchor. A per-arm anchor is a different quantity
    and is refused, not silently substituted.
    """
    outcomes = tuple(outcomes)
    if not outcomes:
        raise BenchEvalError("an estimand needs at least one case outcome")
    table = {(a, b, c): 0 for a in (True, False) for b in (True, False) for c in (True, False)}
    seen: set[str] = set()
    v_count = r_count = 0
    for outcome in outcomes:
        if outcome.instance_id in seen:
            raise BenchEvalError(
                f"{outcome.instance_id} appears more than once; one case contributes once",
            )
        seen.add(outcome.instance_id)
        table[(outcome.anchor_pass, outcome.treatment_pass, outcome.repeat_pass)] += 1
        v_count += int(outcome.anchor_pass != outcome.treatment_pass)
        r_count += int(outcome.anchor_pass != outcome.repeat_pass)
    return RepeatEstimand(
        v_count=v_count,
        r_count=r_count,
        mean_d=(v_count - r_count) / len(outcomes),
        outcome_table=table,
    )


def slot_differences(
    outcomes: tuple[CaseOutcome, ...], slots: dict[str, tuple[str, str, str]]
) -> tuple[int, ...]:
    """Per-block anchor disagreements in chronological slot 2 minus slot 3.

    The order of the result follows the order of ``slots``, so it lines up with
    the schedule's own assignment order and therefore with ``z``.
    """
    if not slots:
        raise BenchEvalError("slot differences need at least one scheduled block")
    grouped: dict[str, list[CaseOutcome]] = {}
    for outcome in outcomes:
        if outcome.block_id not in slots:
            raise BenchEvalError(
                f"{outcome.instance_id} names unscheduled block {outcome.block_id}"
            )
        grouped.setdefault(outcome.block_id, []).append(outcome)
    diffs: list[int] = []
    for block_id, arms in slots.items():
        if len(arms) != 3 or sorted(arms) != sorted(_ARMS) or arms[0] != "anchor":
            raise BenchEvalError(f"{block_id}: slots must be the three arms, anchor first")
        cases = grouped.get(block_id)
        if not cases:
            raise BenchEvalError(f"{block_id}: no case outcomes for a scheduled block")
        diffs.append(_disagreements(cases, arms[1]) - _disagreements(cases, arms[2]))
    return tuple(diffs)


def _disagreements(cases: list[CaseOutcome], arm: str) -> int:
    """How many of ``cases`` disagree with their shared anchor under ``arm``."""
    attribute = f"{arm}_pass"
    return sum(int(getattr(case, attribute) != case.anchor_pass) for case in cases)


# --- the counted reference distribution --------------------------------------------


def subset_sum_counts(values: tuple[int, ...], choose: int) -> dict[int, int]:
    """Number of ``choose``-element subsets of ``values`` for each subset sum.

    The reference distribution follows from this count because, for balanced
    ``z``, ``T(z) = 2 * sum(selected) - sum(all)``.
    """
    values = tuple(values)
    if choose < 0 or choose > len(values):
        raise BenchEvalError(f"cannot choose {choose} of {len(values)} blocks")
    table: list[dict[int, int]] = [{} for _ in range(choose + 1)]
    table[0][0] = 1
    for value in values:
        for taken in range(min(choose, len(table) - 1) - 1, -1, -1):
            source = table[taken]
            if not source:
                continue
            target = table[taken + 1]
            for total, ways in source.items():
                key = total + value
                target[key] = target.get(key, 0) + ways
    return table[choose]


def randomization_p_value(slot_diffs: tuple[int, ...], z: tuple[int, ...]) -> RandomizationResult:
    """Two-sided exact p-value over the balanced allocation space.

    The randomization unit is the block. Permuting individual cases, or treating
    each logical attempt as an independent question, is refused: the reference
    set is the balanced relabelling of whole blocks and nothing else.
    """
    slot_diffs = tuple(slot_diffs)
    z = tuple(z)
    if len(slot_diffs) != len(z):
        raise BenchEvalError("every block needs exactly one assignment sign")
    if not slot_diffs:
        raise BenchEvalError("the reference space needs at least one block")
    if set(z) - {1, -1} or len(z) % 2 or sum(z) != 0:
        raise BenchEvalError(
            "the reference set is the balanced allocation space: z must be +-1 and sum to zero",
        )
    counts = subset_sum_counts(slot_diffs, len(slot_diffs) // 2)
    space = sum(counts.values())
    total = sum(slot_diffs)
    statistic = abs(sum(zi * ei for zi, ei in zip(z, slot_diffs, strict=True)))
    at_or_beyond = sum(
        ways for selected, ways in counts.items() if abs(2 * selected - total) >= statistic
    )
    return RandomizationResult(
        statistic=statistic,
        reference_method="exact-counting",
        allocation_space_size=space,
        at_or_beyond=at_or_beyond,
        # An exactly counted space uses the plain fraction; a ``(hits+1)/(draws+1)``
        # correction exists to tame sampling error there is none of here.
        p_value=at_or_beyond / space,
    )


# --- the observable interval, frozen -----------------------------------------------


def observable_block_interval(
    slot_diffs: tuple[int, ...], z: tuple[int, ...], *, per_block: int, rounds: int = 1
) -> BlockInterval:
    """Two-sided 95% t-interval over ``b_j = z_j * e_j / (per_block * rounds)``.

    Centre is the mean of ``b_j``; the spread is the sample standard deviation
    with ``ddof=1``; the half-width is ``t(0.975, B-1) * sd / sqrt(B)``. Both are
    reported in percentage points. A zero-variance cohort yields a degenerate
    interval of half-width zero, flagged rather than raised.

    ``e_j`` is observable: the anchor disagreements in chronological slot 2 minus
    slot 3. Multiplying by ``z_j`` returns it to the assigned frame. A latent
    per-block effect the analyst cannot see is never an input.
    """
    slot_diffs = tuple(slot_diffs)
    z = tuple(z)
    if len(slot_diffs) != len(z):
        raise BenchEvalError("every block needs exactly one assignment sign")
    if set(z) - {1, -1}:
        raise BenchEvalError("assignment signs must be +1 or -1")
    if len(slot_diffs) < 2:
        raise BenchEvalError("a sample interval needs at least two blocks")
    if per_block < 1 or rounds < 1:
        raise BenchEvalError("per_block and rounds must be positive")
    blocks = len(slot_diffs)
    # Exact rationals: the divisor is a small integer and the oracle is exact, so
    # there is no reason to accumulate float error before the square root.
    estimates = [
        Fraction(zi * ei, per_block * rounds) for zi, ei in zip(z, slot_diffs, strict=True)
    ]
    centre = sum(estimates, Fraction(0)) / blocks
    variance = sum(((x - centre) ** 2 for x in estimates), Fraction(0)) / (blocks - 1)
    degenerate = variance == 0
    half = (
        0.0
        if degenerate
        else _student_t_critical(blocks - 1) * math.sqrt(float(variance)) / math.sqrt(blocks)
    )
    return BlockInterval(
        centre_points=float(centre) * 100,
        half_width_points=half * 100,
        block_count=blocks,
        degenerate=degenerate,
    )


# --- numerical qualification constraints -------------------------------------------


def admissible_effect_sd_bound(
    cases: tuple[tuple[float, float], ...], *, mean_effect: float
) -> float:
    """Largest per-case effect sd a cohort of ``(q_i, d_i)`` pairs can carry, in points.

    The bound is ``sqrt(mean(q_i**2) - mean_effect**2)``. The constant-``q`` form
    ``sqrt(q**2 - delta**2)`` is wrong whenever ``q_i`` varies and understates the
    achievable heterogeneity -- that was F006.
    """
    cases = tuple(cases)
    if not cases:
        raise BenchEvalError("an admissibility bound needs at least one case")
    mean_q_squared = sum(q * q for q, _ in cases) / len(cases)
    return math.sqrt(max(mean_q_squared - mean_effect**2, 0.0)) * 100


def check_cohort_admissible(cases: tuple[tuple[float, float], ...], *, mean_effect: float) -> None:
    """Refuse a cohort whose probabilities or declared mean are not what they claim.

    Requires ``|d_i| <= q_i <= 1`` for every case and a cohort mean effect equal
    to ``mean_effect``. Constrains the numerical qualification only; it says
    nothing about what an observed study result must equal.
    """
    cases = tuple(cases)
    if not cases:
        raise BenchEvalError("an admissibility check needs at least one case")
    for q, d in cases:
        if q < -1e-12 or q > 1 + 1e-12:
            raise BenchEvalError(f"discordance {q} is not a probability")
        if abs(d) > q + 1e-12:
            raise BenchEvalError(
                f"case ({q}, {d}) violates |d_i| <= q_i; q is a constraint, not a free parameter",
            )
    realized = sum(d for _, d in cases) / len(cases)
    if abs(realized - mean_effect) > 1e-9:
        raise BenchEvalError(
            f"cohort mean effect {realized!r} is not the declared {mean_effect!r}",
        )


__all__ = [
    "REPEAT_CONTRACT_VERSION",
    "BlockInterval",
    "CaseOutcome",
    "ProtocolReport",
    "RandomizationResult",
    "ReferenceMethod",
    "RepeatEstimand",
    "admissible_effect_sd_bound",
    "build_estimand",
    "build_protocol_report",
    "check_cohort_admissible",
    "observable_block_interval",
    "randomization_p_value",
    "slot_differences",
    "subset_sum_counts",
]
