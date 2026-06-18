"""Deterministic Markdown report generator for evidence records."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from bencheval.evidence import EvidenceRecord
from bencheval.runtime_compare import (
    compare_runtime_evidence,
    is_runtime_comparison_evidence,
    render_runtime_comparison_markdown,
)

_SMALL_N_WARNING = (
    "Core-8 and Core-16 scores are directional regression signals with small-N "
    "fragility; do not treat pass-rate deltas as statistically significant."
)


def generate_evidence_report(records: list[EvidenceRecord]) -> str:
    if not records:
        return "\n".join(
            [
                "# BenchEval Evidence Report",
                "",
                "No evidence records.",
                "",
                f"> {_SMALL_N_WARNING}",
                "",
            ],
        )

    run_ids = {r.run_id for r in records}
    task_ids = {r.task_id for r in records}
    pass_count = sum(1 for r in records if r.primary_pass)
    pass_rate = pass_count / len(records)
    avg_partial = sum(r.partial_score for r in records) / len(records)
    total_cost = sum(Decimal(str(r.cost_usd)) for r in records)
    total_latency = sum(r.latency_sec for r in records)

    failure_counts: Counter[str] = Counter()
    for record in records:
        for label in record.failure_labels:
            failure_counts[label] += 1

    lines = [
        "# BenchEval Evidence Report",
        "",
        "## Summary",
        "",
        f"- Runs: {len(run_ids)}",
        f"- Tasks (attempts): {len(records)}",
        f"- Unique tasks: {len(task_ids)}",
        f"- Pass rate: {pass_rate:.2%} ({pass_count}/{len(records)})",
        f"- Average partial score: {avg_partial:.4f}",
        f"- Total cost (USD): {total_cost:.4f}",
        f"- Total latency (sec): {total_latency:.2f}",
        "",
        "## Attempts",
        "",
        "| Task | Model | Backend | Pass | Partial | Cost (USD) | Latency (s) | Verifier log |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]

    for record in records:
        verifier = record.verifier_log_path or ""
        lines.append(
            f"| {record.task_id} | {record.model_id} | {record.backend} | "
            f"{'yes' if record.primary_pass else 'no'} | {record.partial_score:.4f} | "
            f"{record.cost_usd:.4f} | {record.latency_sec:.2f} | {verifier} |",
        )

    lines.extend(["", "## Failure taxonomy", ""])

    if failure_counts:
        lines.append("| Label | Count |")
        lines.append("| --- | ---: |")
        for label, count in sorted(failure_counts.items()):
            lines.append(f"| {label} | {count} |")
    else:
        lines.append("No failure labels recorded.")

    lines.extend(["", "## Interpretation", "", f"> {_SMALL_N_WARNING}", ""])
    return "\n".join(lines)


def generate_runtime_comparison_panel(records: list[EvidenceRecord]) -> str | None:
    """Pairwise runtime panels when evidence has multiple runtimes on one benchmark/slice."""
    if not is_runtime_comparison_evidence(records):
        return None
    runtimes = sorted({r.runtime_id for r in records if r.runtime_id})
    if len(runtimes) < 2:
        return None

    panels: list[str] = []
    for i, base_rt in enumerate(runtimes):
        for cur_rt in runtimes[i + 1 :]:
            baseline = [r for r in records if r.runtime_id == base_rt]
            current = [r for r in records if r.runtime_id == cur_rt]
            report = compare_runtime_evidence(baseline, current)
            panels.append(render_runtime_comparison_markdown(report))

    return "\n".join(panels)


def generate_evidence_report_with_runtime_panel(records: list[EvidenceRecord]) -> str:
    base = generate_evidence_report(records)
    panel = generate_runtime_comparison_panel(records)
    if panel is None:
        return base
    return base + "\n" + panel
