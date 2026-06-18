"""F004: live pilot script must exit non-zero when minimum proof is missing."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_live_pilot_exits_nonzero_without_proof() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"
    proc = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env={
            **__import__("os").environ,
            "PATH": "/usr/bin:/bin",
            "BENCHEVAL_PILOT_MODEL": "openai/gpt-test",
        },
    )
    assert proc.returncode != 0
    assert "minimum live proof not met" in (proc.stderr + proc.stdout).lower()
