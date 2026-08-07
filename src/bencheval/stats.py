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
    ci_low = delta - math.sqrt((p_b - lo_b) ** 2 + (hi_c - p_c) ** 2)
    ci_high = delta + math.sqrt((hi_b - p_b) ** 2 + (p_c - lo_c) ** 2)
    return (ci_low, ci_high)


__all__ = ["Z_95", "newcombe_diff", "wilson"]
