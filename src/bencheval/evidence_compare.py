"""Cross-run comparison for vNext EvidenceRecord JSONL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from bencheval.evidence import EvidenceRecord
from bencheval.exceptions import ComparisonError

EvidenceKey = tuple[str, str, str]


def _record_key(record: EvidenceRecord) -> EvidenceKey:
    return (record.task_id, record.model_id, record.backend)


def _index_records(records: list[EvidenceRecord]) -> dict[EvidenceKey, EvidenceRecord]:
    indexed: dict[EvidenceKey, EvidenceRecord] = {}
    for record in records:
        key = _record_key(record)
        if key in indexed:
            raise ComparisonError(
                f"duplicate evidence key {key!r}; keep one row per task/model/backend per file",
            )
        indexed[key] = record
    return indexed


def _pass_rate(records: list[EvidenceRecord]) -> float:
    if not records:
        return 0.0
    passed = sum(1 for record in records if record.primary_pass)
    return passed / len(records)


@dataclass(frozen=True, slots=True)
class TaskEvidenceDelta:
    task_id: str
    model_id: str
    backend: str
    status: str
    baseline_primary_pass: bool | None
    current_primary_pass: bool | None
    baseline_partial_score: float | None
    current_partial_score: float | None
    delta_partial_score: float | None
    baseline_cost_usd: float | None
    current_cost_usd: float | None
    delta_cost_usd: float | None
    baseline_latency_sec: float | None
    current_latency_sec: float | None
    delta_latency_sec: float | None


@dataclass(frozen=True, slots=True)
class BackendPassRate:
    backend: str
    baseline_pass_rate: float
    current_pass_rate: float
    pass_rate_delta: float
    baseline_count: int
    current_count: int


@dataclass(frozen=True, slots=True)
class EvidenceComparisonReport:
    baseline_count: int
    current_count: int
    baseline_pass_rate: float
    current_pass_rate: float
    pass_rate_delta: float
    missing_in_current: tuple[str, ...]
    new_in_current: tuple[str, ...]
    task_deltas: tuple[TaskEvidenceDelta, ...]
    backend_pass_rates: tuple[BackendPassRate, ...]
    generated_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "baseline_count": self.baseline_count,
            "current_count": self.current_count,
            "baseline_pass_rate": self.baseline_pass_rate,
            "current_pass_rate": self.current_pass_rate,
            "pass_rate_delta": self.pass_rate_delta,
            "missing_in_current": list(self.missing_in_current),
            "new_in_current": list(self.new_in_current),
            "backend_pass_rates": [
                {
                    "backend": row.backend,
                    "baseline_pass_rate": row.baseline_pass_rate,
                    "current_pass_rate": row.current_pass_rate,
                    "pass_rate_delta": row.pass_rate_delta,
                    "baseline_count": row.baseline_count,
                    "current_count": row.current_count,
                }
                for row in self.backend_pass_rates
            ],
            "task_deltas": [
                {
                    "task_id": row.task_id,
                    "model_id": row.model_id,
                    "backend": row.backend,
                    "status": row.status,
                    "baseline_primary_pass": row.baseline_primary_pass,
                    "current_primary_pass": row.current_primary_pass,
                    "baseline_partial_score": row.baseline_partial_score,
                    "current_partial_score": row.current_partial_score,
                    "delta_partial_score": row.delta_partial_score,
                    "baseline_cost_usd": row.baseline_cost_usd,
                    "current_cost_usd": row.current_cost_usd,
                    "delta_cost_usd": row.delta_cost_usd,
                    "baseline_latency_sec": row.baseline_latency_sec,
                    "current_latency_sec": row.current_latency_sec,
                    "delta_latency_sec": row.delta_latency_sec,
                }
                for row in self.task_deltas
            ],
            "generated_at": self.generated_at.isoformat(),
        }


def compare_evidence_runs(
    baseline: list[EvidenceRecord],
    current: list[EvidenceRecord],
) -> EvidenceComparisonReport:
    if not baseline:
        raise ComparisonError("baseline evidence must be non-empty")
    if not current:
        raise ComparisonError("current evidence must be non-empty")

    base_index = _index_records(baseline)
    cur_index = _index_records(current)
    base_keys = set(base_index)
    cur_keys = set(cur_index)
    shared = sorted(base_keys & cur_keys)
    missing = sorted({key[0] for key in base_keys - cur_keys})
    new = sorted({key[0] for key in cur_keys - base_keys})

    task_deltas: list[TaskEvidenceDelta] = []
    for task_id, model_id, backend in shared:
        base_row = base_index[(task_id, model_id, backend)]
        cur_row = cur_index[(task_id, model_id, backend)]
        task_deltas.append(
            TaskEvidenceDelta(
                task_id=task_id,
                model_id=model_id,
                backend=backend,
                status="matched",
                baseline_primary_pass=base_row.primary_pass,
                current_primary_pass=cur_row.primary_pass,
                baseline_partial_score=base_row.partial_score,
                current_partial_score=cur_row.partial_score,
                delta_partial_score=cur_row.partial_score - base_row.partial_score,
                baseline_cost_usd=base_row.cost_usd,
                current_cost_usd=cur_row.cost_usd,
                delta_cost_usd=cur_row.cost_usd - base_row.cost_usd,
                baseline_latency_sec=base_row.latency_sec,
                current_latency_sec=cur_row.latency_sec,
                delta_latency_sec=cur_row.latency_sec - base_row.latency_sec,
            ),
        )

    for task_id, model_id, backend in sorted(base_keys - cur_keys):
        base_row = base_index[(task_id, model_id, backend)]
        task_deltas.append(
            TaskEvidenceDelta(
                task_id=task_id,
                model_id=model_id,
                backend=backend,
                status="baseline_only",
                baseline_primary_pass=base_row.primary_pass,
                current_primary_pass=None,
                baseline_partial_score=base_row.partial_score,
                current_partial_score=None,
                delta_partial_score=None,
                baseline_cost_usd=base_row.cost_usd,
                current_cost_usd=None,
                delta_cost_usd=None,
                baseline_latency_sec=base_row.latency_sec,
                current_latency_sec=None,
                delta_latency_sec=None,
            ),
        )

    for task_id, model_id, backend in sorted(cur_keys - base_keys):
        cur_row = cur_index[(task_id, model_id, backend)]
        task_deltas.append(
            TaskEvidenceDelta(
                task_id=task_id,
                model_id=model_id,
                backend=backend,
                status="current_only",
                baseline_primary_pass=None,
                current_primary_pass=cur_row.primary_pass,
                baseline_partial_score=None,
                current_partial_score=cur_row.partial_score,
                delta_partial_score=None,
                baseline_cost_usd=None,
                current_cost_usd=cur_row.cost_usd,
                delta_cost_usd=None,
                baseline_latency_sec=None,
                current_latency_sec=cur_row.latency_sec,
                delta_latency_sec=None,
            ),
        )

    backends = sorted(
        {record.backend for record in baseline} | {record.backend for record in current},
    )
    backend_rows: list[BackendPassRate] = []
    for backend in backends:
        base_subset = [row for row in baseline if row.backend == backend]
        cur_subset = [row for row in current if row.backend == backend]
        base_rate = _pass_rate(base_subset)
        cur_rate = _pass_rate(cur_subset)
        backend_rows.append(
            BackendPassRate(
                backend=backend,
                baseline_pass_rate=base_rate,
                current_pass_rate=cur_rate,
                pass_rate_delta=cur_rate - base_rate,
                baseline_count=len(base_subset),
                current_count=len(cur_subset),
            ),
        )

    base_rate = _pass_rate(baseline)
    cur_rate = _pass_rate(current)
    return EvidenceComparisonReport(
        baseline_count=len(baseline),
        current_count=len(current),
        baseline_pass_rate=base_rate,
        current_pass_rate=cur_rate,
        pass_rate_delta=cur_rate - base_rate,
        missing_in_current=tuple(missing),
        new_in_current=tuple(new),
        task_deltas=tuple(task_deltas),
        backend_pass_rates=tuple(backend_rows),
        generated_at=datetime.now(tz=UTC),
    )


def render_comparison_markdown(report: EvidenceComparisonReport) -> str:
    lines = [
        "# Evidence comparison",
        "",
        f"- Baseline rows: {report.baseline_count}",
        f"- Current rows: {report.current_count}",
        f"- Baseline pass rate: {report.baseline_pass_rate:.3f}",
        f"- Current pass rate: {report.current_pass_rate:.3f}",
        f"- Pass rate delta: {report.pass_rate_delta:+.3f}",
        "",
    ]
    if report.missing_in_current:
        lines.extend(
            ["## Missing in current", ""]
            + [f"- {task_id}" for task_id in report.missing_in_current]
            + [""],
        )
    if report.new_in_current:
        lines.extend(
            ["## New in current", ""]
            + [f"- {task_id}" for task_id in report.new_in_current]
            + [""],
        )
    lines.extend(
        [
            "## Backend pass rates",
            "",
            "| Backend | Baseline | Current | Delta | Baseline n | Current n |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ],
    )
    for row in report.backend_pass_rates:
        lines.append(
            f"| {row.backend} | {row.baseline_pass_rate:.3f} | {row.current_pass_rate:.3f} | "
            f"{row.pass_rate_delta:+.3f} | {row.baseline_count} | {row.current_count} |",
        )
    lines.extend(
        [
            "",
            "## Task deltas",
            "",
            "| Task | Model | Backend | Status | Baseline pass | Current pass | "
            "Δ partial | Δ cost | Δ latency |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: |",
        ],
    )
    for row in report.task_deltas:
        base_pass = "" if row.baseline_primary_pass is None else str(row.baseline_primary_pass)
        cur_pass = "" if row.current_primary_pass is None else str(row.current_primary_pass)
        delta_partial = "" if row.delta_partial_score is None else f"{row.delta_partial_score:+.3f}"
        delta_cost = "" if row.delta_cost_usd is None else f"{row.delta_cost_usd:+.4f}"
        delta_latency = "" if row.delta_latency_sec is None else f"{row.delta_latency_sec:+.3f}"
        lines.append(
            f"| {row.task_id} | {row.model_id} | {row.backend} | {row.status} | "
            f"{base_pass} | {cur_pass} | {delta_partial} | {delta_cost} | {delta_latency} |",
        )
    lines.append("")
    return "\n".join(lines)


def render_comparison_json(report: EvidenceComparisonReport) -> str:
    return json.dumps(report.to_dict(), indent=2) + "\n"
