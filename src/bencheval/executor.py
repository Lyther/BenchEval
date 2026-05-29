"""Unified task execution across local, Inspect, and Harbor backends."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from bencheval.admission import load_admission_document, run_workspace_verifier
from bencheval.backends import HARBOR_BACKEND, INSPECT_BACKEND, LOCAL_BACKEND, ExecutionBackend
from bencheval.doctor import require_doctor_ok, run_doctor
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.harbor_adapter import (
    HARBOR_SUPPORTED_TASKS,
    HarborAdapterConfig,
    HarborRunner,
    export_harbor_task,
    run_harbor_adapter,
)
from bencheval.inspect_adapter import (
    INSPECT_SUPPORTED_TASKS,
    InspectAdapterConfig,
    InspectInvoker,
    assert_model_id,
    execution_profile_for_task,
    mockllm_e0_skips_inspect_doctor,
    run_inspect_adapter,
)
from bencheval.run_result import RunResult
from bencheval.runner import (
    _SUPPORTED_OFFLINE_TASKS,
    LOCAL_HARNESS_MODEL_ID,
    HarnessReferenceProvider,
    TaskModelProvider,
    new_run_id,
)
from bencheval.task_contract import ExecutionProfile
from bencheval.task_registry import load_task_contract, resolve_task_path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _path_for_evidence(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def _resolve_workspace(task_id: str) -> tuple[Path, str]:
    admission = load_admission_document()
    if task_id not in admission.tasks:
        raise BenchEvalError(f"task {task_id} missing from admission document")
    entry = admission.tasks[task_id]
    root = _repo_root()
    workspace = (root / entry.workspace).resolve()
    return workspace, entry.reference_solution


def _write_verifier_log(
    *,
    artifacts_root: Path,
    candidate: Path,
    outcome,
    root: Path,
) -> Path:
    verifier_log = artifacts_root / "verifier.json"
    if verifier_log.exists():
        raise BenchEvalError(
            f"run artifacts already exist: {verifier_log}",
        )
    artifacts_root.mkdir(parents=True, exist_ok=True)
    verifier_log.write_text(
        json.dumps(
            {
                "primary_pass": outcome.primary_pass,
                "partial_score": outcome.partial_score,
                "partial_metrics": outcome.partial_metrics,
                "candidate": _path_for_evidence(candidate, root),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return verifier_log


def _finalize_run(
    *,
    task_id: str,
    model_id: str,
    execution_profile: ExecutionProfile,
    backend: ExecutionBackend,
    candidate: Path,
    cost_usd: float,
    latency_sec: float,
    adapter_metadata: dict[str, str],
    output_path: Path,
    run_id: str | None,
    run_artifacts_dir: Path | None,
) -> RunResult:
    contract = load_task_contract(resolve_task_path(task_id))
    workspace, _reference_name = _resolve_workspace(task_id)
    outcome = run_workspace_verifier(
        workspace,
        candidate,
        timeout_sec=contract.constraints.max_wall_clock_sec,
    )
    root = _repo_root()
    rid = run_id or new_run_id()
    artifacts_root = run_artifacts_dir or (root / "results" / "raw" / rid)
    verifier_log = _write_verifier_log(
        artifacts_root=artifacts_root,
        candidate=candidate,
        outcome=outcome,
        root=root,
    )
    metadata = dict(adapter_metadata)
    metadata.setdefault("backend", backend)
    record = EvidenceRecord(
        run_id=rid,
        task_id=task_id,
        model_id=model_id,
        execution_profile=execution_profile,
        backend=backend,
        primary_pass=outcome.primary_pass,
        partial_score=outcome.partial_score,
        cost_usd=cost_usd,
        latency_sec=latency_sec,
        failure_labels=[] if outcome.primary_pass else ["wrong_solution"],
        artifact_paths=[_path_for_evidence(candidate, root)],
        verifier_log_path=_path_for_evidence(verifier_log, root),
        adapter_metadata=metadata,
        created_at=datetime.now(tz=UTC),
    )
    JsonlEvidenceSink().append_jsonl(output_path, record)
    return RunResult(run_id=rid, evidence=record, verifier_log_path=verifier_log)


def _record_adapter_failure(
    *,
    task_id: str,
    model_id: str,
    execution_profile: ExecutionProfile,
    backend: ExecutionBackend,
    failure_label: str,
    message: str,
    cost_usd: float,
    latency_sec: float,
    adapter_metadata: dict[str, str],
    output_path: Path,
    run_id: str | None,
    run_artifacts_dir: Path | None,
) -> RunResult:
    root = _repo_root()
    rid = run_id or new_run_id()
    artifacts_root = run_artifacts_dir or (root / "results" / "raw" / rid)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    failure_log = artifacts_root / "adapter_failure.json"
    if failure_log.exists():
        raise BenchEvalError(f"run artifacts already exist: {failure_log}")
    failure_log.write_text(
        json.dumps(
            {
                "failure_label": failure_label,
                "message": message,
                "model_id": model_id,
                "backend": backend,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    metadata = dict(adapter_metadata)
    metadata.setdefault("backend", backend)
    metadata.setdefault("adapter_error", message)
    record = EvidenceRecord(
        run_id=rid,
        task_id=task_id,
        model_id=model_id,
        execution_profile=execution_profile,
        backend=backend,
        primary_pass=False,
        partial_score=0.0,
        cost_usd=cost_usd,
        latency_sec=latency_sec,
        failure_labels=[failure_label],
        artifact_paths=[],
        verifier_log_path=_path_for_evidence(failure_log, root),
        adapter_metadata=metadata,
        created_at=datetime.now(tz=UTC),
    )
    JsonlEvidenceSink().append_jsonl(output_path, record)
    return RunResult(run_id=rid, evidence=record, verifier_log_path=failure_log)


def run_single_task(
    *,
    task_id: str,
    model_id: str,
    output_path: Path,
    provider: TaskModelProvider | None = None,
    run_id: str | None = None,
    run_artifacts_dir: Path | None = None,
) -> RunResult:
    return execute_task(
        task_id=task_id,
        model_id=model_id,
        backend=LOCAL_BACKEND,
        output_path=output_path,
        provider=provider,
        run_id=run_id,
        run_artifacts_dir=run_artifacts_dir,
    )


def execute_task(
    *,
    task_id: str,
    model_id: str,
    backend: ExecutionBackend,
    output_path: Path,
    provider: TaskModelProvider | None = None,
    run_id: str | None = None,
    run_artifacts_dir: Path | None = None,
    inspect_invoke: InspectInvoker | None = None,
    harbor_runner: HarborRunner | None = None,
    harbor_package_dir: Path | None = None,
    skip_doctor: bool = False,
) -> RunResult:
    if backend == LOCAL_BACKEND:
        if task_id not in _SUPPORTED_OFFLINE_TASKS:
            raise BenchEvalError(
                f"task {task_id} is not supported for local execution; "
                f"supported: {sorted(_SUPPORTED_OFFLINE_TASKS)}",
            )
        if provider is None and model_id != LOCAL_HARNESS_MODEL_ID:
            raise BenchEvalError(
                f"local runs require --model {LOCAL_HARNESS_MODEL_ID!r}; "
                f"got {model_id!r}. Use --backend inspect or harbor for provider models.",
            )
        execution_profile = _SUPPORTED_OFFLINE_TASKS[task_id]
        contract = load_task_contract(resolve_task_path(task_id))
        if execution_profile not in contract.execution.profiles():
            raise BenchEvalError(
                f"task {task_id} does not include {execution_profile} execution profile",
            )
        workspace, reference_name = _resolve_workspace(task_id)
        prov = provider or HarnessReferenceProvider()
        if prov.model_id != LOCAL_HARNESS_MODEL_ID:
            raise BenchEvalError(
                f"local evidence model_id must be {LOCAL_HARNESS_MODEL_ID!r}; "
                f"provider reported {prov.model_id!r}",
            )
        candidate, cost_usd, latency_sec = prov.produce_candidate(
            workspace=workspace,
            contract=contract,
            reference_name=reference_name,
        )
        return _finalize_run(
            task_id=task_id,
            model_id=prov.model_id,
            execution_profile=execution_profile,
            backend=LOCAL_BACKEND,
            candidate=candidate,
            cost_usd=cost_usd,
            latency_sec=latency_sec,
            adapter_metadata={"backend": LOCAL_BACKEND},
            output_path=output_path,
            run_id=run_id,
            run_artifacts_dir=run_artifacts_dir,
        )

    if backend == INSPECT_BACKEND:
        if task_id not in INSPECT_SUPPORTED_TASKS:
            raise BenchEvalError(
                f"Inspect backend does not support task {task_id!r}; "
                f"supported: {sorted(INSPECT_SUPPORTED_TASKS)}",
            )
        execution_profile = execution_profile_for_task(task_id)
        if not skip_doctor and not mockllm_e0_skips_inspect_doctor(
            model_id=model_id,
            execution_profile=execution_profile,
        ):
            require_doctor_ok(
                run_doctor(
                    INSPECT_BACKEND,
                    model_id=model_id,
                    execution_profile=execution_profile,
                ),
            )
        workspace, reference_name = _resolve_workspace(task_id)
        root = _repo_root()
        rid = run_id or new_run_id()
        artifacts_root = run_artifacts_dir or (root / "results" / "raw" / rid)
        config = InspectAdapterConfig(
            task_id=task_id,
            model_id=model_id,
            execution_profile=execution_profile,
            workspace=workspace,
            reference_artifact_name=reference_name,
            artifacts_dir=artifacts_root,
            sandbox_docker=execution_profile == "E1",
        )
        try:
            invoke_result = run_inspect_adapter(config, invoke=inspect_invoke)
        except AdapterFailureError as e:
            return _record_adapter_failure(
                task_id=task_id,
                model_id=model_id,
                execution_profile=execution_profile,
                backend=INSPECT_BACKEND,
                failure_label=e.failure_label,
                message=str(e),
                cost_usd=e.cost_usd,
                latency_sec=e.latency_sec,
                adapter_metadata=e.adapter_metadata,
                output_path=output_path,
                run_id=rid,
                run_artifacts_dir=artifacts_root,
            )
        assert_model_id(
            requested=model_id,
            reported=invoke_result.adapter_metadata.get("model_id"),
        )
        return _finalize_run(
            task_id=task_id,
            model_id=model_id,
            execution_profile=execution_profile,
            backend=INSPECT_BACKEND,
            candidate=invoke_result.candidate_path,
            cost_usd=invoke_result.cost_usd,
            latency_sec=invoke_result.latency_sec,
            adapter_metadata=invoke_result.adapter_metadata,
            output_path=output_path,
            run_id=rid,
            run_artifacts_dir=artifacts_root,
        )

    if backend == HARBOR_BACKEND:
        if task_id not in HARBOR_SUPPORTED_TASKS:
            raise BenchEvalError(
                f"Harbor backend does not support task {task_id!r}; "
                f"supported: {sorted(HARBOR_SUPPORTED_TASKS)}",
            )
        execution_profile: ExecutionProfile = "E1"
        contract = load_task_contract(resolve_task_path(task_id))
        profiles = contract.execution.profiles()
        if "E2" in profiles:
            execution_profile = "E2"
        elif "E1" in profiles:
            execution_profile = "E1"
        if not skip_doctor:
            require_doctor_ok(run_doctor(HARBOR_BACKEND, model_id=model_id))
        workspace, reference_name = _resolve_workspace(task_id)
        root = _repo_root()
        rid = run_id or new_run_id()
        artifacts_root = run_artifacts_dir or (root / "results" / "raw" / rid)
        package_root = harbor_package_dir or (artifacts_root / "harbor-package")
        config = HarborAdapterConfig(
            task_id=task_id,
            model_id=model_id,
            workspace=workspace,
            reference_artifact_name=reference_name,
            package_dir=package_root,
            artifacts_dir=artifacts_root,
        )
        if harbor_runner is None:
            export_harbor_task(config)
            raise BenchEvalError(
                "Harbor packaging succeeded but live Harbor agent execution is not wired "
                "in this slice; inject harbor_runner for tests or complete harbor jobs "
                "integration before claiming a live Harbor run",
            )
        harbor_result = run_harbor_adapter(
            config,
            runner=harbor_runner,
            export=export_harbor_task,
        )
        assert_model_id(
            requested=model_id,
            reported=harbor_result.adapter_metadata.get("model_id"),
        )
        return _finalize_run(
            task_id=task_id,
            model_id=model_id,
            execution_profile=execution_profile,
            backend=HARBOR_BACKEND,
            candidate=harbor_result.candidate_path,
            cost_usd=harbor_result.cost_usd,
            latency_sec=harbor_result.latency_sec,
            adapter_metadata=harbor_result.adapter_metadata,
            output_path=output_path,
            run_id=rid,
            run_artifacts_dir=artifacts_root,
        )

    raise BenchEvalError(f"unsupported backend {backend!r}")
