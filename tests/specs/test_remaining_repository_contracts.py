"""RED contracts for admission, dependency, CI, and operator-document integrity."""

from __future__ import annotations

import os
import re
import shutil
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.version import Version

from bencheval.adapter_admission import assess_gpqa_admission
from bencheval.benchmark_registry import (
    clear_benchmark_catalog_cache,
    load_benchmark_catalog,
)
from bencheval.slice_manifest import clear_slice_manifest_cache

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Minimum non-vulnerable releases returned by OSV for the 2026-08-06 lock snapshot.
# This is a remediation floor, not a claim that later versions are vulnerability-free.
_OSV_FIXED_FLOORS = (
    ("aiohttp", "3.14.3"),
    ("click", "8.3.3"),
    ("cryptography", "50.0.0"),
    ("idna", "3.15"),
    ("litellm", "1.84.0"),
    ("mcp", "1.28.1"),
    ("pillow", "12.3.0"),
    ("pydantic-settings", "2.14.2"),
    ("pyjwt", "2.13.0"),
    ("python-multipart", "0.0.31"),
    ("soupsieve", "2.8.4"),
    ("starlette", "1.3.1"),
    ("urllib3", "2.7.0"),
)


def _locked_versions() -> dict[str, tuple[Version, ...]]:
    lock = tomllib.loads((_REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    by_name: dict[str, list[Version]] = {}
    for package in lock["package"]:
        by_name.setdefault(package["name"], []).append(Version(package["version"]))
    return {name: tuple(versions) for name, versions in by_name.items()}


@pytest.mark.parametrize(("package", "fixed_floor"), _OSV_FIXED_FLOORS)
def test_eval_lock_does_not_resolve_known_vulnerable_versions(
    package: str,
    fixed_floor: str,
) -> None:
    versions = _locked_versions().get(package, ())

    # Removing an affected transitive dependency is as valid as upgrading it.
    if not versions:
        return
    assert all(version >= Version(fixed_floor) for version in versions), (
        f"{package} resolves {versions}; OSV fixed floor is {fixed_floor}"
    )


def test_admission_pass_requires_every_declared_catalog_and_artifact_gate(
    tmp_path: Path,
) -> None:
    """A disposable real config bundle exercises a safe negative catalog state."""
    bundle = tmp_path / "bencheval-bundle"
    shutil.copytree(_REPO_ROOT / "config", bundle / "config")

    catalog_path = bundle / "config" / "benchmarks.yaml"
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    gpqa = next(row for row in catalog["benchmarks"] if row["id"] == "gpqa-diamond")
    gpqa["executable"] = False
    catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")

    source_dir = bundle / "src" / "bencheval"
    source_dir.mkdir(parents=True)
    for filename in ("gpqa_adapter.py", "control_plane_executor.py"):
        shutil.copy2(_REPO_ROOT / "src" / "bencheval" / filename, source_dir / filename)

    previous_home = os.environ.get("BENCHEVAL_HOME")
    os.environ["BENCHEVAL_HOME"] = str(bundle)
    try:
        clear_benchmark_catalog_cache()
        clear_slice_manifest_cache()
        report = assess_gpqa_admission(repo_root=bundle)
    finally:
        clear_benchmark_catalog_cache()
        clear_slice_manifest_cache()
        if previous_home is None:
            os.environ.pop("BENCHEVAL_HOME", None)
        else:
            os.environ["BENCHEVAL_HOME"] = previous_home

    checks = {name: ok for name, ok, _ in report.checks}
    assert checks["catalog_executable"] is False
    assert checks["typed_slice_smoke"] is True
    assert checks["gpqa_adapter_module"] is True
    assert checks["control_plane_executor"] is True
    assert report.passed is False


def test_roadmap_admitted_benchmarks_match_executable_catalog() -> None:
    roadmap = (_REPO_ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
    match = re.search(r"^\| Benchmarks \|(?P<ids>[^|]+)\|$", roadmap, flags=re.MULTILINE)
    assert match is not None
    documented = set(re.findall(r"`([^`]+)`", match.group("ids")))
    executable = {entry.id for entry in load_benchmark_catalog().benchmarks if entry.executable}

    assert documented == executable


def test_operator_docs_do_not_reference_removed_runtime_or_manifest_paths() -> None:
    runtime_doc = (_REPO_ROOT / "docs" / "context" / "runtime-invocation-contracts.md").read_text(
        encoding="utf-8"
    )
    explicit_runtime_paths = re.findall(
        r"`(config/runtimes/[a-z0-9-]+\.yaml)`",
        runtime_doc,
    )
    assert explicit_runtime_paths
    assert all((_REPO_ROOT / path).is_file() for path in explicit_runtime_paths), (
        explicit_runtime_paths
    )

    manifest_doc = (_REPO_ROOT / "results" / "manifests" / "README.md").read_text(
        encoding="utf-8",
    )
    assert "config/manifests/" not in manifest_doc
    assert "--manifest" not in manifest_doc


def test_ci_installs_and_checks_the_eval_dependency_surface() -> None:
    workflow = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8",
    )
    assert "--extra eval" in workflow or "--all-extras" in workflow


def test_ci_runs_a_locked_dependency_advisory_scan() -> None:
    workflow = (
        (_REPO_ROOT / ".github" / "workflows" / "ci.yml")
        .read_text(
            encoding="utf-8",
        )
        .lower()
    )
    scanners = ("pip-audit", "osv-scanner", "uv audit")

    assert any(scanner in workflow for scanner in scanners)
