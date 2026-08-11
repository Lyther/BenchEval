"""External agent adapter — invoke agent CLI from ``config/agents/*.yaml``.

Capture boundary (same-uid threat model): BenchEval-owned captures live in a
sibling root derived from the artifacts root name — OUTSIDE the agent-visible
``--output-dir`` tree (a hidden sibling inside that tree is not a capability
boundary) — and are byte-verified at capture time. A same-uid mutator with
arbitrary write reach AFTER publication is detected via the digests recorded
in ``adapter_metadata`` (``stdout_sha256``/``stderr_sha256``), not prevented.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

from bencheval.agent_registry import load_agent_catalog
from bencheval.backends import LOCAL_BACKEND
from bencheval.domain import CleanupResult, ExecutionProfile, FailureLabel, RunPlan
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.ids import new_run_id
from bencheval.lifecycle import cleanup_transient_artifacts
from bencheval.path_safety import ensure_resolved_under_root, validate_control_plane_instance_id
from bencheval.paths import repo_root as _repo_root
from bencheval.provider_registry import resolve_openai_compatible_launch
from bencheval.run_isolation import (
    dir_identity_error,
    open_owned_dir_fd,
    reject_symlink_path,
    release_evidence_reservation,
    write_text_at_exclusive,
)

ExternalAgentProcessRunner = Callable[..., "ExternalAgentCliResult"]
_FAILURE_LABELS = frozenset(get_args(FailureLabel))


@dataclass(frozen=True, slots=True)
class ExternalAgentCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExternalAgentInstanceOutcome:
    """One agent attempt; log paths bind to the BenchEval-owned capture tree.

    The capture tree lives outside the agent-visible ``--output-dir`` root
    and its bytes are verified at capture time; ``adapter_metadata`` records
    ``stdout_sha256``/``stderr_sha256`` of the verified bytes so a same-uid
    mutator replacing the files after publication is detected, not prevented.
    """

    instance_id: str
    primary_pass: bool
    partial_score: float
    cost_usd: float
    latency_sec: float
    failure_class: FailureLabel | None
    stdout_path: str | None
    stderr_path: str | None
    adapter_metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class ExternalAgentRunSummary:
    run_id: str
    instance_count: int
    passed_count: int
    failed_count: int
    output_path: Path


def adapter_id_for_agent(agent_id: str) -> str:
    return f"{agent_id}-agent"


def build_external_agent_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[str, ...]:
    if not plan.agent_id:
        raise BenchEvalError("external agent adapter requires plan.agent_id")
    profile = load_agent_catalog().by_id(plan.agent_id)
    cmd = list(profile.agent.command)
    cmd.extend(
        [
            "run",
            "--benchmark",
            plan.benchmark_id,
            "--instance",
            instance_id,
            "--model",
            plan.model_id,
            "--provider",
            plan.provider_id,
            "--output-dir",
            str(artifacts_dir.resolve()),
        ],
    )
    return tuple(cmd)


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
) -> ExternalAgentCliResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"agent timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"agent_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"agent launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"agent_command": " ".join(command)},
        ) from e
    return ExternalAgentCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def _default_capture_root(artifacts_root: Path) -> Path:
    """BenchEval-owned capture root: a SIBLING of the agent-visible tree.

    The launched agent is handed ``<artifacts_root>/<instance_id>`` as
    ``--output-dir`` and can derive the parent, so a hidden child of that
    tree is not a capability boundary; the capture root lives next to it.
    """
    return artifacts_root.parent / f"{artifacts_root.name}.capture"


def _open_instance_dir_fd(artifacts_root: Path, instance_id: str) -> int:
    """Open the instance directory and return a directory file descriptor.

    The post-launch identity check is anchored to this descriptor (see
    ``dir_identity_error``): a launched agent that swaps the directory path —
    symlink or rename-and-recreate — can neither redirect our capture writes
    nor substitute forged evidence.
    """
    instance_dir = artifacts_root / instance_id
    if instance_dir.is_symlink():
        raise BenchEvalError(
            f"refusing to use symlink instance directory: {instance_dir}",
        )
    if instance_dir.exists() and not instance_dir.is_dir():
        raise BenchEvalError(
            f"instance directory is not a directory: {instance_dir}",
        )
    instance_dir = ensure_resolved_under_root(
        instance_dir,
        artifacts_root,
        what="instance directory",
    )
    instance_dir.mkdir(parents=True, exist_ok=True)
    return os.open(instance_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _open_capture_dir_fd(capture_root: Path, instance_id: str) -> int:
    """Open the BenchEval-owned capture directory for one instance.

    The launched agent is told only about its ``--output-dir``; the capture
    tree is never shared with it and lives outside the agent-visible
    artifacts root. Returned log paths therefore bind to a host-owned
    location the agent cannot derive from its output dir, so a post-write
    replacement targeting the agent-known paths cannot forge the evidence
    BenchEval captured.
    """
    capture_dir = capture_root / instance_id
    reject_symlink_path(capture_dir, role="capture directory")
    if capture_dir.exists() and not capture_dir.is_dir():
        raise BenchEvalError(
            f"capture directory is not a directory: {capture_dir}",
        )
    capture_dir = ensure_resolved_under_root(
        capture_dir,
        capture_root,
        what="capture directory",
    )
    return open_owned_dir_fd(capture_dir, role="capture directory")


def _read_text_at(dir_fd: int, name: str) -> str:
    """Read ``name`` relative to an open directory fd without following links."""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    with os.fdopen(fd, encoding="utf-8") as handle:
        return handle.read()


def _capture_content_error(capture_fd: int, cli: ExternalAgentCliResult) -> str | None:
    """None when the capture files still hold exactly the bytes BenchEval wrote.

    A same-uid mutator that located the capture tree and swapped a log after
    the write is caught by this byte-for-byte read-back comparison.
    """
    try:
        stdout_now = _read_text_at(capture_fd, "stdout.log")
        stderr_now = _read_text_at(capture_fd, "stderr.log")
    except OSError as e:
        return f"failed to verify captured agent logs: {e}"
    if stdout_now != cli.stdout or stderr_now != cli.stderr:
        return "captured agent logs were replaced during execution"
    return None


def run_external_agent_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: ExternalAgentProcessRunner | None = None,
    timeout_sec: int | None = None,
    capture_root: Path | None = None,
) -> ExternalAgentInstanceOutcome:
    """Run one agent attempt and capture its logs under BenchEval ownership.

    The capture tree defaults to a sibling of the agent-visible artifacts
    root (``<artifacts_root>.capture``) so the launched agent — handed only
    ``--output-dir`` — cannot derive it. Captured bytes are verified by
    read-back before publication; ``adapter_metadata`` records their sha256
    digests so post-publication tampering by a same-uid mutator is detected,
    not prevented.
    """
    validate_control_plane_instance_id(instance_id)
    artifacts_root = artifacts_dir.resolve()
    instance_dir = artifacts_root / instance_id
    resolved_capture_root = capture_root or _default_capture_root(artifacts_root)
    capture_dir = resolved_capture_root / instance_id
    dir_fd = _open_instance_dir_fd(artifacts_root, instance_id)
    try:
        capture_fd = _open_capture_dir_fd(resolved_capture_root, instance_id)
    except BaseException:
        # Never leak the instance-dir descriptor, whatever the open raises.
        os.close(dir_fd)
        raise
    try:
        command = build_external_agent_command(
            plan=plan,
            instance_id=instance_id,
            artifacts_dir=instance_dir,
        )
        runner = process_runner or _default_process_runner
        if timeout_sec is not None:
            wall = timeout_sec
        else:
            wall = max(1, plan.max_wall_clock_sec_per_instance)
        cli = runner(command, cwd=repo_root, timeout_sec=wall)
        write_error: BenchEvalError | None = None
        try:
            write_text_at_exclusive(capture_fd, "stdout.log", cli.stdout)
            write_text_at_exclusive(capture_fd, "stderr.log", cli.stderr)
        except BenchEvalError as e:
            # e.g. a same-uid mutator unlinked the capture directory mid-run:
            # the dirfd-anchored create fails with ENOENT instead of escaping
            # through a swapped path. Fail closed below; never fall back to
            # pathname writes.
            write_error = e
        for held_fd, path, role in (
            (dir_fd, instance_dir, "instance directory"),
            (capture_fd, capture_dir, "capture directory"),
        ):
            identity_error = dir_identity_error(held_fd, path, role=role)
            if identity_error is not None:
                # A mutator swapped an approved directory mid-run (symlink or
                # rename-and-recreate). The dirfd-anchored writes stayed on
                # the approved inode; fail the attempt as corrupt instead of
                # returning paths that now name attacker-controlled content.
                raise AdapterFailureError(
                    identity_error,
                    failure_label="evidence_corrupt",
                    latency_sec=cli.latency_sec,
                    adapter_metadata={"agent_command": " ".join(cli.command)},
                )
        if write_error is not None:
            raise AdapterFailureError(
                f"failed to capture agent logs under {capture_dir}: {write_error}",
                failure_label="materialization_failure",
                latency_sec=cli.latency_sec,
                adapter_metadata={"agent_command": " ".join(cli.command)},
            )
        content_error = _capture_content_error(capture_fd, cli)
        if content_error is not None:
            raise AdapterFailureError(
                content_error,
                failure_label="evidence_corrupt",
                latency_sec=cli.latency_sec,
                adapter_metadata={"agent_command": " ".join(cli.command)},
            )
    finally:
        os.close(capture_fd)
        os.close(dir_fd)
    stdout_path = capture_dir / "stdout.log"
    stderr_path = capture_dir / "stderr.log"

    # Exit 0 means the agent command completed — not a benchmark pass.
    # Anything under --output-dir is agent-writable and cannot be scoring
    # authority; official verifier wiring remains pending.
    primary_pass = False
    partial_score = 0.0
    failure: FailureLabel | None = None
    metadata: dict[str, str] = {
        "agent_id": plan.agent_id or "",
        "agent_command": " ".join(cli.command),
        "returncode": str(cli.returncode),
        # Digests of the verified captured bytes: downstream consumers can
        # detect post-publication replacement of the capture files.
        "stdout_sha256": hashlib.sha256(cli.stdout.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(cli.stderr.encode("utf-8")).hexdigest(),
    }

    if cli.returncode != 0:
        failure = "runtime_tool_failure"
    else:
        failure = "harness_failure"
        metadata["scoring"] = "missing_verifier_artifact"

    return ExternalAgentInstanceOutcome(
        instance_id=instance_id,
        primary_pass=primary_pass,
        partial_score=partial_score,
        cost_usd=0.0,
        latency_sec=cli.latency_sec,
        failure_class=failure,
        stdout_path=str(stdout_path.resolve()),
        stderr_path=str(stderr_path.resolve()),
        adapter_metadata=metadata,
    )


def _agent_cleanup_result(
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


def _agent_budget_skip_record(
    *,
    plan: RunPlan,
    run_id: str,
    instance_id: str,
    profile: ExecutionProfile,
    adapter_id: str,
    provider_config_hash: str,
    spent_cost_usd: float,
    spent_wall_sec: float,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=run_id,
        task_id=instance_id,
        model_id=plan.model_id,
        execution_profile=profile,
        backend=LOCAL_BACKEND,
        primary_pass=False,
        partial_score=0.0,
        cost_usd=0.0,
        latency_sec=0.0,
        failure_labels=["runtime_budget_exceeded"],
        artifact_paths=[],
        adapter_metadata={
            "adapter_id": adapter_id,
            "agent_id": plan.agent_id or "",
            "spent_cost_usd": f"{spent_cost_usd:.6f}",
            "spent_wall_sec": f"{spent_wall_sec:.3f}",
        },
        created_at=datetime.now(tz=UTC),
        benchmark_id=plan.benchmark_id,
        benchmark_version=plan.benchmark_version,
        slice_id=plan.slice_id,
        adapter_id=adapter_id,
        harness_kind=plan.harness_kind,
        runtime_id=None,
        runtime_kind=None,
        agent_id=plan.agent_id,
        provider_id=plan.provider_id,
        provider_config_hash=provider_config_hash,
        judge_model_id=plan.judge_model_id,
        instance_id=instance_id,
        failure_class="runtime_budget_exceeded",
        cleanup_result="skipped",
    )


def execute_external_agent_run(
    *,
    plan: RunPlan,
    output_path: Path,
    artifacts_dir: Path | None = None,
    process_runner: ExternalAgentProcessRunner | None = None,
    run_id: str | None = None,
) -> ExternalAgentRunSummary:
    if not plan.agent_id:
        raise BenchEvalError("external agent run requires plan.agent_id")
    from bencheval.run_isolation import claim_exclusive_run_outputs

    root = _repo_root()
    rid = run_id or new_run_id()
    run_artifacts = artifacts_dir or (root / "results" / "raw" / rid)
    claim_exclusive_run_outputs(evidence_path=output_path, artifacts_path=run_artifacts)
    try:
        sink = JsonlEvidenceSink()
        profile: ExecutionProfile = "E1"
        provider_config_hash = resolve_openai_compatible_launch(
            plan.provider_id,
            require_api_key=False,
        ).config_hash
        # Keep benchmark adapter identity; agent_id is a separate scaffold axis.
        adapter_id = plan.adapter_id
        passed = 0
        spent_cost_usd = 0.0
        spent_wall_sec = 0.0
        for inst in plan.instances:
            instance_id = inst.instance_id
            cost_hit = plan.max_cost_usd > 0 and spent_cost_usd >= plan.max_cost_usd
            wall_hit = plan.max_wall_clock_sec > 0 and spent_wall_sec >= plan.max_wall_clock_sec
            if cost_hit or wall_hit:
                record = _agent_budget_skip_record(
                    plan=plan,
                    run_id=rid,
                    instance_id=instance_id,
                    profile=profile,
                    adapter_id=adapter_id,
                    provider_config_hash=provider_config_hash,
                    spent_cost_usd=spent_cost_usd,
                    spent_wall_sec=spent_wall_sec,
                )
                sink.append_jsonl(output_path, record)
                continue
            try:
                # Both wall budgets bind every attempt: the run's remaining total
                # and the per-instance ceiling (docs/architecture.md §9).
                remaining = max(1, int(plan.max_wall_clock_sec - spent_wall_sec))
                per_instance = min(remaining, plan.max_wall_clock_sec_per_instance)
                outcome = run_external_agent_instance(
                    plan=plan,
                    instance_id=instance_id,
                    artifacts_dir=run_artifacts,
                    repo_root=root,
                    process_runner=process_runner,
                    timeout_sec=per_instance,
                )
                cleanup_result = _agent_cleanup_result(
                    plan=plan,
                    instance_artifacts=run_artifacts / instance_id,
                    primary_pass=outcome.primary_pass,
                )
                artifact_paths = [p for p in (outcome.stdout_path, outcome.stderr_path) if p]
                failure_labels = [outcome.failure_class] if outcome.failure_class else []
                record = EvidenceRecord(
                    run_id=rid,
                    task_id=outcome.instance_id,
                    model_id=plan.model_id,
                    execution_profile=profile,
                    backend=LOCAL_BACKEND,
                    primary_pass=outcome.primary_pass,
                    partial_score=outcome.partial_score,
                    cost_usd=outcome.cost_usd,
                    latency_sec=outcome.latency_sec,
                    failure_labels=list(failure_labels),
                    artifact_paths=artifact_paths,
                    adapter_metadata=outcome.adapter_metadata,
                    created_at=datetime.now(tz=UTC),
                    benchmark_id=plan.benchmark_id,
                    benchmark_version=plan.benchmark_version,
                    slice_id=plan.slice_id,
                    adapter_id=adapter_id,
                    harness_kind=plan.harness_kind,
                    runtime_id=None,
                    runtime_kind=None,
                    agent_id=plan.agent_id,
                    provider_id=plan.provider_id,
                    provider_config_hash=provider_config_hash,
                    judge_model_id=plan.judge_model_id,
                    instance_id=outcome.instance_id,
                    failure_class=outcome.failure_class,
                    cleanup_result=cleanup_result,
                )
            except AdapterFailureError as e:
                instance_dir = run_artifacts / instance_id
                capture_root = _default_capture_root(run_artifacts.resolve())
                capture_dir = capture_root / instance_id
                metadata = dict(e.adapter_metadata)
                failure_log = capture_dir / "adapter_failure.json"
                failure_payload = (
                    json.dumps(
                        {
                            "instance_id": instance_id,
                            "failure_label": e.failure_label,
                            "message": str(e),
                        },
                        indent=2,
                    )
                    + "\n"
                )
                failure_log_written = False
                try:
                    failure_fd = _open_capture_dir_fd(capture_root, instance_id)
                except BenchEvalError:
                    # The capture path was tampered with (e.g. swapped for a
                    # symlink mid-run); never write through it. The evidence record
                    # below still captures the failure.
                    metadata["failure_log"] = "suppressed_path_tampered"
                else:
                    try:
                        write_text_at_exclusive(failure_fd, "adapter_failure.json", failure_payload)
                        failure_log_written = True
                    except BenchEvalError:
                        metadata["failure_log"] = "write_failed"
                    finally:
                        os.close(failure_fd)
                failure_class = cast(
                    FailureLabel,
                    e.failure_label if e.failure_label in _FAILURE_LABELS else "adapter_error",
                )
                metadata.setdefault("adapter_id", adapter_id)
                metadata.setdefault("agent_id", plan.agent_id or "")
                cleanup_result = _agent_cleanup_result(
                    plan=plan,
                    instance_artifacts=instance_dir,
                    primary_pass=False,
                )
                record = EvidenceRecord(
                    run_id=rid,
                    task_id=instance_id,
                    model_id=plan.model_id,
                    execution_profile=profile,
                    backend=LOCAL_BACKEND,
                    primary_pass=False,
                    partial_score=0.0,
                    cost_usd=e.cost_usd,
                    latency_sec=e.latency_sec,
                    failure_labels=[failure_class],
                    artifact_paths=[str(failure_log.resolve())] if failure_log_written else [],
                    adapter_metadata=metadata,
                    created_at=datetime.now(tz=UTC),
                    benchmark_id=plan.benchmark_id,
                    benchmark_version=plan.benchmark_version,
                    slice_id=plan.slice_id,
                    adapter_id=adapter_id,
                    harness_kind=plan.harness_kind,
                    runtime_id=None,
                    runtime_kind=None,
                    agent_id=plan.agent_id,
                    provider_id=plan.provider_id,
                    provider_config_hash=provider_config_hash,
                    judge_model_id=plan.judge_model_id,
                    instance_id=instance_id,
                    failure_class=failure_class,
                    cleanup_result=cleanup_result,
                )
            spent_cost_usd += record.cost_usd
            spent_wall_sec += record.latency_sec
            if record.primary_pass:
                passed += 1
            sink.append_jsonl(output_path, record)
        total = len(plan.instances)
        return ExternalAgentRunSummary(
            run_id=rid,
            instance_count=total,
            passed_count=passed,
            failed_count=total - passed,
            output_path=output_path.resolve(),
        )
    finally:
        release_evidence_reservation(output_path)


# MOMO naming lives in momo_agent_adapter.py (compat module).

__all__ = [
    "ExternalAgentCliResult",
    "ExternalAgentInstanceOutcome",
    "ExternalAgentProcessRunner",
    "ExternalAgentRunSummary",
    "adapter_id_for_agent",
    "build_external_agent_command",
    "execute_external_agent_run",
    "run_external_agent_instance",
]
