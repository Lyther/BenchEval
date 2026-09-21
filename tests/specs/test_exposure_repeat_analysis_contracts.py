"""X6.2 RED contracts: shared-anchor estimand, exact randomization test, observable interval.

Every expected value below is computed independently of the implementation —
by exhaustive enumeration, by exact rational arithmetic, or from a fixed
Student-t critical value — so these are oracles, not restatements of whatever
the code happens to do.

All of them are expected to FAIL until X6.3 implements
``bencheval.exposure_repeat``; see ``docs/context/bfcl-repeat-spec.md``.
"""

from __future__ import annotations

import math
from fractions import Fraction
from itertools import combinations

import pytest

from bencheval.exceptions import BenchEvalError
from bencheval.exposure_repeat import (
    CaseOutcome,
    admissible_effect_sd_bound,
    build_estimand,
    build_protocol_report,
    check_cohort_admissible,
    observable_block_interval,
    randomization_p_value,
    subset_sum_counts,
)

# t(0.975, 3) from the Student-t table; fixed here so the oracle does not
# borrow the implementation's critical-value rule.
_T_975_DF3 = 3.1824463052837078
_C40_20 = 137_846_528_820


def _enumerate_p(e: tuple[int, ...], z: tuple[int, ...]) -> Fraction:
    """Exhaustive two-sided randomization p-value over balanced allocations."""
    blocks = len(e)
    observed = abs(sum(zi * ei for zi, ei in zip(z, e, strict=True)))
    space = at_or_beyond = 0
    for picks in combinations(range(blocks), blocks // 2):
        chosen = set(picks)
        value = sum(ei if j in chosen else -ei for j, ei in enumerate(e))
        space += 1
        at_or_beyond += abs(value) >= observed
    return Fraction(at_or_beyond, space)


def _balanced(blocks: int, positives: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(1 if j in positives else -1 for j in range(blocks))


# --- A-01, A-02: shared-anchor arithmetic ------------------------------------------


def _outcome(idx: int, a: bool, b: bool, c: bool) -> CaseOutcome:
    return CaseOutcome(
        f"multiple_{idx}", "block-01", anchor_pass=a, treatment_pass=b, repeat_pass=c
    )


def test_estimand_compares_both_arms_against_the_shared_anchor() -> None:
    """A-01/A-02. V and R share the anchor, and all eight cells are reported."""
    outcomes = (
        _outcome(0, True, False, True),  # V=1 R=0 D=+1
        _outcome(1, True, True, False),  # V=0 R=1 D=-1
        _outcome(2, False, False, False),  # V=0 R=0 D=0
        _outcome(3, False, True, True),  # V=1 R=1 D=0
    )
    estimand = build_estimand(outcomes)
    assert estimand.v_count == 2
    assert estimand.r_count == 2
    assert estimand.mean_d == pytest.approx(0.0)
    assert len(estimand.outcome_table) == 8, "all eight A/B/C cells, including the empty ones"
    assert sum(estimand.outcome_table.values()) == len(outcomes)
    assert estimand.outcome_table[(True, False, True)] == 1
    assert estimand.outcome_table[(True, True, True)] == 0


@pytest.mark.parametrize(
    ("outcomes", "v_count", "r_count", "mean_d"),
    [
        # Treatment disagrees more than the repeat: a positive excess.
        (
            (
                _outcome(0, True, False, True),
                _outcome(1, True, False, True),
                _outcome(2, True, False, True),
                _outcome(3, True, True, True),
            ),
            3,
            0,
            0.75,
        ),
        # The repeat disagrees more: a negative excess, which must not be clamped.
        (
            (
                _outcome(0, True, True, False),
                _outcome(1, True, True, False),
                _outcome(2, True, True, True),
                _outcome(3, True, True, True),
            ),
            0,
            2,
            -0.5,
        ),
    ],
)
def test_estimand_reports_nonzero_excess_in_both_directions(
    outcomes: tuple[CaseOutcome, ...], v_count: int, r_count: int, mean_d: float
) -> None:
    """A-01. An implementation that always returns zero cannot satisfy these."""
    estimand = build_estimand(outcomes)
    assert estimand.v_count == v_count
    assert estimand.r_count == r_count
    assert estimand.mean_d == pytest.approx(mean_d)
    assert sum(estimand.outcome_table.values()) == len(outcomes)


def test_estimand_refuses_a_duplicate_case() -> None:
    """A-02. One case cannot contribute twice to a disagreement count."""
    with pytest.raises(BenchEvalError):
        build_estimand((_outcome(0, True, False, True), _outcome(0, True, False, True)))


# --- A-08, A-09, E-07: what the report must keep apart ----------------------------


def test_report_separates_the_tested_null_from_the_estimated_quantity() -> None:
    """A-08. Sharp-null exactness is not average-effect validity, and says so."""
    outcomes = (
        _outcome(0, True, False, True),
        _outcome(1, True, False, True),
        _outcome(2, True, True, True),
        _outcome(3, True, True, True),
    )
    estimand = build_estimand(outcomes)
    z = _balanced(10, (0, 1, 2, 3, 4))
    test = randomization_p_value((3, 1, 0, 2, 1, -1, 0, -2, -1, -3), z)
    interval = observable_block_interval((3, 1, 0, 2, 1, -1, 0, -2, -1, -3), z, per_block=10)
    report = build_protocol_report(estimand, test, interval, population_valid=True)

    payload = report.payload
    assert payload["tested_null"] != payload["estimated_quantity"]
    assert "sharp" in str(payload["tested_null"]).lower()
    assert "average" in str(payload["estimated_quantity"]).lower()
    assert "not" in str(payload["hypothesis_boundary"]).lower()


def test_report_carries_the_precision_wording_not_a_promise() -> None:
    """A-09. Five points is a median planning half-width, stated as such."""
    z = _balanced(10, (0, 1, 2, 3, 4))
    diffs = (3, 1, 0, 2, 1, -1, 0, -2, -1, -3)
    report = build_protocol_report(
        build_estimand((_outcome(0, True, False, True),)),
        randomization_p_value(diffs, z),
        observable_block_interval(diffs, z, per_block=10),
        population_valid=True,
    )
    note = str(report.payload["precision_note"]).lower()
    assert "median" in note
    assert "planning" in note
    assert "not a promise" in note or "not a guarantee" in note


def test_invalid_population_yields_a_diagnostic_record_with_no_headline() -> None:
    """E-07. A diagnostic explains the absence of a result; it never carries one."""
    z = _balanced(10, (0, 1, 2, 3, 4))
    diffs = (3, 1, 0, 2, 1, -1, 0, -2, -1, -3)
    report = build_protocol_report(
        build_estimand((_outcome(0, True, False, True),)),
        randomization_p_value(diffs, z),
        observable_block_interval(diffs, z, per_block=10),
        population_valid=False,
    )
    payload = report.payload
    assert payload["interpretation_label"] == "diagnostic"
    assert "p_value" not in payload
    assert payload.get("registers_pass") is False


# --- O-01: the assignment-space oracles --------------------------------------------


@pytest.mark.parametrize(
    ("e", "positives"),
    [
        ((3, -1, 0, 2, 5, -4, 1, 0, 2, -2), (0, 2, 4, 6, 8)),
        ((7, 7, -3, 0, 1, 1, -9, 4, 4, -1), (1, 3, 5, 7, 9)),
        ((1, -1, 2, -2, 3, -3, 4, -4, 5, -5), (0, 1, 2, 3, 4)),
        ((0, 0, 0, 1, -1, 2, -2, 6, -6, 0), (5, 6, 7, 8, 9)),
    ],
)
def test_counted_reference_equals_exhaustive_enumeration(
    e: tuple[int, ...], positives: tuple[int, ...]
) -> None:
    """O-01. Counting must retain every allocation's multiplicity, exactly."""
    z = _balanced(len(e), positives)
    expected = _enumerate_p(e, z)
    result = randomization_p_value(e, z)
    assert Fraction(result.at_or_beyond, result.allocation_space_size) == expected
    assert result.p_value == pytest.approx(float(expected), abs=1e-15)


def test_zero_statistic_oracle_gives_certainty() -> None:
    """O-01. Every allocation ties the observed zero, so p is exactly 1."""
    result = randomization_p_value((0,) * 10, _balanced(10, (0, 1, 2, 3, 4)))
    assert result.p_value == 1.0
    assert result.at_or_beyond == result.allocation_space_size == 252


def test_ten_block_extreme_oracle_gives_two_over_252() -> None:
    """O-01. A uniform per-block excess is beaten only by itself and its mirror."""
    z = _balanced(10, (0, 2, 4, 6, 8))
    result = randomization_p_value(tuple(4 * zi for zi in z), z)
    assert result.at_or_beyond == 2
    assert result.allocation_space_size == 252
    assert result.p_value == pytest.approx(2 / 252, abs=1e-15)


def test_forty_block_extreme_oracle_uses_the_whole_allocation_space() -> None:
    """A-04/O-01. The selected design's space is C(40,20), counted not sampled."""
    z = _balanced(40, tuple(range(0, 40, 2)))
    result = randomization_p_value(tuple(3 * zi for zi in z), z)
    assert result.allocation_space_size == _C40_20
    assert result.at_or_beyond == 2
    assert result.p_value == pytest.approx(2 / _C40_20, rel=1e-12)


def test_pooled_and_per_round_designs_give_their_two_exact_answers() -> None:
    """O-01. The F001 counterexample, both halves asserted: 1/18 against 1/3.

    Identical latent block scores. The declared design draws a fresh balanced
    assignment per round and enumerates the 36-assignment product space; the
    design the round-1 probes simulated reuses one assignment across both rounds
    and enumerates 6. The observed statistic is 8 either way.
    """
    latent = ((3, 1, 0, 0), (0, 2, -1, 3))

    # Declared: fresh assignment per round.
    z_fresh = ((1, 1, -1, -1), (1, -1, 1, -1))
    observed = tuple(
        tuple(z * d for z, d in zip(zr, dr, strict=True))
        for zr, dr in zip(z_fresh, latent, strict=True)
    )
    statistic = abs(sum(sum(dr) for dr in latent))
    assert statistic == 8
    product = [
        abs(
            sum(v if j in p1 else -v for j, v in enumerate(observed[0]))
            + sum(v if j in p2 else -v for j, v in enumerate(observed[1]))
        )
        for p1 in combinations(range(4), 2)
        for p2 in combinations(range(4), 2)
    ]
    fresh_p = Fraction(sum(1 for v in product if v >= statistic), len(product))
    assert fresh_p == Fraction(1, 18)

    # Simulated: one shared assignment, rounds summed first.
    z_shared = (1, 1, -1, -1)
    pooled = tuple(z * (latent[0][j] + latent[1][j]) for j, z in enumerate(z_shared))
    assert pooled == (3, 3, 1, -3)
    pooled_p = _enumerate_p(pooled, z_shared)
    assert pooled_p == Fraction(1, 3)
    assert pooled_p != fresh_p

    # The production counting primitive must reproduce the declared answer.
    counts1, counts2 = subset_sum_counts(observed[0], 2), subset_sum_counts(observed[1], 2)
    total1, total2 = sum(observed[0]), sum(observed[1])
    space = sum(counts1.values()) * sum(counts2.values())
    assert space == 36
    at_or_beyond = sum(
        w1 * w2
        for s1, w1 in counts1.items()
        for s2, w2 in counts2.items()
        if abs((2 * s1 - total1) + (2 * s2 - total2)) >= statistic
    )
    assert Fraction(at_or_beyond, space) == fresh_p


# --- A-03, A-05, A-06: the unit and the label --------------------------------------


def test_randomization_unit_is_the_block_not_the_case() -> None:
    """A-03. A case-level reference set is a different, larger space."""
    z = _balanced(10, (0, 1, 2, 3, 4))
    e = (5, 4, 3, 2, 1, -1, -2, -3, -4, -5)
    result = randomization_p_value(e, z)
    assert result.allocation_space_size == 252, "block-level space, not 2**1200"


def test_reference_method_is_labelled_exact_counting() -> None:
    """A-05/A-06. No sampled distribution may be reported, or mislabelled."""
    z = _balanced(10, (0, 1, 2, 3, 4))
    result = randomization_p_value((1, 2, 3, 4, 5, 5, 4, 3, 2, 1), z)
    assert result.reference_method == "exact-counting"
    # An exactly counted space uses the plain fraction, never a plus-one form.
    assert result.p_value == pytest.approx(
        result.at_or_beyond / result.allocation_space_size, abs=1e-15
    )


def test_unbalanced_assignment_is_refused() -> None:
    """A-03. The declared space is the balanced one; anything else is a refusal."""
    with pytest.raises(BenchEvalError):
        randomization_p_value((1, 2, 3, 4), (1, 1, 1, -1))


# --- A-07, O-02: the observable interval, frozen -----------------------------------


def test_observable_interval_matches_its_independent_oracle() -> None:
    """A-07/O-02. Fixed drift example; centre and half-width computed by hand.

    z = (+1, +1, -1, -1), latent block effects D = (3, 1, -2, 0), slot drift
    (2, 0, 0, 0), so the observed slot differences are e = z*D + drift =
    (5, 1, 2, 0) and b_j = z_j*e_j/10 = (0.5, 0.1, -0.2, 0.0).
    """
    z = (1, 1, -1, -1)
    e = (5, 1, 2, 0)
    b = [Fraction(zi * ei, 10) for zi, ei in zip(z, e, strict=True)]
    centre = sum(b) / len(b)
    variance = sum((x - centre) ** 2 for x in b) / (len(b) - 1)
    expected_centre = float(centre) * 100
    expected_half = _T_975_DF3 * math.sqrt(float(variance)) / math.sqrt(len(b)) * 100
    assert expected_centre == pytest.approx(10.0, abs=1e-12)
    assert expected_half == pytest.approx(46.8443412303, abs=1e-9)

    interval = observable_block_interval(e, z, per_block=10)
    assert interval.centre_points == pytest.approx(expected_centre, abs=1e-9)
    assert interval.half_width_points == pytest.approx(expected_half, abs=1e-9)
    assert interval.block_count == 4
    assert interval.degenerate is False


def test_observable_interval_rejects_both_ways_of_getting_it_wrong() -> None:
    """O-02. Two named wrong answers, each pinned, each distinct from the right one.

    Same cohort as above. Reading the latent block effects D gives centre 5.0
    and half-width 33.1239513442. Dropping the assignment and reading e_j raw
    gives centre 20.0. Only the observable calculation gives 10.0.
    """
    z = (1, 1, -1, -1)
    e = (5, 1, 2, 0)

    def _t_interval(values: list[Fraction]) -> tuple[float, float]:
        centre = sum(values) / len(values)
        variance = sum((x - centre) ** 2 for x in values) / (len(values) - 1)
        half = _T_975_DF3 * math.sqrt(float(variance)) / math.sqrt(len(values))
        return float(centre) * 100, half * 100

    latent_centre, latent_half = _t_interval([Fraction(d, 10) for d in (3, 1, -2, 0)])
    dropped_centre, _ = _t_interval([Fraction(ei, 10) for ei in e])
    assert latent_centre == pytest.approx(5.0, abs=1e-12)
    assert latent_half == pytest.approx(33.1239513442, abs=1e-9)
    assert dropped_centre == pytest.approx(20.0, abs=1e-12)

    interval = observable_block_interval(e, z, per_block=10)
    assert interval.centre_points == pytest.approx(10.0, abs=1e-9)
    assert interval.centre_points != pytest.approx(latent_centre, abs=1e-6)
    assert interval.half_width_points != pytest.approx(latent_half, abs=1e-6)
    assert interval.centre_points != pytest.approx(dropped_centre, abs=1e-6)


def test_zero_variance_interval_is_degenerate_not_an_error() -> None:
    """A-07. Identical block estimates give half-width zero, flagged and reported."""
    z = (1, 1, -1, -1)
    interval = observable_block_interval(tuple(2 * zi for zi in z), z, per_block=10)
    assert interval.centre_points == pytest.approx(20.0, abs=1e-12)
    assert interval.half_width_points == pytest.approx(0.0, abs=1e-12)
    assert interval.degenerate is True


def test_interval_normalizes_by_block_size_and_rounds() -> None:
    """A-07. ``b_j = z_j * e_j / (per_block * rounds)``; neither divisor is optional."""
    z = (1, 1, -1, -1)
    e = (5, 1, 2, 0)
    single = observable_block_interval(e, z, per_block=10, rounds=1)
    doubled = observable_block_interval(e, z, per_block=10, rounds=2)
    assert doubled.centre_points == pytest.approx(single.centre_points / 2, abs=1e-9)


# --- O-03: generator constraints, scoped to numerical qualification ----------------


#: The F006 counterexamples, each as ``(q_i, d_i, multiplicity)`` over 200 cases.
_COHORTS: tuple[
    tuple[str, tuple[tuple[Fraction, Fraction, int], ...], Fraction, Fraction, float], ...
] = (
    (
        "thirty-points-at-mean-q-12",
        (
            (Fraction(3, 4), Fraction(3, 4), 16),
            (Fraction(3, 4), Fraction(-3, 4), 16),
            (Fraction(0), Fraction(0), 168),
        ),
        Fraction(3, 25),
        Fraction(0),
        30.0,
    ),
    (
        "eight-point-mean-without-a-floor",
        ((Fraction(3, 10), Fraction(2, 10), 80), (Fraction(0), Fraction(0), 120)),
        Fraction(3, 25),
        Fraction(2, 25),
        9.79795897113,
    ),
    (
        "constant-q-beats-the-round-three-max",
        ((Fraction(1, 5), Fraction(1, 5), 140), (Fraction(1, 5), Fraction(-1, 5), 60)),
        Fraction(1, 5),
        Fraction(2, 25),
        18.3303027798,
    ),
)


@pytest.mark.parametrize(("name", "cases", "mean_q", "mean_effect", "effect_sd_points"), _COHORTS)
def test_heterogeneous_discordance_cohorts_are_admissible(
    name: str,
    cases: tuple[tuple[Fraction, Fraction, int], ...],
    mean_q: Fraction,
    mean_effect: Fraction,
    effect_sd_points: float,
) -> None:
    """O-03/O-04. The bound is ``Var(d) <= mean(q^2) - delta^2``, not ``q^2 - delta^2``.

    These three cohorts are the F006 counterexamples, fixed here in exact
    arithmetic so the qualification can never drift back to the constant-q
    bound. They constrain the numerical qualification only; they say nothing
    about what any observed study result must equal.
    """
    n = sum(count for _, _, count in cases)
    assert n == 200
    assert sum(q * c for q, _, c in cases) / n == mean_q
    assert sum(d * c for _, d, c in cases) / n == mean_effect
    variance = sum(d * d * c for _, d, c in cases) / n - mean_effect**2
    assert math.sqrt(float(variance)) * 100 == pytest.approx(effect_sd_points, abs=1e-8)

    # Every implied probability is a probability, exactly.
    for q, d, _ in cases:
        assert (q + d) / 2 >= 0
        assert (q - d) / 2 >= 0
        assert q <= 1
        assert abs(d) <= q

    heterogeneous_bound = sum(q * q * c for q, _, c in cases) / n - mean_effect**2
    assert variance <= heterogeneous_bound
    if name == "thirty-points-at-mean-q-12":
        assert variance == heterogeneous_bound, "this cohort attains the bound"
        assert variance > mean_q**2 - mean_effect**2, "the constant-q bound is visibly wrong"

    flat = tuple((float(q), float(d)) for q, d, count in cases for _ in range(count))
    check_cohort_admissible(flat, mean_effect=float(mean_effect))
    assert admissible_effect_sd_bound(flat, mean_effect=float(mean_effect)) == pytest.approx(
        math.sqrt(float(heterogeneous_bound)) * 100, abs=1e-8
    )


def test_cohort_with_an_impossible_effect_is_refused() -> None:
    """O-03. ``|d_i| <= q_i`` is a constraint, not something to rescale q for."""
    with pytest.raises(BenchEvalError):
        check_cohort_admissible(((0.12, 0.30), (0.12, -0.30)), mean_effect=0.0)


def test_cohort_whose_mean_misses_its_declared_target_is_refused() -> None:
    """O-03. A generator that declares a mean must hit it, not approximate it."""
    with pytest.raises(BenchEvalError):
        check_cohort_admissible(((0.20, 0.10), (0.20, 0.04)), mean_effect=0.08)
