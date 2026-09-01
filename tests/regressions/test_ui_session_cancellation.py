"""Regression for charged-child cancellation ownership.

SUBSTITUTE_JUSTIFICATION
- substitute: ``_group_with_term_resistant_child``,
  ``_leader_exits_with_term_resistant_child``,
  ``_terminal_worker_with_term_resistant_child``, a deliberately closed Pipe, manually injected
  JSON result frames, and a monkeypatched ``os.killpg`` ``PermissionError``
- replaces: the charged ``_run_worker`` process/pipe boundary, including a harness child that
  ignores SIGTERM, a worker that exits before its result frame, and a malformed result frame
- necessity: a real provider/harness cannot safely and deterministically be forced to ignore TERM,
  crash before its result frame, violate the private worker-frame schema, retain a descendant after
  a terminal frame, or produce the platform-specific zombie-group permission failure on demand
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


def _leader_exits_with_term_resistant_child(pid_file: str) -> None:
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
    deadline = time.monotonic() + 5
    while not Path(pid_file).exists() and time.monotonic() < deadline:
        time.sleep(0.01)


def _terminal_worker_with_term_resistant_child(
    pid_file: str,
    sender,
    terminal_frame: str,
) -> None:
    os.setsid()
    sender.send(json.dumps({"event": "ready"}))
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
    deadline = time.monotonic() + 5
    while not Path(pid_file).exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    sender.send(terminal_frame)
    sender.close()
    time.sleep(60)


def _exit_immediately() -> None:
    return


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


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="POSIX process groups required")
def test_cancel_kills_descendant_after_group_leader_exits(tmp_path: Path) -> None:
    pid_file = tmp_path / "orphan.pid"
    process = multiprocessing.get_context("spawn").Process(
        target=_leader_exits_with_term_resistant_child,
        args=(str(pid_file),),
    )
    process.start()
    deadline = time.monotonic() + 10
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text())
    process.join(timeout=5)
    assert not process.is_alive()

    controller = RunSessionController()
    controller._process = process
    controller._process_group_id = process.pid
    controller._state = "failed"
    controller.cancel()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.killpg(process.pid, signal.SIGKILL)
        pytest.fail("harness descendant survived after its worker leader exited")


def test_snapshot_contains_process_group_permission_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process = multiprocessing.get_context("spawn").Process(target=_exit_immediately)
    process.start()
    process.join(timeout=5)
    assert not process.is_alive()

    controller = RunSessionController()
    controller._process = process
    controller._process_group_id = process.pid
    controller._state = "failed"
    controller._message = "worker failed"

    def denied_killpg(group_id: int, sig: int) -> None:
        _ = group_id, sig
        raise PermissionError("process group cannot be signalled")

    monkeypatch.setattr(os, "killpg", denied_killpg)
    view = controller.snapshot()
    assert view.state == "failed"
    assert "cleanup incomplete" in view.message
    assert controller._process_group_id is None


@pytest.mark.parametrize("terminal_ok", [False, True])
@pytest.mark.skipif(not hasattr(os, "killpg"), reason="POSIX process groups required")
def test_terminal_frame_cleans_owned_descendant_before_clearing_group(
    tmp_path: Path,
    terminal_ok: bool,
) -> None:
    child_file = tmp_path / f"terminal-child-{terminal_ok}.pid"
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    run_id = "run-terminal-frame"
    terminal_frame = (
        {
            "ok": True,
            "value": {
                "run_id": run_id,
                "benchmark_id": "gpqa-diamond",
                "slice_id": "smoke",
                "runtime_id": None,
                "model_id": "gpt-5.4-2026-03-05",
                "evidence_path": "/tmp/evidence.jsonl",
                "passed_count": 0,
                "failed_count": 1,
                "outcome": "finished",
            },
        }
        if terminal_ok
        else {"ok": False, "error": "worker failed"}
    )
    worker = context.Process(
        target=_terminal_worker_with_term_resistant_child,
        args=(str(child_file), sender, json.dumps(terminal_frame)),
    )
    worker.start()
    sender.close()
    deadline = time.monotonic() + 10
    while not child_file.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert child_file.exists()
    child_pid = int(child_file.read_text())
    controller = RunSessionController()
    controller._process = worker
    controller._receiver = receiver
    controller._state = "running"
    controller._run_id = run_id
    try:
        deadline = time.monotonic() + 10
        view = controller.snapshot()
        while view.state == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
            view = controller.snapshot()
        assert view.state == ("completed" if terminal_ok else "failed")
        assert controller._process_group_id is None
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("terminal worker frame left its harness descendant alive")
    finally:
        if worker.is_alive():
            os.killpg(worker.pid, signal.SIGKILL)
        worker.join(timeout=5)


def test_run_id_is_visible_before_worker_result() -> None:
    controller = RunSessionController()
    request = __import__(
        "bencheval.application.dto",
        fromlist=["PlanRequestDTO"],
    ).PlanRequestDTO(
        benchmark_id="missing-benchmark",
        slice_id="missing-slice",
        model_id="missing-model",
    )
    try:
        view = controller.start(request, fingerprint="sha256:stale")
        assert view.run_id is not None
        assert view.run_id.startswith("run-")
        run_id = view.run_id
        deadline = time.monotonic() + 10
        while controller.snapshot().state == "running" and time.monotonic() < deadline:
            time.sleep(0.02)
        assert controller.snapshot().run_id == run_id
    finally:
        controller.cancel()


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
