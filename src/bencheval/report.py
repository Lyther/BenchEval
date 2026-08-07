"""Deterministic Markdown report generator for evidence records."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from decimal import Decimal

from bencheval.evidence import EvidenceRecord
from bencheval.runtime_compare import (
    compare_runtime_evidence,
    is_runtime_comparison_evidence,
    render_runtime_comparison_markdown,
)


def _fmt_optional(value: str | None) -> str:
    return f"`{value}`" if value is not None else "`n/a`"


def _aggregate_axis(
    records: list[EvidenceRecord],
    getter: Callable[[EvidenceRecord], str | None],
) -> str:
    """Singleton -> display value; mixed -> ``mixed`` plus sorted unique values."""
    values = {getter(r) for r in records}
    if len(values) == 1:
        return _fmt_optional(next(iter(values)))
    ordered = sorted(values, key=lambda v: (v is not None, v or ""))
    rendered = ", ".join(_fmt_optional(v) for v in ordered)
    return f"mixed ({rendered})"


def _control_plane_axes_section(records: list[EvidenceRecord]) -> list[str]:
    """Expose interpretation / axes / versions / integrity aggregated across rows."""
    if not records:
        return []
    lines = [
        "## Control-plane axes",
        "",
        f"- Interpretation: {_aggregate_axis(records, lambda r: r.interpretation_label)}",
        f"- Benchmark: {_aggregate_axis(records, lambda r: r.benchmark_id)}",
        f"- Benchmark version: {_aggregate_axis(records, lambda r: r.benchmark_version)}",
        f"- Slice: {_aggregate_axis(records, lambda r: r.slice_id)}",
        f"- Adapter: {_aggregate_axis(records, lambda r: r.adapter_id)}",
        f"- Harness: {_aggregate_axis(records, lambda r: r.harness_kind)}",
        f"- Harness version: {_aggregate_axis(records, lambda r: r.harness_version)}",
        f"- Runtime: {_aggregate_axis(records, lambda r: r.runtime_id)}",
        f"- Runtime version: {_aggregate_axis(records, lambda r: r.runtime_version)}",
        f"- Provider: {_aggregate_axis(records, lambda r: r.provider_id)}",
        f"- Provider config hash: {_aggregate_axis(records, lambda r: r.provider_config_hash)}",
        f"- Judge model: {_aggregate_axis(records, lambda r: r.judge_model_id)}",
        f"- Contamination: {_aggregate_axis(records, lambda r: r.contamination_label)}",
        f"- Reward-hack risk: {_aggregate_axis(records, lambda r: r.reward_hack_risk_label)}",
        f"- Verifier integrity: {_aggregate_axis(records, lambda r: r.verifier_integrity_label)}",
        "",
    ]
    return lines


def generate_evidence_report(records: list[EvidenceRecord]) -> str:
    if not records:
        return "\n".join(
            [
                "# BenchEval Evidence Report",
                "",
                "No evidence records.",
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
    ]
    lines.extend(_control_plane_axes_section(records))
    lines.extend(
        [
            "## Attempts",
            "",
            "| Task | Model | Backend | Pass | Partial | Cost (USD) | Latency (s) | Verifier log |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ],
    )

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

    lines.append("")
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
