"""Behavioral tests for run-owned descriptor helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from bencheval.exceptions import BenchEvalError
from bencheval.run_isolation import claim_exclusive_run_artifacts


def test_read_json_at_nofollow_does_not_block_on_fifo(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "verdict.json")
    script = """
import os
import sys
from pathlib import Path

from bencheval.run_isolation import open_owned_dir_fd, read_json_at_nofollow

root = Path(sys.argv[1])
descriptor = open_owned_dir_fd(root, role="test artifact directory")
try:
    assert read_json_at_nofollow(descriptor, "verdict.json") == (False, None)
finally:
    os.close(descriptor)
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=1.0,
    )

    assert result.returncode == 0, result.stderr


def test_artifacts_claim_rejects_dangling_symlink_as_bencheval_error(tmp_path: Path) -> None:
    target = tmp_path / "artifacts"
    target.symlink_to(tmp_path / "missing", target_is_directory=True)

    with pytest.raises(BenchEvalError, match="symlink"):
        claim_exclusive_run_artifacts(target)


def test_run_cli_reports_dangling_artifacts_symlink_without_traceback(tmp_path: Path) -> None:
    target = tmp_path / "artifacts"
    target.symlink_to(tmp_path / "missing", target_is_directory=True)
    evidence = tmp_path / "evidence.jsonl"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bencheval.cli",
            "run",
            "terminal-bench/tier1-one",
            "--runtime",
            "codex-cli",
            "--model",
            "kimi-k2.7-code",
            "--provider",
            "bytellm",
            "--output",
            str(evidence),
            "--artifacts-dir",
            str(target),
            "--yes",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=10.0,
    )

    assert result.returncode == 1
    assert result.stderr.startswith("error:")
    assert "Traceback" not in result.stderr
    assert not evidence.exists()
    assert not (tmp_path / "missing").exists()
