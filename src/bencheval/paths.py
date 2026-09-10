"""Resolve BenchEval config/data root for editable installs and wheel-only deployments."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from bencheval.exceptions import BenchEvalError

_BENCHEVAL_HOME_ENV = "BENCHEVAL_HOME"
_CONFIG_MARKER = Path("config") / "benchmarks.yaml"
_BUNDLE_REQUIRED_FILES: tuple[Path, ...] = (
    Path("config") / "models.yaml",
    Path("config") / "bfcl-v4-supported-models.yaml",
)

# Minimum tree for the control-plane CLI (catalog, planner, dry-run, preflight):
# agents are a launch surface since CF2, so a bundle without them cannot plan
# or preflight an agent selection.
_BUNDLE_REQUIRED_DIRS: tuple[Path, ...] = (
    Path("config") / "runtimes",
    Path("config") / "providers",
    Path("config") / "slices",
    Path("config") / "agents",
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
        if rel == Path("config") / "providers" and not yaml_files:
            raise BenchEvalError(
                f"config bundle {rel.as_posix()} must contain at least one provider profile",
            )
        if rel == Path("config") / "slices" and not yaml_files:
            raise BenchEvalError(
                f"config bundle {rel.as_posix()} must contain at least one slice manifest",
            )
        if rel == Path("config") / "agents" and not yaml_files:
            raise BenchEvalError(
                f"config bundle {rel.as_posix()} must contain at least one agent profile",
            )
    for rel in _BUNDLE_REQUIRED_FILES:
        if not (resolved / rel).is_file():
            raise BenchEvalError(f"config bundle missing required file {rel.as_posix()}")


def _walk_up_for_config(start: Path) -> Path | None:
    current = start.resolve()
    for _ in range(32):
        if _has_config_marker(current):
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def _bundled_config_root() -> Path | None:
    """Config tree shipped inside the wheel as package data (``bencheval/_bundled``).

    Present only in a built/installed wheel (see ``force-include`` in pyproject);
    absent in an editable checkout, where the live ``config/`` tree is used instead.
    """
    try:
        from importlib.resources import files

        root = Path(str(files("bencheval") / "_bundled"))
    except (ModuleNotFoundError, TypeError, ValueError, OSError):
        return None
    return root if _has_config_marker(root) else None


def repo_root() -> Path:
    """Directory containing the BenchEval config bundle (project or ``BENCHEVAL_HOME``).

    Resolution order:

    1. ``BENCHEVAL_HOME`` when it passes :func:`validate_config_bundle`.
    2. Walk upward from ``Path.cwd()`` when the marker file exists.
    3. Layout-relative path next to the installed ``bencheval`` package (editable checkout).
    4. Config packaged inside the wheel (``bencheval/_bundled``) — the one-click
       non-editable install path: no ``BENCHEVAL_HOME``, no exported bundle.
    5. Fall back to package-parent layout (may error on missing config at use site).
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

    # src layout: <checkout>/src/bencheval/paths.py -> parents[1] is the checkout.
    package_root = Path(__file__).resolve().parent
    layout_guess = package_root.parents[1]
    if _has_config_marker(layout_guess):
        validate_config_bundle(layout_guess)
        return layout_guess.resolve()

    bundled = _bundled_config_root()
    if bundled is not None:
        validate_config_bundle(bundled)
        return bundled

    return layout_guess.resolve()


ConfigSource = Literal["bencheval_home", "wheel", "checkout", "config_tree"]


def is_project_checkout(root: Path) -> bool:
    """True when ``root`` carries the project and its lockfile (preparation can run there)."""
    return (root / "pyproject.toml").is_file() and (root / "uv.lock").is_file()


def describe_config_root() -> tuple[Path, ConfigSource]:
    """The resolved config root and how it was found.

    ``bencheval_home`` (the override), ``wheel`` (config packaged inside the
    installed wheel), ``checkout`` (a project tree with pyproject.toml and
    uv.lock), or ``config_tree`` (a bare config tree found from the working
    directory or the package layout).
    """
    root = repo_root()
    env_home = os.environ.get(_BENCHEVAL_HOME_ENV, "").strip()
    if env_home and Path(env_home).expanduser().resolve() == root:
        return root, "bencheval_home"
    bundled = _bundled_config_root()
    if bundled is not None and bundled.resolve() == root.resolve():
        return root, "wheel"
    if is_project_checkout(root):
        return root, "checkout"
    return root, "config_tree"


__all__ = [
    "ConfigSource",
    "describe_config_root",
    "is_project_checkout",
    "repo_root",
    "validate_config_bundle",
]
