"""Execute four-axis control-plane plans into EvidenceRecord JSONL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from bencheval.backends import (
    HARBOR_BACKEND,
    INSPECT_BACKEND,
    LOCAL_BACKEND,
    ExecutionBackend,
)
from bencheval.benchmark_registry import execution_support_label, load_benchmark_catalog
from bencheval.bfcl_native_adapter import (
    BFCL_ADAPTER_ID,
    BfclInstanceOutcome,
    BfclProcessRunner,
    run_bfcl_instance,
)
from bencheval.cybergym_adapter import (
    CYBERGYM_ADAPTER_ID,
    CybergymInstanceOutcome,
    CybergymProcessRunner,
    run_cybergym_instance,
)
from bencheval.doctor import require_doctor_ok, run_doctor
from bencheval.domain import ExecutionProfile, FailureLabel, InterpretationLabel, RunPlan
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.exploitgym_adapter import (
    EXPLOITGYM_ADAPTER_ID,
    ExploitgymInstanceOutcome,
    ExploitgymProcessRunner,
    run_exploitgym_instance,
)
from bencheval.external_agent_adapter import (
    ExternalAgentProcessRunner,
    execute_external_agent_run,
)
from bencheval.gpqa_adapter import (
    GPQA_ADAPTER_ID,
    GpqaInstanceOutcome,
    GpqaProcessRunner,
    run_gpqa_slice,
)
from bencheval.hle_adapter import (
    HLE_ADAPTER_ID,
    HleInstanceOutcome,
    HleProcessRunner,
    run_hle_slice,
)
from bencheval.ids import new_run_id
from bencheval.paths import repo_root as _repo_root
from bencheval.swebench_adapter import (
    SWEBENCH_ADAPTER_ID,
    SwebenchInstanceOutcome,
    SwebenchProcessRunner,
    run_swebench_instance,
)
from bencheval.swebench_pro_harbor import (
    SWEBENCH_PRO_ADAPTER_ID,
    run_swebench_pro_instance,
)
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
    if plan.adapter_id in (
        SWEBENCH_ADAPTER_ID,
        BFCL_ADAPTER_ID,
        GPQA_ADAPTER_ID,
        HLE_ADAPTER_ID,
    ):
        return INSPECT_BACKEND
    if plan.adapter_id in (CYBERGYM_ADAPTER_ID, EXPLOITGYM_ADAPTER_ID):
        return LOCAL_BACKEND
    if plan.harness_kind in (
        "swebench-native",
        "bfcl-native",
        "inspect-evals",
        "hle-native",
    ):
        return INSPECT_BACKEND
    if plan.harness_kind in ("cybergym-native", "exploitgym-native"):
        return LOCAL_BACKEND
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
        agent_id=plan.agent_id,
        provider_id=plan.provider_id,
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
        agent_id=plan.agent_id,
        provider_id=plan.provider_id,
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
        agent_id=plan.agent_id,
        provider_id=plan.provider_id,
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
    return _evidence_from_scored_instance(
        plan=plan,
        run_id=run_id,
        instance_id=outcome.instance_id,
        execution_profile=execution_profile,
        backend=INSPECT_BACKEND,
        primary_pass=outcome.primary_pass,
        partial_score=outcome.partial_score,
        cost_usd=outcome.cost_usd,
        latency_sec=outcome.latency_sec,
        failure_class=outcome.failure_class,
        native_score=outcome.native_score,
        adapter_metadata=outcome.adapter_metadata,
        paths=(outcome.verifier_log_path, outcome.stdout_path, outcome.stderr_path),
        verifier_log_path=outcome.verifier_log_path,
    )


def _evidence_from_scored_instance(
    *,
    plan: RunPlan,
    run_id: str,
    instance_id: str,
    execution_profile: ExecutionProfile,
    backend: ExecutionBackend,
    primary_pass: bool,
    partial_score: float,
    cost_usd: float,
    latency_sec: float,
    failure_class: FailureLabel | None,
    native_score: dict[str, object],
    adapter_metadata: dict[str, str],
    paths: tuple[str | None, ...],
    verifier_log_path: str | None,
    counts_toward_pass_at_k: bool | None = None,
) -> EvidenceRecord:
    artifact_paths = [p for p in paths if p]
    failure_labels: list[str] = []
    if not primary_pass and failure_class:
        failure_labels.append(failure_class)
    return EvidenceRecord(
        run_id=run_id,
        task_id=instance_id,
        model_id=plan.model_id,
        execution_profile=execution_profile,
        backend=backend,
        primary_pass=primary_pass,
        partial_score=partial_score,
        cost_usd=cost_usd,
        latency_sec=latency_sec,
        failure_labels=failure_labels,
        artifact_paths=artifact_paths,
        verifier_log_path=verifier_log_path,
        adapter_metadata=adapter_metadata,
        created_at=datetime.now(tz=UTC),
        benchmark_id=plan.benchmark_id,
        benchmark_version=plan.benchmark_version,
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        harness_version=adapter_metadata.get("harness_version"),
        runtime_id=plan.runtime_id,
        runtime_kind=plan.runtime_kind,
        agent_id=plan.agent_id,
        provider_id=plan.provider_id,
        instance_id=instance_id,
        native_score=native_score,
        normalized_score=partial_score,
        interpretation_label=_interpretation_label(plan),
        contamination_label=_contamination_label(plan),
        failure_class=failure_class,
        cleanup_result=None,
        counts_toward_pass_at_k=counts_toward_pass_at_k,
    )


def _evidence_from_gpqa_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: GpqaInstanceOutcome,
    execution_profile: ExecutionProfile,
) -> EvidenceRecord:
    return _evidence_from_scored_instance(
        plan=plan,
        run_id=run_id,
        instance_id=outcome.instance_id,
        execution_profile=execution_profile,
        backend=INSPECT_BACKEND,
        primary_pass=outcome.primary_pass,
        partial_score=outcome.partial_score,
        cost_usd=outcome.cost_usd,
        latency_sec=outcome.latency_sec,
        failure_class=outcome.failure_class,
        native_score=outcome.native_score,
        adapter_metadata=outcome.adapter_metadata,
        paths=(outcome.verifier_log_path, outcome.stdout_path, outcome.stderr_path),
        verifier_log_path=outcome.verifier_log_path,
        counts_toward_pass_at_k=outcome.counts_toward_pass_at_k,
    )


def _evidence_from_hle_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: HleInstanceOutcome,
    execution_profile: ExecutionProfile,
) -> EvidenceRecord:
    return _evidence_from_scored_instance(
        plan=plan,
        run_id=run_id,
        instance_id=outcome.instance_id,
        execution_profile=execution_profile,
        backend=INSPECT_BACKEND,
        primary_pass=outcome.primary_pass,
        partial_score=outcome.partial_score,
        cost_usd=outcome.cost_usd,
        latency_sec=outcome.latency_sec,
        failure_class=outcome.failure_class,
        native_score=outcome.native_score,
        adapter_metadata=outcome.adapter_metadata,
        paths=(outcome.verifier_log_path, outcome.stdout_path, outcome.stderr_path),
        verifier_log_path=outcome.verifier_log_path,
        counts_toward_pass_at_k=outcome.counts_toward_pass_at_k,
    )


def _evidence_from_cybergym_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: CybergymInstanceOutcome,
    execution_profile: ExecutionProfile,
) -> EvidenceRecord:
    return _evidence_from_scored_instance(
        plan=plan,
        run_id=run_id,
        instance_id=outcome.instance_id,
        execution_profile=execution_profile,
        backend=LOCAL_BACKEND,
        primary_pass=outcome.primary_pass,
        partial_score=outcome.partial_score,
        cost_usd=outcome.cost_usd,
        latency_sec=outcome.latency_sec,
        failure_class=outcome.failure_class,
        native_score=outcome.native_score,
        adapter_metadata=outcome.adapter_metadata,
        paths=(outcome.verifier_log_path, outcome.stdout_path, outcome.stderr_path),
        verifier_log_path=outcome.verifier_log_path,
    )


def _evidence_from_exploitgym_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: ExploitgymInstanceOutcome,
    execution_profile: ExecutionProfile,
) -> EvidenceRecord:
    return _evidence_from_scored_instance(
        plan=plan,
        run_id=run_id,
        instance_id=outcome.instance_id,
        execution_profile=execution_profile,
        backend=LOCAL_BACKEND,
        primary_pass=outcome.primary_pass,
        partial_score=outcome.partial_score,
        cost_usd=outcome.cost_usd,
        latency_sec=outcome.latency_sec,
        failure_class=outcome.failure_class,
        native_score=outcome.native_score,
        adapter_metadata=outcome.adapter_metadata,
        paths=(outcome.verifier_log_path, outcome.stdout_path, outcome.stderr_path),
        verifier_log_path=outcome.verifier_log_path,
        counts_toward_pass_at_k=outcome.counts_toward_pass_at_k,
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
    gpqa_process_runner: GpqaProcessRunner | None = None,
    hle_process_runner: HleProcessRunner | None = None,
    cybergym_process_runner: CybergymProcessRunner | None = None,
    exploitgym_process_runner: ExploitgymProcessRunner | None = None,
    agent_process_runner: ExternalAgentProcessRunner | None = None,
    momo_process_runner: ExternalAgentProcessRunner | None = None,
    run_id: str | None = None,
) -> ControlPlaneRunSummary:
    """Dispatch a ``RunPlan`` to the matching adapter and append evidence rows."""
    _require_executable_benchmark(plan)
    # Official harness adapters must win over the generic --agent external path.
    if plan.adapter_id == CYBERGYM_ADAPTER_ID:
        return _execute_cybergym(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            cybergym_process_runner=cybergym_process_runner,
            run_id=run_id,
        )
    if plan.adapter_id == EXPLOITGYM_ADAPTER_ID:
        return _execute_exploitgym(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            exploitgym_process_runner=exploitgym_process_runner,
            run_id=run_id,
        )
    if plan.adapter_id == GPQA_ADAPTER_ID:
        return _execute_gpqa(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            gpqa_process_runner=gpqa_process_runner,
            run_id=run_id,
        )
    if plan.adapter_id == HLE_ADAPTER_ID:
        return _execute_hle(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            hle_process_runner=hle_process_runner,
            run_id=run_id,
        )
    if plan.adapter_id == SWEBENCH_PRO_ADAPTER_ID:
        if plan.agent_id is not None:
            runner = agent_process_runner or momo_process_runner
            summary = execute_external_agent_run(
                plan=plan,
                output_path=output_path,
                artifacts_dir=artifacts_dir,
                process_runner=runner,
                run_id=run_id,
            )
            return ControlPlaneRunSummary(
                run_id=summary.run_id,
                instance_count=summary.instance_count,
                passed_count=summary.passed_count,
                failed_count=summary.failed_count,
                output_path=summary.output_path,
            )
        return _execute_swebench_pro_harbor(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            harbor_process_runner=harbor_process_runner,
            run_id=run_id,
        )
    if plan.agent_id is not None:
        runner = agent_process_runner or momo_process_runner
        summary = execute_external_agent_run(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            process_runner=runner,
            run_id=run_id,
        )
        return ControlPlaneRunSummary(
            run_id=summary.run_id,
            instance_count=summary.instance_count,
            passed_count=summary.passed_count,
            failed_count=summary.failed_count,
            output_path=summary.output_path,
        )
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
        f"{SWEBENCH_PRO_ADAPTER_ID!r}, {BFCL_ADAPTER_ID!r}, {GPQA_ADAPTER_ID!r}, "
        f"{HLE_ADAPTER_ID!r}, {CYBERGYM_ADAPTER_ID!r}, {EXPLOITGYM_ADAPTER_ID!r}",
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


def _execute_swebench_pro_harbor(
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
            outcome = run_swebench_pro_instance(
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


def _execute_gpqa(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None,
    gpqa_process_runner: GpqaProcessRunner | None,
    run_id: str | None,
) -> ControlPlaneRunSummary:
    root = _repo_root()
    rid = run_id or new_run_id()
    run_artifacts = artifacts_dir or (root / "results" / "raw" / rid)
    run_artifacts.mkdir(parents=True, exist_ok=True)
    sink = JsonlEvidenceSink()
    execution_profile = _execution_profile_for_plan(plan)
    try:
        outcomes = run_gpqa_slice(
            plan=plan,
            artifacts_dir=run_artifacts,
            repo_root=root,
            process_runner=gpqa_process_runner,
        )
    except AdapterFailureError as e:
        outcomes = []
        for inst in plan.instances:
            record = _record_instance_failure(
                plan=plan,
                run_id=rid,
                instance_id=inst.instance_id,
                execution_profile=execution_profile,
                error=e,
                artifacts_dir=run_artifacts,
            )
            sink.append_jsonl(output_path, record)
        total = len(plan.instances)
        return ControlPlaneRunSummary(
            run_id=rid,
            instance_count=total,
            passed_count=0,
            failed_count=total,
            output_path=output_path.resolve(),
        )
    passed = 0
    for outcome in outcomes:
        record = _evidence_from_gpqa_outcome(
            plan=plan,
            run_id=rid,
            outcome=outcome,
            execution_profile=execution_profile,
        )
        if record.primary_pass:
            passed += 1
        sink.append_jsonl(output_path, record)
    total = len(outcomes)
    return ControlPlaneRunSummary(
        run_id=rid,
        instance_count=total,
        passed_count=passed,
        failed_count=total - passed,
        output_path=output_path.resolve(),
    )


def _execute_hle(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None,
    hle_process_runner: HleProcessRunner | None,
    run_id: str | None,
) -> ControlPlaneRunSummary:
    root = _repo_root()
    rid = run_id or new_run_id()
    run_artifacts = artifacts_dir or (root / "results" / "raw" / rid)
    run_artifacts.mkdir(parents=True, exist_ok=True)
    sink = JsonlEvidenceSink()
    execution_profile = _execution_profile_for_plan(plan)
    try:
        outcomes = run_hle_slice(
            plan=plan,
            artifacts_dir=run_artifacts,
            repo_root=root,
            process_runner=hle_process_runner,
        )
    except AdapterFailureError as e:
        for inst in plan.instances:
            record = _record_instance_failure(
                plan=plan,
                run_id=rid,
                instance_id=inst.instance_id,
                execution_profile=execution_profile,
                error=e,
                artifacts_dir=run_artifacts,
            )
            sink.append_jsonl(output_path, record)
        total = len(plan.instances)
        return ControlPlaneRunSummary(
            run_id=rid,
            instance_count=total,
            passed_count=0,
            failed_count=total,
            output_path=output_path.resolve(),
        )
    passed = 0
    for outcome in outcomes:
        record = _evidence_from_hle_outcome(
            plan=plan,
            run_id=rid,
            outcome=outcome,
            execution_profile=execution_profile,
        )
        if record.primary_pass:
            passed += 1
        sink.append_jsonl(output_path, record)
    total = len(outcomes)
    return ControlPlaneRunSummary(
        run_id=rid,
        instance_count=total,
        passed_count=passed,
        failed_count=total - passed,
        output_path=output_path.resolve(),
    )


def _execute_cybergym(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None,
    cybergym_process_runner: CybergymProcessRunner | None,
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
            outcome = run_cybergym_instance(
                plan=plan,
                instance_id=instance_id,
                artifacts_dir=run_artifacts,
                repo_root=root,
                process_runner=cybergym_process_runner,
            )
            record = _evidence_from_cybergym_outcome(
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


def _execute_exploitgym(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None,
    exploitgym_process_runner: ExploitgymProcessRunner | None,
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
            outcome = run_exploitgym_instance(
                plan=plan,
                instance_id=instance_id,
                artifacts_dir=run_artifacts,
                repo_root=root,
                process_runner=exploitgym_process_runner,
            )
            record = _evidence_from_exploitgym_outcome(
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
