"""Shared budget-class defaults for control-plane planning."""

from __future__ import annotations

from bencheval.domain import BudgetClass

BUDGET_CLASS_DEFAULTS: dict[BudgetClass, dict[str, float | int]] = {
    "B0": {"max_cost_usd": 0.05, "max_wall_clock_sec": 60},
    "B1": {"max_cost_usd": 0.25, "max_wall_clock_sec": 180},
    "B2": {"max_cost_usd": 2.00, "max_wall_clock_sec": 300},
    "B3": {"max_cost_usd": 0.0, "max_wall_clock_sec": 0},
}

__all__ = ["BUDGET_CLASS_DEFAULTS"]
