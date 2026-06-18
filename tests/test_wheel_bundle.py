"""Wheel install + BENCHEVAL_HOME bundle (release prove path)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from bencheval.paths import repo_root, validate_config_bundle


def _copy_control_plane_bundle(src_repo: Path, dest: Path) -> None:
    for sub in ("runtimes", "slices", "manifests"):
        shutil.copytree(src_repo / "config" / sub, dest / "config" / sub, dirs_exist_ok=True)
    for name in ("benchmarks.yaml", "models.yaml", "suites.yaml"):
        src = src_repo / "config" / name
        if src.is_file():
            shutil.copy2(src, dest / "config" / name)


def test_bencheval_home_wheel_cli_reads_catalog(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    bundle = tmp_path / "bundle"
    (bundle / "config").mkdir(parents=True)
    _copy_control_plane_bundle(repo, bundle)
    validate_config_bundle(bundle)
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "from bencheval.benchmark_registry import load_benchmark_catalog; "
            "c=load_benchmark_catalog(); assert len(c.benchmarks) > 0",
        ],
        env={**os.environ, "BENCHEVAL_HOME": str(bundle)},
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


def test_bencheval_home_supports_dry_run_planner(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    bundle = tmp_path / "bundle"
    (bundle / "config").mkdir(parents=True)
    _copy_control_plane_bundle(repo, bundle)
    dry_run_cmd = (
        "from bencheval.cli import main; "
        "raise SystemExit(main(['run', '--benchmark', 'bfcl-v4', '--slice', 'smoke-5', "
        "'--runtime', 'native-api', '--model', 'openai/gpt-test', '--dry-run']))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", dry_run_cmd],
        env={**os.environ, "BENCHEVAL_HOME": str(bundle)},
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_repo_root_matches_checkout_marker() -> None:
    root = repo_root()
    assert (root / "config" / "benchmarks.yaml").is_file()
