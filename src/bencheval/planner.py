"""Offline dry-run planner for BenchEval vNext suites."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bencheval.task_contract import BudgetClass, ExecutionProfile, TaskContract
from bencheval.task_registry import index_tasks, load_task_contract, tasks_for_suite

BUDGET_CLASS_DEFAULTS: dict[BudgetClass, dict[str, float | int]] = {
    "B0": {"max_cost_usd": 0.05, "max_wall_clock_sec": 60, "max_steps": 4},
    "B1": {"max_cost_usd": 0.25, "max_wall_clock_sec": 180, "max_steps": 10},
    "B2": {"max_cost_usd": 2.00, "max_wall_clock_sec": 300, "max_steps": 20},
    "B3": {"max_cost_usd": 0.0, "max_wall_clock_sec": 0, "max_steps": 0},
}


@dataclass(frozen=True, slots=True)
class BudgetClassInfo:
    name: BudgetClass
    max_cost_usd: float
    max_wall_clock_sec: int
    max_steps: int


@dataclass(frozen=True, slots=True)
class PlannedTask:
    task_id: str
    title: str
    category: str
    execution_profiles: tuple[ExecutionProfile, ...]
    budget_class: BudgetClass
    max_cost_usd: float
    max_wall_clock_sec: int
    max_steps: int
    is_calibration: bool
    is_stretch: bool


@dataclass(frozen=True, slots=True)
class DryRunPlan:
    suite: str
    model_id: str
    tasks: tuple[PlannedTask, ...]
    budget_classes: tuple[BudgetClass, ...]
    execution_profiles: tuple[ExecutionProfile, ...]
    total_max_cost_usd: float
    total_max_wall_clock_sec: int
    requires_harbor: bool
    requires_sandbox: bool
    includes_calibration: bool
    includes_stretch: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "suite": self.suite,
            "model_id": self.model_id,
            "task_count": len(self.tasks),
            "tasks": [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "category": t.category,
                    "execution_profiles": list(t.execution_profiles),
                    "budget_class": t.budget_class,
                    "max_cost_usd": t.max_cost_usd,
                    "max_wall_clock_sec": t.max_wall_clock_sec,
                    "max_steps": t.max_steps,
                    "is_calibration": t.is_calibration,
                    "is_stretch": t.is_stretch,
                }
                for t in self.tasks
            ],
            "budget_classes": list(self.budget_classes),
            "execution_profiles": list(self.execution_profiles),
            "total_max_cost_usd": self.total_max_cost_usd,
            "total_max_wall_clock_sec": self.total_max_wall_clock_sec,
            "requires_harbor": self.requires_harbor,
            "requires_sandbox": self.requires_sandbox,
            "includes_calibration": self.includes_calibration,
            "includes_stretch": self.includes_stretch,
        }


def budget_class_info(name: BudgetClass) -> BudgetClassInfo:
    defaults = BUDGET_CLASS_DEFAULTS[name]
    return BudgetClassInfo(
        name=name,
        max_cost_usd=float(defaults["max_cost_usd"]),
        max_wall_clock_sec=int(defaults["max_wall_clock_sec"]),
        max_steps=int(defaults["max_steps"]),
    )


def _plan_task(contract: TaskContract) -> PlannedTask:
    profiles = tuple(contract.execution.profiles())
    return PlannedTask(
        task_id=contract.task.id,
        title=contract.task.title,
        category=contract.task.category,
        execution_profiles=profiles,
        budget_class=contract.constraints.budget_class,
        max_cost_usd=contract.constraints.max_cost_usd,
        max_wall_clock_sec=contract.constraints.max_wall_clock_sec,
        max_steps=contract.constraints.max_steps,
        is_calibration=contract.is_calibration,
        is_stretch=contract.is_stretch,
    )


def plan_dry_run(
    *,
    suite: str,
    model_id: str,
    tasks_root: Path | None = None,
) -> DryRunPlan:
    task_ids = tasks_for_suite(suite)
    task_index = index_tasks(tasks_root)
    planned: list[PlannedTask] = []
    all_profiles: set[ExecutionProfile] = set()
    all_budgets: set[BudgetClass] = set()
    total_cost = 0.0
    total_wall = 0
    requires_harbor = False
    requires_sandbox = False
    includes_calibration = False
    includes_stretch = False

    for task_id in task_ids:
        if task_id not in task_index:
            raise ValueError(
                f"task {task_id} listed in suite {suite} but not found under tasks root",
            )
        contract = load_task_contract(task_index[task_id])
        pt = _plan_task(contract)
        planned.append(pt)
        all_profiles.update(pt.execution_profiles)
        all_budgets.add(pt.budget_class)
        total_cost += pt.max_cost_usd
        total_wall += pt.max_wall_clock_sec
        if "E2" in pt.execution_profiles:
            requires_harbor = True
        if any(p in pt.execution_profiles for p in ("E1", "E2")):
            requires_sandbox = True
        includes_calibration = includes_calibration or pt.is_calibration
        includes_stretch = includes_stretch or pt.is_stretch

    return DryRunPlan(
        suite=suite,
        model_id=model_id,
        tasks=tuple(planned),
        budget_classes=tuple(sorted(all_budgets)),
        execution_profiles=tuple(sorted(all_profiles)),
        total_max_cost_usd=round(total_cost, 6),
        total_max_wall_clock_sec=total_wall,
        requires_harbor=requires_harbor,
        requires_sandbox=requires_sandbox,
        includes_calibration=includes_calibration,
        includes_stretch=includes_stretch,
    )
