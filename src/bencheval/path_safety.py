"""Path and identifier guards for repo-scoped operations."""

from __future__ import annotations

import re
from pathlib import Path

from bencheval.exceptions import BenchEvalError

_INSTANCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def ensure_resolved_under_root(path: Path, root: Path, *, what: str) -> Path:
    """Return ``path`` if it resolves inside ``root``; otherwise raise."""
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except (OSError, ValueError) as e:
        raise BenchEvalError(f"{what} path is invalid: {path!s}") from e
    try:
        resolved.relative_to(root_resolved)
    except ValueError as e:
        raise BenchEvalError(f"{what} escapes repository root: {resolved}") from e
    return resolved


def validate_control_plane_instance_id(instance_id: str) -> str:
    if not instance_id or not _INSTANCE_ID_PATTERN.fullmatch(instance_id):
        raise BenchEvalError(
            f"invalid instance_id {instance_id!r}: use alphanumeric, dot, underscore, hyphen",
        )
    return instance_id
