"""BenchEval vNext CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bencheval.admission import audit_suite_admission, audit_task_admission
from bencheval.backends import HARBOR_BACKEND, INSPECT_BACKEND, LOCAL_BACKEND, ExecutionBackend
from bencheval.doctor import run_doctor
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError, TaskContractError
from bencheval.executor import execute_task
from bencheval.planner import plan_dry_run
from bencheval.report import generate_evidence_report
from bencheval.runner import LOCAL_HARNESS_MODEL_ID, new_run_id
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
        report = audit_task_admission(target)
        payload = report.to_dict()
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    admitted = payload.get("admitted", False)
    return 0 if admitted else 1


def _run_dry(args: argparse.Namespace) -> int:
    suite = args.suite or "smoke"
    plan = plan_dry_run(suite=suite, model_id=args.model)
    sys.stdout.write(json.dumps(plan.to_dict(), indent=2) + "\n")
    return 0


def _run_execute(args: argparse.Namespace) -> int:
    if args.output is None:
        sys.stderr.write("error: non-dry-run requires --output evidence JSONL path\n")
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

    task_ids: list[str]
    if args.task is not None:
        task_ids = [args.task]
    elif args.suite is not None:
        task_ids = list(tasks_for_suite(args.suite))
    else:
        sys.stderr.write("error: non-dry-run requires --task or --suite\n")
        return 2

    results = []
    for task_id in task_ids:
        run_id = new_run_id()
        run_artifacts_dir = args.artifacts_dir
        if run_artifacts_dir is not None:
            if len(task_ids) == 1:
                run_artifacts_dir = Path(run_artifacts_dir)
            else:
                run_artifacts_dir = Path(run_artifacts_dir) / run_id / task_id
        results.append(
            execute_task(
                task_id=task_id,
                model_id=args.model,
                backend=backend,
                output_path=Path(args.output),
                run_id=run_id,
                run_artifacts_dir=run_artifacts_dir,
            ),
        )
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
        "primary_pass": last_result.evidence.primary_pass,
        "partial_score": last_result.evidence.partial_score,
        "verifier_log_path": last_result.evidence.verifier_log_path,
        "failure_labels": last_result.evidence.failure_labels,
        "task_count": len(task_ids),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "failed_tasks": failed_tasks,
    }
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0 if failed_count == 0 else 1


def _doctor_run(args: argparse.Namespace) -> int:
    report = run_doctor(
        args.backend,
        model_id=args.model,
        execution_profile=args.profile,
    )
    sys.stdout.write(json.dumps(report.to_dict(), indent=2) + "\n")
    return 0 if report.ok else 1


def _export_run(args: argparse.Namespace) -> int:
    from bencheval.export import export_evidence

    output = export_evidence(
        Path(args.evidence),
        fmt=args.format,
        output_dir=Path(args.output),
    )
    payload = {"format": args.format, "output": str(output.resolve())}
    sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    return 0


def _compare_run(args: argparse.Namespace) -> int:
    from bencheval.evidence_compare import (
        compare_evidence_runs,
        render_comparison_json,
        render_comparison_markdown,
    )

    baseline = read_evidence_jsonl(Path(args.baseline))
    current = read_evidence_jsonl(Path(args.current))
    report = compare_evidence_runs(baseline, current)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        output_path.write_text(render_comparison_json(report), encoding="utf-8")
    else:
        output_path.write_text(render_comparison_markdown(report), encoding="utf-8")
    payload = {
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
    report_md = generate_evidence_report(records)
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

    audit = task_sub.add_parser("audit", help="Audit Core-8 admission gates")
    audit.add_argument("target", help="Task id or suite name (e.g. core-8, smoke)")
    audit.set_defaults(handler=_task_audit)

    run = sub.add_parser("run", help="Run planning and execution")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="Estimate run envelope without executing",
    )
    run.add_argument("--suite", default=None, help="Suite name for dry-run or batch execution")
    run.add_argument("--task", default=None, help="Single task id for non-dry-run execution")
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
        required=True,
        help="Backend to check",
    )
    doctor.add_argument(
        "--model",
        default=None,
        help="Optional model id to check provider credential env vars",
    )
    doctor.add_argument(
        "--profile",
        choices=("E0", "E1", "E2"),
        default=None,
        help="Execution profile for profile-specific checks (Inspect E1/Harbor require Docker)",
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
    export.set_defaults(handler=_export_run)

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
