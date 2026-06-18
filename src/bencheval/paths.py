"""Resolve BenchEval config/data root for editable installs and wheel-only deployments."""

from __future__ import annotations

import os
from pathlib import Path

from bencheval.exceptions import BenchEvalError

_BENCHEVAL_HOME_ENV = "BENCHEVAL_HOME"
_CONFIG_MARKER = Path("config") / "benchmarks.yaml"

# Minimum tree for v0.3 control-plane CLI (catalog, planner, dry-run).
_BUNDLE_REQUIRED_DIRS: tuple[Path, ...] = (
    Path("config") / "runtimes",
    Path("config") / "slices",
    Path("config") / "manifests",
)


def _has_config_marker(root: Path) -> bool:
    return (root / _CONFIG_MARKER).is_file()


def validate_config_bundle(root: Path) -> None:
    """Raise when ``root`` cannot satisfy control-plane config reads."""
    resolved = root.resolve()
    if not _has_config_marker(resolved):
        marker = _CONFIG_MARKER.as_posix()
        raise BenchEvalError(f"config bundle missing marker file {marker} under {resolved}")
    for rel in _BUNDLE_REQUIRED_DIRS:
        path = resolved / rel
        if not path.is_dir():
            raise BenchEvalError(f"config bundle missing required directory {rel.as_posix()}")
        yaml_files = [
            p for p in path.iterdir() if p.is_file() and p.suffix.lower() in (".yaml", ".yml")
        ]
        if rel == Path("config") / "runtimes" and not yaml_files:
            raise BenchEvalError(
                f"config bundle {rel.as_posix()} must contain at least one runtime profile",
            )
        if rel == Path("config") / "slices" and not yaml_files:
            raise BenchEvalError(
                f"config bundle {rel.as_posix()} must contain at least one slice manifest",
            )


def _walk_up_for_config(start: Path) -> Path | None:
    current = start.resolve()
    for _ in range(32):
        if _has_config_marker(current):
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def repo_root() -> Path:
    """Directory containing the BenchEval config bundle (project or ``BENCHEVAL_HOME``).

    Resolution order:

    1. ``BENCHEVAL_HOME`` when it passes :func:`validate_config_bundle`.
    2. Walk upward from ``Path.cwd()`` when the marker file exists.
    3. Layout-relative path next to the installed ``bencheval`` package (editable checkout).
    4. Fall back to package-parent layout (may error on missing config at use site).
    """
    env_home = os.environ.get(_BENCHEVAL_HOME_ENV, "").strip()
    if env_home:
        candidate = Path(env_home).expanduser().resolve()
        try:
            validate_config_bundle(candidate)
        except BenchEvalError as exc:
            raise BenchEvalError(
                f"{_BENCHEVAL_HOME_ENV}={env_home!r}: {exc}",
            ) from exc
        return candidate

    from_cwd = _walk_up_for_config(Path.cwd())
    if from_cwd is not None:
        validate_config_bundle(from_cwd)
        return from_cwd

    package_root = Path(__file__).resolve().parent
    layout_guess = package_root.parents[2]
    if _has_config_marker(layout_guess):
        validate_config_bundle(layout_guess)
        return layout_guess.resolve()

    return layout_guess.resolve()


__all__ = ["repo_root", "validate_config_bundle"]
