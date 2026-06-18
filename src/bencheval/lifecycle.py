"""Run lifecycle helpers for manifest-driven single-task execution."""

from __future__ import annotations

import shutil
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


def cleanup_transient_artifacts(
    run_artifacts_dir: Path,
    *,
    policy: CleanupPolicy,
    primary_pass: bool,
) -> CleanupReport:
    """Remove BenchEval-owned transient directories for one task run."""
    if policy == "never":
        return CleanupReport(policy=policy, attempted=False, removed_paths=())
    if policy == "on-success" and not primary_pass:
        return CleanupReport(policy=policy, attempted=False, removed_paths=())

    root = run_artifacts_dir.resolve()
    removed: list[str] = []
    for name in sorted(TRANSIENT_ARTIFACT_DIR_NAMES):
        target = root / name
        if target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
        else:
            continue
        removed.append(str(target))
    return CleanupReport(
        policy=policy,
        attempted=True,
        removed_paths=tuple(removed),
    )
