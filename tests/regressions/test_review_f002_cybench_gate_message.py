"""F002: cybench non-execute failure must mention execution_support / metadata_only."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_cybench_run_stderr_documents_non_executable() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [
            "uv",
            "run",
            "--no-sync",
            "bencheval",
            "run",
            "--benchmark",
            "cybench",
            "--slice",
            "cybench-smoke-5",
            "--runtime",
            "native-api",
            "--model",
            "openai/gpt-test",
            "--output",
            "/tmp/bencheval-cybench-gate-test.jsonl",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode != 0
    combined = (proc.stdout + proc.stderr).lower()
    assert "metadata_only" in combined or "execution_support" in combined
