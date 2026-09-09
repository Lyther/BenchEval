"""Wilson / Newcombe interval helpers for evidence compare (no scipy)."""

from __future__ import annotations

import math

Z_95 = 1.96


def wilson(k: int, n: int) -> tuple[float, float, float]:
    """Return (p_hat, lo, hi) with p_hat = k/n and (lo, hi) the Wilson score interval."""
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


def newcombe_diff(
    p_b: float,
    lo_b: float,
    hi_b: float,
    p_c: float,
    lo_c: float,
    hi_c: float,
    delta: float,
) -> tuple[float, float]:
    """Newcombe (1998) method 10 interval for ``delta = p_c - p_b``.

    The lower bound subtracts the candidate's lower Wilson distance combined
    with the baseline's upper distance; the upper bound adds the candidate's
    upper distance combined with the baseline's lower distance.
    """
    ci_low = delta - math.sqrt((p_c - lo_c) ** 2 + (hi_b - p_b) ** 2)
    ci_high = delta + math.sqrt((hi_c - p_c) ** 2 + (p_b - lo_b) ** 2)
    return (ci_low, ci_high)


def exact_binomial_two_sided(b: int, c: int) -> float:
    """Two-sided exact binomial p-value for discordant pair counts ``b`` and ``c``.

    Under the null the discordant pairs split evenly; the p-value doubles the
    lower tail of Binomial(b + c, 0.5) at min(b, c) and is capped at 1.0. Zero
    discordant pairs carry no evidence and return 1.0.
    """
    if b < 0 or c < 0:
        raise ValueError("discordant counts must be non-negative")
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2.0 * tail)


__all__ = ["Z_95", "exact_binomial_two_sided", "newcombe_diff", "wilson"]
