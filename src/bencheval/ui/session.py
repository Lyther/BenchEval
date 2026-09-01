"""Single active run-session controller with process-group cancellation."""

from __future__ import annotations

import atexit
import json
import multiprocessing
import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing.connection import Connection

from bencheval.application.dto import PlanRequestDTO, RunExecutionDTO
from bencheval.application.operations import OperatorOperations
from bencheval.exceptions import BenchEvalError
from bencheval.redaction import env_secret_values, redact_string


def _run_worker(request_json: str, fingerprint: str, sender: Connection) -> None:
    try:
        if hasattr(os, "setsid"):
            os.setsid()
        sender.send(json.dumps({"event": "ready"}))
        result = OperatorOperations().start(
            PlanRequestDTO.model_validate_json(request_json),
            expected_fingerprint=fingerprint,
        )
        sender.send(json.dumps({"ok": True, "value": result.model_dump(mode="json")}))
    except BaseException as exc:
        message = redact_string(
            str(exc).splitlines()[0][:500],
            extra_secrets=env_secret_values(),
        )
        sender.send(json.dumps({"ok": False, "error": message}))
    finally:
        sender.close()


@dataclass(frozen=True, slots=True)
class RunSessionView:
    state: str
    run_id: str | None
    started_at: str | None
    message: str
    result: RunExecutionDTO | None


class RunSessionController:
    """Own exactly one mutating run child; durable state remains elsewhere."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: multiprocessing.Process | None = None
        self._receiver: Connection | None = None
        self._state = "idle"
        self._started_at: str | None = None
        self._message = "No active run"
        self._result: RunExecutionDTO | None = None

    def start(self, request: PlanRequestDTO, *, fingerprint: str) -> RunSessionView:
        with self._lock:
            self._refresh_locked()
            if self._process is not None and self._process.is_alive():
                raise BenchEvalError("another run session is already active")
            context = multiprocessing.get_context("spawn")
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=_run_worker,
                args=(request.model_dump_json(), fingerprint, sender),
                daemon=False,
            )
            process.start()
            sender.close()
            self._process = process
            self._receiver = receiver
            self._state = "running"
            self._started_at = datetime.now(tz=UTC).isoformat()
            self._message = "Run launched; refresh never relaunches it"
            self._result = None
            return self._view_locked()

    def snapshot(self) -> RunSessionView:
        with self._lock:
            self._refresh_locked()
            return self._view_locked()

    def cancel(self) -> RunSessionView:
        with self._lock:
            self._refresh_locked()
            process = self._process
            if process is None or not process.is_alive():
                return self._view_locked()
            try:
                group_signalled = False
                if hasattr(os, "killpg"):
                    try:
                        # A pre-setsid child has no process group matching its PID,
                        # so this is safe even before the ready event is consumed.
                        os.killpg(process.pid, signal.SIGTERM)
                        group_signalled = True
                    except ProcessLookupError:
                        pass
                if not group_signalled:
                    process.terminate()
                grace_deadline = time.monotonic() + 2
                process.join(timeout=2)
                remaining = grace_deadline - time.monotonic()
                if group_signalled and remaining > 0:
                    time.sleep(remaining)
                if group_signalled:
                    try:
                        # Escalate the group even when its leader already exited;
                        # resistant descendants may still own the group.
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif process.is_alive():
                    process.kill()
                process.join(timeout=2)
            finally:
                self._state = "cancelled"
                self._message = "Cancellation requested; inspect durable evidence before retrying"
            return self._view_locked()

    def _refresh_locked(self) -> None:
        while self._receiver is not None and self._receiver.poll():
            try:
                payload = json.loads(self._receiver.recv())
                if not isinstance(payload, dict):
                    raise ValueError("run process frame must be an object")
                if payload.get("event") == "ready":
                    continue
                if payload.get("ok") is True:
                    self._result = RunExecutionDTO.model_validate(payload["value"])
                    self._state = "completed"
                    self._message = f"Run {self._result.run_id} completed"
                else:
                    self._state = "failed"
                    self._message = str(payload.get("error", "run failed"))
            except (EOFError, KeyError, OSError, TypeError, ValueError):
                self._receiver.close()
                self._receiver = None
                if self._state == "running":
                    self._state = "failed"
                    self._message = "Run process exited without a result; inspect durable artifacts"
                break
            self._receiver.close()
            self._receiver = None
        if self._process is not None and not self._process.is_alive():
            self._process.join(timeout=0)
            if self._state == "running":
                self._state = "failed"
                self._message = "Run process exited without a result; inspect durable artifacts"

    def _view_locked(self) -> RunSessionView:
        return RunSessionView(
            state=self._state,
            run_id=self._result.run_id if self._result else None,
            started_at=self._started_at,
            message=self._message,
            result=self._result,
        )


RUN_SESSION = RunSessionController()
atexit.register(RUN_SESSION.cancel)
