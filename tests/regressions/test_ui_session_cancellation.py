"""Regression for charged-child cancellation ownership.

SUBSTITUTE_JUSTIFICATION
- substitute: ``_group_with_term_resistant_child``, a deliberately closed Pipe, and manually
  injected JSON success frames with a missing or invalid ``RunExecutionDTO`` value
- replaces: the charged ``_run_worker`` process/pipe boundary, including a harness child that
  ignores SIGTERM, a worker that exits before its result frame, and a malformed result frame
- necessity: a real provider/harness cannot safely and deterministically be forced to ignore TERM,
  crash before its result frame, or violate the private worker-frame schema
- real-option: a charged run is nondeterministic, could leave billable work behind, and the real
  worker is designed never to emit a malformed success frame
- proof-limit: proves local POSIX process-group termination and defensive frame parsing only, not
  adapter cleanup, provider billing, or live native cancellation
- real-proof: BLOCKED on a future operator-host charged worker success/cancel run with retained
  cleanup evidence; BenchEval has no non-charged benchmark worker path
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import multiprocessing
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bencheval.ui.session import RunSessionController


def _group_with_term_resistant_child(pid_file: str) -> None:
    os.setsid()
    subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import os,signal,time,pathlib;"
                "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
                f"pathlib.Path({pid_file!r}).write_text(str(os.getpid()));"
                "time.sleep(60)"
            ),
        ],
        start_new_session=False,
    )
    time.sleep(60)


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="POSIX process groups required")
def test_cancel_kills_term_resistant_descendant(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    process = multiprocessing.get_context("spawn").Process(
        target=_group_with_term_resistant_child,
        args=(str(pid_file),),
    )
    process.start()
    deadline = time.monotonic() + 10
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text())

    controller = RunSessionController()
    controller._process = process
    controller._state = "running"
    assert controller.cancel().state == "cancelled"
    assert controller.snapshot().state == "cancelled"

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.kill(child_pid, signal.SIGKILL)
        pytest.fail("TERM-resistant harness descendant survived UI cancellation")


def test_snapshot_recovers_from_worker_pipe_eof() -> None:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    sender.close()
    controller = RunSessionController()
    controller._receiver = receiver
    controller._state = "cancelled"
    view = controller.snapshot()
    assert view.state == "cancelled"
    assert controller._receiver is None


@pytest.mark.parametrize(
    "frame",
    [
        {"ok": True},
        {"ok": True, "value": {"not": "a RunExecutionDTO"}},
    ],
)
def test_snapshot_rejects_malformed_success_frame(frame: dict[str, object]) -> None:
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    sender.send(json.dumps(frame))
    sender.close()
    controller = RunSessionController()
    controller._receiver = receiver
    controller._state = "running"
    view = controller.snapshot()
    assert view.state == "failed"
    assert "without a result" in view.message
    assert controller._receiver is None
