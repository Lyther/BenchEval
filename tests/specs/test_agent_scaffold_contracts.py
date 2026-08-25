"""RED contracts for cataloged-but-non-executable agent scaffolds.

MOMO remains discoverable so its integration contract can evolve, but it is not
an admitted v1 execution profile.  Every run path must therefore reject it
before a charged launch or output reservation.  These tests use only the real
typed catalog, planner, and CLI dry-run path; no test substitute is involved.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from bencheval.agent_registry import load_agent_catalog
from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import BenchEvalError


def test_momo_is_cataloged_as_scaffold_not_admitted() -> None:
    profile = load_agent_catalog().by_id("momo")

    assert profile.admission == "scaffold"


def test_planner_rejects_momo_before_producing_a_run_plan() -> None:
    with pytest.raises(BenchEvalError, match=r"momo.*scaffold|scaffold.*momo"):
        plan_control_plane(
            benchmark_id="terminal-bench",
            slice_id="smoke-5",
            runtime_id=None,
            agent_id="momo",
            model_id="kimi-k2.7-code",
        )


def test_cli_dry_run_rejects_momo_without_materializing_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "must-not-exist.jsonl"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "bencheval.cli",
            "run",
            "terminal-bench/smoke-5",
            "--agent",
            "momo",
            "--model",
            "kimi-k2.7-code",
            "--dry-run",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    assert proc.returncode == 1
    assert "scaffold" in proc.stderr.lower()
    assert not output.exists()
