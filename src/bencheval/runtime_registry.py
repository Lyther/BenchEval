"""Runtime registry loader for ``config/runtimes/*.yaml``.

A runtime profile declares how an agent scaffold (claude-code, codex-cli, ...)
launches noninteractively, what it can do, and what safety boundary it enforces.
The authoritative type definitions live in :mod:`bencheval.domain`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from bencheval.domain import RuntimeCatalog, RuntimeProfile
from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root as _repo_root


def default_runtimes_dir() -> Path:
    return _repo_root() / "config" / "runtimes"


def load_runtime_profile(path: Path | str) -> RuntimeProfile:
    """Load and validate a single runtime profile YAML file."""
    p = Path(path).resolve()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as e:
        raise BenchEvalError(f"cannot decode runtime profile {p} as UTF-8: {e}") from e
    except OSError as e:
        raise BenchEvalError(f"cannot read runtime profile {p}: {e}") from e
    except yaml.YAMLError as e:
        raise BenchEvalError(f"{p.name}: invalid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise BenchEvalError(f"{p.name}: runtime profile must be a YAML mapping")
    try:
        return RuntimeProfile.model_validate(raw)
    except ValidationError as e:
        raise BenchEvalError(f"{p.name}: {e}") from e


@lru_cache(maxsize=4)
def _load_runtime_catalog_cached(dir_path_str: str) -> RuntimeCatalog:
    d = Path(dir_path_str)
    if not d.is_dir():
        raise BenchEvalError(f"runtime profiles directory not found: {d}")
    profiles: list[RuntimeProfile] = []
    seen: dict[str, str] = {}
    for entry in sorted(d.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in (".yaml", ".yml"):
            continue
        profile = load_runtime_profile(entry)
        rid = profile.runtime.id
        if rid in seen:
            raise BenchEvalError(
                f"duplicate runtime id {rid!r}: {seen[rid]} and {entry.name}",
            )
        seen[rid] = entry.name
        profiles.append(profile)
    if not profiles:
        raise BenchEvalError(f"no runtime profiles found under {d}")
    return RuntimeCatalog(schema_version="0.1", runtimes=tuple(profiles))


def clear_runtime_catalog_cache() -> None:
    _load_runtime_catalog_cached.cache_clear()


def load_runtime_catalog(dir_path: Path | str | None = None) -> RuntimeCatalog:
    """Load every ``*.yaml`` runtime profile under ``dir_path`` (default config/runtimes)."""
    d = Path(dir_path) if dir_path is not None else default_runtimes_dir()
    return _load_runtime_catalog_cached(str(d.resolve()))


__all__ = [
    "default_runtimes_dir",
    "load_runtime_catalog",
    "load_runtime_profile",
]
