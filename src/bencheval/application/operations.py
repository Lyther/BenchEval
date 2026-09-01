"""Transport-neutral operator actions over canonical BenchEval modules."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from bencheval.agent_registry import load_agent_catalog
from bencheval.application.dto import (
    ActionDTO,
    ArtifactResultDTO,
    CatalogItemDTO,
    CatalogPageDTO,
    CatalogSnapshotDTO,
    DoctorCheckDTO,
    DoctorViewDTO,
    EvidenceSummaryDTO,
    PlanPreviewDTO,
    PlanRequestDTO,
    ProofViewDTO,
    QualificationViewDTO,
    ReadinessItemDTO,
    RunDetailDTO,
    RunExecutionDTO,
    RunSummaryDTO,
)
from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import execution_support_label, load_benchmark_catalog
from bencheval.control_plane_executor import diagnostic_capable_benchmark, execute_control_plane_run
from bencheval.doctor import run_doctor, run_pilot_doctor
from bencheval.evidence import read_evidence_jsonl
from bencheval.evidence_compare import (
    compare_evidence_runs,
    render_comparison_json,
    render_comparison_markdown,
)
from bencheval.exceptions import BenchEvalError, LiveRunManifestError
from bencheval.export import export_evidence
from bencheval.ids import new_run_id
from bencheval.live_proof import producer_content_ok, qualify_lane, registration_identity_mismatch
from bencheval.live_run_manifest import (
    LiveRunRecord,
    LiveRunStatus,
    append_live_run,
    default_runs_manifest_path,
    read_live_run_projections,
    read_live_runs,
)
from bencheval.model_compare import (
    compare_model_evidence,
    is_model_comparison_evidence,
    render_model_comparison_json,
    render_model_comparison_markdown,
)
from bencheval.model_registry import load_model_registry
from bencheval.paths import repo_root
from bencheval.proof_bundle import (
    default_proofs_dir,
    export_private_proof,
    import_private_proof,
    inspect_private_proof,
    scan_private_proofs,
)
from bencheval.provider_registry import load_provider_catalog
from bencheval.report import generate_evidence_report_with_runtime_panel
from bencheval.run_bundle import RedactionMode, export_run_bundle
from bencheval.runtime_compare import (
    compare_runtime_evidence,
    is_dual_axis_comparison_drift,
    is_runtime_comparison_evidence,
    render_runtime_comparison_json,
    render_runtime_comparison_markdown,
)
from bencheval.runtime_registry import load_runtime_catalog
from bencheval.swebench_adapter import SWEBENCH_ADAPTER_ID, default_swebench_process_runner

CompareFormat = Literal["markdown", "json"]


def proof_inventory_counts(proofs: tuple[ProofViewDTO, ...]) -> tuple[int, int]:
    """Return verified and corrupt proof counts for truthful UI projections."""
    verified = sum(row.verified for row in proofs)
    return verified, len(proofs) - verified


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _artifact(path: Path, *, role: str, visibility: str | None = None) -> ArtifactResultDTO:
    resolved = path.resolve()
    if resolved.is_dir():
        digest = hashlib.sha256()
        size = 0
        for child in sorted(resolved.rglob("*")):
            if child.is_symlink():
                raise BenchEvalError(f"artifact directory contains a symlink: {child}")
            if not child.is_file():
                continue
            relative = child.relative_to(resolved).as_posix()
            child_digest = _digest_file(child)
            child_size = child.stat().st_size
            digest.update(f"{relative}\0{child_size}\0{child_digest}\n".encode())
            size += child_size
        return ArtifactResultDTO(
            role=role,
            path=str(resolved),
            size=size,
            sha256=f"sha256:{digest.hexdigest()}",
            visibility=visibility,
        )
    return ArtifactResultDTO(
        role=role,
        path=str(resolved),
        size=resolved.stat().st_size,
        sha256=_digest_file(resolved),
        visibility=visibility,
    )


def _write_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise BenchEvalError(f"cannot create exclusive output {path}: {exc}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _symlink_component(path: Path) -> Path | None:
    """Return the first existing symlink in ``path`` without resolving through it."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if current.is_symlink():
            # macOS exposes root-owned compatibility aliases such as
            # /var -> /private/var and /tmp -> /private/tmp. They are part of
            # the platform namespace, not an operator-controlled redirect.
            if current.parent == Path(absolute.anchor) and os.lstat(current).st_uid == 0:
                continue
            return current
    return None


class OperatorOperations:
    """Small application facade; it owns composition, never benchmark semantics."""

    def catalog(self) -> CatalogSnapshotDTO:
        benchmarks = load_benchmark_catalog().benchmarks
        items: list[CatalogItemDTO] = []
        for entry in benchmarks:
            support = execution_support_label(entry)
            items.append(
                CatalogItemDTO(
                    kind="benchmark",
                    id=entry.id,
                    name=entry.name,
                    status=support,
                    detail=(entry.category, entry.tier, entry.adapter_status),
                    runnable=entry.executable,
                    default_slice=entry.default_slice,
                ),
            )
        for entry in load_model_registry().models:
            items.append(
                CatalogItemDTO(
                    kind="model",
                    id=entry.id,
                    name=entry.display_name,
                    status=entry.provider_route or "unrouted",
                    detail=(entry.family,),
                ),
            )
        for profile in load_runtime_catalog().runtimes:
            items.append(
                CatalogItemDTO(
                    kind="runtime",
                    id=profile.runtime.id,
                    name=profile.runtime.display_name,
                    status=profile.admission,
                    detail=tuple(profile.runtime.supported_harnesses),
                    runnable=profile.admission == "admitted",
                ),
            )
        for profile in load_agent_catalog().agents:
            items.append(
                CatalogItemDTO(
                    kind="agent",
                    id=profile.agent.id,
                    name=profile.agent.display_name,
                    status=profile.admission,
                    detail=tuple(profile.agent.supported_harnesses),
                    runnable=profile.admission == "admitted",
                ),
            )
        for profile in load_provider_catalog().providers:
            items.append(
                CatalogItemDTO(
                    kind="provider",
                    id=profile.provider.id,
                    name=profile.provider.display_name,
                    status=profile.admission,
                    detail=(profile.provider.kind, profile.provider.api_key_env),
                    runnable=profile.admission == "admitted",
                ),
            )
        executable = sum(entry.executable for entry in benchmarks)
        diagnostic = sum(
            not entry.executable and diagnostic_capable_benchmark(entry) for entry in benchmarks
        )
        return CatalogSnapshotDTO(
            items=tuple(items),
            benchmark_count=len(benchmarks),
            executable_count=executable,
            diagnostic_count=diagnostic,
        )

    def catalog_page(
        self,
        *,
        kind: str | None = None,
        query: str = "",
        cursor: str | None = None,
        limit: int = 50,
    ) -> CatalogPageDTO:
        if not 1 <= limit <= 200:
            raise BenchEvalError("catalog page limit must be between 1 and 200")
        items = tuple(
            item
            for item in self.catalog().items
            if (kind is None or item.kind == kind)
            and (not query or query.casefold() in f"{item.id} {item.name} {item.status}".casefold())
        )
        source = hashlib.sha256(
            "\n".join(item.model_dump_json() for item in items).encode(),
        ).hexdigest()
        offset = 0
        if cursor is not None:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
                raise BenchEvalError("catalog cursor is invalid") from exc
            if not isinstance(decoded, dict):
                raise BenchEvalError("catalog cursor is invalid")
            if decoded.get("source") != source:
                raise BenchEvalError("catalog changed; refresh required")
            raw_offset = decoded.get("offset")
            if isinstance(raw_offset, bool) or not isinstance(raw_offset, int) or raw_offset < 0:
                raise BenchEvalError("catalog cursor is invalid")
            offset = raw_offset
        page = items[offset : offset + limit]
        next_cursor = None
        if offset + limit < len(items):
            payload = json.dumps({"offset": offset + limit, "source": source}, sort_keys=True)
            next_cursor = base64.urlsafe_b64encode(payload.encode()).decode()
        return CatalogPageDTO(items=page, source_revision=source, next_cursor=next_cursor)

    def plan(self, request: PlanRequestDTO) -> PlanPreviewDTO:
        benchmark = load_benchmark_catalog().by_id_or_alias(request.benchmark_id)
        if request.diagnostic:
            if benchmark.executable:
                raise BenchEvalError(
                    "diagnostic mode is only valid for a demoted benchmark",
                )
            if not diagnostic_capable_benchmark(benchmark):
                raise BenchEvalError(
                    f"benchmark {benchmark.id!r} has no wired diagnostic lifecycle",
                )
        elif not benchmark.executable:
            hint = (
                "; enable diagnostic mode for a permanently ineligible run"
                if diagnostic_capable_benchmark(benchmark)
                else ""
            )
            raise BenchEvalError(
                f"benchmark {benchmark.id!r} is not executable{hint}",
            )
        plan = plan_control_plane(
            benchmark_id=request.benchmark_id,
            slice_id=request.slice_id,
            runtime_id=request.runtime_id,
            agent_id=request.agent_id,
            provider_id=request.provider_id,
            model_id=request.model_id,
            diagnostic=request.diagnostic,
        )
        canonical = plan.model_dump_json(exclude_none=False)
        fingerprint = f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"
        executable = benchmark.executable
        return PlanPreviewDTO(
            request=request,
            fingerprint=fingerprint,
            benchmark_version=plan.benchmark_version,
            adapter_id=plan.adapter_id,
            harness_kind=plan.harness_kind,
            backend="harbor" if plan.harness_kind == "harbor" else "inspect",
            execution_profile=load_benchmark_catalog()
            .by_id_or_alias(plan.benchmark_id)
            .recommended_profile,
            instance_count=len(plan.instances),
            runtime_id=plan.runtime_id,
            agent_id=plan.agent_id,
            provider_id=plan.provider_id,
            model_id=plan.model_id,
            max_cost_usd=plan.max_cost_usd,
            max_wall_clock_sec=plan.max_wall_clock_sec,
            network_policy=plan.network_policy,
            diagnostic=plan.diagnostic,
            executable=executable,
            caveats=plan.caveats,
        )

    def doctor(
        self,
        *,
        backend: Literal["inspect", "harbor"] | None,
        profile: str | None,
        model_id: str | None,
    ) -> DoctorViewDTO:
        if profile == "pilot":
            report = run_pilot_doctor(model_id=model_id)
        else:
            if backend is None:
                raise BenchEvalError("backend is required unless profile is pilot")
            report = run_doctor(backend, model_id=model_id, execution_profile=profile)
        return DoctorViewDTO(
            backend=report.backend,
            ok=report.ok,
            checks=tuple(
                DoctorCheckDTO(name=row.name, status=row.status, message=row.message)
                for row in report.checks
            ),
        )

    def start(self, request: PlanRequestDTO, *, expected_fingerprint: str) -> RunExecutionDTO:
        preview = self.plan(request)
        if preview.fingerprint != expected_fingerprint:
            raise BenchEvalError("run plan changed; refresh and confirm the new plan")
        if not preview.executable and not request.diagnostic:
            raise BenchEvalError(
                "benchmark is not executable; explicit diagnostic mode is required"
            )
        run_id = new_run_id()
        root = Path.cwd()
        output = (
            Path(request.output_path)
            if request.output_path
            else root / "results" / "evidence" / f"{run_id}.jsonl"
        )
        artifacts = (
            Path(request.artifacts_dir)
            if request.artifacts_dir
            else root / "results" / "raw" / run_id
        )
        plan = plan_control_plane(
            benchmark_id=request.benchmark_id,
            slice_id=request.slice_id,
            runtime_id=request.runtime_id,
            agent_id=request.agent_id,
            provider_id=request.provider_id,
            model_id=request.model_id,
            diagnostic=request.diagnostic,
        )
        summary = execute_control_plane_run(
            plan=plan,
            output_path=output,
            artifacts_dir=artifacts,
            run_id=run_id,
            swebench_process_runner=(
                default_swebench_process_runner if plan.adapter_id == SWEBENCH_ADAPTER_ID else None
            ),
        )
        return RunExecutionDTO(
            run_id=summary.run_id,
            benchmark_id=request.benchmark_id,
            slice_id=request.slice_id,
            runtime_id=request.runtime_id,
            model_id=request.model_id,
            evidence_path=str(summary.output_path.resolve()),
            passed_count=summary.passed_count,
            failed_count=summary.failed_count,
        )

    def runs(self, manifest_path: Path | None = None) -> tuple[RunSummaryDTO, ...]:
        path = manifest_path or default_runs_manifest_path()
        if not path.exists():
            return ()
        rows = sorted(
            read_live_run_projections(path), key=lambda row: row.last_generated_at, reverse=True
        )
        return tuple(
            RunSummaryDTO(
                run_id=row.run_id,
                model_id=row.model_id,
                host=row.host,
                status=row.status,
                benchmark_id=row.benchmark,
                slice_id=row.slice_id,
                runtime_id=row.runtime,
                evidence_path=row.evidence_path,
                report_path=row.report_path,
                bundle_path=row.bundle_path,
                event_count=row.event_count,
                last_generated_at=row.last_generated_at.isoformat(),
            )
            for row in rows
        )

    def qualify(self, evidence_path: Path) -> QualificationViewDTO:
        records = read_evidence_jsonl(evidence_path)
        if not records:
            raise BenchEvalError("evidence is empty")
        first = records[0]
        if first.benchmark_id is None or first.slice_id is None:
            return QualificationViewDTO(
                ok=False,
                eligible_count=0,
                reasons=("evidence lacks benchmark/slice identity",),
            )
        plan = plan_control_plane(
            benchmark_id=first.benchmark_id,
            slice_id=first.slice_id,
            runtime_id=first.runtime_id,
            agent_id=first.agent_id,
            provider_id=first.provider_id,
            model_id=first.model_id,
            diagnostic=first.interpretation_label == "diagnostic",
        )
        result = qualify_lane(
            evidence_path,
            expected_instances=len(plan.instances),
            benchmark_id=first.benchmark_id,
            slice_id=first.slice_id,
            require_runtime=first.runtime_id is not None,
        )
        return QualificationViewDTO(
            ok=result.ok,
            eligible_count=len(result.eligible_rows),
            reasons=tuple(result.reasons),
        )

    def run_detail(self, run_id: str, manifest_path: Path | None = None) -> RunDetailDTO:
        path = manifest_path or default_runs_manifest_path()
        summaries = {row.run_id: row for row in self.runs(path)}
        if run_id not in summaries:
            raise BenchEvalError(f"run not found: {run_id}")
        summary = summaries[run_id]
        history = tuple(
            {
                "status": row.status,
                "generated_at": row.generated_at.isoformat(),
                "notes": row.notes,
                "evidence_path": row.evidence_path,
                "report_path": row.report_path,
                "bundle_path": row.bundle_path,
            }
            for row in read_live_runs(path)
            if row.run_id == run_id
        )
        records = read_evidence_jsonl(Path(summary.evidence_path)) if summary.evidence_path else []
        evidence = tuple(
            EvidenceSummaryDTO(
                task_id=row.task_id,
                instance_id=row.instance_id,
                primary_pass=row.primary_pass,
                partial_score=row.partial_score,
                failure_class=row.failure_class,
                attempt_validity=row.attempt_validity,
                interpretation_label=row.interpretation_label,
                cost_usd=row.cost_usd,
                cost_basis=row.adapter_metadata.get("cost_basis"),
                artifacts=tuple(
                    [*row.artifact_paths]
                    + ([row.verifier_log_path] if row.verifier_log_path else []),
                ),
            )
            for row in records[:200]
        )
        qualification = self.qualify(Path(summary.evidence_path)) if summary.evidence_path else None
        has_evidence = bool(records)
        actions = (
            ActionDTO(
                id="report.generate",
                allowed=has_evidence,
                disabled_reason=None if has_evidence else "evidence is missing",
            ),
            ActionDTO(
                id="bundle.export",
                allowed=has_evidence,
                disabled_reason=None if has_evidence else "evidence is missing",
            ),
            ActionDTO(
                id="proof.export",
                allowed=has_evidence and summary.benchmark_id is not None,
                disabled_reason=(
                    None
                    if has_evidence and summary.benchmark_id is not None
                    else "bound benchmark evidence is required"
                ),
            ),
            ActionDTO(id="evidence.register", allowed=True),
        )
        return RunDetailDTO(
            summary=summary,
            history=history,
            evidence=evidence,
            qualification=qualification,
            actions=actions,
        )

    def register(
        self,
        *,
        run_id: str,
        model_id: str,
        status: LiveRunStatus,
        benchmark_id: str | None = None,
        slice_id: str | None = None,
        runtime_id: str | None = None,
        evidence_path: Path | None = None,
        report_path: Path | None = None,
        bundle_path: Path | None = None,
        notes: str = "",
        host: str | None = None,
        manifest_path: Path | None = None,
    ) -> RunSummaryDTO:
        terminal = status in {"completed", "passed", "failed", "archived"}
        if terminal and evidence_path is None:
            raise BenchEvalError("terminal status requires evidence")
        for role, path in (
            ("evidence", evidence_path),
            ("report", report_path),
            ("bundle", bundle_path),
        ):
            if path is not None and not path.resolve().is_file():
                raise BenchEvalError(f"{role} path is not a regular file: {path.resolve()}")
        records = read_evidence_jsonl(evidence_path) if evidence_path is not None else []
        if terminal and not records:
            raise BenchEvalError("terminal status requires non-empty EvidenceRecord JSONL")
        if status == "passed":
            if benchmark_id is None or slice_id is None or evidence_path is None:
                raise BenchEvalError("passed requires benchmark, slice, and evidence")
            entry = load_benchmark_catalog().by_id_or_alias(benchmark_id)
            if not entry.executable:
                raise BenchEvalError("passed requires a catalog-executable benchmark")
            population_qualification = self.qualify(evidence_path)
            if not population_qualification.ok:
                raise BenchEvalError(
                    "passed registration is not live-proof qualified: "
                    + "; ".join(population_qualification.reasons),
                )
            qualification = qualify_lane(
                evidence_path,
                expected_instances=1,
                benchmark_id=benchmark_id,
                slice_id=slice_id,
                require_runtime=runtime_id is not None,
            )
            if not qualification.ok:
                raise BenchEvalError(
                    "passed registration is not live-proof qualified: "
                    + "; ".join(qualification.reasons),
                )
            mismatch = registration_identity_mismatch(
                qualification.eligible_rows,
                run_id=run_id,
                model_id=model_id,
                runtime_id=runtime_id,
            )
            if mismatch is not None:
                raise BenchEvalError(f"passed registration identity mismatch: {mismatch}")
            contents = {
                row.adapter_metadata.get("producer_content_sha256")
                for row in qualification.eligible_rows
            }
            if len(contents) != 1 or any(not producer_content_ok(value) for value in contents):
                raise BenchEvalError("passed requires one producer content digest on every row")
        record = LiveRunRecord(
            run_id=run_id,
            host=host or socket.gethostname(),
            benchmark=benchmark_id,
            slice_id=slice_id,
            runtime=runtime_id,
            model_id=model_id,
            evidence_path=str(evidence_path.resolve()) if evidence_path else None,
            report_path=str(report_path.resolve()) if report_path else None,
            bundle_path=str(bundle_path.resolve()) if bundle_path else None,
            status=status,
            notes=notes,
            generated_at=datetime.now(tz=UTC),
        )
        try:
            append_live_run(manifest_path or default_runs_manifest_path(), record)
        except (LiveRunManifestError, ValidationError, ValueError, OSError) as exc:
            raise BenchEvalError(str(exc)) from exc
        return next(row for row in self.runs(manifest_path) if row.run_id == run_id)

    def report(self, evidence_path: Path, output_path: Path) -> ArtifactResultDTO:
        symlink = _symlink_component(output_path)
        if symlink is not None:
            raise BenchEvalError(f"report output contains a symlink component: {symlink}")
        records = read_evidence_jsonl(evidence_path)
        _write_exclusive(output_path, generate_evidence_report_with_runtime_panel(records))
        return _artifact(output_path, role="report")

    def compare(
        self,
        baseline_path: Path,
        current_path: Path,
        output_path: Path,
        *,
        output_format: CompareFormat,
    ) -> ArtifactResultDTO:
        symlink = _symlink_component(output_path)
        if symlink is not None:
            raise BenchEvalError(f"comparison output contains a symlink component: {symlink}")
        baseline = read_evidence_jsonl(baseline_path)
        current = read_evidence_jsonl(current_path)
        if is_dual_axis_comparison_drift(baseline, current):
            raise BenchEvalError("dual-axis drift: hold model or runtime constant")
        use_runtime = is_runtime_comparison_evidence(baseline, current)
        use_model = not use_runtime and is_model_comparison_evidence(baseline, current)
        if use_model:
            result = compare_model_evidence(baseline, current)
            text = (
                render_model_comparison_json(result)
                if output_format == "json"
                else render_model_comparison_markdown(result)
            )
            valid = result.validity.valid
        elif use_runtime:
            result = compare_runtime_evidence(baseline, current)
            text = (
                render_runtime_comparison_json(result)
                if output_format == "json"
                else render_runtime_comparison_markdown(result)
            )
            valid = result.validity.valid
        else:
            result = compare_evidence_runs(baseline, current)
            text = (
                render_comparison_json(result)
                if output_format == "json"
                else render_comparison_markdown(result)
            )
            valid = result.comparison_valid
        _write_exclusive(output_path, text)
        artifact = _artifact(output_path, role="comparison")
        details: tuple[str, ...] = ()
        if not valid:
            if hasattr(result, "validity_reasons"):
                details = tuple(result.validity_reasons)
            elif hasattr(result, "validity"):
                details = tuple(result.validity.reasons)
        return artifact.model_copy(
            update={
                "valid": valid,
                "detail": details or (() if valid else ("comparison is invalid",)),
            },
        )

    def warehouse(self, evidence_path: Path, output_dir: Path, *, fmt: str) -> ArtifactResultDTO:
        symlink = _symlink_component(output_dir)
        if symlink is not None:
            raise BenchEvalError(f"warehouse output contains a symlink component: {symlink}")
        if output_dir.exists():
            if not output_dir.is_dir():
                raise BenchEvalError(f"warehouse output is not a directory: {output_dir}")
            try:
                occupied = any(output_dir.iterdir())
            except OSError as exc:
                raise BenchEvalError(
                    f"cannot inspect warehouse output {output_dir}: {exc}"
                ) from exc
            if occupied:
                raise BenchEvalError(f"warehouse output must be empty or missing: {output_dir}")
        output = export_evidence(evidence_path, fmt=fmt, output_dir=output_dir)
        return _artifact(output, role=f"warehouse:{fmt}")

    def bundle(
        self,
        evidence_path: Path,
        output_dir: Path,
        *,
        raw_dir: Path | None,
        redaction: RedactionMode,
    ) -> ArtifactResultDTO:
        symlink = _symlink_component(output_dir)
        if symlink is not None:
            raise BenchEvalError(f"bundle output contains a symlink component: {symlink}")
        archive = export_run_bundle(
            evidence_path=evidence_path,
            output_dir=output_dir,
            raw_dir=raw_dir,
            redaction=redaction,
        )
        return _artifact(archive, role="run-bundle", visibility=redaction)

    def proof_export(
        self,
        *,
        run_id: str,
        evidence_path: Path,
        artifacts_dir: Path,
        manifest_path: Path,
        output_dir: Path,
        capture_dir: Path | None = None,
    ) -> ProofViewDTO:
        symlink = _symlink_component(output_dir)
        if symlink is not None:
            raise BenchEvalError(f"proof output contains a symlink component: {symlink}")
        proof = export_private_proof(
            run_id=run_id,
            evidence_path=evidence_path,
            artifacts_dir=artifacts_dir,
            manifest_path=manifest_path,
            output_dir=output_dir,
            capture_dir=capture_dir,
        )
        return ProofViewDTO(
            proof_id=proof.proof_id,
            run_id=run_id,
            path=str(proof.root.resolve()),
            classification=proof.classification,
            classification_reason=proof.classification_reason,
            verified=True,
            benchmark_id=inspect_private_proof(proof.root).benchmark_id,
        )

    def proof_verify(self, path: Path, expected: str | None = None) -> ProofViewDTO:
        summary = inspect_private_proof(path, expected_proof_id=expected)
        return ProofViewDTO(
            proof_id=summary.proof_id,
            run_id=summary.run_id,
            path=str(summary.path),
            classification=summary.classification,
            classification_reason=summary.classification_reason,
            verified=True,
            benchmark_id=summary.benchmark_id,
        )

    def proof_import(self, path: Path, store: Path | None = None) -> ProofViewDTO:
        installed = import_private_proof(path, store_root=store or default_proofs_dir())
        return self.proof_verify(installed)

    def proofs(self, store: Path | None = None) -> tuple[ProofViewDTO, ...]:
        views: list[ProofViewDTO] = []
        for scan in scan_private_proofs(store or default_proofs_dir()):
            if scan.summary is None:
                views.append(
                    ProofViewDTO(
                        proof_id=scan.proof_id,
                        run_id=scan.run_id,
                        path=str(scan.path),
                        classification="corrupt",
                        classification_reason=scan.error,
                        verified=False,
                        benchmark_id=None,
                    ),
                )
                continue
            row = scan.summary
            views.append(
                ProofViewDTO(
                    proof_id=row.proof_id,
                    run_id=row.run_id,
                    path=str(row.path),
                    classification=row.classification,
                    classification_reason=row.classification_reason,
                    verified=True,
                    benchmark_id=row.benchmark_id,
                ),
            )
        return tuple(views)

    def readiness(self) -> tuple[ReadinessItemDTO, ...]:
        root = repo_root()
        registered = {
            row.benchmark_id
            for row in self.runs()
            if row.status == "passed" and row.benchmark_id is not None
        }
        proof_benchmarks = {
            row.benchmark_id for row in self.proofs() if row.verified and row.benchmark_id
        }
        result: list[ReadinessItemDTO] = []
        for benchmark in load_benchmark_catalog().benchmarks:
            ledger = root / "docs" / "context" / "tier2" / f"{benchmark.id}.md"
            if ledger.is_file():
                ledger_text = ledger.read_text(encoding="utf-8")
                tier2_state = (
                    "not-claimed"
                    if "**Tier-2 decision:** not claimed" in ledger_text
                    else "claimed"
                    if "**Tier-2 decision:** claimed" in ledger_text
                    else "unknown"
                )
            else:
                tier2_state = "missing-ledger"
            blockers: list[str] = []
            if not benchmark.executable:
                blockers.append("catalog-only or diagnostic-only")
            if tier2_state != "claimed":
                blockers.append("Tier-2 is not claimed")
            result.append(
                ReadinessItemDTO(
                    benchmark_id=benchmark.id,
                    executable=benchmark.executable,
                    software_state="executable" if benchmark.executable else "demoted",
                    tier1_state=(
                        "registered-passed"
                        if benchmark.id in registered
                        else "proof-present-not-tier1"
                        if benchmark.id in proof_benchmarks
                        else "proof-required"
                    ),
                    tier2_state=tier2_state,
                    ledger=str(ledger) if ledger.is_file() else None,
                    blockers=tuple(blockers),
                ),
            )
        return tuple(result)
