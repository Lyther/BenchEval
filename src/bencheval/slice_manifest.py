"""Typed slice manifest manager.

A :class:`~bencheval.domain.SliceManifest` wraps a plain-text instance manifest
(``config/manifests/*.txt``) with budget, purpose, and caveat labels. The instance
list itself is still read by :func:`bencheval.manifest.read_manifest_task_ids`;
this module adds the typed envelope and validates that the declared instance count
fits the budget.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError

from bencheval.domain import SliceManifest
from bencheval.exceptions import BenchEvalError
from bencheval.manifest import read_manifest_task_ids
from bencheval.paths import repo_root as _repo_root


def default_slices_dir() -> Path:
    return _repo_root() / "config" / "slices"


def list_slice_manifest_paths(dir_path: Path | str | None = None) -> tuple[Path, ...]:
    """Return sorted ``*.yaml`` slice manifest paths under ``config/slices``."""
    d = Path(dir_path) if dir_path is not None else default_slices_dir()
    if not d.is_dir():
        return ()
    return tuple(
        sorted(
            p.resolve()
            for p in d.iterdir()
            if p.is_file() and p.suffix.lower() in (".yaml", ".yml")
        ),
    )


def slices_for_benchmark(
    benchmark_id: str,
    dir_path: Path | str | None = None,
) -> tuple[SliceManifest, ...]:
    """Load all typed slice manifests whose ``slice.benchmark_id`` matches."""
    out: list[SliceManifest] = []
    for path in list_slice_manifest_paths(dir_path):
        manifest = load_slice_manifest(path)
        if manifest.slice.benchmark_id == benchmark_id:
            out.append(manifest)
    return tuple(out)


def _resolve_instances_source(slice_yaml_path: Path, instances_source: str) -> Path:
    """Resolve ``instances_source`` relative to the slice YAML or the repo manifests dir."""
    candidate = (slice_yaml_path.parent / instances_source).resolve()
    if candidate.is_file():
        return candidate
    manifests_candidate = (_repo_root() / instances_source).resolve()
    if manifests_candidate.is_file():
        return manifests_candidate
    # Allow a bare filename resolved under config/manifests.
    bare = _repo_root() / "config" / "manifests" / Path(instances_source).name
    if bare.is_file():
        return bare
    raise BenchEvalError(
        f"slice {slice_yaml_path.name}: instances_source {instances_source!r} not found",
    )


@lru_cache(maxsize=64)
def _load_slice_manifest_cached(path_str: str) -> SliceManifest:
    p = Path(path_str)
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError as e:
        raise BenchEvalError(f"cannot decode slice manifest {p} as UTF-8: {e}") from e
    except OSError as e:
        raise BenchEvalError(f"cannot read slice manifest {p}: {e}") from e
    except yaml.YAMLError as e:
        raise BenchEvalError(f"{p.name}: invalid YAML: {e}") from e
    try:
        manifest = SliceManifest.model_validate(raw)
    except ValidationError as e:
        raise BenchEvalError(f"{p.name}: {e}") from e
    instances_path = _resolve_instances_source(p, manifest.slice.instances_source)
    try:
        instance_ids = read_manifest_task_ids(instances_path)
    except BenchEvalError as e:
        raise BenchEvalError(f"{p.name}: cannot read instances_source: {e}") from e
    if len(instance_ids) > manifest.budget.max_instances:
        raise BenchEvalError(
            f"{p.name}: instance count {len(instance_ids)} exceeds "
            f"budget.max_instances {manifest.budget.max_instances}",
        )
    return manifest


def clear_slice_manifest_cache() -> None:
    _load_slice_manifest_cached.cache_clear()


def load_slice_manifest(path: Path | str) -> SliceManifest:
    """Load and validate a typed slice manifest YAML."""
    return _load_slice_manifest_cached(str(Path(path).resolve()))


def slice_instance_ids(manifest: SliceManifest, slice_yaml_path: Path | str) -> tuple[str, ...]:
    """Return the ordered instance ids referenced by a slice manifest."""
    instances_path = _resolve_instances_source(
        Path(slice_yaml_path),
        manifest.slice.instances_source,
    )
    return read_manifest_task_ids(instances_path)


def resolve_instances_source_path(slice_yaml_path: Path | str, instances_source: str) -> Path:
    """Public wrapper for manifest path resolution (dry-run fingerprints)."""
    return _resolve_instances_source(Path(slice_yaml_path), instances_source)


__all__ = [
    "default_slices_dir",
    "list_slice_manifest_paths",
    "load_slice_manifest",
    "resolve_instances_source_path",
    "slice_instance_ids",
    "slices_for_benchmark",
]
