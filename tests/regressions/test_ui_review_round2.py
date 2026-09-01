"""Regressions from the independent operator-console readiness review.

SUBSTITUTE_JUSTIFICATION
- substitute: ``browser_recorder.py`` selected through the standard ``BROWSER`` environment hook
- replaces: the desktop browser application launched by Python's real ``webbrowser`` integration
- necessity: the test must capture the exact URL NiceGUI asks the OS to open without opening a
  user-owned browser window during pytest
- real-option: a real browser launch was used by the independent reviewer but cannot expose its
  launch argument deterministically to an automated assertion
- proof-limit: proves the default CLI/server/browser-launch URL only; it does not prove rendering
- real-proof: ``uv run bencheval ui`` in the local Chromium acceptance journey
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


def _free_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def test_default_ui_opens_the_capability_url(tmp_path: Path) -> None:
    recorded = tmp_path / "opened-url.txt"
    recorder = tmp_path / "browser_recorder.py"
    recorder.write_text(
        "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])\n",
        encoding="utf-8",
    )
    port = _free_loopback_port()
    env = os.environ.copy()
    env.pop("PYTEST_CURRENT_TEST", None)
    env["BROWSER"] = f"{sys.executable} {recorder} {recorded} %s"
    process = subprocess.Popen(
        [sys.executable, "-m", "bencheval.cli", "ui", "--port", str(port)],
        cwd=Path(__file__).parents[2],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 15
        while not recorded.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert recorded.exists(), process.stderr.read() if process.poll() is not None else "no URL"
        opened = recorded.read_text(encoding="utf-8")
        assert opened.startswith(f"http://127.0.0.1:{port}/?cap=")
        assert opened.count("http://") == 1
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
