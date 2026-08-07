"""Run lifecycle helpers for manifest-driven single-task execution."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CleanupPolicy = Literal["never", "on-success", "always"]
RunMode = Literal["batch", "single"]

TRANSIENT_ARTIFACT_DIR_NAMES: frozenset[str] = frozenset(
    {
        "agent-workspace",
        "harbor-package",
        "materialized-workspace",
    },
)


@dataclass(frozen=True, slots=True)
class CleanupReport:
    policy: CleanupPolicy
    attempted: bool
    removed_paths: tuple[str, ...]


def _is_symlink(path: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def cleanup_transient_artifacts(
    run_artifacts_dir: Path,
    *,
    policy: CleanupPolicy,
    primary_pass: bool,
) -> CleanupReport:
    """Remove BenchEval-owned transient directories for one task run.

    Uses a non-resolving absolute root so a symlinked run directory cannot
    redirect ``rmtree`` into an external tree.
    """
    if policy == "never":
        return CleanupReport(policy=policy, attempted=False, removed_paths=())
    if policy == "on-success" and not primary_pass:
        return CleanupReport(policy=policy, attempted=False, removed_paths=())

    root = Path(os.path.abspath(str(run_artifacts_dir)))
    if _is_symlink(root) or not root.is_dir():
        return CleanupReport(policy=policy, attempted=True, removed_paths=())

    removed: list[str] = []
    for name in sorted(TRANSIENT_ARTIFACT_DIR_NAMES):
        target = root / name
        if _is_symlink(target):
            target.unlink()
        elif target.is_dir() and not _is_symlink(target):
            shutil.rmtree(target)
        else:
            continue
        removed.append(str(target))
    return CleanupReport(
        policy=policy,
        attempted=True,
        removed_paths=tuple(removed),
    )
