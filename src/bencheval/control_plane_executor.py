"""Execute four-axis control-plane plans into EvidenceRecord JSONL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from bencheval.backends import HARBOR_BACKEND, INSPECT_BACKEND, ExecutionBackend
from bencheval.benchmark_registry import execution_support_label, load_benchmark_catalog
from bencheval.bfcl_native_adapter import (
    BFCL_ADAPTER_ID,
    BfclInstanceOutcome,
    BfclProcessRunner,
    run_bfcl_instance,
)
from bencheval.doctor import require_doctor_ok, run_doctor
from bencheval.domain import FailureLabel, InterpretationLabel, RunPlan
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.paths import repo_root as _repo_root
from bencheval.runner import new_run_id
from bencheval.swebench_adapter import (
    SWEBENCH_ADAPTER_ID,
    SwebenchInstanceOutcome,
    SwebenchProcessRunner,
    run_swebench_instance,
)
from bencheval.task_contract import ExecutionProfile
from bencheval.terminal_bench_harbor import (
    TERMINAL_BENCH_ADAPTER_ID,
    HarborProcessRunner,
    TerminalBenchInstanceOutcome,
    run_terminal_bench_instance,
)

_FAILURE_LABELS = frozenset(get_args(FailureLabel))


@dataclass(frozen=True, slots=True)
class ControlPlaneRunSummary:
    run_id: str
    instance_count: int
    passed_count: int
    failed_count: int
    output_path: Path


def _execution_profile_for_plan(plan: RunPlan) -> ExecutionProfile:
    if plan.requires_harbor:
        return "E2"
    if plan.requires_sandbox:
        return "E1"
    return "E0"


def control_plane_interpretation_label(plan: RunPlan) -> InterpretationLabel:
    """Map a frozen :class:`RunPlan` to the evidence/report interpretation label."""
    return _interpretation_label(plan)


def _interpretation_label(plan: RunPlan) -> InterpretationLabel:
    if plan.benchmark_id == "swe-bench-verified":
        return "contaminated_or_legacy"
    validity = plan.comparison_validity
    if validity == "invalid":
        return "rough_regression"
    if validity == "diagnostic_only":
        return "benchmark_native_claim"
    if validity in ("model_comparison", "runtime_comparison", "adapter_smoke"):
        return validity
    return "adapter_smoke"


def _contamination_label(plan: RunPlan) -> str | None:
    if any("contamination" in c for c in plan.caveats):
        return "public_possible"
    return None


def _backend_for_plan(plan: RunPlan) -> ExecutionBackend:
    if plan.adapter_id in (SWEBENCH_ADAPTER_ID, BFCL_ADAPTER_ID):
        return INSPECT_BACKEND
    if plan.harness_kind in ("swebench-native", "bfcl-native"):
        return INSPECT_BACKEND
    return HARBOR_BACKEND


def _evidence_from_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: TerminalBenchInstanceOutcome,
    execution_profile: ExecutionProfile,
) -> EvidenceRecord:
    artifact_paths: list[str] = []
    if outcome.raw_result_path:
        artifact_paths.append(outcome.raw_result_path)
    if outcome.stdout_path:
        artifact_paths.append(outcome.stdout_path)
    if outcome.stderr_path:
        artifact_paths.append(outcome.stderr_path)

    failure_labels: list[str] = []
    if not outcome.primary_pass and outcome.failure_class:
        failure_labels.append(outcome.failure_class)

    return EvidenceRecord(
        run_id=run_id,
        task_id=outcome.instance_id,
        model_id=plan.model_id,
        execution_profile=execution_profile,
        backend=HARBOR_BACKEND,
        primary_pass=outcome.primary_pass,
        partial_score=outcome.partial_score,
        cost_usd=outcome.cost_usd,
        latency_sec=outcome.latency_sec,
        failure_labels=failure_labels,
        artifact_paths=artifact_paths,
        verifier_log_path=outcome.raw_result_path,
        adapter_metadata=outcome.adapter_metadata,
        created_at=datetime.now(tz=UTC),
        benchmark_id=plan.benchmark_id,
        benchmark_version=plan.benchmark_version,
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        harness_version=outcome.adapter_metadata.get("harness_version"),
        runtime_id=plan.runtime_id,
        runtime_kind=plan.runtime_kind,
        instance_id=outcome.instance_id,
        native_score=outcome.native_score,
        normalized_score=outcome.partial_score,
        interpretation_label=_interpretation_label(plan),
        contamination_label=_contamination_label(plan),
        failure_class=outcome.failure_class,
        cleanup_result=None,
    )


def _record_instance_failure(
    *,
    plan: RunPlan,
    run_id: str,
    instance_id: str,
    execution_profile: ExecutionProfile,
    error: AdapterFailureError,
    artifacts_dir: Path,
) -> EvidenceRecord:
    failure_log = artifacts_dir / "adapter_failure.json"
    failure_log.parent.mkdir(parents=True, exist_ok=True)
    failure_log.write_text(
        json.dumps(
            {
                "instance_id": instance_id,
                "failure_label": error.failure_label,
                "message": str(error),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    root = _repo_root()
    try:
        rel_log = str(failure_log.resolve().relative_to(root))
    except ValueError:
        rel_log = str(failure_log.resolve())

    metadata = dict(error.adapter_metadata)
    metadata.setdefault("adapter_id", plan.adapter_id)

    return EvidenceRecord(
        run_id=run_id,
        task_id=instance_id,
        model_id=plan.model_id,
        execution_profile=execution_profile,
        backend=_backend_for_plan(plan),
        primary_pass=False,
        partial_score=0.0,
        cost_usd=error.cost_usd,
        latency_sec=error.latency_sec,
        failure_labels=[error.failure_label],
        artifact_paths=[],
        verifier_log_path=rel_log,
        adapter_metadata=metadata,
        created_at=datetime.now(tz=UTC),
        benchmark_id=plan.benchmark_id,
        benchmark_version=plan.benchmark_version,
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        runtime_id=plan.runtime_id,
        runtime_kind=plan.runtime_kind,
        instance_id=instance_id,
        interpretation_label=_interpretation_label(plan),
        contamination_label=_contamination_label(plan),
        failure_class=(
            error.failure_label if error.failure_label in _FAILURE_LABELS else "adapter_error"
        ),
    )


def _evidence_from_swebench_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: SwebenchInstanceOutcome,
    execution_profile: ExecutionProfile,
) -> EvidenceRecord:
    artifact_paths: list[str] = []
    for path in (
        outcome.verifier_log_path,
        outcome.workspace_diff_path,
        outcome.stdout_path,
        outcome.stderr_path,
    ):
        if path:
            artifact_paths.append(path)

    failure_labels: list[str] = []
    if not outcome.primary_pass and outcome.failure_class:
        failure_labels.append(outcome.failure_class)

    return EvidenceRecord(
        run_id=run_id,
        task_id=outcome.instance_id,
        model_id=plan.model_id,
        execution_profile=execution_profile,
        backend=INSPECT_BACKEND,
        primary_pass=outcome.primary_pass,
        partial_score=outcome.partial_score,
        cost_usd=outcome.cost_usd,
        latency_sec=outcome.latency_sec,
        failure_labels=failure_labels,
        artifact_paths=artifact_paths,
        verifier_log_path=outcome.verifier_log_path,
        adapter_metadata=outcome.adapter_metadata,
        created_at=datetime.now(tz=UTC),
        benchmark_id=plan.benchmark_id,
        benchmark_version=plan.benchmark_version,
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        harness_version=outcome.adapter_metadata.get("harness_version"),
        runtime_id=plan.runtime_id,
        runtime_kind=plan.runtime_kind,
        instance_id=outcome.instance_id,
        native_score=outcome.native_score,
        normalized_score=outcome.partial_score,
        interpretation_label=_interpretation_label(plan),
        contamination_label=_contamination_label(plan),
        failure_class=outcome.failure_class,
        cleanup_result=None,
    )


def _evidence_from_bfcl_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: BfclInstanceOutcome,
    execution_profile: ExecutionProfile,
) -> EvidenceRecord:
    artifact_paths: list[str] = []
    for path in (outcome.verifier_log_path, outcome.stdout_path, outcome.stderr_path):
        if path:
            artifact_paths.append(path)

    failure_labels: list[str] = []
    if not outcome.primary_pass and outcome.failure_class:
        failure_labels.append(outcome.failure_class)

    return EvidenceRecord(
        run_id=run_id,
        task_id=outcome.instance_id,
        model_id=plan.model_id,
        execution_profile=execution_profile,
        backend=INSPECT_BACKEND,
        primary_pass=outcome.primary_pass,
        partial_score=outcome.partial_score,
        cost_usd=outcome.cost_usd,
        latency_sec=outcome.latency_sec,
        failure_labels=failure_labels,
        artifact_paths=artifact_paths,
        verifier_log_path=outcome.verifier_log_path,
        adapter_metadata=outcome.adapter_metadata,
        created_at=datetime.now(tz=UTC),
        benchmark_id=plan.benchmark_id,
        benchmark_version=plan.benchmark_version,
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        harness_version=outcome.adapter_metadata.get("harness_version"),
        runtime_id=plan.runtime_id,
        runtime_kind=plan.runtime_kind,
        instance_id=outcome.instance_id,
        native_score=outcome.native_score,
        normalized_score=outcome.partial_score,
        interpretation_label=_interpretation_label(plan),
        contamination_label=_contamination_label(plan),
        failure_class=outcome.failure_class,
        cleanup_result=None,
    )


def _require_executable_benchmark(plan: RunPlan) -> None:
    catalog = load_benchmark_catalog()
    benchmark = catalog.by_id_or_alias(plan.benchmark_id)
    support = execution_support_label(benchmark)
    if support != "executable_adapter":
        raise BenchEvalError(
            f"benchmark {plan.benchmark_id!r} has execution_support={support!r}; "
            "control-plane execute requires executable_adapter",
        )


def execute_control_plane_run(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None = None,
    harbor_process_runner: HarborProcessRunner | None = None,
    swebench_process_runner: SwebenchProcessRunner | None = None,
    bfcl_process_runner: BfclProcessRunner | None = None,
    run_id: str | None = None,
) -> ControlPlaneRunSummary:
    """Dispatch a ``RunPlan`` to the matching adapter and append evidence rows."""
    _require_executable_benchmark(plan)
    if plan.adapter_id == TERMINAL_BENCH_ADAPTER_ID:
        return _execute_terminal_bench_harbor(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            harbor_process_runner=harbor_process_runner,
            run_id=run_id,
        )
    if plan.adapter_id == SWEBENCH_ADAPTER_ID:
        return _execute_swebench(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            swebench_process_runner=swebench_process_runner,
            run_id=run_id,
        )
    if plan.adapter_id == BFCL_ADAPTER_ID:
        return _execute_bfcl(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            bfcl_process_runner=bfcl_process_runner,
            run_id=run_id,
        )
    raise BenchEvalError(
        f"no executor for adapter_id={plan.adapter_id!r}; "
        f"supported: {TERMINAL_BENCH_ADAPTER_ID!r}, {SWEBENCH_ADAPTER_ID!r}, "
        f"{BFCL_ADAPTER_ID!r}",
    )


def _execute_terminal_bench_harbor(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None,
    harbor_process_runner: HarborProcessRunner | None,
    run_id: str | None,
) -> ControlPlaneRunSummary:
    root = _repo_root()
    rid = run_id or new_run_id()
    run_artifacts = artifacts_dir or (root / "results" / "raw" / rid)
    run_artifacts.mkdir(parents=True, exist_ok=True)
    if harbor_process_runner is None:
        require_doctor_ok(run_doctor(HARBOR_BACKEND, model_id=plan.model_id))
    sink = JsonlEvidenceSink()
    execution_profile = _execution_profile_for_plan(plan)

    passed = 0
    for inst in plan.instances:
        instance_id = inst.instance_id
        try:
            outcome = run_terminal_bench_instance(
                plan=plan,
                instance_id=instance_id,
                artifacts_dir=run_artifacts,
                repo_root=root,
                process_runner=harbor_process_runner,
            )
            record = _evidence_from_outcome(
                plan=plan,
                run_id=rid,
                outcome=outcome,
                execution_profile=execution_profile,
            )
        except AdapterFailureError as e:
            record = _record_instance_failure(
                plan=plan,
                run_id=rid,
                instance_id=instance_id,
                execution_profile=execution_profile,
                error=e,
                artifacts_dir=run_artifacts / instance_id,
            )
        if record.primary_pass:
            passed += 1
        sink.append_jsonl(output_path, record)

    total = len(plan.instances)
    return ControlPlaneRunSummary(
        run_id=rid,
        instance_count=total,
        passed_count=passed,
        failed_count=total - passed,
        output_path=output_path.resolve(),
    )


def _execute_swebench(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None,
    swebench_process_runner: SwebenchProcessRunner | None,
    run_id: str | None,
) -> ControlPlaneRunSummary:
    root = _repo_root()
    rid = run_id or new_run_id()
    run_artifacts = artifacts_dir or (root / "results" / "raw" / rid)
    run_artifacts.mkdir(parents=True, exist_ok=True)
    sink = JsonlEvidenceSink()
    execution_profile = _execution_profile_for_plan(plan)
    passed = 0
    for inst in plan.instances:
        instance_id = inst.instance_id
        try:
            outcome = run_swebench_instance(
                plan=plan,
                instance_id=instance_id,
                artifacts_dir=run_artifacts,
                repo_root=root,
                process_runner=swebench_process_runner,
            )
            record = _evidence_from_swebench_outcome(
                plan=plan,
                run_id=rid,
                outcome=outcome,
                execution_profile=execution_profile,
            )
        except AdapterFailureError as e:
            record = _record_instance_failure(
                plan=plan,
                run_id=rid,
                instance_id=instance_id,
                execution_profile=execution_profile,
                error=e,
                artifacts_dir=run_artifacts / instance_id,
            )
        if record.primary_pass:
            passed += 1
        sink.append_jsonl(output_path, record)

    total = len(plan.instances)
    return ControlPlaneRunSummary(
        run_id=rid,
        instance_count=total,
        passed_count=passed,
        failed_count=total - passed,
        output_path=output_path.resolve(),
    )


def _execute_bfcl(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None,
    bfcl_process_runner: BfclProcessRunner | None,
    run_id: str | None,
) -> ControlPlaneRunSummary:
    root = _repo_root()
    rid = run_id or new_run_id()
    run_artifacts = artifacts_dir or (root / "results" / "raw" / rid)
    run_artifacts.mkdir(parents=True, exist_ok=True)
    sink = JsonlEvidenceSink()
    execution_profile = _execution_profile_for_plan(plan)
    passed = 0
    for inst in plan.instances:
        instance_id = inst.instance_id
        try:
            outcome = run_bfcl_instance(
                plan=plan,
                instance_id=instance_id,
                artifacts_dir=run_artifacts,
                repo_root=root,
                process_runner=bfcl_process_runner,
            )
            record = _evidence_from_bfcl_outcome(
                plan=plan,
                run_id=rid,
                outcome=outcome,
                execution_profile=execution_profile,
            )
        except AdapterFailureError as e:
            record = _record_instance_failure(
                plan=plan,
                run_id=rid,
                instance_id=instance_id,
                execution_profile=execution_profile,
                error=e,
                artifacts_dir=run_artifacts / instance_id,
            )
        if record.primary_pass:
            passed += 1
        sink.append_jsonl(output_path, record)

    total = len(plan.instances)
    return ControlPlaneRunSummary(
        run_id=rid,
        instance_count=total,
        passed_count=passed,
        failed_count=total - passed,
        output_path=output_path.resolve(),
    )


__all__ = [
    "ControlPlaneRunSummary",
    "control_plane_interpretation_label",
    "execute_control_plane_run",
]
