"""Resolve selftest task paths (P9.2: config/selftest with legacy fallback)."""

from __future__ import annotations

from pathlib import Path

from bencheval.task_registry import selftest_tasks_root


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def core8_dir() -> Path:
    return selftest_tasks_root() / "core-8"


def core16_dir() -> Path:
    return selftest_tasks_root() / "core-16"


def core8_workspace(task_id: str) -> Path:
    return core8_dir() / "workspaces" / task_id


def core16_workspace(task_id: str) -> Path:
    return core16_dir() / "workspaces" / task_id
