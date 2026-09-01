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
from multiprocessing.connection import wait as wait_connections

from bencheval.application.dto import PlanRequestDTO, RunExecutionDTO
from bencheval.application.operations import OperatorOperations
from bencheval.exceptions import BenchEvalError
from bencheval.ids import new_run_id
from bencheval.redaction import env_secret_values, redact_string


def _run_worker(request_json: str, fingerprint: str, run_id: str, sender: Connection) -> None:
    try:
        if hasattr(os, "setsid"):
            os.setsid()
        sender.send(json.dumps({"event": "ready"}))
        result = OperatorOperations().start(
            PlanRequestDTO.model_validate_json(request_json),
            expected_fingerprint=fingerprint,
            run_id=run_id,
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
        self._process_group_id: int | None = None
        self._receiver: Connection | None = None
        self._state = "idle"
        self._started_at: str | None = None
        self._message = "No active run"
        self._result: RunExecutionDTO | None = None
        self._run_id: str | None = None

    def start(self, request: PlanRequestDTO, *, fingerprint: str) -> RunSessionView:
        with self._lock:
            self._refresh_locked()
            if self._process is not None and self._process.is_alive():
                raise BenchEvalError("another run session is already active")
            context = multiprocessing.get_context("spawn")
            receiver, sender = context.Pipe(duplex=False)
            run_id = new_run_id()
            process = context.Process(
                target=_run_worker,
                args=(request.model_dump_json(), fingerprint, run_id, sender),
                daemon=False,
            )
            process.start()
            sender.close()
            self._process = process
            self._process_group_id = None
            self._receiver = receiver
            self._state = "running"
            self._started_at = datetime.now(tz=UTC).isoformat()
            self._message = "Run launched; refresh never relaunches it"
            self._result = None
            self._run_id = run_id
            return self._view_locked()

    def snapshot(self) -> RunSessionView:
        with self._lock:
            self._refresh_locked()
            return self._view_locked()

    def cancel(self) -> RunSessionView:
        with self._lock:
            self._refresh_locked()
            process = self._process
            process_exited = process is None or self._process_exited_without_reaping(process)
            if process_exited and self._process_group_id is None:
                return self._view_locked()
            cleanup_error = None
            try:
                cleanup_error = self._stop_owned_process_locked(process)
            finally:
                self._state = "cancelled"
                self._message = "Cancellation requested; inspect durable evidence before retrying"
                if cleanup_error is not None:
                    self._message += f"; process-group cleanup incomplete: {cleanup_error}"
            return self._view_locked()

    @staticmethod
    def _process_exited_without_reaping(process: multiprocessing.Process) -> bool:
        """Use the process sentinel so PGID cleanup happens before waitpid reaps the leader."""
        return bool(wait_connections([process.sentinel], timeout=0))

    def _stop_owned_process_locked(
        self,
        process: multiprocessing.Process | None,
    ) -> str | None:
        group_id = self._process_group_id
        group_signalled = False
        cleanup_errors: list[str] = []
        if (
            group_id is None
            and process is not None
            and process.is_alive()
            and hasattr(os, "killpg")
        ):
            # Before the ready frame is consumed, try the worker PID as its
            # setsid-created group. A pre-setsid worker has no matching group,
            # so killpg fails without signalling the console's own group.
            group_id = process.pid
        if group_id is not None and hasattr(os, "killpg"):
            try:
                os.killpg(group_id, signal.SIGTERM)
                group_signalled = True
            except OSError as exc:
                if not isinstance(exc, ProcessLookupError):
                    cleanup_errors.append(f"SIGTERM {type(exc).__name__}: {exc}")
        if not group_signalled and process is not None and process.is_alive():
            process.terminate()
        grace_deadline = time.monotonic() + 2
        if group_signalled:
            if process is not None:
                # Waiting on the sentinel observes exit without waitpid. Keep
                # the leader unreaped so its PID/PGID cannot be reused before
                # the final group signal.
                wait_connections([process.sentinel], timeout=2)
            remaining = grace_deadline - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
        elif process is not None:
            process.join(timeout=2)
        if group_signalled and group_id is not None:
            try:
                os.killpg(group_id, signal.SIGKILL)
            except OSError as exc:
                if not isinstance(exc, ProcessLookupError):
                    cleanup_errors.append(f"SIGKILL {type(exc).__name__}: {exc}")
        elif process is not None and process.is_alive():
            process.kill()
        if process is not None:
            process.join(timeout=2)
        self._process_group_id = None
        return "; ".join(cleanup_errors) or None

    def _refresh_locked(self) -> None:
        while self._receiver is not None and self._receiver.poll():
            try:
                payload = json.loads(self._receiver.recv())
                if not isinstance(payload, dict):
                    raise ValueError("run process frame must be an object")
                if payload.get("event") == "ready":
                    if self._process is not None:
                        self._process_group_id = self._process.pid
                    continue
                if payload.get("ok") is True:
                    result = RunExecutionDTO.model_validate(payload["value"])
                    if self._run_id is not None and result.run_id != self._run_id:
                        raise ValueError("run process returned a different run_id")
                    self._result = result
                    self._state = "completed"
                    self._message = f"Run {self._result.run_id} completed"
                    cleanup_error = self._stop_owned_process_locked(self._process)
                    if cleanup_error is not None:
                        self._message += f"; process-group cleanup incomplete: {cleanup_error}"
                else:
                    self._state = "failed"
                    self._message = str(payload.get("error", "run failed"))
                    cleanup_error = self._stop_owned_process_locked(self._process)
                    if cleanup_error is not None:
                        self._message += f"; process-group cleanup incomplete: {cleanup_error}"
            except (EOFError, KeyError, OSError, TypeError, ValueError):
                self._receiver.close()
                self._receiver = None
                if self._state == "running":
                    self._state = "failed"
                    self._message = "Run process exited without a result; inspect durable artifacts"
                break
            self._receiver.close()
            self._receiver = None
        if self._process is not None and self._process_exited_without_reaping(self._process):
            cleanup_error = None
            if self._process_group_id is not None:
                cleanup_error = self._stop_owned_process_locked(self._process)
            else:
                self._process.join(timeout=0)
            if self._state == "running":
                self._state = "failed"
                self._message = "Run process exited without a result; inspect durable artifacts"
            if cleanup_error is not None:
                self._message += f"; process-group cleanup incomplete: {cleanup_error}"

    def _view_locked(self) -> RunSessionView:
        return RunSessionView(
            state=self._state,
            run_id=self._run_id,
            started_at=self._started_at,
            message=self._message,
            result=self._result,
        )


RUN_SESSION = RunSessionController()
atexit.register(RUN_SESSION.cancel)
