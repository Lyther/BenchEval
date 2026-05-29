"""Deterministic Markdown report generator for evidence records."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from bencheval.evidence import EvidenceRecord

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
