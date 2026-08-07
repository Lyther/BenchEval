"""Exclusive run-output ownership helpers (evidence + artifact trees)."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from bencheval.exceptions import BenchEvalError

# Authoritative score/verdict filenames adapters may consume from a prior run.
AUTHORITATIVE_ARTIFACT_NAMES: frozenset[str] = frozenset(
    {
        "verifier.json",
        "result.json",
        "verdict.json",
        "official_scores.json",
        "gpqa_summary.json",
        "hle_summary.json",
    },
)


def _is_symlink_path(path: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def reject_symlink_path(path: Path, *, role: str) -> None:
    """Fail closed when ``path`` itself is a symlink (do not follow)."""
    if _is_symlink_path(path):
        raise BenchEvalError(f"{role} must not be a symlink: {path}")


def claim_exclusive_evidence_path(path: Path) -> None:
    """Refuse reuse of an existing evidence JSONL path."""
    target = path.expanduser()
    if target.exists():
        raise BenchEvalError(
            f"evidence output already exists (exclusive write required): {target}",
        )


def claim_exclusive_run_artifacts(path: Path) -> None:
    """Require a missing or empty run-artifacts directory; reject symlink roots."""
    target = path.expanduser()
    if target.exists():
        reject_symlink_path(target, role="run artifacts directory")
        if not target.is_dir():
            raise BenchEvalError(f"run artifacts path exists but is not a directory: {target}")
        if any(target.iterdir()):
            raise BenchEvalError(
                "run artifacts directory is not empty "
                f"(exclusive run ownership required): {target}",
            )
        return
    target.mkdir(parents=True, exist_ok=False)


def prepare_instance_artifacts_dir(
    instance_dir: Path,
    *,
    clear_names: frozenset[str] = AUTHORITATIVE_ARTIFACT_NAMES,
) -> Path:
    """Create an instance dir and clear authoritative leftover score artifacts."""
    reject_symlink_path(instance_dir, role="instance artifacts directory")
    if instance_dir.exists() and not instance_dir.is_dir():
        raise BenchEvalError(f"instance artifacts path is not a directory: {instance_dir}")
    instance_dir.mkdir(parents=True, exist_ok=True)
    reject_symlink_path(instance_dir, role="instance artifacts directory")
    for name in sorted(clear_names):
        target = instance_dir / name
        if not target.exists() and not _is_symlink_path(target):
            continue
        if _is_symlink_path(target) or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
    return instance_dir


__all__ = [
    "AUTHORITATIVE_ARTIFACT_NAMES",
    "claim_exclusive_evidence_path",
    "claim_exclusive_run_artifacts",
    "prepare_instance_artifacts_dir",
    "reject_symlink_path",
]
