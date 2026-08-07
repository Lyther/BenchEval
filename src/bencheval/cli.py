"""BenchEval CLI: list / run / doctor / catalog / report / compare / export."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

from bencheval.agent_registry import load_agent_catalog
from bencheval.benchmark_plan import (
    dry_run_slice_resolution,
    plan_control_plane,
    run_plan_to_dry_run_dict,
)
from bencheval.benchmark_registry import (
    BenchmarkAdapterStatus,
    BenchmarkCategory,
    BenchmarkEntry,
    BenchmarkFilter,
    BenchmarkTier,
    execution_support_label,
    filter_benchmarks,
    load_benchmark_catalog,
)
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.doctor import run_doctor, run_pilot_doctor
from bencheval.domain import RunPlan
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.ids import new_run_id
from bencheval.live_run_manifest import (
    LiveRunRecord,
    LiveRunStatus,
    append_live_run,
    default_runs_manifest_path,
)
from bencheval.model_registry import load_model_registry
from bencheval.provider_registry import DEFAULT_PROVIDER_ID, load_provider_catalog
from bencheval.report import generate_evidence_report_with_runtime_panel
from bencheval.runtime_registry import load_runtime_catalog


def _benchmark_payload(benchmark: BenchmarkEntry) -> dict[str, object]:
    data = benchmark.model_dump(mode="json")
    data["execution_support"] = execution_support_label(benchmark)
    return data


def _list_benchmarks(args: argparse.Namespace) -> int:
    catalog = load_benchmark_catalog()
    support = getattr(args, "execution_support", "executable_adapter")
    filtered = filter_benchmarks(
        catalog,
        BenchmarkFilter(
            category=args.category,
            tier=args.tier,
            adapter_status=args.status,
            execution_support=None if support == "all" else support,
        ),
    )
    if args.format == "json":
        payload = {
            "count": len(filtered),
            "benchmarks": [_benchmark_payload(b) for b in filtered],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0
    for b in filtered:
        sys.stdout.write(f"{b.id}\t{execution_support_label(b)}\t{b.name}\n")
    return 0


def _parse_target(target: str) -> tuple[str, str]:
    """Parse ``benchmark/slice`` or bare ``benchmark`` (uses catalog ``default_slice``)."""
    raw = target.strip()
    if not raw:
        raise BenchEvalError("run target must be <benchmark> or <benchmark>/<slice>")
    if "/" in raw:
        benchmark_id, slice_id = raw.split("/", 1)
        if not benchmark_id or not slice_id:
            raise BenchEvalError(f"run target must be <benchmark>/<slice>, got {target!r}")
        return benchmark_id, slice_id
    catalog = load_benchmark_catalog()
    try:
        entry = catalog.by_id_or_alias(raw)
    except KeyError as e:
        raise BenchEvalError(f"benchmark not found: {raw!r}") from e
    if entry.default_slice is None:
        raise BenchEvalError(
            f"run target {raw!r} needs an explicit /<slice> "
            f"(benchmark {entry.id!r} has no default_slice)",
        )
    return entry.id, entry.default_slice


def _build_plan(args: argparse.Namespace) -> RunPlan:
    benchmark_id, slice_id = _parse_target(args.target)
    return plan_control_plane(
        benchmark_id=benchmark_id,
        slice_id=slice_id,
        runtime_id=args.runtime,
        agent_id=args.agent,
        provider_id=args.provider,
        model_id=args.model,
    )


def _print_plan_envelope(plan: RunPlan, *, slice_resolution: dict[str, object]) -> None:
    payload = run_plan_to_dry_run_dict(plan, slice_resolution=slice_resolution)
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")


def _confirm_continue(plan: RunPlan) -> bool:
    cost_note = f"~${plan.max_cost_usd:.2f}"
    if "max_cost_usd_unenforced_estimate" in plan.caveats:
        cost_note = f"~${plan.max_cost_usd:.2f} unenforced estimate"
    prompt = (
        f"Continue? ({cost_note}, {len(plan.instances)} instances, "
        f"provider={plan.provider_id}) [y/N] "
    )
    try:
        answer = input(prompt)
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def _run_command(args: argparse.Namespace) -> int:
    if not args.model:
        sys.stderr.write("error: --model is required\n")
        return 2
    try:
        plan = _build_plan(args)
        resolution = dry_run_slice_resolution(
            benchmark_id=plan.benchmark_id,
            slice_id=plan.slice_id,
        )
    except BenchEvalError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    support = resolution.get("execution_support")
    if support != "executable_adapter":
        sys.stderr.write(
            f"error: benchmark {plan.benchmark_id!r} has execution_support={support!r}; "
            "requires executable_adapter\n",
        )
        return 1

    _print_plan_envelope(plan, slice_resolution=resolution)
    if args.dry_run:
        return 0
    if not args.yes and not _confirm_continue(plan):
        sys.stderr.write("aborted\n")
        return 1

    rid = new_run_id()
    root = Path.cwd()
    output = Path(args.output) if args.output else root / "results" / "evidence" / f"{rid}.jsonl"
    artifacts = Path(args.artifacts_dir) if args.artifacts_dir else root / "results" / "raw" / rid
    try:
        summary = execute_control_plane_run(
            plan=plan,
            output_path=output,
            artifacts_dir=artifacts,
            run_id=rid,
        )
    except BenchEvalError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    payload = {
        "run_id": summary.run_id,
        "instance_count": summary.instance_count,
        "passed_count": summary.passed_count,
        "failed_count": summary.failed_count,
        "output": str(summary.output_path),
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0 if summary.failed_count == 0 else 1


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


def _catalog_benchmark_list(args: argparse.Namespace) -> int:
    return _list_benchmarks(args)


def _catalog_benchmark_show(args: argparse.Namespace) -> int:
    try:
        b = load_benchmark_catalog().by_id_or_alias(args.benchmark_id)
    except BenchEvalError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    sys.stdout.write(json.dumps(_benchmark_payload(b), indent=2) + "\n")
    return 0


def _catalog_runtime_list(args: argparse.Namespace) -> int:
    catalog = load_runtime_catalog()
    rows = [
        {"id": rp.runtime.id, "display_name": rp.runtime.display_name, "admission": rp.admission}
        for rp in catalog.runtimes
    ]
    if args.format == "json":
        sys.stdout.write(json.dumps({"count": len(rows), "runtimes": rows}, indent=2) + "\n")
    else:
        for row in rows:
            sys.stdout.write(f"{row['id']}\t{row['admission']}\t{row['display_name']}\n")
    return 0


def _catalog_runtime_show(args: argparse.Namespace) -> int:
    try:
        rp = load_runtime_catalog().by_id(args.runtime_id)
    except KeyError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    sys.stdout.write(json.dumps(rp.model_dump(mode="json"), indent=2) + "\n")
    return 0


def _catalog_agent_list(args: argparse.Namespace) -> int:
    catalog = load_agent_catalog()
    rows = [
        {"id": a.agent.id, "display_name": a.agent.display_name, "admission": a.admission}
        for a in catalog.agents
    ]
    if args.format == "json":
        sys.stdout.write(json.dumps({"count": len(rows), "agents": rows}, indent=2) + "\n")
    else:
        for row in rows:
            sys.stdout.write(f"{row['id']}\t{row['admission']}\t{row['display_name']}\n")
    return 0


def _catalog_agent_show(args: argparse.Namespace) -> int:
    try:
        profile = load_agent_catalog().by_id(args.agent_id)
    except KeyError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    sys.stdout.write(json.dumps(profile.model_dump(mode="json"), indent=2) + "\n")
    return 0


def _catalog_provider_list(args: argparse.Namespace) -> int:
    catalog = load_provider_catalog()
    rows = [
        {
            "id": p.provider.id,
            "display_name": p.provider.display_name,
            "admission": p.admission,
        }
        for p in catalog.providers
    ]
    if args.format == "json":
        sys.stdout.write(json.dumps({"count": len(rows), "providers": rows}, indent=2) + "\n")
    else:
        for row in rows:
            sys.stdout.write(f"{row['id']}\t{row['admission']}\t{row['display_name']}\n")
    return 0


def _catalog_provider_show(args: argparse.Namespace) -> int:
    try:
        profile = load_provider_catalog().by_id(args.provider_id)
    except KeyError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    sys.stdout.write(json.dumps(profile.model_dump(mode="json"), indent=2) + "\n")
    return 0


def _catalog_model_list(args: argparse.Namespace) -> int:
    registry = load_model_registry()
    rows = [m.model_dump(mode="json") for m in registry.models]
    if args.format == "json":
        sys.stdout.write(json.dumps({"count": len(rows), "models": rows}, indent=2) + "\n")
    else:
        for m in registry.models:
            route = m.provider_route or "-"
            sys.stdout.write(f"{m.id}\t{route}\t{m.display_name}\n")
    return 0


def _catalog_model_show(args: argparse.Namespace) -> int:
    try:
        entry = load_model_registry().by_id(args.model_id)
    except KeyError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    sys.stdout.write(json.dumps(entry.model_dump(mode="json"), indent=2) + "\n")
    return 0


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

    try:
        baseline = read_evidence_jsonl(Path(args.baseline))
        current = read_evidence_jsonl(Path(args.current))
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if is_dual_axis_comparison_drift(baseline, current):
            sys.stderr.write(
                "error: dual-axis drift: hold either model_id or runtime_id constant "
                "for comparison\n",
            )
            return 2

        use_runtime = is_runtime_comparison_evidence(baseline, current)
        use_model = not use_runtime and is_model_comparison_evidence(baseline, current)
        fmt = "json" if args.format == "json" else "markdown"
        if use_model:
            model_report = compare_model_evidence(baseline, current)
            if fmt == "json":
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
                "format": fmt,
                "output": str(output_path.resolve()),
                "interpretation_label": model_report.interpretation_label,
                "pass_rate_delta": model_report.pass_rate_delta,
                "comparison_valid": model_report.validity.valid,
            }
            comparison_valid = model_report.validity.valid
        elif use_runtime:
            runtime_report = compare_runtime_evidence(baseline, current)
            if fmt == "json":
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
                "format": fmt,
                "output": str(output_path.resolve()),
                "interpretation_label": runtime_report.interpretation_label,
                "pass_rate_delta": runtime_report.pass_rate_delta,
                "comparison_valid": runtime_report.validity.valid,
            }
            comparison_valid = runtime_report.validity.valid
        else:
            report = compare_evidence_runs(baseline, current)
            if fmt == "json":
                output_path.write_text(render_comparison_json(report), encoding="utf-8")
            else:
                output_path.write_text(render_comparison_markdown(report), encoding="utf-8")
            payload = {
                "mode": "legacy",
                "baseline": str(Path(args.baseline).resolve()),
                "current": str(Path(args.current).resolve()),
                "format": fmt,
                "output": str(output_path.resolve()),
                "pass_rate_delta": report.pass_rate_delta,
            }
            comparison_valid = True
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        # Pilot proof treats a zero exit as a successful comparison; invalid
        # model/runtime comparisons must not look green (F005).
        return 0 if comparison_valid else 1
    except BenchEvalError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1


def _report_generate(args: argparse.Namespace) -> int:
    evidence_path = Path(args.evidence)
    output_path = Path(args.output)
    try:
        records = read_evidence_jsonl(evidence_path)
        report_md = generate_evidence_report_with_runtime_panel(records)
    except BenchEvalError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_md, encoding="utf-8")
    payload = {
        "evidence": str(evidence_path.resolve()),
        "output": str(output_path.resolve()),
        "record_count": len(records),
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


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
    from pydantic import ValidationError

    from bencheval.exceptions import LiveRunManifestError

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
    try:
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
            notes=args.notes or "",
            generated_at=datetime.now(tz=UTC),
        )
        target = append_live_run(manifest_path, record)
    except (LiveRunManifestError, ValidationError, ValueError) as e:
        sys.stderr.write(f"error: {e}\n")
        return 1
    payload = {
        "schema_version": record.schema_version,
        "run_id": record.run_id,
        "host": record.host,
        "benchmark": record.benchmark,
        "slice_id": record.slice_id,
        "runtime": record.runtime,
        "model_id": record.model_id,
        "status": record.status,
        "manifest_path": str(target.resolve()),
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


def _add_benchmark_list_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--category", choices=get_args(BenchmarkCategory), default=None)
    parser.add_argument("--tier", choices=get_args(BenchmarkTier), default=None)
    parser.add_argument("--status", choices=get_args(BenchmarkAdapterStatus), default=None)
    parser.add_argument(
        "--execution-support",
        dest="execution_support",
        choices=("executable_adapter", "manifest_only", "metadata_only", "all"),
        default="executable_adapter",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bencheval",
        description=(
            "benchmark → (runtime|agent)? → model → evidence. "
            "Providers bind models (bytellm | ollama-cloud)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="List runnable benchmarks")
    _add_benchmark_list_flags(list_cmd)
    list_cmd.set_defaults(handler=_list_benchmarks)

    # Compat alias used by production gate / existing tests.
    benchmark = sub.add_parser("benchmark", help="Benchmark catalog (compat)")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_command", required=True)
    bl = benchmark_sub.add_parser("list", help="List benchmarks")
    _add_benchmark_list_flags(bl)
    bl.set_defaults(handler=_list_benchmarks)
    bs = benchmark_sub.add_parser("show", help="Show one benchmark")
    bs.add_argument("benchmark_id")
    bs.set_defaults(handler=_catalog_benchmark_show)

    run = sub.add_parser("run", help="Plan then optionally execute a benchmark slice")
    run.add_argument("target", help="<benchmark>/<slice>")
    run.add_argument("--model", required=True)
    run.add_argument("--runtime", default=None)
    run.add_argument("--agent", default=None)
    run.add_argument("--provider", default=DEFAULT_PROVIDER_ID)
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("-y", "--yes", action="store_true", help="Skip continue prompt")
    run.add_argument("--output", default=None)
    run.add_argument("--artifacts-dir", default=None)
    run.set_defaults(handler=_run_command)

    doctor = sub.add_parser("doctor", help="Preflight checks")
    doctor.add_argument("--backend", choices=("inspect", "harbor"), default=None)
    doctor.add_argument("--profile", choices=("E0", "E1", "E2", "E3", "E4", "pilot"), default=None)
    doctor.add_argument("--model", default=None)
    doctor.set_defaults(handler=_doctor_run)

    catalog = sub.add_parser("catalog", help="Discover benchmarks/runtimes/agents/models/providers")
    catalog_sub = catalog.add_subparsers(dest="catalog_group", required=True)

    cb = catalog_sub.add_parser("benchmark")
    cb_sub = cb.add_subparsers(dest="catalog_command", required=True)
    cbl = cb_sub.add_parser("list")
    _add_benchmark_list_flags(cbl)
    cbl.set_defaults(handler=_catalog_benchmark_list)
    cbs = cb_sub.add_parser("show")
    cbs.add_argument("benchmark_id")
    cbs.set_defaults(handler=_catalog_benchmark_show)

    cr = catalog_sub.add_parser("runtime")
    cr_sub = cr.add_subparsers(dest="catalog_command", required=True)
    crl = cr_sub.add_parser("list")
    crl.add_argument("--format", choices=("text", "json"), default="text")
    crl.set_defaults(handler=_catalog_runtime_list)
    crs = cr_sub.add_parser("show")
    crs.add_argument("runtime_id")
    crs.set_defaults(handler=_catalog_runtime_show)

    ca = catalog_sub.add_parser("agent")
    ca_sub = ca.add_subparsers(dest="catalog_command", required=True)
    cal = ca_sub.add_parser("list")
    cal.add_argument("--format", choices=("text", "json"), default="text")
    cal.set_defaults(handler=_catalog_agent_list)
    cas = ca_sub.add_parser("show")
    cas.add_argument("agent_id")
    cas.set_defaults(handler=_catalog_agent_show)

    cp = catalog_sub.add_parser("provider")
    cp_sub = cp.add_subparsers(dest="catalog_command", required=True)
    cpl = cp_sub.add_parser("list")
    cpl.add_argument("--format", choices=("text", "json"), default="text")
    cpl.set_defaults(handler=_catalog_provider_list)
    cps = cp_sub.add_parser("show")
    cps.add_argument("provider_id")
    cps.set_defaults(handler=_catalog_provider_show)

    cm = catalog_sub.add_parser("model")
    cm_sub = cm.add_subparsers(dest="catalog_command", required=True)
    cml = cm_sub.add_parser("list")
    cml.add_argument("--format", choices=("text", "json"), default="text")
    cml.set_defaults(handler=_catalog_model_list)
    cms = cm_sub.add_parser("show")
    cms.add_argument("model_id")
    cms.set_defaults(handler=_catalog_model_show)

    report = sub.add_parser("report", help="Generate markdown report from evidence JSONL")
    report.add_argument("evidence")
    report.add_argument("--output", required=True)
    report.set_defaults(handler=_report_generate)

    compare = sub.add_parser("compare", help="Compare two evidence JSONL files")
    compare.add_argument("baseline")
    compare.add_argument("current")
    compare.add_argument("--output", required=True)
    compare.add_argument("--format", choices=("markdown", "json", "md"), default="markdown")
    compare.set_defaults(handler=_compare_run)

    export = sub.add_parser("export", help="Export evidence to warehouse tables")
    export.add_argument("evidence")
    export.add_argument("--format", choices=("parquet", "duckdb"), default="parquet")
    export.add_argument("--output", required=True)
    export.set_defaults(handler=_export_warehouse)

    export_run = sub.add_parser("export-run", help="Export a redacted run bundle")
    export_run.add_argument("--evidence", required=True)
    export_run.add_argument("--output", required=True)
    export_run.add_argument("--raw-dir", default=None, type=Path)
    export_run.add_argument(
        "--redaction",
        choices=("public", "private"),
        default="private",
    )
    export_run.add_argument("--compare-baseline", default=None, type=Path)
    export_run.add_argument("--compare-current", default=None, type=Path)
    export_run.add_argument("--compare-report", default=None, type=Path)
    export_run.set_defaults(handler=_export_run_bundle)

    evidence = sub.add_parser("evidence", help="Evidence helpers")
    evidence_sub = evidence.add_subparsers(dest="evidence_command", required=True)
    register = evidence_sub.add_parser("register", help="Append a live-run manifest row")
    register.add_argument("--run-id", required=True)
    register.add_argument("--benchmark", default=None)
    register.add_argument("--slice", default=None)
    register.add_argument("--runtime", default=None)
    register.add_argument("--model", required=True)
    register.add_argument("--status", required=True, choices=get_args(LiveRunStatus))
    register.add_argument("--evidence", default=None, type=Path)
    register.add_argument("--report", default=None, type=Path)
    register.add_argument("--bundle", default=None, type=Path)
    register.add_argument("--notes", default=None)
    register.add_argument("--host", default=None)
    register.add_argument("--manifest-path", default=None)
    register.add_argument("--allow-missing-artifacts", action="store_true")
    register.set_defaults(handler=_evidence_register)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return int(handler(args))
    except BenchEvalError as e:
        sys.stderr.write(f"error: {e}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
