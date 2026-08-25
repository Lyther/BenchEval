"""Execute four-axis control-plane plans into EvidenceRecord JSONL."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args
from urllib.parse import urlsplit

from bencheval.agent_registry import require_admitted_agent
from bencheval.backends import (
    HARBOR_BACKEND,
    INSPECT_BACKEND,
    ExecutionBackend,
)
from bencheval.benchmark_registry import (
    BenchmarkEntry,
    execution_support_label,
    load_benchmark_catalog,
)
from bencheval.bfcl_native_adapter import (
    BFCL_ADAPTER_ID,
    BfclInstanceOutcome,
    BfclProcessRunner,
    bfcl_pinned_harness_version,
    run_bfcl_instance,
)
from bencheval.doctor import require_doctor_ok, run_doctor
from bencheval.domain import (
    CleanupResult,
    ExecutionProfile,
    FailureLabel,
    InterpretationLabel,
    RunPlan,
    RuntimeProfile,
)
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import AdapterFailureError, BenchEvalError
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
from bencheval.lifecycle import cleanup_transient_artifacts
from bencheval.paths import repo_root as _repo_root
from bencheval.provider_registry import resolve_openai_compatible_launch
from bencheval.run_isolation import (
    claim_exclusive_run_outputs,
    open_owned_dir_fd,
    release_evidence_reservation,
    write_text_at_exclusive,
)
from bencheval.runtime_registry import load_runtime_catalog
from bencheval.terminal_bench_harbor import (
    TERMINAL_BENCH_ADAPTER_ID,
    TERMINAL_BENCH_RELEASE_VERSION,
    HarborProcessRunner,
    TerminalBenchInstanceOutcome,
    run_terminal_bench_instance,
)

_FAILURE_LABELS = frozenset(get_args(FailureLabel))
_VERSION_COMMAND_TIMEOUT_SEC = 15


@dataclass(frozen=True, slots=True)
class ControlPlaneRunSummary:
    run_id: str
    instance_count: int
    passed_count: int
    failed_count: int
    output_path: Path


@dataclass(frozen=True, slots=True)
class _RuntimeProvenance:
    """Captured once per run; None fields mean capture failed (do not invent)."""

    runtime_version: str | None
    runtime_config_hash: str | None


def _run_version_command(command: tuple[str, ...]) -> str | None:
    try:
        proc = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_VERSION_COMMAND_TIMEOUT_SEC,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or proc.stderr or "").strip()
    if not text:
        return None
    return text.splitlines()[0][:200]


def _hash_config_inputs(inputs: tuple[str, ...], *, root: Path) -> str | None:
    """Content hash of config inputs; path order does not affect the digest."""
    if not inputs:
        return None
    digest = hashlib.sha256()
    root_resolved = root.resolve()
    # Sort so registry tuple order cannot change identity.
    for rel in sorted(inputs):
        path = (root / rel).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError:
            return None
        if path.is_file():
            digest.update(rel.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
            continue
        if path.is_dir():
            for child in sorted(p for p in path.rglob("*") if p.is_file()):
                rel_child = child.relative_to(root_resolved).as_posix()
                digest.update(rel_child.encode("utf-8"))
                digest.update(b"\0")
                digest.update(child.read_bytes())
                digest.update(b"\0")
            continue
        # Absent optional inputs still contribute a stable marker.
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0missing\0")
    return f"sha256:{digest.hexdigest()}"


# Env vars that alter Harbor/runtime launch options for admitted CLI agents.
_RUNTIME_EFFECTIVE_ENV_KEYS: tuple[str, ...] = (
    "BENCHEVAL_CLAUDE_CODE_ALLOWED_TOOLS",
    "OPENAI_BASE_URL",
    "ANTHROPIC_BASE_URL",
    "BENCHEVAL_CODEX_ENV_KEY",
    "BENCHEVAL_HARBOR_FORWARD_PROXY",
    "BENCHEVAL_CLAUDE_CODE_NPM_REGISTRY",
    "BENCHEVAL_CLAUDE_CODE_NPM_FETCH_TIMEOUT_MS",
    "BENCHEVAL_CLAUDE_CODE_NPM_FETCH_RETRIES",
)
_PROXY_PRESENCE_ENV_KEYS: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)


def _proxy_url_route(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return "opaque"
    host = (parsed.hostname or "").lower()
    if not host and not parsed.scheme:
        return "opaque"
    netloc = host
    if parsed.port is not None:
        netloc = f"{host}:{parsed.port}"
    # Drop userinfo, query, and fragment — credentials must stay hash-neutral.
    return f"{(parsed.scheme or '').lower()}://{netloc}{parsed.path}"


def _proxy_route_identity(name: str, value: str) -> str:
    """Normalize proxy routing for provenance: scheme/host/port/NO_PROXY, no userinfo."""
    if name.lower() == "no_proxy":
        parts: set[str] = set()
        for part in value.split(","):
            token = part.strip()
            if not token:
                continue
            if "://" in token or "@" in token:
                parts.add(_proxy_url_route(token))
            else:
                parts.add(token.lower())
        return ",".join(sorted(parts))
    return _proxy_url_route(value)


def _hash_effective_runtime_options(*, plan: RunPlan) -> str:
    """Hash runtime-affecting launch inputs so evidence identity tracks effective config."""
    digest = hashlib.sha256()
    runtime_id = plan.runtime_id or ""
    digest.update(runtime_id.encode("utf-8"))
    digest.update(b"\0")
    digest.update(f"network_policy={plan.network_policy}".encode())
    digest.update(b"\0")
    for key in _RUNTIME_EFFECTIVE_ENV_KEYS:
        value = os.environ.get(key, "")
        digest.update(key.encode("utf-8"))
        digest.update(b"=")
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    # Hash non-secret proxy routing identity (endpoint/NO_PROXY), never credentials.
    for key in _PROXY_PRESENCE_ENV_KEYS:
        raw = os.environ.get(key)
        digest.update(key.encode("utf-8"))
        digest.update(b"=")
        if raw:
            digest.update(_proxy_route_identity(key, raw).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _combine_config_hashes(*parts: str | None) -> str | None:
    present = [p for p in parts if p]
    if not present:
        return None
    digest = hashlib.sha256()
    for part in present:
        digest.update(part.encode("utf-8"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _capture_runtime_provenance(
    plan: RunPlan,
    *,
    profile: RuntimeProfile | None = None,
) -> _RuntimeProvenance | None:
    """Best-effort runtime version + config hash; leave None on any capture failure.

    Harbor runtimes execute the agent inside the harness container, so the host
    ``version_command`` cannot prove what ran: skip the host probe and fold the
    profile's ``agent_version_pin`` into the config hash instead. The evidence
    row's ``runtime_version`` for Harbor runs is stamped from the trial
    result's ``agent_info`` (see :func:`_evidence_from_outcome`).
    """
    if plan.runtime_id is None:
        return None
    if profile is None:
        try:
            profile = load_runtime_catalog().by_id(plan.runtime_id)
        except BenchEvalError:
            return _RuntimeProvenance(runtime_version=None, runtime_config_hash=None)
    env_hash = _hash_effective_runtime_options(plan=plan)
    file_hash = _hash_config_inputs(
        profile.versioning.config_hash_inputs,
        root=_repo_root(),
    )
    if plan.requires_harbor:
        pin = profile.versioning.agent_version_pin
        pin_part = f"agent_version_pin={pin.strip()}" if pin and pin.strip() else None
        config_hash = _combine_config_hashes(file_hash, env_hash, pin_part)
        return _RuntimeProvenance(runtime_version=None, runtime_config_hash=config_hash)
    version = _run_version_command(profile.versioning.version_command)
    config_hash = _combine_config_hashes(file_hash, env_hash)
    return _RuntimeProvenance(runtime_version=version, runtime_config_hash=config_hash)


def _apply_provenance(
    record: EvidenceRecord,
    provenance: _RuntimeProvenance | None,
    provider_config_hash: str,
) -> EvidenceRecord:
    update: dict[str, str | None] = {"provider_config_hash": provider_config_hash}
    if provenance is not None:
        update["runtime_config_hash"] = provenance.runtime_config_hash
        # Keep a row-carried runtime_version (Harbor rows carry the
        # container-side agent_info version); the host probe only fills rows
        # that carry none.
        if record.runtime_version is None:
            update["runtime_version"] = provenance.runtime_version
    return record.model_copy(
        update=update,
    )


@dataclass(frozen=True, slots=True)
class _ProvenanceEvidenceSink:
    """Jsonl sink that stamps runtime provenance onto every appended row."""

    inner: JsonlEvidenceSink
    provenance: _RuntimeProvenance | None
    provider_config_hash: str

    def append_jsonl(self, path: Path, record: EvidenceRecord) -> None:
        self.inner.append_jsonl(
            path,
            _apply_provenance(record, self.provenance, self.provider_config_hash),
        )


def _evidence_sink(plan: RunPlan) -> _ProvenanceEvidenceSink:
    provider_config_hash = resolve_openai_compatible_launch(
        plan.provider_id,
        require_api_key=False,
    ).config_hash
    return _ProvenanceEvidenceSink(
        JsonlEvidenceSink(),
        _capture_runtime_provenance(plan),
        provider_config_hash,
    )


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
    if plan.diagnostic:
        return "diagnostic"
    if plan.benchmark_id == "swe-bench-verified":
        return "contaminated_or_legacy"
    validity = plan.comparison_validity
    if validity == "invalid":
        return "rough_regression"
    if validity == "diagnostic_only":
        return "benchmark_native_claim"
    if validity in ("model_comparison", "runtime_comparison", "adapter_smoke", "rough_regression"):
        return validity
    return "adapter_smoke"


def _contamination_label(plan: RunPlan) -> str | None:
    if any("contamination" in c for c in plan.caveats):
        return "public_possible"
    return None


def _backend_for_plan(plan: RunPlan) -> ExecutionBackend:
    # BFCL/GPQA/HLE are all model-only inspect-driven adapters; their scored
    # rows stamp INSPECT_BACKEND, so budget-skip and adapter-failure rows must
    # stamp the same backend (review F004: bfcl was omitted here and mixed
    # "harbor" failure rows into "inspect" runs).
    if plan.adapter_id in (GPQA_ADAPTER_ID, HLE_ADAPTER_ID, BFCL_ADAPTER_ID):
        return INSPECT_BACKEND
    return HARBOR_BACKEND


def _evidence_from_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: TerminalBenchInstanceOutcome,
    execution_profile: ExecutionProfile,
    cleanup_result: CleanupResult | None = None,
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
    # Stamp native only when Harbor produced an identity-bound result artifact.
    verifier_label = "native" if outcome.raw_result_path else None

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
        benchmark_version=_evidence_benchmark_version(plan, outcome.adapter_metadata),
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        harness_version=outcome.adapter_metadata.get("harness_version"),
        runtime_id=plan.runtime_id,
        runtime_kind=plan.runtime_kind,
        # Harbor rows carry the container-side agent version from the trial
        # result's agent_info; _apply_provenance keeps it (the host probe is
        # skipped for Harbor plans and only fills rows that carry none).
        runtime_version=outcome.agent_version,
        agent_id=plan.agent_id,
        provider_id=plan.provider_id,
        judge_model_id=plan.judge_model_id,
        instance_id=outcome.instance_id,
        native_score=outcome.native_score,
        normalized_score=outcome.partial_score,
        interpretation_label=_interpretation_label(plan),
        contamination_label=_contamination_label(plan),
        failure_class=outcome.failure_class,
        cleanup_result=cleanup_result,
        verifier_integrity_label=verifier_label,
    )


def _record_budget_skip(
    *,
    plan: RunPlan,
    run_id: str,
    instance_id: str,
    execution_profile: ExecutionProfile,
    spent_cost_usd: float,
    spent_wall_sec: float,
) -> EvidenceRecord:
    """Evidence row for an instance never launched because the run envelope was exhausted."""
    return EvidenceRecord(
        run_id=run_id,
        task_id=instance_id,
        model_id=plan.model_id,
        execution_profile=execution_profile,
        backend=_backend_for_plan(plan),
        primary_pass=False,
        partial_score=0.0,
        cost_usd=0.0,
        latency_sec=0.0,
        failure_labels=["runtime_budget_exceeded"],
        artifact_paths=[],
        adapter_metadata={
            "adapter_id": plan.adapter_id,
            "spent_cost_usd": f"{spent_cost_usd:.6f}",
            "spent_wall_sec": f"{spent_wall_sec:.3f}",
            "max_cost_usd": f"{plan.max_cost_usd:.6f}",
            "max_wall_clock_sec": str(plan.max_wall_clock_sec),
            "max_wall_clock_sec_per_instance": str(plan.max_wall_clock_sec_per_instance),
        },
        created_at=datetime.now(tz=UTC),
        benchmark_id=plan.benchmark_id,
        benchmark_version=_evidence_benchmark_version(plan),
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        runtime_id=plan.runtime_id,
        runtime_kind=plan.runtime_kind,
        agent_id=plan.agent_id,
        provider_id=plan.provider_id,
        judge_model_id=plan.judge_model_id,
        instance_id=instance_id,
        interpretation_label=_interpretation_label(plan),
        contamination_label=_contamination_label(plan),
        failure_class="runtime_budget_exceeded",
        cleanup_result="skipped",
    )


def _apply_cleanup(
    *,
    plan: RunPlan,
    instance_artifacts: Path,
    primary_pass: bool,
) -> CleanupResult:
    report = cleanup_transient_artifacts(
        instance_artifacts,
        policy=plan.cleanup_policy,
        primary_pass=primary_pass,
    )
    if not report.attempted:
        return "skipped"
    return "success" if report.removed_paths else "skipped"


def _evidence_benchmark_version(
    plan: RunPlan,
    adapter_metadata: Mapping[str, str] | None = None,
) -> str | None:
    """Prefer captured release/adapter identity over provisional planner labels.

    Terminal-Bench stamps its pinned release; the gpqa/hle/bfcl adapters stamp
    their verified pinned identity into ``adapter_metadata["benchmark_version"]``
    after pre-launch verification, which wins over the plan's provisional label.
    When the adapter captured nothing, the provisional plan label stands and
    qualification keeps failing closed on it.
    """
    if plan.adapter_id == TERMINAL_BENCH_ADAPTER_ID:
        return TERMINAL_BENCH_RELEASE_VERSION
    if adapter_metadata:
        captured = adapter_metadata.get("benchmark_version")
        if captured:
            return captured
    return plan.benchmark_version


def _budget_exhausted(plan: RunPlan, *, spent_cost_usd: float, spent_wall_sec: float) -> bool:
    cost_hit = plan.max_cost_usd > 0 and spent_cost_usd >= plan.max_cost_usd
    wall_hit = plan.max_wall_clock_sec > 0 and spent_wall_sec >= plan.max_wall_clock_sec
    return cost_hit or wall_hit


def _record_instance_failure(
    *,
    plan: RunPlan,
    run_id: str,
    instance_id: str,
    execution_profile: ExecutionProfile,
    error: AdapterFailureError,
    artifacts_dir: Path,
    cleanup_result: CleanupResult | None = None,
) -> EvidenceRecord:
    failure_log = artifacts_dir / "adapter_failure.json"
    # open_owned_dir_fd creates the parent when missing and converts OSError
    # to BenchEvalError (e.g. FileExistsError when the agent swapped the
    # instance dir to a regular file) instead of leaking a raw traceback out
    # of this failure handler. The anchored, no-follow, exclusive recreate
    # then unlinks a planted symlink or hard link (never opening, truncating,
    # or following it) and replaces it with a fresh regular file.
    failure_log_fd = open_owned_dir_fd(
        failure_log.parent,
        role="instance failure-log directory",
    )
    try:
        write_text_at_exclusive(
            failure_log_fd,
            failure_log.name,
            json.dumps(
                {
                    "instance_id": instance_id,
                    "failure_label": error.failure_label,
                    "message": str(error),
                },
                indent=2,
            )
            + "\n",
        )
    finally:
        os.close(failure_log_fd)
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
        benchmark_version=_evidence_benchmark_version(plan, metadata),
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        runtime_id=plan.runtime_id,
        runtime_kind=plan.runtime_kind,
        agent_id=plan.agent_id,
        provider_id=plan.provider_id,
        judge_model_id=plan.judge_model_id,
        instance_id=instance_id,
        interpretation_label=_interpretation_label(plan),
        contamination_label=_contamination_label(plan),
        failure_class=(
            error.failure_label if error.failure_label in _FAILURE_LABELS else "adapter_error"
        ),
        cleanup_result=cleanup_result,
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
    cleanup_result: CleanupResult | None = None,
) -> EvidenceRecord:
    artifact_paths = [p for p in paths if p]
    failure_labels: list[str] = []
    if not primary_pass and failure_class:
        failure_labels.append(failure_class)
    # Official/native scorer path only — stdout/stderr alone never authorize native.
    verifier_label = "native" if verifier_log_path else None
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
        benchmark_version=_evidence_benchmark_version(plan, adapter_metadata),
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        harness_version=adapter_metadata.get("harness_version"),
        runtime_id=plan.runtime_id,
        runtime_kind=plan.runtime_kind,
        agent_id=plan.agent_id,
        provider_id=plan.provider_id,
        judge_model_id=plan.judge_model_id,
        instance_id=instance_id,
        native_score=native_score,
        normalized_score=partial_score,
        interpretation_label=_interpretation_label(plan),
        contamination_label=_contamination_label(plan),
        failure_class=failure_class,
        cleanup_result=cleanup_result,
        counts_toward_pass_at_k=counts_toward_pass_at_k,
        verifier_integrity_label=verifier_label,
    )


def _evidence_from_gpqa_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: GpqaInstanceOutcome,
    execution_profile: ExecutionProfile,
    cleanup_result: CleanupResult | None = None,
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
        cleanup_result=cleanup_result,
    )


def _evidence_from_hle_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: HleInstanceOutcome,
    execution_profile: ExecutionProfile,
    cleanup_result: CleanupResult | None = None,
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
        cleanup_result=cleanup_result,
    )


def _evidence_from_bfcl_outcome(
    *,
    plan: RunPlan,
    run_id: str,
    outcome: BfclInstanceOutcome,
    execution_profile: ExecutionProfile,
    cleanup_result: CleanupResult | None = None,
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
        cleanup_result=cleanup_result,
    )


# Adapters with a real executor dispatch in this module; ``--diagnostic`` may
# relax the catalog ``executable`` gate only for these.
_DIAGNOSTIC_CAPABLE_ADAPTER_IDS = frozenset(
    {TERMINAL_BENCH_ADAPTER_ID, GPQA_ADAPTER_ID, HLE_ADAPTER_ID, BFCL_ADAPTER_ID},
)


def diagnostic_capable_benchmark(benchmark: BenchmarkEntry) -> bool:
    """True when a demoted benchmark still has a wired executor dispatch."""
    return benchmark.adapter_id in _DIAGNOSTIC_CAPABLE_ADAPTER_IDS


def _require_executable_benchmark(plan: RunPlan) -> None:
    catalog = load_benchmark_catalog()
    benchmark = catalog.by_id_or_alias(plan.benchmark_id)
    support = execution_support_label(benchmark)
    if support == "executable_adapter":
        return
    # Explicitly opted-in diagnostic runs may execute a demoted benchmark, but
    # only when its adapter has a real dispatch path below — a diagnostic run
    # is still a real launch, never an invented one, and its evidence can never
    # register ``passed`` (the registration gate re-checks ``executable``).
    if plan.diagnostic and plan.adapter_id in _DIAGNOSTIC_CAPABLE_ADAPTER_IDS:
        return
    hint = (
        "; opt in with --diagnostic for a labeled, non-registering run"
        if plan.adapter_id in _DIAGNOSTIC_CAPABLE_ADAPTER_IDS
        else ""
    )
    raise BenchEvalError(
        f"benchmark {plan.benchmark_id!r} has execution_support={support!r}; "
        f"control-plane execute requires executable_adapter{hint}",
    )


def _claim_control_plane_outputs(
    *,
    output_path: Path,
    artifacts_dir: Path | None,
    rid: str,
    root: Path,
) -> Path:
    """Exclusive evidence file + empty run-artifacts tree for one control-plane run."""
    run_artifacts = artifacts_dir or (root / "results" / "raw" / rid)
    claim_exclusive_run_outputs(evidence_path=output_path, artifacts_path=run_artifacts)
    return run_artifacts


def execute_control_plane_run(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None = None,
    harbor_process_runner: HarborProcessRunner | None = None,
    gpqa_process_runner: GpqaProcessRunner | None = None,
    hle_process_runner: HleProcessRunner | None = None,
    bfcl_process_runner: BfclProcessRunner | None = None,
    agent_process_runner: ExternalAgentProcessRunner | None = None,
    momo_process_runner: ExternalAgentProcessRunner | None = None,
    gpqa_benchmark_identity: str | None = None,
    hle_benchmark_identity: str | None = None,
    bfcl_benchmark_identity: str | None = None,
    run_id: str | None = None,
) -> ControlPlaneRunSummary:
    """Dispatch a ``RunPlan`` to the matching adapter and append evidence rows."""
    if plan.agent_id is not None:
        try:
            require_admitted_agent(plan.agent_id)
        except KeyError as e:
            raise BenchEvalError(f"unknown agent {plan.agent_id!r}") from e
    _require_executable_benchmark(plan)
    if plan.adapter_id == GPQA_ADAPTER_ID:
        return _execute_gpqa(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            gpqa_process_runner=gpqa_process_runner,
            gpqa_benchmark_identity=gpqa_benchmark_identity,
            run_id=run_id,
        )
    if plan.adapter_id == HLE_ADAPTER_ID:
        return _execute_hle(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            hle_process_runner=hle_process_runner,
            hle_benchmark_identity=hle_benchmark_identity,
            run_id=run_id,
        )
    if plan.adapter_id == BFCL_ADAPTER_ID:
        return _execute_bfcl(
            plan=plan,
            output_path=output_path,
            artifacts_dir=artifacts_dir,
            bfcl_process_runner=bfcl_process_runner,
            bfcl_benchmark_identity=bfcl_benchmark_identity,
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
    raise BenchEvalError(
        f"no executor for adapter_id={plan.adapter_id!r}; "
        f"supported: {TERMINAL_BENCH_ADAPTER_ID!r}, {GPQA_ADAPTER_ID!r}, "
        f"{HLE_ADAPTER_ID!r}, {BFCL_ADAPTER_ID!r}",
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
    run_artifacts = _claim_control_plane_outputs(
        output_path=output_path,
        artifacts_dir=artifacts_dir,
        rid=rid,
        root=root,
    )
    try:
        if harbor_process_runner is None:
            require_doctor_ok(run_doctor(HARBOR_BACKEND, model_id=plan.model_id))
        sink = _evidence_sink(plan)
        execution_profile = _execution_profile_for_plan(plan)

        passed = 0
        spent_cost_usd = 0.0
        spent_wall_sec = 0.0
        for inst in plan.instances:
            instance_id = inst.instance_id
            if _budget_exhausted(
                plan,
                spent_cost_usd=spent_cost_usd,
                spent_wall_sec=spent_wall_sec,
            ):
                record = _record_budget_skip(
                    plan=plan,
                    run_id=rid,
                    instance_id=instance_id,
                    execution_profile=execution_profile,
                    spent_cost_usd=spent_cost_usd,
                    spent_wall_sec=spent_wall_sec,
                )
                sink.append_jsonl(output_path, record)
                continue
            instance_artifacts = run_artifacts / instance_id
            try:
                outcome = run_terminal_bench_instance(
                    plan=plan,
                    instance_id=instance_id,
                    artifacts_dir=run_artifacts,
                    repo_root=root,
                    process_runner=harbor_process_runner,
                )
                cleanup_result = _apply_cleanup(
                    plan=plan,
                    instance_artifacts=instance_artifacts,
                    primary_pass=outcome.primary_pass,
                )
                record = _evidence_from_outcome(
                    plan=plan,
                    run_id=rid,
                    outcome=outcome,
                    execution_profile=execution_profile,
                    cleanup_result=cleanup_result,
                )
            except AdapterFailureError as e:
                cleanup_result = _apply_cleanup(
                    plan=plan,
                    instance_artifacts=instance_artifacts,
                    primary_pass=False,
                )
                record = _record_instance_failure(
                    plan=plan,
                    run_id=rid,
                    instance_id=instance_id,
                    execution_profile=execution_profile,
                    error=e,
                    artifacts_dir=instance_artifacts,
                    cleanup_result=cleanup_result,
                )
            spent_cost_usd += record.cost_usd
            spent_wall_sec += record.latency_sec
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
    finally:
        release_evidence_reservation(output_path)


def _execute_gpqa(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None,
    gpqa_process_runner: GpqaProcessRunner | None,
    gpqa_benchmark_identity: str | None = None,
    run_id: str | None,
) -> ControlPlaneRunSummary:
    root = _repo_root()
    rid = run_id or new_run_id()
    if gpqa_process_runner is None:
        require_doctor_ok(run_doctor(INSPECT_BACKEND, model_id=plan.model_id))
    run_artifacts = _claim_control_plane_outputs(
        output_path=output_path,
        artifacts_dir=artifacts_dir,
        rid=rid,
        root=root,
    )
    try:
        sink = _evidence_sink(plan)
        execution_profile = _execution_profile_for_plan(plan)
        try:
            outcomes = run_gpqa_slice(
                plan=plan,
                artifacts_dir=run_artifacts,
                repo_root=root,
                process_runner=gpqa_process_runner,
                benchmark_identity=gpqa_benchmark_identity,
            )
        except AdapterFailureError as e:
            cleanup_result = _apply_cleanup(
                plan=plan,
                instance_artifacts=run_artifacts,
                primary_pass=False,
            )
            for inst in plan.instances:
                record = _record_instance_failure(
                    plan=plan,
                    run_id=rid,
                    instance_id=inst.instance_id,
                    execution_profile=execution_profile,
                    error=e,
                    artifacts_dir=run_artifacts,
                    cleanup_result=cleanup_result,
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
        cleanup_result = _apply_cleanup(
            plan=plan,
            instance_artifacts=run_artifacts,
            primary_pass=any(o.primary_pass for o in outcomes),
        )
        passed = 0
        for outcome in outcomes:
            record = _evidence_from_gpqa_outcome(
                plan=plan,
                run_id=rid,
                outcome=outcome,
                execution_profile=execution_profile,
                cleanup_result=cleanup_result,
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
    finally:
        release_evidence_reservation(output_path)


def _execute_hle(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None,
    hle_process_runner: HleProcessRunner | None,
    hle_benchmark_identity: str | None = None,
    run_id: str | None,
) -> ControlPlaneRunSummary:
    root = _repo_root()
    rid = run_id or new_run_id()
    run_artifacts = _claim_control_plane_outputs(
        output_path=output_path,
        artifacts_dir=artifacts_dir,
        rid=rid,
        root=root,
    )
    try:
        sink = _evidence_sink(plan)
        execution_profile = _execution_profile_for_plan(plan)
        try:
            outcomes = run_hle_slice(
                plan=plan,
                artifacts_dir=run_artifacts,
                repo_root=root,
                process_runner=hle_process_runner,
                run_id=rid,
                benchmark_identity=hle_benchmark_identity,
            )
        except AdapterFailureError as e:
            cleanup_result = _apply_cleanup(
                plan=plan,
                instance_artifacts=run_artifacts,
                primary_pass=False,
            )
            for inst in plan.instances:
                record = _record_instance_failure(
                    plan=plan,
                    run_id=rid,
                    instance_id=inst.instance_id,
                    execution_profile=execution_profile,
                    error=e,
                    artifacts_dir=run_artifacts,
                    cleanup_result=cleanup_result,
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
        cleanup_result = _apply_cleanup(
            plan=plan,
            instance_artifacts=run_artifacts,
            primary_pass=any(o.primary_pass for o in outcomes),
        )
        passed = 0
        for outcome in outcomes:
            record = _evidence_from_hle_outcome(
                plan=plan,
                run_id=rid,
                outcome=outcome,
                execution_profile=execution_profile,
                cleanup_result=cleanup_result,
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
    finally:
        release_evidence_reservation(output_path)


def _execute_bfcl(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None,
    bfcl_process_runner: BfclProcessRunner | None,
    bfcl_benchmark_identity: str | None = None,
    run_id: str | None,
) -> ControlPlaneRunSummary:
    root = _repo_root()
    rid = run_id or new_run_id()
    run_artifacts = _claim_control_plane_outputs(
        output_path=output_path,
        artifacts_dir=artifacts_dir,
        rid=rid,
        root=root,
    )
    try:
        sink = _evidence_sink(plan)
        execution_profile = _execution_profile_for_plan(plan)
        # Injected-runner boundary: the caller owns the test seam, so the
        # executor supplies the manifest-pinned harness label for it; the real
        # path recaptures the installed distribution identity inside the
        # adapter immediately before launch.
        harness_version = bfcl_pinned_harness_version() if bfcl_process_runner is not None else None

        passed = 0
        spent_cost_usd = 0.0
        spent_wall_sec = 0.0
        for inst in plan.instances:
            instance_id = inst.instance_id
            if _budget_exhausted(
                plan,
                spent_cost_usd=spent_cost_usd,
                spent_wall_sec=spent_wall_sec,
            ):
                record = _record_budget_skip(
                    plan=plan,
                    run_id=rid,
                    instance_id=instance_id,
                    execution_profile=execution_profile,
                    spent_cost_usd=spent_cost_usd,
                    spent_wall_sec=spent_wall_sec,
                )
                sink.append_jsonl(output_path, record)
                continue
            instance_artifacts = run_artifacts / instance_id
            try:
                outcome = run_bfcl_instance(
                    plan=plan,
                    instance_id=instance_id,
                    artifacts_dir=run_artifacts,
                    repo_root=root,
                    process_runner=bfcl_process_runner,
                    harness_version=harness_version,
                    benchmark_identity=bfcl_benchmark_identity,
                )
                cleanup_result = _apply_cleanup(
                    plan=plan,
                    instance_artifacts=instance_artifacts,
                    primary_pass=outcome.primary_pass,
                )
                record = _evidence_from_bfcl_outcome(
                    plan=plan,
                    run_id=rid,
                    outcome=outcome,
                    execution_profile=execution_profile,
                    cleanup_result=cleanup_result,
                )
            except AdapterFailureError as e:
                cleanup_result = _apply_cleanup(
                    plan=plan,
                    instance_artifacts=instance_artifacts,
                    primary_pass=False,
                )
                record = _record_instance_failure(
                    plan=plan,
                    run_id=rid,
                    instance_id=instance_id,
                    execution_profile=execution_profile,
                    error=e,
                    artifacts_dir=instance_artifacts,
                    cleanup_result=cleanup_result,
                )
            spent_cost_usd += record.cost_usd
            spent_wall_sec += record.latency_sec
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
    finally:
        release_evidence_reservation(output_path)


__all__ = [
    "ControlPlaneRunSummary",
    "control_plane_interpretation_label",
    "diagnostic_capable_benchmark",
    "execute_control_plane_run",
]
