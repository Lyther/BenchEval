#!/usr/bin/env python3
"""Compare two JSONL summary files and emit a §7 delta report (Markdown or JSON)."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC
from pathlib import Path

from bencheval import GuardedComparisonReporter, read_summary_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.models import ComparisonReport


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Compare BenchEval JSONL summary runs.")
    p.add_argument("--baseline", type=Path, required=True, help="Path to baseline JSONL summaries")
    p.add_argument("--current", type=Path, required=True, help="Path to current JSONL summaries")
    p.add_argument(
        "--equivalence-note",
        default=None,
        help="Optional note when auth lanes differ but are treated as comparable",
    )
    p.add_argument(
        "--format",
        choices=("md", "json"),
        default="md",
        help="Output format",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write output to this path (default: stdout)",
    )
    return p.parse_args(argv)


def _fmt_num(x: float | None) -> str:
    if x is None:
        return "n/a"
    return f"{x:.4f}"


def _fmt_ci(lo: float | None, hi: float | None) -> str:
    if lo is None or hi is None:
        return "n/a"
    return f"[{_fmt_num(lo)}, {_fmt_num(hi)}]"


def _render_markdown(report: ComparisonReport) -> str:
    gen = report.generated_at
    if gen.tzinfo is None:
        gen = gen.replace(tzinfo=UTC)
    else:
        gen = gen.astimezone(UTC)
    gen_s = gen.isoformat().replace("+00:00", "Z")
    note_line = report.equivalence_note if report.equivalence_note is not None else "`(none)`"
    lines = [
        f"# {report.title}",
        "",
        f"- Generated: {gen_s}",
        f"- Equivalence note: {note_line}",
        "",
        "| Metric | Baseline | Current | Delta | 95% CI |",
        "|---|---:|---:|---:|---|",
    ]
    for m in report.metrics:
        lines.append(
            "| "
            + " | ".join(
                [
                    m.label,
                    _fmt_num(m.baseline),
                    _fmt_num(m.compare),
                    _fmt_num(m.delta),
                    _fmt_ci(m.ci_low, m.ci_high),
                ],
            )
            + " |",
        )
    lines.append("")
    return "\n".join(lines)


def _emit(text: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        baseline_rows = read_summary_jsonl(args.baseline)
        current_rows = read_summary_jsonl(args.current)
        report = GuardedComparisonReporter().compare(
            baseline_rows,
            current_rows,
            equivalence_note=args.equivalence_note,
        )
        if args.format == "json":
            out = report.model_dump_json(indent=2) + "\n"
        else:
            out = _render_markdown(report)
        _emit(out, args.output)
        return 0
    except BenchEvalError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
