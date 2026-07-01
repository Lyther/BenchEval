"""Runtime comparison for v0.3 control-plane evidence (same benchmark/slice)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from bencheval.compare import _newcombe_diff, _wilson
from bencheval.evidence import (
    EvidenceRecord,
    count_ineligible_pass_at_k,
    eligible_for_pass_at_k,
)
from bencheval.exceptions import ComparisonError


def _instance_key(record: EvidenceRecord) -> str:
    return record.instance_id or record.task_id


def _index_by_instance(records: list[EvidenceRecord], side: str) -> dict[str, EvidenceRecord]:
    indexed: dict[str, EvidenceRecord] = {}
    for record in records:
        key = _instance_key(record)
        if key in indexed:
            raise ComparisonError(
                f"duplicate instance {key!r} in {side}; one row per instance per file",
            )
        indexed[key] = record
    return indexed


def _axis_values(records: list[EvidenceRecord], getter) -> set[str | None]:
    return {getter(r) for r in records}


@dataclass(frozen=True, slots=True)
class ComparisonValidityVerdict:
    valid: bool
    interpretation_label: str
    reasons: tuple[str, ...]
    caveats: tuple[str, ...]
    benchmark_id: str | None
    slice_id: str | None
    baseline_runtime_id: str | None
    current_runtime_id: str | None


@dataclass(frozen=True, slots=True)
class RuntimePassRateCI:
    pass_rate: float
    ci_low: float
    ci_high: float
    pass_count: int
    attempt_count: int


@dataclass(frozen=True, slots=True)
class RuntimeInstanceDelta:
    instance_id: str
    baseline_runtime_id: str
    current_runtime_id: str
    baseline_pass: bool
    current_pass: bool
    baseline_cost_usd: float
    current_cost_usd: float
    baseline_latency_sec: float
    current_latency_sec: float


@dataclass(frozen=True, slots=True)
class RuntimeComparisonReport:
    benchmark_id: str
    slice_id: str
    adapter_id: str
    model_id: str
    baseline_runtime_id: str
    current_runtime_id: str
    interpretation_label: str
    validity: ComparisonValidityVerdict
    caveats: tuple[str, ...]
    instance_count: int
    baseline_pass_rate: float
    current_pass_rate: float
    pass_rate_delta: float
    baseline_pass_ci: RuntimePassRateCI
    current_pass_ci: RuntimePassRateCI
    pass_rate_delta_ci_low: float
    pass_rate_delta_ci_high: float
    baseline_total_cost_usd: float
    current_total_cost_usd: float
    baseline_total_latency_sec: float
    current_total_latency_sec: float
    baseline_failed_attempts: int
    current_failed_attempts: int
    baseline_invalid_excluded: int
    current_invalid_excluded: int
    instance_deltas: tuple[RuntimeInstanceDelta, ...]
    missing_in_current: tuple[str, ...]
    missing_in_baseline: tuple[str, ...]
    generated_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_id": self.benchmark_id,
            "slice_id": self.slice_id,
            "adapter_id": self.adapter_id,
            "model_id": self.model_id,
            "baseline_runtime_id": self.baseline_runtime_id,
            "current_runtime_id": self.current_runtime_id,
            "interpretation_label": self.interpretation_label,
            "validity": {
                "valid": self.validity.valid,
                "interpretation_label": self.validity.interpretation_label,
                "reasons": list(self.validity.reasons),
                "caveats": list(self.validity.caveats),
            },
            "caveats": list(self.caveats),
            "instance_count": self.instance_count,
            "baseline_pass_rate": self.baseline_pass_rate,
            "current_pass_rate": self.current_pass_rate,
            "pass_rate_delta": self.pass_rate_delta,
            "baseline_pass_ci": {
                "pass_rate": self.baseline_pass_ci.pass_rate,
                "ci_low": self.baseline_pass_ci.ci_low,
                "ci_high": self.baseline_pass_ci.ci_high,
                "pass_count": self.baseline_pass_ci.pass_count,
                "attempt_count": self.baseline_pass_ci.attempt_count,
            },
            "current_pass_ci": {
                "pass_rate": self.current_pass_ci.pass_rate,
                "ci_low": self.current_pass_ci.ci_low,
                "ci_high": self.current_pass_ci.ci_high,
                "pass_count": self.current_pass_ci.pass_count,
                "attempt_count": self.current_pass_ci.attempt_count,
            },
            "pass_rate_delta_ci_low": self.pass_rate_delta_ci_low,
            "pass_rate_delta_ci_high": self.pass_rate_delta_ci_high,
            "baseline_total_cost_usd": self.baseline_total_cost_usd,
            "current_total_cost_usd": self.current_total_cost_usd,
            "baseline_total_latency_sec": self.baseline_total_latency_sec,
            "current_total_latency_sec": self.current_total_latency_sec,
            "baseline_failed_attempts": self.baseline_failed_attempts,
            "current_failed_attempts": self.current_failed_attempts,
            "baseline_invalid_excluded": self.baseline_invalid_excluded,
            "current_invalid_excluded": self.current_invalid_excluded,
            "missing_in_current": list(self.missing_in_current),
            "missing_in_baseline": list(self.missing_in_baseline),
            "instance_deltas": [
                {
                    "instance_id": row.instance_id,
                    "baseline_runtime_id": row.baseline_runtime_id,
                    "current_runtime_id": row.current_runtime_id,
                    "baseline_pass": row.baseline_pass,
                    "current_pass": row.current_pass,
                    "baseline_cost_usd": row.baseline_cost_usd,
                    "current_cost_usd": row.current_cost_usd,
                    "baseline_latency_sec": row.baseline_latency_sec,
                    "current_latency_sec": row.current_latency_sec,
                }
                for row in self.instance_deltas
            ],
            "generated_at": self.generated_at.isoformat(),
        }


def _pass_rate_ci(records: list[EvidenceRecord]) -> RuntimePassRateCI:
    eligible = [r for r in records if eligible_for_pass_at_k(r)]
    n = len(eligible)
    k = sum(1 for r in eligible if r.primary_pass)
    if n == 0:
        return RuntimePassRateCI(0.0, 0.0, 0.0, 0, 0)
    p, lo, hi = _wilson(k, n)
    return RuntimePassRateCI(
        pass_rate=float(p),
        ci_low=float(lo),
        ci_high=float(hi),
        pass_count=k,
        attempt_count=n,
    )


def _pass_rate_ci_on_shared_instances(
    baseline: list[EvidenceRecord],
    current: list[EvidenceRecord],
) -> tuple[RuntimePassRateCI, RuntimePassRateCI]:
    """Wilson CI on the instance intersection only (aligned with ``instance_count``)."""
    base_by = _index_by_instance(baseline, "baseline")
    cur_by = _index_by_instance(current, "current")
    shared = sorted(set(base_by) & set(cur_by))
    if not shared:
        empty = RuntimePassRateCI(0.0, 0.0, 0.0, 0, 0)
        return empty, empty
    return (
        _pass_rate_ci([base_by[i] for i in shared]),
        _pass_rate_ci([cur_by[i] for i in shared]),
    )


def assess_runtime_comparison_validity(
    baseline: list[EvidenceRecord],
    current: list[EvidenceRecord],
) -> ComparisonValidityVerdict:
    if not baseline or not current:
        raise ComparisonError("baseline and current evidence must be non-empty")

    reasons: list[str] = []
    caveats: list[str] = []

    benchmarks = _axis_values(baseline + current, lambda r: r.benchmark_id)
    slices = _axis_values(baseline + current, lambda r: r.slice_id)
    adapters = _axis_values(baseline + current, lambda r: r.adapter_id)
    harness_versions = _axis_values(baseline + current, lambda r: r.harness_version)
    models = _axis_values(baseline + current, lambda r: r.model_id)
    runtimes_b = {r.runtime_id for r in baseline if r.runtime_id}
    runtimes_c = {r.runtime_id for r in current if r.runtime_id}

    if None in benchmarks or len(benchmarks) != 1:
        reasons.append("benchmark_id must be identical across all rows")
    if None in slices or len(slices) != 1:
        reasons.append("slice_id must be identical across all rows")
    if None in adapters or len(adapters) != 1:
        reasons.append("adapter_id must be identical across all rows")
    if len({v for v in harness_versions if v is not None}) > 1:
        reasons.append("harness_version differs; waive explicitly or re-run with pinned harness")
    if len(models) != 1 or None in models:
        reasons.append("model_id must match for runtime comparison (hold model constant)")
    if len(runtimes_b) != 1 or len(runtimes_c) != 1:
        reasons.append("each file must have exactly one runtime_id")
    elif runtimes_b == runtimes_c:
        reasons.append("runtime_id must differ between baseline and current for runtime comparison")

    failed_b = sum(1 for r in baseline if not r.primary_pass)
    failed_c = sum(1 for r in current if not r.primary_pass)
    if failed_b or failed_c:
        caveats.append(
            f"failed attempts reported not dropped (baseline={failed_b}, current={failed_c})",
        )
    invalid_b = count_ineligible_pass_at_k(baseline)
    invalid_c = count_ineligible_pass_at_k(current)
    if invalid_b or invalid_c:
        caveats.append(
            f"pass@k invalid rows excluded from CIs (baseline={invalid_b}, current={invalid_c})",
        )

    contamination = any(
        r.contamination_label in ("public_possible", "known_contaminated", "legacy")
        or r.interpretation_label == "contaminated_or_legacy"
        for r in baseline + current
    )
    if contamination:
        caveats.append("contaminated_or_legacy")

    valid = len(reasons) == 0
    if contamination and valid:
        label = "contaminated_or_legacy"
    elif valid:
        label = "runtime_comparison"
    else:
        label = "diagnostic_only"

    return ComparisonValidityVerdict(
        valid=valid,
        interpretation_label=label,
        reasons=tuple(reasons),
        caveats=tuple(caveats),
        benchmark_id=(
            next(iter(benchmarks)) if len(benchmarks) == 1 and None not in benchmarks else None
        ),
        slice_id=next(iter(slices)) if len(slices) == 1 and None not in slices else None,
        baseline_runtime_id=next(iter(runtimes_b)) if len(runtimes_b) == 1 else None,
        current_runtime_id=next(iter(runtimes_c)) if len(runtimes_c) == 1 else None,
    )


def _control_plane_axes_complete(records: list[EvidenceRecord]) -> bool:
    if not records:
        return False
    return all(
        r.benchmark_id and r.slice_id and r.adapter_id and r.runtime_id and r.model_id
        for r in records
    )


def is_runtime_comparison_evidence(
    baseline: list[EvidenceRecord],
    current: list[EvidenceRecord] | None = None,
) -> bool:
    """Detect v0.3 runtime comparison routing (baseline vs current).

    With one argument, returns whether rows carry complete control-plane axes (report
    panels). With two arguments, returns whether CLI/library should route to
    :func:`compare_runtime_evidence` (same model, different runtime per file).
    """
    if current is None:
        if not baseline:
            return False
        return all(
            r.benchmark_id and r.slice_id and r.adapter_id and r.runtime_id for r in baseline
        )

    if not baseline or not current:
        return False
    if not _control_plane_axes_complete(baseline) or not _control_plane_axes_complete(current):
        return False

    models_b = {r.model_id for r in baseline}
    models_c = {r.model_id for r in current}
    if len(models_b) != 1 or len(models_c) != 1 or models_b != models_c:
        return False

    runtimes_b = {r.runtime_id for r in baseline}
    runtimes_c = {r.runtime_id for r in current}
    if len(runtimes_b) != 1 or len(runtimes_c) != 1:
        return False
    return next(iter(runtimes_b)) != next(iter(runtimes_c))


def is_dual_axis_comparison_drift(
    baseline: list[EvidenceRecord],
    current: list[EvidenceRecord],
) -> bool:
    """Both model_id and runtime_id differ between baseline and current files."""
    if not baseline or not current:
        return False
    if not _control_plane_axes_complete(baseline) or not _control_plane_axes_complete(current):
        return False
    models_b = {r.model_id for r in baseline}
    models_c = {r.model_id for r in current}
    runtimes_b = {r.runtime_id for r in baseline}
    runtimes_c = {r.runtime_id for r in current}
    if len(models_b) != 1 or len(models_c) != 1 or len(runtimes_b) != 1 or len(runtimes_c) != 1:
        return False
    return models_b != models_c and runtimes_b != runtimes_c


def compare_runtime_evidence(
    baseline: list[EvidenceRecord],
    current: list[EvidenceRecord],
) -> RuntimeComparisonReport:
    validity = assess_runtime_comparison_validity(baseline, current)
    if validity.benchmark_id is None or validity.slice_id is None:
        msg = (
            "cannot compare: " + "; ".join(validity.reasons) if validity.reasons else "missing axes"
        )
        raise ComparisonError(msg)
    if validity.baseline_runtime_id is None or validity.current_runtime_id is None:
        raise ComparisonError(
            "cannot compare: runtime_id missing or ambiguous on one or both sides",
        )

    base_by_inst = _index_by_instance(baseline, "baseline")
    cur_by_inst = _index_by_instance(current, "current")
    base_keys = set(base_by_inst)
    cur_keys = set(cur_by_inst)
    shared = sorted(base_keys & cur_keys)
    missing_in_current = sorted(base_keys - cur_keys)
    missing_in_baseline = sorted(cur_keys - base_keys)

    instance_deltas: list[RuntimeInstanceDelta] = []
    for iid in shared:
        b_row = base_by_inst[iid]
        c_row = cur_by_inst[iid]
        instance_deltas.append(
            RuntimeInstanceDelta(
                instance_id=iid,
                baseline_runtime_id=validity.baseline_runtime_id,
                current_runtime_id=validity.current_runtime_id,
                baseline_pass=b_row.primary_pass,
                current_pass=c_row.primary_pass,
                baseline_cost_usd=b_row.cost_usd,
                current_cost_usd=c_row.cost_usd,
                baseline_latency_sec=b_row.latency_sec,
                current_latency_sec=c_row.latency_sec,
            ),
        )

    b_ci, c_ci = _pass_rate_ci_on_shared_instances(baseline, current)
    delta = c_ci.pass_rate - b_ci.pass_rate
    delta_lo, delta_hi = _newcombe_diff(
        b_ci.pass_rate,
        b_ci.ci_low,
        b_ci.ci_high,
        c_ci.pass_rate,
        c_ci.ci_low,
        c_ci.ci_high,
        delta,
    )

    adapter_ids = {r.adapter_id for r in baseline if r.adapter_id}
    model_ids = {r.model_id for r in baseline if r.model_id}
    if len(adapter_ids) != 1 or len(model_ids) != 1:
        raise ComparisonError("adapter_id and model_id must be present and constant on baseline")
    adapter_id = next(iter(adapter_ids))
    model_id = next(iter(model_ids))
    all_caveats = validity.caveats

    return RuntimeComparisonReport(
        benchmark_id=validity.benchmark_id,
        slice_id=validity.slice_id,
        adapter_id=adapter_id,
        model_id=model_id,
        baseline_runtime_id=validity.baseline_runtime_id,
        current_runtime_id=validity.current_runtime_id,
        interpretation_label=validity.interpretation_label,
        validity=validity,
        caveats=all_caveats,
        instance_count=len(shared),
        baseline_pass_rate=b_ci.pass_rate,
        current_pass_rate=c_ci.pass_rate,
        pass_rate_delta=delta,
        baseline_pass_ci=b_ci,
        current_pass_ci=c_ci,
        pass_rate_delta_ci_low=float(delta_lo),
        pass_rate_delta_ci_high=float(delta_hi),
        baseline_total_cost_usd=sum(r.cost_usd for r in baseline),
        current_total_cost_usd=sum(r.cost_usd for r in current),
        baseline_total_latency_sec=sum(r.latency_sec for r in baseline),
        current_total_latency_sec=sum(r.latency_sec for r in current),
        baseline_failed_attempts=sum(1 for r in baseline if not r.primary_pass),
        current_failed_attempts=sum(1 for r in current if not r.primary_pass),
        baseline_invalid_excluded=count_ineligible_pass_at_k(baseline),
        current_invalid_excluded=count_ineligible_pass_at_k(current),
        instance_deltas=tuple(instance_deltas),
        missing_in_current=tuple(missing_in_current),
        missing_in_baseline=tuple(missing_in_baseline),
        generated_at=datetime.now(tz=UTC),
    )


def render_runtime_comparison_markdown(report: RuntimeComparisonReport) -> str:
    v = report.validity
    lines = [
        "# Runtime comparison",
        "",
        f"- Interpretation: **{report.interpretation_label}**",
        f"- Comparison valid (§13.3): {'yes' if v.valid else 'no'}",
        f"- Benchmark: `{report.benchmark_id}` · Slice: `{report.slice_id}`",
        f"- Adapter: `{report.adapter_id}` · Model: `{report.model_id}`",
        f"- Baseline runtime: `{report.baseline_runtime_id}`",
        f"- Current runtime: `{report.current_runtime_id}`",
        "",
    ]
    if v.reasons:
        lines.extend(["## Validity blockers", ""] + [f"- {r}" for r in v.reasons] + [""])
    if report.caveats:
        lines.extend(["## Caveats", ""] + [f"- {c}" for c in report.caveats] + [""])

    lines.extend(
        [
            "## Per-runtime summary",
            "",
            "| Runtime | Pass rate | 95% CI | Passes | Attempts | "
            "Excluded (invalid) | Total cost (USD) | Total latency (s) | Failed attempts |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            f"| {report.baseline_runtime_id} | {report.baseline_pass_rate:.3f} | "
            f"[{report.baseline_pass_ci.ci_low:.3f}, {report.baseline_pass_ci.ci_high:.3f}] | "
            f"{report.baseline_pass_ci.pass_count} | {report.baseline_pass_ci.attempt_count} | "
            f"{report.baseline_invalid_excluded} | "
            f"{report.baseline_total_cost_usd:.4f} | {report.baseline_total_latency_sec:.2f} | "
            f"{report.baseline_failed_attempts} |",
            f"| {report.current_runtime_id} | {report.current_pass_rate:.3f} | "
            f"[{report.current_pass_ci.ci_low:.3f}, {report.current_pass_ci.ci_high:.3f}] | "
            f"{report.current_pass_ci.pass_count} | {report.current_pass_ci.attempt_count} | "
            f"{report.current_invalid_excluded} | "
            f"{report.current_total_cost_usd:.4f} | {report.current_total_latency_sec:.2f} | "
            f"{report.current_failed_attempts} |",
            "",
            f"- Pass rate delta: {report.pass_rate_delta:+.3f} "
            f"(95% CI [{report.pass_rate_delta_ci_low:+.3f}, "
            f"{report.pass_rate_delta_ci_high:+.3f}])",
            "",
        ],
    )

    if report.missing_in_current or report.missing_in_baseline:
        lines.append("## Instance coverage")
        lines.append("")
        if report.missing_in_current:
            miss_cur = [f"- {i}" for i in report.missing_in_current]
            lines.extend(["Missing in current:", "", *miss_cur, ""])
        if report.missing_in_baseline:
            miss_base = [f"- {i}" for i in report.missing_in_baseline]
            lines.extend(["Missing in baseline:", "", *miss_base, ""])

    lines.extend(
        [
            "## Instance deltas",
            "",
            "| Instance | Baseline pass | Current pass | Δ cost | Δ latency |",
            "| --- | ---: | ---: | ---: | ---: |",
        ],
    )
    for row in report.instance_deltas:
        d_cost = row.current_cost_usd - row.baseline_cost_usd
        d_lat = row.current_latency_sec - row.baseline_latency_sec
        lines.append(
            f"| {row.instance_id} | {row.baseline_pass} | {row.current_pass} | "
            f"{d_cost:+.4f} | {d_lat:+.3f} |",
        )
    lines.append("")
    if report.instance_count < 30:
        lines.extend(
            [
                "> Small-N smoke slices are directional only; "
                "do not claim statistical superiority.",
                "",
            ],
        )
    return "\n".join(lines)


def render_runtime_comparison_json(report: RuntimeComparisonReport) -> str:
    return json.dumps(report.to_dict(), indent=2) + "\n"
