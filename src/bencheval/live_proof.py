"""Live-pilot proof qualification (audit H3 / F005).

The live pilot (``scripts/run-live-pilot-matrix.sh``) may count a lane toward
its PASSED set only when the lane's evidence shows real native-harness
execution, not infrastructure-failure-only rows. A lane qualifies iff:

1. the evidence holds at least the expected number of records, AND
2. at least ``expected_instances`` rows are eligible native-harness attempts:
   pass@k-eligible per :func:`bencheval.evidence.eligible_for_pass_at_k`, free
   of infrastructure failure classes, with an explicit native/official verifier
   result (nonempty ``artifact_paths`` or an on-disk ``verifier_log_path``, plus
   ``verifier_integrity_label`` in :data:`NATIVE_VERIFIER_LABELS`), every
   required provenance axis populated, every referenced artifact present on
   disk, and benchmark/slice identity matching the pilot's intent.

Artifact path resolution: the run pipeline records ``artifact_paths`` and
``verifier_log_path`` relative to the repo root when the target lives under it
(see ``control_plane_executor._record_instance_failure`` and
``terminal_bench_harbor.parse_harbor_instance_outcome``), absolute otherwise.
Relative references are therefore resolved against ``--repo-root`` (default:
:func:`bencheval.paths.repo_root`); absolute references are checked as-is.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from bencheval.domain import VerifierIntegrityLabel
from bencheval.evidence import (
    INFRASTRUCTURE_FAILURE_CLASSES,
    EvidenceRecord,
    eligible_for_pass_at_k,
    read_evidence_jsonl,
)
from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root as default_repo_root
from bencheval.provenance_gates import (
    is_captured_axis,
    is_captured_harness_version,
    is_provisional_benchmark_version,
)

# Canonical eligibility taxonomy lives in bencheval.evidence (single source of
# truth); it is re-exported here for live-proof callers.
# VerifierIntegrityLabel values that prove an official/native scorer judged the
# attempt. Domain currently defines native | bencheval | unknown; only "native"
# counts for live proof (there is no separate "official" label).
NATIVE_VERIFIER_LABELS: frozenset[VerifierIntegrityLabel] = frozenset({"native"})

# Provenance axes required on every counted row. harness_version is always
# required; runtime_version/runtime_config_hash join when require_runtime.
REQUIRED_PROVENANCE_AXES: tuple[str, ...] = (
    "benchmark_id",
    "benchmark_version",
    "slice_id",
    "adapter_id",
    "harness_kind",
    "harness_version",
    "model_id",
    "provider_id",
    "provider_config_hash",
)

_RUNTIME_PROVENANCE_AXES: tuple[str, ...] = (
    "runtime_id",
    "runtime_version",
    "runtime_config_hash",
)


@dataclass(frozen=True, slots=True)
class Qualification:
    """Outcome of qualifying one pilot lane's evidence file."""

    ok: bool
    reasons: tuple[str, ...]
    eligible_rows: tuple[EvidenceRecord, ...]
    row_count: int


def _resolve_ref(raw: str, *, repo_root: Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = repo_root / path
    return path


def _has_native_verifier_result(record: EvidenceRecord, *, repo_root: Path) -> bool:
    """True when the row carries an explicit on-disk native/official verifier result."""
    if record.verifier_integrity_label not in NATIVE_VERIFIER_LABELS:
        return False
    if record.artifact_paths:
        return True
    if record.verifier_log_path:
        return _resolve_ref(record.verifier_log_path, repo_root=repo_root).is_file()
    return False


def is_native_harness_attempt(record: EvidenceRecord, *, repo_root: Path) -> bool:
    """True when the attempt reached the native harness/scorer for a verdict.

    A null ``failure_class`` alone is not enough: the row must also carry an
    explicit native verifier result (artifacts or on-disk verifier log plus a
    native integrity label).
    """
    if record.failure_class is not None and record.failure_class in INFRASTRUCTURE_FAILURE_CLASSES:
        return False
    return _has_native_verifier_result(record, repo_root=repo_root)


def _missing_artifact_refs(record: EvidenceRecord, *, repo_root: Path) -> list[str]:
    refs = list(record.artifact_paths)
    if record.verifier_log_path:
        refs.append(record.verifier_log_path)
    missing: list[str] = []
    for raw in refs:
        if not _resolve_ref(raw, repo_root=repo_root).is_file():
            missing.append(raw)
    return missing


def _row_disqualifiers(
    record: EvidenceRecord,
    *,
    require_runtime: bool,
    repo_root: Path,
) -> list[str]:
    """Row-level reject categories; an empty list means the row counts."""
    categories: list[str] = []
    if not eligible_for_pass_at_k(record):
        categories.append("pass@k-ineligible")
    if not is_native_harness_attempt(record, repo_root=repo_root):
        if (
            record.failure_class is not None
            and record.failure_class in INFRASTRUCTURE_FAILURE_CLASSES
        ):
            categories.append(f"infrastructure-failure({record.failure_class})")
        else:
            categories.append("no-native-verifier-result")
    missing_axes = [
        axis for axis in REQUIRED_PROVENANCE_AXES if not is_captured_axis(getattr(record, axis))
    ]
    if record.adapter_id == "hle" and not is_captured_axis(record.judge_model_id):
        missing_axes.append("judge_model_id")
    if require_runtime:
        for axis in _RUNTIME_PROVENANCE_AXES:
            if not is_captured_axis(getattr(record, axis)):
                missing_axes.append(axis)
    if missing_axes:
        categories.append(f"missing-provenance({','.join(missing_axes)})")
    if is_provisional_benchmark_version(record.benchmark_version):
        categories.append("provisional-benchmark-identity")
    if not is_captured_harness_version(record.harness_version):
        # Missing harness_version is already covered by missing-provenance; when
        # present but placeholder, name the fallback explicitly.
        if record.harness_version:
            categories.append("uncaptured-harness-version-fallback")
    missing_refs = _missing_artifact_refs(record, repo_root=repo_root)
    if missing_refs:
        categories.append(f"missing-artifacts({','.join(missing_refs)})")
    return categories


def qualify_lane(
    evidence_path: Path | str,
    *,
    expected_instances: int,
    benchmark_id: str,
    slice_id: str,
    require_runtime: bool,
    repo_root: Path | None = None,
) -> Qualification:
    """Qualify one pilot lane's evidence for live proof.

    Raises :class:`~bencheval.exceptions.BenchEvalError` when the evidence file
    cannot be read or parsed (the CLI maps that to exit code 2).
    """
    root = repo_root if repo_root is not None else default_repo_root()
    rows = read_evidence_jsonl(Path(evidence_path))

    reasons: list[str] = []
    if len(rows) < expected_instances:
        reasons.append(f"evidence record count {len(rows)} < expected {expected_instances}")
    run_ids = {row.run_id for row in rows}
    if len(run_ids) != 1:
        reasons.append(f"evidence must contain exactly one run_id, found {len(run_ids)}")

    tallies: dict[str, int] = {}
    eligible: list[EvidenceRecord] = []
    seen_instance_ids: set[str] = set()
    for row in rows:
        categories = _row_disqualifiers(row, require_runtime=require_runtime, repo_root=root)
        if row.benchmark_id != benchmark_id or row.slice_id != slice_id:
            categories.append(
                f"identity-mismatch(benchmark_id={row.benchmark_id},slice_id={row.slice_id})",
            )
        instance_id = row.instance_id
        if not isinstance(instance_id, str) or not instance_id.strip():
            categories.append("missing-instance-id")
        elif instance_id in seen_instance_ids:
            categories.append("duplicate-instance-id")
        if categories:
            for category in categories:
                key = category.split("(", maxsplit=1)[0]
                tallies[key] = tallies.get(key, 0) + 1
            continue
        seen_instance_ids.add(instance_id)
        eligible.append(row)

    unique_eligible = len({r.instance_id for r in eligible if r.instance_id})
    if unique_eligible < expected_instances:
        breakdown = ", ".join(f"{key}={count}" for key, count in sorted(tallies.items()))
        reasons.append(
            f"unique eligible native-harness instance_ids {unique_eligible} "
            f"< expected {expected_instances} in {len(rows)} rows"
            + (f"; row rejects: {breakdown}" if breakdown else ""),
        )

    return Qualification(
        ok=(
            len(rows) >= expected_instances
            and unique_eligible >= expected_instances
            and len(run_ids) == 1
        ),
        reasons=tuple(reasons),
        eligible_rows=tuple(eligible),
        row_count=len(rows),
    )


def eligible_native_instance_ids(
    evidence_path: Path | str,
    *,
    require_runtime: bool = False,
    repo_root: Path | None = None,
) -> set[str]:
    """Instance ids of rows that count as eligible native-harness attempts."""
    root = repo_root if repo_root is not None else default_repo_root()
    ids: set[str] = set()
    for row in read_evidence_jsonl(Path(evidence_path)):
        if row.instance_id is None:
            continue
        if _row_disqualifiers(row, require_runtime=require_runtime, repo_root=root):
            continue
        ids.add(row.instance_id)
    return ids


def shared_eligible_instances(
    path_a: Path | str,
    path_b: Path | str,
    *,
    require_runtime: bool = False,
    repo_root: Path | None = None,
) -> set[str]:
    """Instance ids with eligible native-harness attempts on BOTH sides."""
    root = repo_root if repo_root is not None else default_repo_root()
    ids_a = eligible_native_instance_ids(path_a, require_runtime=require_runtime, repo_root=root)
    ids_b = eligible_native_instance_ids(path_b, require_runtime=require_runtime, repo_root=root)
    return ids_a & ids_b


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qualify live-pilot evidence (audit H3): reject failure-only rows.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    qualify = sub.add_parser(
        "qualify-lane",
        help="exit 0 when one lane's evidence qualifies for live proof",
    )
    qualify.add_argument("evidence", help="evidence JSONL path")
    qualify.add_argument("--expected", type=int, required=True, help="expected record count")
    qualify.add_argument("--benchmark-id", required=True)
    qualify.add_argument("--slice-id", required=True)
    qualify.add_argument(
        "--require-runtime",
        action="store_true",
        help="runtime lane: counted rows must populate runtime provenance axes",
    )
    qualify.add_argument(
        "--repo-root",
        default=None,
        help="base for repo-root-relative artifact refs (default: bencheval repo root)",
    )

    shared = sub.add_parser(
        "shared-instances",
        help="exit 0 (printing the count) when two evidence files share an eligible instance",
    )
    shared.add_argument("evidence_a")
    shared.add_argument("evidence_b")
    shared.add_argument("--require-runtime", action="store_true")
    shared.add_argument("--repo-root", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry: ``qualify-lane`` / ``shared-instances``. 0 ok, 1 rejected, 2 error."""
    args = _parser().parse_args(argv)
    root = Path(args.repo_root).resolve() if args.repo_root else None
    try:
        if args.command == "qualify-lane":
            q = qualify_lane(
                args.evidence,
                expected_instances=args.expected,
                benchmark_id=args.benchmark_id,
                slice_id=args.slice_id,
                require_runtime=args.require_runtime,
                repo_root=root,
            )
            if q.ok:
                ids = sorted({r.instance_id for r in q.eligible_rows if r.instance_id})
                print(
                    f"qualify-lane OK: {args.evidence} rows={q.row_count} "
                    f"eligible={len(q.eligible_rows)} instances={','.join(ids)}",
                )
                return 0
            for reason in q.reasons:
                print(f"qualify-lane not-qualified: {reason}", file=sys.stderr)
            return 1
        shared = shared_eligible_instances(
            args.evidence_a,
            args.evidence_b,
            require_runtime=args.require_runtime,
            repo_root=root,
        )
        if shared:
            print(len(shared))
            print(f"shared eligible instances: {', '.join(sorted(shared))}", file=sys.stderr)
            return 0
        print("no shared eligible native instances", file=sys.stderr)
        return 1
    except BenchEvalError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "INFRASTRUCTURE_FAILURE_CLASSES",
    "NATIVE_VERIFIER_LABELS",
    "REQUIRED_PROVENANCE_AXES",
    "Qualification",
    "eligible_native_instance_ids",
    "is_native_harness_attempt",
    "main",
    "qualify_lane",
    "shared_eligible_instances",
]
