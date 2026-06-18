"""Agent-visible workspace staging; excludes verifier-only fixture paths."""

from __future__ import annotations

import shutil
from pathlib import Path

from bencheval.exceptions import BenchEvalError

VERIFIER_ONLY_DIR_NAMES: frozenset[str] = frozenset(
    {
        "verifier_only",
        "hidden_fixtures",
        "hidden",
        "compatibility",
    },
)

VERIFIER_ONLY_FILE_NAMES: frozenset[str] = frozenset(
    {
        "hidden_variants.json",
        "hidden_gold.json",
        "invariants.json",
    },
)

VERIFIER_ARTIFACT_FILE_NAMES: frozenset[str] = frozenset(
    {
        "verify.py",
        "reference.json",
        "negative.json",
        "reference.patch.json",
        "negative.patch.json",
    },
)


def is_verifier_only_relative_path(relative_path: str | Path) -> bool:
    rel = Path(relative_path)
    if rel.name in VERIFIER_ONLY_FILE_NAMES or rel.name in VERIFIER_ARTIFACT_FILE_NAMES:
        return True
    return any(part in VERIFIER_ONLY_DIR_NAMES for part in rel.parts)


def verifier_only_paths(workspace: Path) -> list[Path]:
    root = workspace.resolve()
    if not root.is_dir():
        raise BenchEvalError(f"workspace is not a directory: {root}")
    hidden: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if is_verifier_only_relative_path(rel):
            hidden.append(path)
    return hidden


def stage_agent_workspace(source: Path, destination: Path) -> Path:
    src = source.resolve()
    dest = destination.resolve()
    if not src.is_dir():
        raise BenchEvalError(f"workspace is not a directory: {src}")
    if dest.exists():
        if not dest.is_dir():
            raise BenchEvalError(f"staging destination exists and is not a directory: {dest}")
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)

    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if is_verifier_only_relative_path(rel):
            continue
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return dest


def assert_agent_workspace_clean(workspace: Path) -> None:
    leaked = verifier_only_paths(workspace)
    if leaked:
        sample = ", ".join(p.name for p in leaked[:3])
        raise BenchEvalError(
            f"agent workspace contains verifier-only paths ({len(leaked)} total; e.g. {sample})",
        )


def requires_agent_staging(workspace: Path) -> bool:
    root = workspace.resolve()
    if verifier_only_paths(root):
        return True
    return any((root / name).is_file() for name in VERIFIER_ARTIFACT_FILE_NAMES)


def agent_workspace_for_run(source: Path, staging_root: Path) -> Path:
    src = source.resolve()
    if not requires_agent_staging(src):
        return src
    return stage_agent_workspace(src, staging_root / "agent-workspace")
