"""Behavioral tests for run-owned descriptor helpers."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
