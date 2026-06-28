"""BenchEval vNext CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

from bencheval.admission import (
    admission_path_for_task,
    audit_suite_admission,
    audit_task_admission,
)
from bencheval.backends import HARBOR_BACKEND, INSPECT_BACKEND, LOCAL_BACKEND, ExecutionBackend
from bencheval.benchmark_plan import (
    dry_run_slice_resolution,
    list_adapter_descriptors,
    plan_control_plane,
    run_plan_to_dry_run_dict,
)
from bencheval.benchmark_registry import (
    BenchmarkAdapterStatus,
    BenchmarkCategory,
    BenchmarkEntry,
    BenchmarkFilter,
    BenchmarkTier,
    ExecutionSupport,
    SafetyReview,
    execution_support_label,
    filter_benchmarks,
    load_benchmark_catalog,
)
from bencheval.control_plane_executor import (
    control_plane_interpretation_label,
    execute_control_plane_run,
)
from bencheval.doctor import run_doctor, run_pilot_doctor
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError, TaskContractError
from bencheval.executor import execute_task
from bencheval.lifecycle import CleanupPolicy, RunMode, cleanup_transient_artifacts
from bencheval.live_run_manifest import (
    LiveRunRecord,
    LiveRunStatus,
    append_live_run,
    default_runs_manifest_path,
)
from bencheval.manifest import load_manifest, read_manifest_task_ids
from bencheval.model_registry import load_model_registry
from bencheval.paths import repo_root as _repo_root
from bencheval.planner import plan_dry_run
from bencheval.report import generate_evidence_report_with_runtime_panel
from bencheval.runner import LOCAL_HARNESS_MODEL_ID, new_run_id
from bencheval.runtime_registry import load_runtime_catalog
from bencheval.slice_manifest import slices_for_benchmark
from bencheval.task_registry import (
    lint_task_path,
    load_suites,
    load_task_contract,
    resolve_task_path,
    tasks_for_suite,
)


def _task_lint(args: argparse.Namespace) -> int:
    path = resolve_task_path(args.target)
    report = lint_task_path(path, suites=load_suites())
    if args.format == "json":
        payload = {
            "path": report.path,
            "ok": report.ok,
            "issues": [
                {
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message,
                    "path": i.path,
                }
                for i in report.issues
            ],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        if not report.issues:
            sys.stderr.write(f"{report.path}: ok\n")
        for issue in report.issues:
            line = f"{issue.severity.upper()} [{issue.code}] {issue.path}: {issue.message}\n"
            sys.stderr.write(line)
    return 0 if report.ok else 1


def _task_validate(args: argparse.Namespace) -> int:
    path = resolve_task_path(args.target)
    report = lint_task_path(path, suites=load_suites())
    contract = load_task_contract(path)
    payload = {
        "ok": report.ok,
        "path": str(path),
        "task_id": contract.task.id,
        "version": contract.task.version,
        "category": contract.task.category,
        "execution_profile": contract.execution.profile,
        "budget_class": contract.constraints.budget_class,
        "issues": [
            {"severity": i.severity, "code": i.code, "message": i.message, "path": i.path}
            for i in report.issues
        ],
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0 if report.ok else 1


def _task_audit(args: argparse.Namespace) -> int:
    target = args.target
    suites = load_suites()
    if target in suites:
        report = audit_suite_admission(target)
        payload = report.to_dict()
    else:
        report = audit_task_admission(target, admission_path=admission_path_for_task(target))
        payload = report.to_dict()
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    admitted = payload.get("admitted", False)
    return 0 if admitted else 1


def _benchmark_payload(benchmark: BenchmarkEntry) -> dict[str, object]:
    payload = benchmark.model_dump(mode="json")
    payload["execution_support"] = execution_support_label(benchmark)
    return payload


def _benchmark_list(args: argparse.Namespace) -> int:
    catalog = load_benchmark_catalog()
    filters = BenchmarkFilter(
        category=cast("BenchmarkCategory | None", args.category),
        tier=cast("BenchmarkTier | None", args.tier),
        adapter_status=cast("BenchmarkAdapterStatus | None", args.status),
        safety_review=cast("SafetyReview | None", args.safety),
        execution_support=cast("ExecutionSupport | None", args.execution_support),
    )
    benchmarks = filter_benchmarks(catalog, filters)
    if args.format == "json":
        payload = {
            "schema_version": catalog.schema_version,
            "count": len(benchmarks),
            "benchmarks": [_benchmark_payload(benchmark) for benchmark in benchmarks],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0

    for benchmark in benchmarks:
        sys.stdout.write(
            "\t".join(
                (
                    benchmark.id,
                    execution_support_label(benchmark),
                    benchmark.category,
                    benchmark.tier,
                    benchmark.adapter_status,
                    benchmark.safety_review,
                    benchmark.name,
                ),
            )
            + "\n",
        )
    return 0


def _benchmark_show(args: argparse.Namespace) -> int:
    catalog = load_benchmark_catalog()
    benchmark = catalog.by_id_or_alias(args.target)
    payload = _benchmark_payload(benchmark)
    if args.format == "json":
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    for key, value in payload.items():
        sys.stdout.write(f"{key}: {value}\n")
    return 0


def _benchmark_slices(args: argparse.Namespace) -> int:
    catalog = load_benchmark_catalog()
    benchmark = catalog.by_id_or_alias(args.target)
    slices = slices_for_benchmark(benchmark.id)
    if args.format == "json":
        payload = {
            "benchmark_id": benchmark.id,
            "slices": [s.model_dump(mode="json") for s in slices],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    for s in slices:
        sys.stdout.write(
            "\t".join((s.slice.id, s.slice.purpose, s.slice.instances_source)) + "\n",
        )
    return 0


def _runtime_list(args: argparse.Namespace) -> int:
    catalog = load_runtime_catalog()
    if args.format == "json":
        payload = {
            "runtimes": [
                {
                    "id": rp.runtime.id,
                    "kind": rp.runtime.kind,
                    "display_name": rp.runtime.display_name,
                    "admission": rp.admission,
                }
                for rp in catalog.runtimes
            ],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    for rp in catalog.runtimes:
        sys.stdout.write(
            "\t".join((rp.runtime.id, rp.runtime.kind, rp.admission, rp.runtime.display_name))
            + "\n",
        )
    return 0


def _runtime_show(args: argparse.Namespace) -> int:
    catalog = load_runtime_catalog()
    profile = catalog.by_id(args.target)
    payload = profile.model_dump(mode="json")
    if args.format == "json":
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    for key, value in payload.items():
        sys.stdout.write(f"{key}: {value}\n")
    return 0


def _model_list(args: argparse.Namespace) -> int:
    registry = load_model_registry()
    if args.format == "json":
        payload = {"models": [m.model_dump(mode="json") for m in registry.models]}
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    for m in registry.models:
        sys.stdout.write("\t".join((m.id, m.family, m.display_name)) + "\n")
    return 0


def _model_show(args: argparse.Namespace) -> int:
    registry = load_model_registry()
    try:
        entry = registry.by_id(args.target)
    except KeyError as e:
        raise BenchEvalError(str(e)) from e
    payload = entry.model_dump(mode="json")
    if args.format == "json":
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    for key, value in payload.items():
        sys.stdout.write(f"{key}: {value}\n")
    return 0


def _adapter_list(args: argparse.Namespace) -> int:
    adapters = list_adapter_descriptors()
    if args.format == "json":
        payload = {
            "adapters": [
                {
                    "adapter_id": a.adapter_id,
                    "harness_kind": a.harness_kind,
                    "benchmark_ids": list(a.benchmark_ids),
                }
                for a in adapters
            ],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    for a in adapters:
        sys.stdout.write(
            "\t".join((a.adapter_id, a.harness_kind, ",".join(a.benchmark_ids))) + "\n",
        )
    return 0


_CONTROL_PLANE_AXIS_NAMES = ("benchmark", "slice", "runtime", "model")


def _control_plane_axis_values(args: argparse.Namespace) -> tuple[str | None, ...]:
    return tuple(getattr(args, name, None) for name in _CONTROL_PLANE_AXIS_NAMES)


def _control_plane_run_selected(args: argparse.Namespace) -> bool:
    return all(v is not None for v in _control_plane_axis_values(args))


def _reject_partial_control_plane_axes(args: argparse.Namespace) -> int | None:
    benchmark = getattr(args, "benchmark", None)
    slice_id = getattr(args, "slice", None)
    runtime = getattr(args, "runtime", None)
    model = getattr(args, "model", None)
    cp_selected = (benchmark, slice_id, runtime)
    if not any(cp_selected):
        return None
    if benchmark is not None and slice_id is not None and runtime is not None and model is not None:
        return None
    sys.stderr.write(
        "error: four-axis run requires all of --benchmark, --slice, --runtime, and --model\n",
    )
    return 2


def _run_dry(args: argparse.Namespace) -> int:
    partial_err = _reject_partial_control_plane_axes(args)
    if partial_err is not None:
        return partial_err
    if _control_plane_run_selected(args):
        plan = plan_control_plane(
            benchmark_id=args.benchmark,
            slice_id=args.slice,
            runtime_id=args.runtime,
            model_id=args.model,
            cleanup_policy=args.cleanup,
        )
        resolution = dry_run_slice_resolution(
            benchmark_id=args.benchmark,
            slice_id=args.slice,
        )
        payload = run_plan_to_dry_run_dict(plan, slice_resolution=resolution)
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0

    selected = sum(x is not None for x in (args.task, args.suite, args.manifest))
    if selected > 1:
        sys.stderr.write("error: choose only one of --task, --suite, or --manifest\n")
        return 2
    if args.manifest is not None:
        digest = load_manifest(Path(args.manifest))
        task_ids = read_manifest_task_ids(Path(args.manifest))
        payload = {
            "dry_run": True,
            "model_id": args.model,
            "backend": args.backend,
            "mode": args.mode,
            "cleanup": args.cleanup,
            "manifest": str(Path(args.manifest).resolve()),
            "benchmark": digest.benchmark,
            "task_manifest_hash": digest.content_sha256,
            "task_count": len(task_ids),
            "task_ids": list(task_ids),
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    if args.task is not None:
        payload = {
            "dry_run": True,
            "model_id": args.model,
            "backend": args.backend,
            "mode": args.mode,
            "cleanup": args.cleanup,
            "task_count": 1,
            "task_ids": [args.task],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    suite = args.suite or "smoke"
    plan = plan_dry_run(suite=suite, model_id=args.model)
    sys.stdout.write(json.dumps(plan.to_dict(), indent=2) + "\n")
    return 0


def _selected_task_ids(args: argparse.Namespace) -> tuple[list[str], dict[str, object]]:
    selected = sum(x is not None for x in (args.task, args.suite, args.manifest))
    if selected != 1:
        raise ValueError("non-dry-run requires exactly one of --task, --suite, or --manifest")
    if args.task is not None:
        return [args.task], {}
    if args.suite is not None:
        return list(tasks_for_suite(args.suite)), {"suite": args.suite}
    digest = load_manifest(Path(args.manifest))
    task_ids = read_manifest_task_ids(Path(args.manifest))
    return list(task_ids), {
        "manifest": str(Path(args.manifest).resolve()),
        "benchmark": digest.benchmark,
        "task_manifest_hash": digest.content_sha256,
        "manifest_order_preserved": True,
    }


def _artifacts_dir_for_task(
    *,
    artifacts_dir: Path | None,
    run_id: str,
    task_id: str,
    task_count: int,
) -> Path:
    if artifacts_dir is None:
        return _repo_root() / "results" / "raw" / run_id
    root = Path(artifacts_dir)
    if task_count == 1:
        return root
    return root / run_id / task_id


def _run_execute(args: argparse.Namespace) -> int:
    partial_err = _reject_partial_control_plane_axes(args)
    if partial_err is not None:
        return partial_err
    if _control_plane_run_selected(args):
        if args.output is None:
            sys.stderr.write("error: four-axis run requires --output evidence JSONL path\n")
            return 2
        plan = plan_control_plane(
            benchmark_id=args.benchmark,
            slice_id=args.slice,
            runtime_id=args.runtime,
            model_id=args.model,
            cleanup_policy=args.cleanup,
        )
        summary = execute_control_plane_run(
            plan=plan,
            output_path=Path(args.output),
            artifacts_dir=args.artifacts_dir,
        )
        payload = {
            "run_id": summary.run_id,
            "benchmark_id": plan.benchmark_id,
            "slice_id": plan.slice_id,
            "runtime_id": plan.runtime_id,
            "model_id": plan.model_id,
            "adapter_id": plan.adapter_id,
            "output": str(summary.output_path),
            "instance_count": summary.instance_count,
            "passed_count": summary.passed_count,
            "failed_count": summary.failed_count,
            "comparison_validity": plan.comparison_validity,
            "interpretation_label": control_plane_interpretation_label(plan),
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0 if summary.failed_count == 0 else 1

    if args.output is None:
        sys.stderr.write("error: non-dry-run requires --output evidence JSONL path\n")
        return 2
    mode = cast("RunMode", args.mode)
    cleanup_policy = cast("CleanupPolicy", args.cleanup)
    if cleanup_policy != "never" and mode != "single":
        sys.stderr.write("error: --cleanup is only supported with --mode single\n")
        return 2
    backend: ExecutionBackend = args.backend
    if backend == LOCAL_BACKEND and args.model != LOCAL_HARNESS_MODEL_ID:
        sys.stderr.write(
            f"error: local backend requires --model {LOCAL_HARNESS_MODEL_ID!r}; "
            f"got {args.model!r}. Use --backend inspect or harbor for provider models.\n",
        )
        return 1
    if backend != LOCAL_BACKEND and args.model == LOCAL_HARNESS_MODEL_ID:
        sys.stderr.write(
            "error: inspect/harbor backends require a real provider model id, "
            f"not {LOCAL_HARNESS_MODEL_ID!r}\n",
        )
        return 1

    try:
        task_ids, selection_metadata = _selected_task_ids(args)
    except (TaskContractError, BenchEvalError, ValueError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 2

    results = []
    removed_paths: list[str] = []
    for task_id in task_ids:
        run_id = new_run_id()
        run_artifacts_dir = _artifacts_dir_for_task(
            artifacts_dir=args.artifacts_dir,
            run_id=run_id,
            task_id=task_id,
            task_count=len(task_ids),
        )
        try:
            result = execute_task(
                task_id=task_id,
                model_id=args.model,
                backend=backend,
                output_path=Path(args.output),
                run_id=run_id,
                run_artifacts_dir=run_artifacts_dir,
            )
        except Exception:
            if mode == "single" and cleanup_policy == "always":
                cleanup = cleanup_transient_artifacts(
                    run_artifacts_dir,
                    policy=cleanup_policy,
                    primary_pass=False,
                )
                removed_paths.extend(cleanup.removed_paths)
            raise
        results.append(result)
        if mode == "single":
            cleanup = cleanup_transient_artifacts(
                run_artifacts_dir,
                policy=cleanup_policy,
                primary_pass=result.evidence.primary_pass,
            )
            removed_paths.extend(cleanup.removed_paths)
    last_result = results[-1]
    passed_count = sum(1 for result in results if result.evidence.primary_pass)
    failed_count = len(results) - passed_count
    failed_tasks = [
        result.evidence.task_id for result in results if not result.evidence.primary_pass
    ]
    payload = {
        "run_id": last_result.run_id,
        "task_id": last_result.evidence.task_id,
        "model_id": last_result.evidence.model_id,
        "backend": last_result.evidence.backend,
        "output": str(Path(args.output).resolve()),
        "mode": mode,
        "primary_pass": last_result.evidence.primary_pass,
        "partial_score": last_result.evidence.partial_score,
        "verifier_log_path": last_result.evidence.verifier_log_path,
        "failure_labels": last_result.evidence.failure_labels,
        "task_count": len(task_ids),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "failed_tasks": failed_tasks,
        "cleanup": {
            "policy": cleanup_policy,
            "removed_path_count": len(removed_paths),
            "removed_paths": removed_paths,
        },
    }
    payload.update(selection_metadata)
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0 if failed_count == 0 else 1


def _doctor_run(args: argparse.Namespace) -> int:
    if args.profile == "pilot":
        report = run_pilot_doctor(model_id=args.model)
    else:
        if args.backend is None:
            sys.stderr.write("error: --backend is required unless --profile pilot is used\n")
            return 2
        report = run_doctor(
            args.backend,
            model_id=args.model,
            execution_profile=args.profile,
        )
    sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    return 0 if report.ok else 1


def _export_warehouse(args: argparse.Namespace) -> int:
    from bencheval.export import export_evidence

    output = export_evidence(
        Path(args.evidence),
        fmt=args.format,
        output_dir=Path(args.output),
    )
    payload = {"format": args.format, "output": str(output.resolve())}
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


def _export_run_bundle(args: argparse.Namespace) -> int:
    from bencheval.run_bundle import RedactionMode, export_run_bundle

    archive = export_run_bundle(
        evidence_path=Path(args.evidence),
        output_dir=Path(args.output),
        raw_dir=args.raw_dir,
        redaction=cast("RedactionMode", args.redaction),
        compare_baseline=args.compare_baseline,
        compare_current=args.compare_current,
        compare_report_path=args.compare_report,
    )
    payload = {
        "bundle_dir": str(Path(args.output).resolve()),
        "archive": str(archive.resolve()),
        "redaction": args.redaction,
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


def _replay_run(args: argparse.Namespace) -> int:
    from bencheval.replay import load_run_record, replay, verify_bound_evidence

    if args.verify_evidence is not None:
        # nargs="?" means: None -> flag absent; "" -> derive by convention; path -> explicit.
        evidence_arg = args.verify_evidence or None
        rows = verify_bound_evidence(
            args.record,
            evidence_path=evidence_arg,
            allow_missing_evidence=args.allow_missing_evidence,
        )
        if args.format == "json":
            payload = {
                "record": str(Path(args.record).resolve()),
                "row_count": len(rows),
                "rows": [json.loads(r.model_dump_json()) for r in rows],
            }
            sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        else:
            run_record = load_run_record(args.record)
            binding = "legacy_unbound" if run_record.is_legacy_unbound else "v1_bound"
            if not rows and args.allow_missing_evidence:
                sys.stdout.write(
                    f"No evidence file found for run record {run_record.path} "
                    f"(schema {run_record.schema_version}, {binding}); "
                    f"--allow-missing-evidence was set.\n",
                )
            else:
                sys.stdout.write(
                    f"Verified {len(rows)} evidence row(s) bound to run record "
                    f"{run_record.path} (schema {run_record.schema_version}, {binding}).\n",
                )
            for r in rows:
                status = "PASS" if r.primary_pass else "FAIL"
                sys.stdout.write(
                    f"  {r.task_id} | {r.model_id} | {status} | "
                    f"cost=${r.cost_usd:.4f} | {r.latency_sec:.2f}s\n",
                )
        return 0
    return replay(
        args.record,
        color=not args.no_color,
        speed=args.speed,
        max_delay_sec=args.max_delay,
    )


def _compare_run(args: argparse.Namespace) -> int:
    from bencheval.evidence_compare import (
        compare_evidence_runs,
        render_comparison_json,
        render_comparison_markdown,
    )
    from bencheval.model_compare import (
        compare_model_evidence,
        is_model_comparison_evidence,
        render_model_comparison_json,
        render_model_comparison_markdown,
    )
    from bencheval.runtime_compare import (
        compare_runtime_evidence,
        is_dual_axis_comparison_drift,
        is_runtime_comparison_evidence,
        render_runtime_comparison_json,
        render_runtime_comparison_markdown,
    )

    baseline = read_evidence_jsonl(Path(args.baseline))
    current = read_evidence_jsonl(Path(args.current))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if is_dual_axis_comparison_drift(baseline, current):
        sys.stderr.write(
            "error: dual-axis drift: hold either model_id or runtime_id constant for comparison\n",
        )
        return 2

    use_runtime = is_runtime_comparison_evidence(baseline, current)
    use_model = not use_runtime and is_model_comparison_evidence(baseline, current)
    if use_model:
        model_report = compare_model_evidence(baseline, current)
        if args.format == "json":
            output_path.write_text(
                render_model_comparison_json(model_report),
                encoding="utf-8",
            )
        else:
            output_path.write_text(
                render_model_comparison_markdown(model_report),
                encoding="utf-8",
            )
        payload = {
            "mode": "model",
            "baseline": str(Path(args.baseline).resolve()),
            "current": str(Path(args.current).resolve()),
            "format": args.format,
            "output": str(output_path.resolve()),
            "interpretation_label": model_report.interpretation_label,
            "pass_rate_delta": model_report.pass_rate_delta,
            "comparison_valid": model_report.validity.valid,
        }
    elif use_runtime:
        runtime_report = compare_runtime_evidence(baseline, current)
        if args.format == "json":
            output_path.write_text(
                render_runtime_comparison_json(runtime_report),
                encoding="utf-8",
            )
        else:
            output_path.write_text(
                render_runtime_comparison_markdown(runtime_report),
                encoding="utf-8",
            )
        payload = {
            "mode": "runtime",
            "baseline": str(Path(args.baseline).resolve()),
            "current": str(Path(args.current).resolve()),
            "format": args.format,
            "output": str(output_path.resolve()),
            "interpretation_label": runtime_report.interpretation_label,
            "pass_rate_delta": runtime_report.pass_rate_delta,
            "comparison_valid": runtime_report.validity.valid,
        }
    else:
        report = compare_evidence_runs(baseline, current)
        if args.format == "json":
            output_path.write_text(render_comparison_json(report), encoding="utf-8")
        else:
            output_path.write_text(render_comparison_markdown(report), encoding="utf-8")
        payload = {
            "mode": "legacy",
            "baseline": str(Path(args.baseline).resolve()),
            "current": str(Path(args.current).resolve()),
            "format": args.format,
            "output": str(output_path.resolve()),
            "pass_rate_delta": report.pass_rate_delta,
        }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


def _report_generate(args: argparse.Namespace) -> int:
    evidence_path = Path(args.evidence)
    output_path = Path(args.output)
    records = read_evidence_jsonl(evidence_path)
    report_md = generate_evidence_report_with_runtime_panel(records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_md, encoding="utf-8")
    payload = {
        "evidence": str(evidence_path.resolve()),
        "output": str(output_path.resolve()),
        "record_count": len(records),
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


def _run_handler(args: argparse.Namespace) -> int:
    if args.dry_run:
        return _run_dry(args)
    return _run_execute(args)


def _resolve_optional_path(value: object) -> str | None:
    if value is None:
        return None
    return str(Path(str(value)).resolve())


_TERMINAL_RUN_STATUSES: frozenset[LiveRunStatus] = frozenset(
    {"completed", "passed", "failed", "archived"},
)


def _validate_register_artifact_paths(
    *,
    status: LiveRunStatus,
    evidence: Path | None,
    report: Path | None,
    bundle: Path | None,
    allow_missing: bool,
) -> str | None:
    if allow_missing:
        return None
    for label, path in (
        ("evidence", evidence),
        ("report", report),
        ("bundle", bundle),
    ):
        if path is None:
            continue
        resolved = path.resolve()
        if not resolved.is_file():
            return f"error: {label} path is not a regular file: {resolved}"
    if status in _TERMINAL_RUN_STATUSES and evidence is None:
        return "error: terminal status requires --evidence (or --allow-missing-artifacts for dev)"
    if status in _TERMINAL_RUN_STATUSES and evidence is not None:
        try:
            records = read_evidence_jsonl(evidence)
        except BenchEvalError as e:
            return f"error: evidence path is not valid EvidenceRecord JSONL: {e}"
        if not records:
            return "error: terminal status requires non-empty EvidenceRecord JSONL"
    return None


def _evidence_register(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest_path) if args.manifest_path else default_runs_manifest_path()
    host = args.host or socket.gethostname()
    allow_missing = bool(getattr(args, "allow_missing_artifacts", False))
    artifact_err = _validate_register_artifact_paths(
        status=cast("LiveRunStatus", args.status),
        evidence=args.evidence,
        report=args.report,
        bundle=args.bundle,
        allow_missing=allow_missing,
    )
    if artifact_err is not None:
        sys.stderr.write(f"{artifact_err}\n")
        return 1
    record = LiveRunRecord(
        run_id=args.run_id,
        host=host,
        benchmark=args.benchmark,
        slice_id=args.slice,
        runtime=args.runtime,
        model_id=args.model,
        evidence_path=_resolve_optional_path(args.evidence),
        report_path=_resolve_optional_path(args.report),
        bundle_path=_resolve_optional_path(args.bundle),
        status=args.status,
        notes=args.notes,
        generated_at=datetime.now(tz=UTC),
    )
    target = append_live_run(manifest_path, record)
    payload = {
        "schema_version": record.schema_version,
        "run_id": record.run_id,
        "host": record.host,
        "benchmark": record.benchmark,
        "slice_id": record.slice_id,
        "runtime": record.runtime,
        "model_id": record.model_id,
        "status": record.status,
        "manifest_path": str(target),
        "generated_at": record.generated_at.isoformat(),
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bencheval")
    sub = parser.add_subparsers(dest="command", required=True)

    task = sub.add_parser("task", help="Task contract operations")
    task_sub = task.add_subparsers(dest="task_command", required=True)

    lint = task_sub.add_parser("lint", help="Lint a task contract")
    lint.add_argument("target", help="Task id or path to YAML")
    lint.add_argument("--format", choices=("text", "json"), default="text")
    lint.set_defaults(handler=_task_lint)

    validate = task_sub.add_parser("validate", help="Validate a task contract")
    validate.add_argument("target", help="Task id or path to YAML")
    validate.set_defaults(handler=_task_validate)

    audit = task_sub.add_parser(
        "audit",
        help="Audit Core-8/Core-16 admission gates (exit 1 when not fully admitted)",
    )
    audit.add_argument("target", help="Task id or suite name (e.g. core-8, core-16, smoke)")
    audit.set_defaults(handler=_task_audit)

    benchmark = sub.add_parser("benchmark", help="External benchmark catalog operations")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_command", required=True)

    benchmark_list = benchmark_sub.add_parser(
        "list",
        help="List cataloged Calibration/Stretch benchmark support metadata",
    )
    benchmark_list.add_argument("--format", choices=("text", "json"), default="text")
    benchmark_list.add_argument(
        "--category",
        choices=get_args(BenchmarkCategory),
        default=None,
        help="Filter by benchmark category",
    )
    benchmark_list.add_argument(
        "--tier",
        choices=get_args(BenchmarkTier),
        default=None,
        help="Filter by BenchEval tier",
    )
    benchmark_list.add_argument(
        "--status",
        choices=get_args(BenchmarkAdapterStatus),
        default=None,
        help="Filter by adapter support status",
    )
    benchmark_list.add_argument(
        "--safety",
        choices=get_args(SafetyReview),
        default=None,
        help="Filter by safety review lane",
    )
    benchmark_list.add_argument(
        "--execution-support",
        dest="execution_support",
        choices=("executable_adapter", "manifest_only", "metadata_only"),
        default=None,
        help="Filter by execution_support (production: executable_adapter = 3 benchmarks)",
    )
    benchmark_list.set_defaults(handler=_benchmark_list)

    benchmark_show = benchmark_sub.add_parser(
        "show",
        help="Show one benchmark by id or alias",
    )
    benchmark_show.add_argument("target", help="Benchmark id or alias")
    benchmark_show.add_argument("--format", choices=("text", "json"), default="json")
    benchmark_show.set_defaults(handler=_benchmark_show)

    benchmark_slices = benchmark_sub.add_parser(
        "slices",
        help="List typed slice manifests for a benchmark",
    )
    benchmark_slices.add_argument("target", help="Benchmark id or alias")
    benchmark_slices.add_argument("--format", choices=("text", "json"), default="text")
    benchmark_slices.set_defaults(handler=_benchmark_slices)

    runtime = sub.add_parser("runtime", help="Runtime/scaffold registry")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)

    runtime_list = runtime_sub.add_parser("list", help="List runtime profiles")
    runtime_list.add_argument("--format", choices=("text", "json"), default="text")
    runtime_list.set_defaults(handler=_runtime_list)

    runtime_show = runtime_sub.add_parser("show", help="Show one runtime profile")
    runtime_show.add_argument("target", help="Runtime id")
    runtime_show.add_argument("--format", choices=("text", "json"), default="json")
    runtime_show.set_defaults(handler=_runtime_show)

    model = sub.add_parser("model", help="Model registry (non-secret metadata)")
    model_sub = model.add_subparsers(dest="model_command", required=True)

    model_list = model_sub.add_parser("list", help="List registered models")
    model_list.add_argument("--format", choices=("text", "json"), default="text")
    model_list.set_defaults(handler=_model_list)

    model_show = model_sub.add_parser("show", help="Show one model entry")
    model_show.add_argument("target", help="Model id")
    model_show.add_argument("--format", choices=("text", "json"), default="json")
    model_show.set_defaults(handler=_model_show)

    adapter = sub.add_parser("adapter", help="Planned benchmark adapter catalog")
    adapter_sub = adapter.add_subparsers(dest="adapter_command", required=True)

    adapter_list = adapter_sub.add_parser("list", help="List adapter descriptors")
    adapter_list.add_argument("--format", choices=("text", "json"), default="text")
    adapter_list.set_defaults(handler=_adapter_list)

    run = sub.add_parser("run", help="Run planning and execution")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate run envelope without executing",
    )
    run.add_argument(
        "--benchmark",
        default=None,
        help="Benchmark id for four-axis control-plane run (with --slice, --runtime, --model)",
    )
    run.add_argument("--slice", default=None, help="Slice id for four-axis control-plane run")
    run.add_argument("--runtime", default=None, help="Runtime id for four-axis control-plane run")
    run.add_argument("--suite", default=None, help="Suite name for dry-run or batch execution")
    run.add_argument("--task", default=None, help="Single task id for non-dry-run execution")
    run.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Task-id manifest for sequential execution (one id per non-comment line)",
    )
    run.add_argument("--model", dest="model", required=True, help="Model identifier")
    run.add_argument(
        "--backend",
        choices=(LOCAL_BACKEND, INSPECT_BACKEND, HARBOR_BACKEND),
        default=LOCAL_BACKEND,
        help="Execution backend (default: local reference harness)",
    )
    run.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Evidence JSONL output path (required for non-dry-run)",
    )
    run.add_argument(
        "--artifacts-dir",
        type=Path,
        default=None,
        help="Directory for verifier logs (default: results/raw/<run_id>/)",
    )
    run.add_argument(
        "--mode",
        choices=("batch", "single"),
        default="batch",
        help=(
            "Execution lifecycle mode. 'single' runs one task lifecycle at a time "
            "and enables transient cleanup."
        ),
    )
    run.add_argument(
        "--cleanup",
        choices=("never", "on-success", "always"),
        default="never",
        help="Transient cleanup policy for --mode single (default: never)",
    )
    run.set_defaults(handler=_run_handler)

    report = sub.add_parser("report", help="Generate Markdown report from evidence JSONL")
    report.add_argument("evidence", type=Path, help="Evidence JSONL input path")
    report.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Markdown report output path",
    )
    report.set_defaults(handler=_report_generate)

    doctor = sub.add_parser("doctor", help="Preflight checks for live execution backends")
    doctor.add_argument(
        "--backend",
        choices=(INSPECT_BACKEND, HARBOR_BACKEND),
        default=None,
        help="Backend to check (required unless --profile pilot is used)",
    )
    doctor.add_argument(
        "--model",
        default=None,
        help="Optional model id to check provider credential env vars",
    )
    doctor.add_argument(
        "--profile",
        choices=("E0", "E1", "E2", "pilot"),
        default=None,
        help=(
            "Execution profile for profile-specific checks (Inspect E1/Harbor require Docker); "
            "'pilot' aggregates harbor/docker/bfcl/mini-extra host deps"
        ),
    )
    doctor.set_defaults(handler=_doctor_run)

    compare = sub.add_parser("compare", help="Compare two vNext evidence JSONL runs")
    compare.add_argument("baseline", type=Path, help="Baseline evidence JSONL path")
    compare.add_argument("current", type=Path, help="Current evidence JSONL path")
    compare.add_argument(
        "--format",
        choices=("md", "json"),
        default="md",
        help="Comparison report format (default: md)",
    )
    compare.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Comparison report output path",
    )
    compare.set_defaults(handler=_compare_run)

    evidence = sub.add_parser("evidence", help="Live run registry operations")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)

    evidence_register = evidence_sub.add_parser(
        "register",
        help="Append a live run record to the runs manifest JSONL",
    )
    evidence_register.add_argument("--run-id", required=True, help="Run identifier")
    evidence_register.add_argument(
        "--model",
        required=True,
        help="Model identifier (non-secret metadata only)",
    )
    evidence_register.add_argument("--benchmark", default=None, help="Benchmark id")
    evidence_register.add_argument("--slice", default=None, help="Slice id")
    evidence_register.add_argument("--runtime", default=None, help="Runtime id")
    evidence_register.add_argument(
        "--evidence",
        type=Path,
        default=None,
        help="Evidence JSONL path (resolved and stored as evidence_path)",
    )
    evidence_register.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Report path (resolved and stored as report_path)",
    )
    evidence_register.add_argument(
        "--bundle",
        type=Path,
        default=None,
        help="Bundle archive path (resolved and stored as bundle_path)",
    )
    evidence_register.add_argument(
        "--status",
        choices=get_args(LiveRunStatus),
        default="registered",
        help=(
            "Run status (default: registered; terminal statuses require "
            "valid non-empty EvidenceRecord JSONL)"
        ),
    )
    evidence_register.add_argument(
        "--notes",
        default="",
        help="Free-form notes (no secrets; secret-like content is rejected)",
    )
    evidence_register.add_argument(
        "--host",
        default=None,
        help="Host name (default: auto-detected via socket.gethostname)",
    )
    evidence_register.add_argument(
        "--manifest-path",
        type=Path,
        default=None,
        help="Runs manifest JSONL path (default: results/manifests/runs.jsonl)",
    )
    evidence_register.add_argument(
        "--allow-missing-artifacts",
        action="store_true",
        help="Skip artifact path existence checks (development only)",
    )
    evidence_register.set_defaults(handler=_evidence_register)

    export = sub.add_parser("export", help="Export evidence JSONL to analytics tables")
    export.add_argument("evidence", type=Path, help="Evidence JSONL input path")
    export.add_argument(
        "--format",
        choices=("parquet", "duckdb"),
        default="parquet",
        help="Export format (default: parquet)",
    )
    export.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output directory for warehouse tables",
    )
    export.set_defaults(handler=_export_warehouse)

    export_run = sub.add_parser(
        "export-run",
        help="Bundle evidence, report, raw artifacts, manifest, and tar.gz",
    )
    export_run.add_argument("--evidence", type=Path, required=True, help="Evidence JSONL path")
    export_run.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Empty or new bundle directory (archive written alongside as <name>.tar.gz)",
    )
    export_run.add_argument(
        "--raw-dir",
        type=Path,
        default=None,
        help="Optional raw logs/artifacts tree to copy into bundle/raw/",
    )
    export_run.add_argument(
        "--redaction",
        choices=("public", "private"),
        default="private",
        help="public redacts sensitive hints; private keeps full evidence (never paste into chat)",
    )
    export_run.add_argument(
        "--compare-baseline",
        type=Path,
        default=None,
        help="Optional baseline evidence path recorded in manifest.json",
    )
    export_run.add_argument(
        "--compare-current",
        type=Path,
        default=None,
        help="Optional current evidence path recorded in manifest.json",
    )
    export_run.add_argument(
        "--compare-report",
        type=Path,
        default=None,
        help="Optional compare report markdown copied as compare_report.md",
    )
    export_run.set_defaults(handler=_export_run_bundle)

    replay = sub.add_parser(
        "replay",
        help="Replay a captured run record (events.jsonl) to the terminal",
    )
    replay.add_argument(
        "record",
        type=Path,
        help="Run record JSONL (events.jsonl) produced by a live run or adapter",
    )
    replay.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color in the replayed output",
    )
    replay.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Replay speed multiplier (default: 1.0; >1 speeds up, <1 slows down)",
    )
    replay.add_argument(
        "--max-delay",
        type=float,
        default=2.0,
        help="Cap per-event sleep at this many seconds (default: 2.0)",
    )
    replay.add_argument(
        "--verify-evidence",
        nargs="?",
        const="",
        default=None,
        type=str,
        help=(
            "Verify evidence rows bound to this run record. Without a path argument, "
            "derives the sibling evidence file by convention. With a path, uses it "
            "explicitly. Prints a summary (text) or full rows (json)."
        ),
    )
    replay.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format for --verify-evidence (default: text)",
    )
    replay.add_argument(
        "--allow-missing-evidence",
        action="store_true",
        help="Do not fail when the evidence file is missing (dry inspection; default: fail)",
    )
    replay.set_defaults(handler=_replay_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (BenchEvalError, TaskContractError, ValueError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
