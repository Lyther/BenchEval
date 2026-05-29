"""Offline E0/E1 task execution producing EvidenceRecord rows."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from bencheval.exceptions import BenchEvalError
from bencheval.run_result import RunResult
from bencheval.task_contract import ExecutionProfile, TaskContract

LOCAL_HARNESS_MODEL_ID = "local/harness"
_SUPPORTED_OFFLINE_TASKS: dict[str, ExecutionProfile] = {
    "be-core-t1-single-structured-call": "E0",
    "be-core-t2-multi-tool-join": "E0",
    "be-core-c1-small-logic-patch": "E1",
    "be-core-c2-regression-test-authoring": "E1",
    "be-core-a1-multi-file-repo-fix": "E1",
    "be-core-a2-build-log-triage": "E1",
    "be-core-s1-secure-input-boundary-patch": "E1",
    "be-core-s4-local-prompt-injection-resistance": "E1",
}


class TaskModelProvider(Protocol):
    model_id: str

    def produce_candidate(
        self,
        *,
        workspace: Path,
        contract: TaskContract,
        reference_name: str,
    ) -> tuple[Path, float, float]:
        """Return candidate artifact path, cost_usd, latency_sec."""


class HarnessReferenceProvider:
    """Explicit offline provider that submits the workspace reference solution."""

    model_id = LOCAL_HARNESS_MODEL_ID

    def produce_candidate(
        self,
        *,
        workspace: Path,
        contract: TaskContract,
        reference_name: str,
    ) -> tuple[Path, float, float]:
        del contract
        ref = workspace / reference_name
        if not ref.is_file():
            raise BenchEvalError(f"reference missing for harness run: {ref}")
        return ref, 0.0, 0.0


def new_run_id() -> str:
    stamp = datetime.now(tz=UTC).strftime("run-%Y%m%d-%H%M%S-%f")
    return f"{stamp}-{uuid4().hex[:8]}"


def run_single_task(
    *,
    task_id: str,
    model_id: str,
    output_path: Path,
    provider: TaskModelProvider | None = None,
    run_id: str | None = None,
    run_artifacts_dir: Path | None = None,
) -> RunResult:
    from bencheval.executor import execute_task

    return execute_task(
        task_id=task_id,
        model_id=model_id,
        backend="local",
        output_path=output_path,
        provider=provider,
        run_id=run_id,
        run_artifacts_dir=run_artifacts_dir,
    )
