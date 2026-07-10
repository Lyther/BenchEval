"""Wheel install + BENCHEVAL_HOME bundle (release prove path)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv required to build/install the wheel")
def test_wheel_install_is_self_contained_without_bencheval_home(tmp_path: Path) -> None:
    """F003 acceptance: from a clean cwd, installed wheel only, no BENCHEVAL_HOME —
    ``bencheval benchmark list`` works because config ships as package data."""
    repo = Path(__file__).resolve().parents[1]
    wheel_dir = tmp_path / "wheels"
    wheel_dir.mkdir()
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    wheels = list(wheel_dir.glob("*.whl"))
    assert wheels, "no wheel was built"

    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    env = {k: v for k, v in os.environ.items() if k != "BENCHEVAL_HOME"}
    run = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            str(wheels[0]),
            "bencheval",
            "benchmark",
            "list",
            "--execution-support",
            "executable_adapter",
            "--format",
            "json",
        ],
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    payload = json.loads(run.stdout)
    ids = {b["id"] for b in payload["benchmarks"]}
    assert ids  # non-empty: the bundled catalog resolved
    assert all(b["execution_support"] == "executable_adapter" for b in payload["benchmarks"])
    assert {"terminal-bench", "swe-bench-verified", "bfcl-v4"} <= ids
