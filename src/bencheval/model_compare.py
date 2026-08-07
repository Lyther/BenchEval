"""Model comparison for v0.3 control-plane evidence (same benchmark/slice/runtime)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from bencheval.evidence import (
    EvidenceRecord,
    count_ineligible_pass_at_k,
    eligible_for_pass_at_k,
)
from bencheval.exceptions import ComparisonError
from bencheval.provenance_gates import (
    is_captured_axis,
    is_captured_harness_version,
    is_provisional_benchmark_version,
    is_uncaptured_harness_version,
)
from bencheval.runtime_compare import (
    _eligible_shared_instance_ids,
    _index_by_instance,
    _instance_key,
    _pass_rate_ci_on_shared_instances,
)
from bencheval.stats import newcombe_diff


@dataclass(frozen=True, slots=True)
class ModelComparisonValidityVerdict:
    valid: bool
    interpretation_label: str
    reasons: tuple[str, ...]
    caveats: tuple[str, ...]
    benchmark_id: str | None
    slice_id: str | None
    baseline_model_id: str | None
    current_model_id: str | None
    runtime_id: str | None


@dataclass(frozen=True, slots=True)
class ModelComparisonReport:
    benchmark_id: str
    slice_id: str
    adapter_id: str
    runtime_id: str | None
    baseline_model_id: str
    current_model_id: str
    interpretation_label: str
    validity: ModelComparisonValidityVerdict
    caveats: tuple[str, ...]
    instance_count: int
    baseline_pass_rate: float
    current_pass_rate: float
    pass_rate_delta: float
    baseline_pass_ci_low: float
    baseline_pass_ci_high: float
    current_pass_ci_low: float
    current_pass_ci_high: float
    pass_rate_delta_ci_low: float
    pass_rate_delta_ci_high: float
    baseline_total_cost_usd: float
    current_total_cost_usd: float
    baseline_failed_attempts: int
    current_failed_attempts: int
    baseline_invalid_excluded: int
    current_invalid_excluded: int
    missing_in_current: tuple[str, ...]
    missing_in_baseline: tuple[str, ...]
    generated_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "benchmark_id": self.benchmark_id,
            "slice_id": self.slice_id,
            "adapter_id": self.adapter_id,
            "runtime_id": self.runtime_id,
            "baseline_model_id": self.baseline_model_id,
            "current_model_id": self.current_model_id,
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
            "baseline_pass_ci_low": self.baseline_pass_ci_low,
            "baseline_pass_ci_high": self.baseline_pass_ci_high,
            "current_pass_ci_low": self.current_pass_ci_low,
            "current_pass_ci_high": self.current_pass_ci_high,
            "pass_rate_delta_ci_low": self.pass_rate_delta_ci_low,
            "pass_rate_delta_ci_high": self.pass_rate_delta_ci_high,
            "baseline_total_cost_usd": self.baseline_total_cost_usd,
            "current_total_cost_usd": self.current_total_cost_usd,
            "baseline_failed_attempts": self.baseline_failed_attempts,
            "current_failed_attempts": self.current_failed_attempts,
            "baseline_invalid_excluded": self.baseline_invalid_excluded,
            "current_invalid_excluded": self.current_invalid_excluded,
            "missing_in_current": list(self.missing_in_current),
            "missing_in_baseline": list(self.missing_in_baseline),
            "generated_at": self.generated_at.isoformat(),
        }


def is_model_comparison_evidence(
    baseline: list[EvidenceRecord],
    current: list[EvidenceRecord],
) -> bool:
    if not baseline or not current:
        return False
    # Model-only rows carry runtime_id=None; that is a valid held-constant axis.
    if not all(
        r.benchmark_id and r.slice_id and r.adapter_id and r.model_id for r in baseline + current
    ):
        return False
    runtimes_b = {r.runtime_id for r in baseline}
    runtimes_c = {r.runtime_id for r in current}
    if len(runtimes_b) != 1 or len(runtimes_c) != 1 or runtimes_b != runtimes_c:
        return False
    models_b = {r.model_id for r in baseline}
    models_c = {r.model_id for r in current}
    if len(models_b) != 1 or len(models_c) != 1:
        return False
    return next(iter(models_b)) != next(iter(models_c))


def assess_model_comparison_validity(
    baseline: list[EvidenceRecord],
    current: list[EvidenceRecord],
) -> ModelComparisonValidityVerdict:
    reasons: list[str] = []
    caveats: list[str] = []

    benchmarks = {r.benchmark_id for r in baseline + current}
    slices = {r.slice_id for r in baseline + current}
    adapters = {r.adapter_id for r in baseline + current}
    harness = {r.harness_version for r in baseline + current}
    benchmark_versions = {r.benchmark_version for r in baseline + current}
    providers = {r.provider_id for r in baseline + current}
    provider_hashes = {r.provider_config_hash for r in baseline + current}
    judge_models = {r.judge_model_id for r in baseline + current}
    runtimes_b = {r.runtime_id for r in baseline}
    runtimes_c = {r.runtime_id for r in current}
    models_b = {r.model_id for r in baseline}
    models_c = {r.model_id for r in current}

    if len(benchmarks) != 1 or None in benchmarks:
        reasons.append("benchmark_id must match and be set on all rows")
    if len(slices) != 1 or None in slices:
        reasons.append("slice_id must match and be set on all rows")
    if len(adapters) != 1 or None in adapters:
        reasons.append("adapter_id must match and be set on all rows")
    if any(is_uncaptured_harness_version(v) for v in harness):
        reasons.append("uncaptured harness_version fallback cannot qualify a model comparison")
    elif len(harness) != 1 or not is_captured_harness_version(next(iter(harness))):
        reasons.append(
            "harness_version must be a single captured nonempty revision across all rows",
        )
    if len(benchmark_versions) != 1 or None in benchmark_versions:
        reasons.append("benchmark_version must be present and identical across all rows")
    elif any(not is_captured_axis(v) for v in benchmark_versions):
        reasons.append("benchmark_version must be a nonempty captured axis")
    elif any(is_provisional_benchmark_version(v) for v in benchmark_versions):
        reasons.append("provisional benchmark_version cannot qualify a model comparison")
    if len(providers) != 1 or None in providers:
        reasons.append("provider_id must be present and identical across all rows")
    elif any(not is_captured_axis(v) for v in providers):
        reasons.append("provider_id must be a nonempty captured axis")
    if (
        None in provider_hashes
        or len(provider_hashes) != 1
        or any(not is_captured_axis(v) for v in provider_hashes)
    ):
        reasons.append("provider_config_hash must be present and identical across all rows")
    if judge_models != {None} and (
        None in judge_models
        or len(judge_models) != 1
        or any(not is_captured_axis(v) for v in judge_models)
    ):
        reasons.append("judge_model_id must be present and identical when a judge is used")
    if len(runtimes_b) != 1 or len(runtimes_c) != 1 or runtimes_b != runtimes_c:
        reasons.append("runtime_id must match and be constant (hold runtime constant)")
    if len(models_b) != 1 or len(models_c) != 1:
        reasons.append("each file must have exactly one model_id")
    elif models_b == models_c:
        reasons.append("model_id must differ between baseline and current for model comparison")

    # Model-only (all runtime_id None): skip runtime version/hash checks.
    # Runtime-backed: hold runtime_version and runtime_config_hash constant across both sides.
    model_only = runtimes_b == {None} and runtimes_c == {None}
    if not model_only and len(runtimes_b) == 1 and None not in runtimes_b:
        runtime_versions = {r.runtime_version for r in baseline + current}
        runtime_hashes = {r.runtime_config_hash for r in baseline + current}
        if (
            None in runtime_versions
            or len(runtime_versions) != 1
            or any(not is_captured_axis(v) for v in runtime_versions)
        ):
            reasons.append("runtime_version must be present and identical across all rows")
        if (
            None in runtime_hashes
            or len(runtime_hashes) != 1
            or any(not is_captured_axis(v) for v in runtime_hashes)
        ):
            reasons.append("runtime_config_hash must be present and identical across all rows")

    if any(r.interpretation_label != "model_comparison" for r in baseline + current):
        reasons.append(
            "interpretation_label must be model_comparison on all rows for valid model comparison",
        )

    eligible_b = [r for r in baseline if eligible_for_pass_at_k(r)]
    eligible_c = [r for r in current if eligible_for_pass_at_k(r)]
    if not eligible_b or not eligible_c:
        reasons.append("zero eligible attempts; comparison requires eligible rows")
    else:
        base_by = _index_by_instance(baseline, "baseline")
        cur_by = _index_by_instance(current, "current")
        shared_ids = set(base_by) & set(cur_by)
        base_eligible_ids = {_instance_key(r) for r in eligible_b}
        cur_eligible_ids = {_instance_key(r) for r in eligible_c}
        paired = base_eligible_ids & cur_eligible_ids
        if not paired:
            reasons.append("zero shared eligible instances between baseline and current")
        asymmetric = [
            iid for iid in shared_ids if (iid in base_eligible_ids) != (iid in cur_eligible_ids)
        ]
        if asymmetric:
            reasons.append(
                "shared instances must be eligible on both sides "
                f"(asymmetric: {','.join(sorted(asymmetric))})",
            )

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

    valid = len(reasons) == 0
    label = "model_comparison" if valid else "diagnostic_only"

    runtime_id = next(iter(runtimes_b)) if len(runtimes_b) == 1 else None
    return ModelComparisonValidityVerdict(
        valid=valid,
        interpretation_label=label,
        reasons=tuple(reasons),
        caveats=tuple(caveats),
        benchmark_id=(
            next(iter(benchmarks)) if len(benchmarks) == 1 and None not in benchmarks else None
        ),
        slice_id=next(iter(slices)) if len(slices) == 1 and None not in slices else None,
        baseline_model_id=next(iter(models_b)) if len(models_b) == 1 else None,
        current_model_id=next(iter(models_c)) if len(models_c) == 1 else None,
        runtime_id=runtime_id,
    )


def compare_model_evidence(
    baseline: list[EvidenceRecord],
    current: list[EvidenceRecord],
) -> ModelComparisonReport:
    validity = assess_model_comparison_validity(baseline, current)
    if validity.benchmark_id is None or validity.slice_id is None:
        msg = (
            "cannot compare: " + "; ".join(validity.reasons) if validity.reasons else "missing axes"
        )
        raise ComparisonError(msg)
    if validity.baseline_model_id is None or validity.current_model_id is None:
        raise ComparisonError("cannot compare: model_id missing or ambiguous on one or both sides")
    # runtime_id may be None for model-only (GPQA/BFCL/HLE) comparisons.

    base_by_inst = _index_by_instance(baseline, "baseline")
    cur_by_inst = _index_by_instance(current, "current")
    paired = _eligible_shared_instance_ids(baseline, current)
    missing_in_current = sorted(set(base_by_inst) - set(cur_by_inst))
    missing_in_baseline = sorted(set(cur_by_inst) - set(base_by_inst))

    b_ci, c_ci = _pass_rate_ci_on_shared_instances(baseline, current)
    delta = c_ci.pass_rate - b_ci.pass_rate
    delta_lo, delta_hi = newcombe_diff(
        b_ci.pass_rate,
        b_ci.ci_low,
        b_ci.ci_high,
        c_ci.pass_rate,
        c_ci.ci_low,
        c_ci.ci_high,
        delta,
    )

    adapter_ids = {r.adapter_id for r in baseline if r.adapter_id}
    if len(adapter_ids) != 1:
        raise ComparisonError("adapter_id must be present and constant on baseline")
    adapter_id = next(iter(adapter_ids))

    return ModelComparisonReport(
        benchmark_id=validity.benchmark_id,
        slice_id=validity.slice_id,
        adapter_id=adapter_id,
        runtime_id=validity.runtime_id,
        baseline_model_id=validity.baseline_model_id,
        current_model_id=validity.current_model_id,
        interpretation_label=validity.interpretation_label,
        validity=validity,
        caveats=validity.caveats,
        instance_count=len(paired),
        baseline_pass_rate=b_ci.pass_rate,
        current_pass_rate=c_ci.pass_rate,
        pass_rate_delta=delta,
        baseline_pass_ci_low=b_ci.ci_low,
        baseline_pass_ci_high=b_ci.ci_high,
        current_pass_ci_low=c_ci.ci_low,
        current_pass_ci_high=c_ci.ci_high,
        pass_rate_delta_ci_low=float(delta_lo),
        pass_rate_delta_ci_high=float(delta_hi),
        baseline_total_cost_usd=sum(base_by_inst[i].cost_usd for i in paired),
        current_total_cost_usd=sum(cur_by_inst[i].cost_usd for i in paired),
        baseline_failed_attempts=sum(1 for i in paired if not base_by_inst[i].primary_pass),
        current_failed_attempts=sum(1 for i in paired if not cur_by_inst[i].primary_pass),
        baseline_invalid_excluded=count_ineligible_pass_at_k(baseline),
        current_invalid_excluded=count_ineligible_pass_at_k(current),
        missing_in_current=tuple(missing_in_current),
        missing_in_baseline=tuple(missing_in_baseline),
        generated_at=datetime.now(tz=UTC),
    )


def render_model_comparison_markdown(report: ModelComparisonReport) -> str:
    v = report.validity
    lines = [
        "# Model comparison",
        "",
        f"- Interpretation: **{report.interpretation_label}**",
        f"- Comparison valid (§13.3): {'yes' if v.valid else 'no'}",
        f"- Benchmark: `{report.benchmark_id}` · Slice: `{report.slice_id}`",
        f"- Adapter: `{report.adapter_id}` · Runtime: `{report.runtime_id}`",
        f"- Baseline model: `{report.baseline_model_id}`",
        f"- Current model: `{report.current_model_id}`",
        "",
    ]
    if v.reasons:
        lines.extend(["## Validity blockers", ""] + [f"- {r}" for r in v.reasons] + [""])
    if report.caveats:
        lines.extend(["## Caveats", ""] + [f"- {c}" for c in report.caveats] + [""])
    lines.extend(
        [
            "## Summary",
            "",
            f"- Baseline pass rate: {report.baseline_pass_rate:.3f} "
            f"[{report.baseline_pass_ci_low:.3f}, {report.baseline_pass_ci_high:.3f}]",
            f"- Current pass rate: {report.current_pass_rate:.3f} "
            f"[{report.current_pass_ci_low:.3f}, {report.current_pass_ci_high:.3f}]",
            f"- Pass rate delta: {report.pass_rate_delta:+.3f} "
            f"(95% CI [{report.pass_rate_delta_ci_low:+.3f}, "
            f"{report.pass_rate_delta_ci_high:+.3f}])",
            f"- Excluded from Pass@k (invalid/output-cap): baseline "
            f"{report.baseline_invalid_excluded}, current {report.current_invalid_excluded}",
            "",
        ],
    )
    return "\n".join(lines)


def render_model_comparison_json(report: ModelComparisonReport) -> str:
    return json.dumps(report.to_dict(), indent=2) + "\n"
