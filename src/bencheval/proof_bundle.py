"""Immutable portable private proof (schema ``private_proof_v1``)."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from bencheval.domain import RunPlan
from bencheval.evidence import EvidenceRecord, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.live_run_manifest import (
    LiveRunProjection,
    LiveRunRecord,
    project_live_runs,
    read_live_runs,
)
from bencheval.paths import repo_root as _repo_root
from bencheval.report import generate_evidence_report_with_runtime_panel
from bencheval.run_bundle import _portable_private_artifact, _resolve_private_artifact, _sha256_file
from bencheval.run_isolation import dir_identity_error, open_owned_dir_fd

PROOF_SCHEMA = "private_proof_v1"
INVENTORY_SCHEMA = "private_proof_inventory_v1"
INDEX_SCHEMA = "proof_index_v1"
PROOF_ID_PREFIX = "sha256:"
_PROOF_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")

ProofClassification = Literal["complete", "legacy_unverifiable"]
ProofRole = Literal[
    "proof",
    "history",
    "projection",
    "evidence",
    "run_plan",
    "report",
    "artifact",
]

_ROLE_BY_PATH: dict[str, ProofRole] = {
    "proof.json": "proof",
    "history.jsonl": "history",
    "projection.json": "projection",
    "evidence.jsonl": "evidence",
    "run-plan.json": "run_plan",
    "report.md": "report",
}
_REQUIRED_PROOF_ROLES: dict[str, ProofRole] = {
    path: role for path, role in _ROLE_BY_PATH.items() if path != "run-plan.json"
}
_AGGREGATE_ADAPTER_IDS = frozenset({"gpqa", "hle"})


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    path: str
    role: ProofRole
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class PrivateProofExport:
    root: Path
    proof_id: str
    classification: ProofClassification
    classification_reason: str | None


@dataclass(frozen=True, slots=True)
class PrivateProofSummary:
    proof_id: str
    run_id: str
    path: Path
    classification: str
    classification_reason: str | None
    benchmark_id: str | None


@dataclass(frozen=True, slots=True)
class PrivateProofScan:
    """One index-bound proof inspection, including isolated object corruption."""

    proof_id: str
    run_id: str
    path: Path
    summary: PrivateProofSummary | None
    error: str | None


def default_proofs_dir() -> Path:
    return _repo_root() / "results" / "proofs"


def _validate_relpath(value: str) -> str:
    if not value or "\x00" in value or "\\" in value or value.startswith("/"):
        raise BenchEvalError(f"illegal proof path: {value!r}")
    if unicodedata.normalize("NFC", value) != value:
        raise BenchEvalError(f"proof path is not NFC: {value}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise BenchEvalError(f"illegal proof path: {value}")
    return value


def _reject_collisions(paths: list[str]) -> None:
    folded: dict[str, str] = {}
    for path in paths:
        key = path.casefold()
        prior = folded.get(key)
        if prior is not None:
            kind = "duplicate path" if prior == path else "case-fold collision"
            raise BenchEvalError(f"{kind}: {path}")
        folded[key] = path


def _role_for(rel: str) -> ProofRole:
    _validate_relpath(rel)
    if rel != "proof.json" and rel.endswith("/proof.json"):
        raise BenchEvalError(f"nested proof: {rel}")
    if rel.endswith("/inventory.json") or rel == "inventory.json":
        raise BenchEvalError(f"nested proof: {rel}")
    if rel in _ROLE_BY_PATH:
        return _ROLE_BY_PATH[rel]
    if rel.startswith("artifacts/"):
        return "artifact"
    raise BenchEvalError(f"unknown proof path: {rel}")


def _walk_on_error(error: OSError) -> None:
    raise BenchEvalError(f"cannot list proof directory {error.filename}: {error}") from error


def _iter_regular_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=_walk_on_error):
        for name in dirnames:
            path = Path(dirpath) / name
            if path.is_symlink():
                raise BenchEvalError(f"symlink rejected: {path}")
        for name in filenames:
            path = Path(dirpath) / name
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode):
                raise BenchEvalError(f"symlink rejected: {path}")
            if not stat.S_ISREG(info.st_mode):
                raise BenchEvalError(f"special file rejected: {path}")
            if info.st_nlink > 1:
                raise BenchEvalError(f"hardlink rejected: {path}")
            found.append(path)
    return found


def _prepare_output_target(path: Path) -> Path:
    requested = path.expanduser()
    if requested.is_symlink():
        raise BenchEvalError(f"proof output must not be a symlink: {requested}")
    dest = Path(os.path.abspath(requested))
    if dest.exists():
        if not dest.is_dir():
            raise BenchEvalError(f"proof output exists but is not a directory: {dest}")
        try:
            occupied = any(dest.iterdir())
        except OSError as e:
            raise BenchEvalError(f"cannot inspect proof output {dest}: {e}") from e
        if occupied:
            raise BenchEvalError(f"proof output directory must be empty or missing: {dest}")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise BenchEvalError(f"cannot create proof output parent {dest.parent}: {e}") from e
    return dest


def _load_single_run_evidence(evidence_path: Path, run_id: str) -> list[EvidenceRecord]:
    records = read_evidence_jsonl(evidence_path)
    if not records:
        raise BenchEvalError("evidence is empty")
    found = {record.run_id for record in records}
    if found != {run_id}:
        raise BenchEvalError(f"evidence run_id must be exactly {run_id!r}, got {sorted(found)}")
    return records


def _history_for_run(manifest_path: Path, run_id: str) -> list[LiveRunRecord]:
    rows = [row for row in read_live_runs(manifest_path) if row.run_id == run_id]
    if not rows:
        raise BenchEvalError(f"no live-run history for {run_id!r}")
    return rows


def _normalize_history_row(row: LiveRunRecord) -> LiveRunRecord:
    updates = {
        field: None
        for field in ("evidence_path", "report_path", "bundle_path")
        if isinstance(getattr(row, field), str) and Path(str(getattr(row, field))).is_absolute()
    }
    return row.model_copy(update=updates) if updates else row


def _write_history_and_projection(dest: Path, history: list[LiveRunRecord]) -> None:
    normalized = [_normalize_history_row(row) for row in history]
    dest.joinpath("history.jsonl").write_text(
        "".join(row.model_dump_json() + "\n" for row in normalized),
        encoding="utf-8",
    )
    views = project_live_runs(normalized)
    _write_json(dest / "projection.json", _projection_payload(views[0]))


def _projection_payload(view: LiveRunProjection) -> dict[str, object]:
    return {
        "benchmark": view.benchmark,
        "bundle_path": view.bundle_path,
        "event_count": view.event_count,
        "evidence_path": view.evidence_path,
        "first_generated_at": view.first_generated_at.isoformat(),
        "host": view.host,
        "last_generated_at": view.last_generated_at.isoformat(),
        "model_id": view.model_id,
        "notes": view.notes,
        "report_path": view.report_path,
        "run_id": view.run_id,
        "runtime": view.runtime,
        "slice_id": view.slice_id,
        "status": view.status,
    }


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _require_contained_realpath(path: Path, *roots: Path) -> None:
    real = Path(os.path.realpath(path))
    for root in roots:
        try:
            real.relative_to(Path(os.path.realpath(root)))
            return
        except ValueError:
            continue
    raise BenchEvalError(f"artifact path is outside declared raw/capture roots: {path}")


def _copy_referenced_artifact(
    value: str,
    *,
    dest: Path,
    raw_root: Path,
    capture_root: Path,
) -> str:
    source = _resolve_private_artifact(value, raw_root=raw_root, capture_root=capture_root)
    _require_contained_realpath(source, raw_root, capture_root)
    portable = _portable_private_artifact(value, raw_root=raw_root, capture_root=capture_root)
    relative = f"artifacts/{portable}"
    _role_for(relative)
    target = dest / relative
    if target.exists():
        if _sha256_file(target) != _sha256_file(source):
            raise BenchEvalError(f"duplicate artifact path with different bytes: {relative}")
        return relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return relative


def _rewrite_records(
    records: list[EvidenceRecord],
    *,
    dest: Path,
    raw_root: Path,
    capture_root: Path,
) -> list[EvidenceRecord]:
    rewritten: list[EvidenceRecord] = []
    for record in records:
        verifier = record.verifier_log_path
        rewritten.append(
            record.model_copy(
                update={
                    "artifact_paths": [
                        _copy_referenced_artifact(
                            path,
                            dest=dest,
                            raw_root=raw_root,
                            capture_root=capture_root,
                        )
                        for path in record.artifact_paths
                    ],
                    "verifier_log_path": (
                        _copy_referenced_artifact(
                            verifier,
                            dest=dest,
                            raw_root=raw_root,
                            capture_root=capture_root,
                        )
                        if verifier is not None
                        else None
                    ),
                },
            ),
        )
    return rewritten


def _copy_run_plan(source: Path, dest: Path) -> tuple[ProofClassification, str | None]:
    if source.is_symlink():
        raise BenchEvalError("run-plan.json must not be a symlink")
    if source.exists() and not source.is_file():
        raise BenchEvalError("run-plan.json must be a regular file")
    if not source.is_file():
        return "legacy_unverifiable", "run_plan_missing_legacy"
    try:
        RunPlan.model_validate_json(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValidationError, ValueError) as e:
        raise BenchEvalError(f"captured run-plan.json is not a valid RunPlan: {e}") from e
    shutil.copyfile(source, dest)
    return "complete", None


def _require_axis(actual: object, expected: object, *, axis: str) -> None:
    if not isinstance(actual, str) or not isinstance(expected, str):
        raise BenchEvalError(f"complete proof is missing required axis {axis}")
    if actual != expected:
        raise BenchEvalError(f"complete proof {axis} disagrees: {actual!r} != {expected!r}")


def _require_optional_axis(actual: object, expected: str | None, *, axis: str) -> None:
    if expected is None:
        if actual is not None:
            raise BenchEvalError(f"complete proof {axis} disagrees: {actual!r} != {expected!r}")
        return
    _require_axis(actual, expected, axis=axis)


def _is_bound_aggregate_population(plan: RunPlan, records: list[EvidenceRecord]) -> bool:
    if plan.adapter_id not in _AGGREGATE_ADAPTER_IDS or len(records) != 1:
        return False
    record = records[0]
    expected_id = f"{plan.benchmark_id}-{plan.slice_id}-aggregate"
    if record.instance_id != expected_id:
        return False
    metadata = record.adapter_metadata
    native = record.native_score
    if not isinstance(metadata, Mapping) or metadata.get("evidence_shape") != "aggregate_slice":
        return False
    planned_slots = native.get("planned_sample_slots") if isinstance(native, Mapping) else None
    return (
        isinstance(planned_slots, int)
        and not isinstance(planned_slots, bool)
        and planned_slots == len(plan.instances)
    )


def _assert_complete_identity(
    *,
    plan: RunPlan,
    records: list[EvidenceRecord],
    history: list[LiveRunRecord],
    projection: dict[str, object],
) -> None:
    planned_ids = [instance.instance_id for instance in plan.instances]
    if len(set(planned_ids)) != len(planned_ids):
        raise BenchEvalError("complete proof plan contains duplicate instance ids")
    if not records:
        raise BenchEvalError("complete proof is missing required axis evidence")
    for record in records:
        _require_axis(record.benchmark_id, plan.benchmark_id, axis="benchmark")
        _require_axis(record.slice_id, plan.slice_id, axis="slice")
        _require_axis(record.model_id, plan.model_id, axis="model")
        _require_axis(record.adapter_id, plan.adapter_id, axis="adapter")
        _require_axis(record.harness_kind, plan.harness_kind, axis="harness")
        _require_axis(record.provider_id, plan.provider_id, axis="provider")
        _require_optional_axis(record.runtime_id, plan.runtime_id, axis="runtime")
        _require_optional_axis(record.agent_id, plan.agent_id, axis="agent")
    observed_ids = [record.instance_id for record in records]
    if any(instance_id is None for instance_id in observed_ids):
        raise BenchEvalError("complete proof instance is not in the planned population")
    planned_counts = Counter(planned_ids)
    observed_counts = Counter(observed_ids)
    if observed_counts != planned_counts and not _is_bound_aggregate_population(plan, records):
        missing = sorted((planned_counts - observed_counts).elements())
        extra = sorted((observed_counts - planned_counts).elements())
        duplicates = sorted(
            instance_id
            for instance_id, count in observed_counts.items()
            if count > planned_counts.get(instance_id, 0)
        )
        raise BenchEvalError(
            "complete proof planned population mismatch "
            f"missing={missing} extra={extra} duplicates={duplicates}",
        )
    for row in history:
        if row.benchmark is not None:
            _require_axis(row.benchmark, plan.benchmark_id, axis="benchmark")
        if row.slice_id is not None:
            _require_axis(row.slice_id, plan.slice_id, axis="slice")
        _require_axis(row.model_id, plan.model_id, axis="model")
        if row.runtime is not None:
            _require_optional_axis(row.runtime, plan.runtime_id, axis="runtime")
    _require_axis(projection.get("benchmark"), plan.benchmark_id, axis="benchmark")
    _require_axis(projection.get("slice_id"), plan.slice_id, axis="slice")
    _require_axis(projection.get("model_id"), plan.model_id, axis="model")
    _require_optional_axis(projection.get("runtime"), plan.runtime_id, axis="runtime")


def _canonical_inventory_bytes(entries: list[InventoryEntry]) -> bytes:
    payload = {
        "files": [
            {"path": entry.path, "role": entry.role, "sha256": entry.sha256, "size": entry.size}
            for entry in sorted(entries, key=lambda item: item.path)
        ],
        "schema_version": INVENTORY_SCHEMA,
    }
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    return text.encode("utf-8")


def _collect_inventory(root: Path) -> list[InventoryEntry]:
    entries: list[InventoryEntry] = []
    for path in _iter_regular_files(root):
        relative = path.relative_to(root).as_posix()
        if relative == "inventory.json":
            continue
        entries.append(
            InventoryEntry(
                path=relative,
                role=_role_for(relative),
                size=path.stat().st_size,
                sha256=_sha256_file(path),
            ),
        )
    _reject_collisions([entry.path for entry in entries])
    return entries


def _write_inventory(root: Path) -> str:
    payload = _canonical_inventory_bytes(_collect_inventory(root))
    (root / "inventory.json").write_bytes(payload)
    return f"{PROOF_ID_PREFIX}{hashlib.sha256(payload).hexdigest()}"


def export_private_proof(
    *,
    run_id: str,
    evidence_path: Path,
    artifacts_dir: Path,
    manifest_path: Path,
    output_dir: Path,
    capture_dir: Path | None = None,
) -> PrivateProofExport:
    records = _load_single_run_evidence(evidence_path, run_id)
    raw_root = artifacts_dir.resolve()
    capture_root = (
        capture_dir.resolve()
        if capture_dir is not None
        else (artifacts_dir.parent / f"{artifacts_dir.name}.capture").resolve()
    )
    dest = _prepare_output_target(output_dir)
    with tempfile.TemporaryDirectory(prefix=f".{dest.name}.", dir=dest.parent) as temp_root:
        staged = Path(temp_root) / "proof"
        staged.mkdir()
        rewritten = _rewrite_records(
            records,
            dest=staged,
            raw_root=raw_root,
            capture_root=capture_root,
        )
        staged.joinpath("evidence.jsonl").write_text(
            "".join(record.model_dump_json() + "\n" for record in rewritten),
            encoding="utf-8",
        )
        staged.joinpath("report.md").write_text(
            generate_evidence_report_with_runtime_panel(rewritten),
            encoding="utf-8",
        )
        classification, reason = _copy_run_plan(
            raw_root / "run-plan.json",
            staged / "run-plan.json",
        )
        history = _history_for_run(manifest_path, run_id)
        _write_history_and_projection(staged, history)
        if classification == "complete":
            plan = RunPlan.model_validate_json(
                (staged / "run-plan.json").read_text(encoding="utf-8"),
            )
            views = project_live_runs([_normalize_history_row(row) for row in history])
            _assert_complete_identity(
                plan=plan,
                records=rewritten,
                history=history,
                projection=_projection_payload(views[0]),
            )
        _write_json(
            staged / "proof.json",
            {
                "classification": classification,
                "classification_reason": reason,
                "run_id": run_id,
                "schema_version": PROOF_SCHEMA,
            },
        )
        proof_id = _write_inventory(staged)
        try:
            os.replace(staged, dest)
        except OSError as e:
            raise BenchEvalError(f"cannot finalize proof output {dest}: {e}") from e
    return PrivateProofExport(dest, proof_id, classification, reason)


def _reject_publication_derivative(root: Path) -> None:
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict) or data.get("schema_version") != "run_bundle_v1":
        return
    kind = "public redacted" if data.get("redaction") == "public" else "publication"
    raise BenchEvalError(f"{kind} bundles cannot verify as private proof")


def _parse_inventory(raw: bytes) -> list[InventoryEntry]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BenchEvalError(f"invalid inventory.json: {e}") from e
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("schema_version") != INVENTORY_SCHEMA:
        raise BenchEvalError("inventory.json is not a private proof inventory")
    if not isinstance(files, list):
        raise BenchEvalError("inventory.json files must be a list")
    entries: list[InventoryEntry] = []
    for item in files:
        if not isinstance(item, dict):
            raise BenchEvalError("inventory entry must be an object")
        path = item.get("path")
        role = item.get("role")
        sha256 = item.get("sha256")
        size = item.get("size")
        if not isinstance(path, str) or not isinstance(sha256, str):
            raise BenchEvalError("inventory entry is missing path/sha256")
        if role not in _ROLE_BY_PATH.values() and role != "artifact":
            raise BenchEvalError(f"unknown inventory role: {role!r}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise BenchEvalError(f"invalid inventory size for {path}")
        entries.append(InventoryEntry(path=path, role=role, size=size, sha256=sha256))
    _reject_collisions([entry.path for entry in entries])
    if raw != _canonical_inventory_bytes(entries):
        raise BenchEvalError("inventory.json is not canonical")
    roles_by_path = {entry.path: entry.role for entry in entries}
    for path, role in _REQUIRED_PROOF_ROLES.items():
        if roles_by_path.get(path) != role:
            raise BenchEvalError(f"required proof role is missing: {path} ({role})")
    return entries


def _read_proof_history(path: Path) -> list[LiveRunRecord]:
    try:
        rows = [
            LiveRunRecord.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, ValidationError, ValueError) as e:
        raise BenchEvalError(f"invalid history.jsonl: {e}") from e
    return rows


def _load_json_object(path: Path, *, role: str) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        raise BenchEvalError(f"invalid {role}: {e}") from e
    if not isinstance(data, dict):
        raise BenchEvalError(f"{role} must be an object")
    return data


def _assert_run_id_coherence(root: Path, run_id: str) -> None:
    evidence_ids = {row.run_id for row in read_evidence_jsonl(root / "evidence.jsonl")}
    history = _read_proof_history(root / "history.jsonl")
    if not history:
        raise BenchEvalError("history.jsonl is empty")
    views = project_live_runs(history)
    if not views:
        raise BenchEvalError("history.jsonl produced no projection")
    history_ids = {row.run_id for row in history}
    stored = _load_json_object(root / "projection.json", role="projection.json")
    derived = _projection_payload(views[0])
    if evidence_ids != {run_id} or history_ids != {run_id}:
        raise BenchEvalError(f"proof run_id is not coherent for {run_id!r}")
    if stored != derived or stored.get("run_id") != run_id:
        raise BenchEvalError("stored projection does not match derived history")


def _assert_classification(root: Path, meta: dict[str, object]) -> None:
    classification = meta.get("classification")
    reason = meta.get("classification_reason")
    plan = root / "run-plan.json"
    if classification == "complete":
        if reason is not None:
            raise BenchEvalError("complete proof cannot carry a classification_reason")
        try:
            RunPlan.model_validate_json(plan.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValidationError, ValueError) as e:
            raise BenchEvalError(f"complete proof has an invalid run-plan.json: {e}") from e
        return
    if classification == "legacy_unverifiable":
        if reason != "run_plan_missing_legacy":
            raise BenchEvalError("legacy proof requires run_plan_missing_legacy")
        if plan.exists():
            raise BenchEvalError("legacy proof must not invent a run-plan.json")
        return
    raise BenchEvalError(f"unknown proof classification: {classification!r}")


def _assert_references_inventoried(root: Path, inventory_paths: set[str]) -> None:
    for record in read_evidence_jsonl(root / "evidence.jsonl"):
        values = [*record.artifact_paths]
        if record.verifier_log_path is not None:
            values.append(record.verifier_log_path)
        for value in values:
            _validate_relpath(value)
            if value not in inventory_paths or not (root / value).is_file():
                raise BenchEvalError(f"referenced artifact is not inventoried: {value}")


def verify_private_proof(root: Path, *, expected_proof_id: str | None = None) -> str:
    proof_root = root.resolve()
    if not proof_root.is_dir():
        raise BenchEvalError(f"proof root is not a directory: {proof_root}")
    _reject_publication_derivative(proof_root)
    inventory_path = proof_root / "inventory.json"
    if not inventory_path.is_file() or inventory_path.is_symlink():
        raise BenchEvalError("private_proof_v1 inventory.json is missing")
    raw = inventory_path.read_bytes()
    proof_id = f"{PROOF_ID_PREFIX}{hashlib.sha256(raw).hexdigest()}"
    if expected_proof_id is not None and expected_proof_id != proof_id:
        raise BenchEvalError("proof digest does not match expected value")
    entries = _parse_inventory(raw)
    disk = {
        path.relative_to(proof_root).as_posix()
        for path in _iter_regular_files(proof_root)
        if path.relative_to(proof_root).as_posix() != "inventory.json"
    }
    listed = {entry.path for entry in entries}
    if disk != listed:
        extra = disk - listed
        missing = listed - disk
        raise BenchEvalError(f"proof file-set mismatch extra={extra} missing={missing}")
    for entry in entries:
        path = proof_root / entry.path
        if path.stat().st_size != entry.size or _sha256_file(path) != entry.sha256:
            raise BenchEvalError(f"proof digest mismatch: {entry.path}")
        if _role_for(entry.path) != entry.role:
            raise BenchEvalError(f"proof role mismatch: {entry.path}")
    meta = _load_json_object(proof_root / "proof.json", role="proof.json")
    if meta.get("schema_version") != PROOF_SCHEMA:
        raise BenchEvalError("proof.json is not private_proof_v1")
    run_id = meta.get("run_id")
    if not isinstance(run_id, str):
        raise BenchEvalError("proof.json is missing run_id")
    _assert_run_id_coherence(proof_root, run_id)
    _assert_classification(proof_root, meta)
    if meta.get("classification") == "complete":
        plan = RunPlan.model_validate_json(
            (proof_root / "run-plan.json").read_text(encoding="utf-8"),
        )
        history = _read_proof_history(proof_root / "history.jsonl")
        stored = _load_json_object(proof_root / "projection.json", role="projection.json")
        _assert_complete_identity(
            plan=plan,
            records=read_evidence_jsonl(proof_root / "evidence.jsonl"),
            history=history,
            projection=stored,
        )
    _assert_references_inventoried(proof_root, listed)
    return proof_id


def _safe_extract(archive: tarfile.TarFile, dest: Path) -> None:
    for member in archive.getmembers():
        name = member.name.replace("\\", "/")
        parts = Path(name).parts
        if name.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise BenchEvalError(f"unsafe archive member: {member.name}")
        if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
            raise BenchEvalError(f"unsafe archive member: {member.name}")
    archive.extractall(dest, filter="data")


def _unpack_archive(source: Path, dest: Path) -> Path:
    archive_name = source.name
    if not source.is_file() or not archive_name.endswith((".tar.gz", ".tgz")):
        raise BenchEvalError("proof source must be a directory or .tar.gz")
    try:
        with tarfile.open(source, "r:gz") as archive:
            _safe_extract(archive, dest)
        children = [child for child in dest.iterdir() if not child.name.startswith(".")]
    except BenchEvalError:
        raise
    except (OSError, tarfile.TarError) as e:
        raise BenchEvalError(f"cannot unpack proof archive {source}: {e}") from e
    if len(children) == 1 and children[0].is_dir() and (children[0] / "inventory.json").is_file():
        return children[0]
    return dest


def _install_or_reuse(
    source: Path,
    dest: Path,
    *,
    expected_proof_id: str,
    object_root: Path,
    object_root_fd: int,
) -> None:
    identity_error = dir_identity_error(
        object_root_fd,
        object_root,
        role="proof object directory",
    )
    if identity_error is not None:
        raise BenchEvalError(identity_error)
    leaf = dest.name
    try:
        existing = os.stat(leaf, dir_fd=object_root_fd, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    except OSError as e:
        raise BenchEvalError(f"cannot inspect proof destination {dest}: {e}") from e
    if existing is not None:
        if not stat.S_ISDIR(existing.st_mode):
            raise BenchEvalError(
                f"conflicting existing proof: destination is not a directory: {dest}",
            )
        try:
            verify_private_proof(dest, expected_proof_id=expected_proof_id)
        except BenchEvalError as e:
            raise BenchEvalError(f"conflicting existing proof: {e}") from e
        identity_error = dir_identity_error(
            object_root_fd,
            object_root,
            role="proof object directory",
        )
        if identity_error is not None:
            raise BenchEvalError(identity_error)
        return
    try:
        os.rename(source, leaf, dst_dir_fd=object_root_fd)
    except OSError as e:
        raise BenchEvalError(f"cannot install verified proof {dest}: {e}") from e
    identity_error = dir_identity_error(
        object_root_fd,
        object_root,
        role="proof object directory",
    )
    if identity_error is not None:
        raise BenchEvalError(identity_error)
    verify_private_proof(dest, expected_proof_id=expected_proof_id)
    identity_error = dir_identity_error(
        object_root_fd,
        object_root,
        role="proof object directory",
    )
    if identity_error is not None:
        raise BenchEvalError(identity_error)


@contextmanager
def _proof_index_lock(store_root: Path) -> Iterator[None]:
    lock_path = store_root / "proofs.jsonl.lock"
    store_root.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_RDWR
        | os.O_CREAT
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as e:
        raise BenchEvalError(f"cannot lock proof index {lock_path}: {e}") from e
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BenchEvalError(f"cannot lock proof index {lock_path}: not an owned regular file")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _open_owned_index_file(index: Path, flags: int) -> int:
    safe_flags = (
        flags
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(index, safe_flags, 0o600)
    except OSError as e:
        raise BenchEvalError(f"cannot open proof index {index}: {e}") from e
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise BenchEvalError(f"corrupt proof index {index}: not an owned regular file")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _load_proof_index_rows(
    index: Path,
    *,
    validate_installed: bool = True,
) -> list[dict[str, object]]:
    if index.is_symlink():
        raise BenchEvalError(f"corrupt proof index {index}: symlink rejected")
    if not index.exists():
        return []
    if not index.is_file():
        raise BenchEvalError(f"corrupt proof index {index}: not a regular file")
    descriptor = _open_owned_index_file(index, os.O_RDONLY)
    try:
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            text = handle.read()
    except (OSError, UnicodeError) as e:
        raise BenchEvalError(f"cannot read proof index {index}: {e}") from e
    rows: list[dict[str, object]] = []
    seen_proof_ids: set[str] = set()
    required_keys = {"installed_path", "proof_id", "run_id", "schema_version"}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as e:
            raise BenchEvalError(f"corrupt proof index {index}: {e}") from e
        if not isinstance(parsed, dict):
            raise BenchEvalError(f"corrupt proof index {index}: row is not an object")
        if set(parsed) != required_keys:
            raise BenchEvalError(f"corrupt proof index {index}: row schema is not closed")
        proof_id = parsed.get("proof_id")
        run_id = parsed.get("run_id")
        installed_path = parsed.get("installed_path")
        if parsed.get("schema_version") != INDEX_SCHEMA:
            raise BenchEvalError(f"corrupt proof index {index}: wrong schema_version")
        if not isinstance(proof_id, str) or _PROOF_ID_PATTERN.fullmatch(proof_id) is None:
            raise BenchEvalError(f"corrupt proof index {index}: invalid proof_id")
        if not isinstance(run_id, str) or not run_id.strip():
            raise BenchEvalError(f"corrupt proof index {index}: invalid run_id")
        expected_path = f"sha256/{proof_id.removeprefix(PROOF_ID_PREFIX)}"
        if installed_path != expected_path:
            raise BenchEvalError(f"corrupt proof index {index}: invalid installed_path")
        if proof_id in seen_proof_ids:
            raise BenchEvalError(f"corrupt proof index {index}: duplicate proof_id {proof_id}")
        seen_proof_ids.add(proof_id)
        rows.append(parsed)
    if not validate_installed:
        return rows
    for row in rows:
        proof_id = str(row["proof_id"])
        run_id = str(row["run_id"])
        installed_path = str(row["installed_path"])
        installed = index.parent / installed_path
        if installed.is_symlink() or not installed.is_dir():
            raise BenchEvalError(
                f"corrupt proof index {index}: installed proof is missing for {proof_id}",
            )
        try:
            inventory_path = installed / "inventory.json"
            if inventory_path.is_symlink() or not inventory_path.is_file():
                raise BenchEvalError("installed inventory.json is missing")
            raw_inventory = inventory_path.read_bytes()
            if f"{PROOF_ID_PREFIX}{hashlib.sha256(raw_inventory).hexdigest()}" != proof_id:
                raise BenchEvalError("installed inventory digest disagrees")
            inventory = _parse_inventory(raw_inventory)
            proof_entries = [entry for entry in inventory if entry.path == "proof.json"]
            if len(proof_entries) != 1:
                raise BenchEvalError("installed inventory does not bind proof.json")
            proof_path = installed / "proof.json"
            proof_info = os.lstat(proof_path)
            proof_entry = proof_entries[0]
            proof_bytes = proof_path.read_bytes()
            if (
                not stat.S_ISREG(proof_info.st_mode)
                or proof_info.st_nlink > 1
                or len(proof_bytes) != proof_entry.size
                or hashlib.sha256(proof_bytes).hexdigest() != proof_entry.sha256
            ):
                raise BenchEvalError("installed proof.json digest disagrees")
            metadata = json.loads(proof_bytes.decode("utf-8"))
            if not isinstance(metadata, dict):
                raise BenchEvalError("installed proof.json is not an object")
        except (BenchEvalError, OSError, UnicodeError, json.JSONDecodeError) as e:
            raise BenchEvalError(
                f"corrupt proof index {index}: conflicting existing proof for {proof_id}: {e}",
            ) from e
        if metadata.get("schema_version") != PROOF_SCHEMA or metadata.get("run_id") != run_id:
            raise BenchEvalError(
                f"corrupt proof index {index}: proof metadata disagrees for {proof_id}",
            )
    return rows


def _proof_index_row(proof_id: str, run_id: str) -> dict[str, object]:
    return {
        "installed_path": f"sha256/{proof_id.removeprefix(PROOF_ID_PREFIX)}",
        "proof_id": proof_id,
        "run_id": run_id,
        "schema_version": INDEX_SCHEMA,
    }


def _reject_proof_index_conflict(
    rows: list[dict[str, object]],
    intended: dict[str, object],
) -> None:
    proof_id = intended["proof_id"]
    for existing in rows:
        if existing.get("proof_id") == proof_id:
            if existing == intended:
                return
            raise BenchEvalError(f"conflicting proof index row for {proof_id}")


def _append_proof_index_row(
    store_root: Path,
    proof_id: str,
    run_id: str,
    dest: Path,
    *,
    existing_rows: list[dict[str, object]] | None = None,
) -> None:
    row = _proof_index_row(proof_id, run_id)
    if dest != store_root / str(row["installed_path"]):
        raise BenchEvalError(f"proof install path disagrees for {proof_id}")
    line = json.dumps(row, sort_keys=True, ensure_ascii=False)
    index = store_root / "proofs.jsonl"
    rows = _load_proof_index_rows(index) if existing_rows is None else existing_rows
    _reject_proof_index_conflict(rows, row)
    if any(existing.get("proof_id") == proof_id for existing in rows):
        return
    descriptor = _open_owned_index_file(index, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _import_verified(unpacked: Path, store_root: Path) -> Path:
    with _proof_index_lock(store_root):
        source_proof_id = verify_private_proof(unpacked)
        source_meta = _load_json_object(unpacked / "proof.json", role="proof.json")
        source_run_id = source_meta.get("run_id")
        if not isinstance(source_run_id, str):
            raise BenchEvalError("imported proof is missing run_id")
        source_dest = store_root / "sha256" / source_proof_id.removeprefix(PROOF_ID_PREFIX)
        intended_row = _proof_index_row(source_proof_id, source_run_id)
        existing_rows = _load_proof_index_rows(store_root / "proofs.jsonl")
        _reject_proof_index_conflict(existing_rows, intended_row)
        object_root = store_root / "sha256"
        object_root_fd = open_owned_dir_fd(object_root, role="proof object directory")
        try:
            with tempfile.TemporaryDirectory(
                prefix=".bencheval-proof-import-",
                dir=store_root,
            ) as temp_root:
                staged = Path(temp_root) / "proof"
                try:
                    shutil.copytree(unpacked, staged, symlinks=True)
                except (OSError, shutil.Error) as e:
                    raise BenchEvalError(f"cannot stage proof import {unpacked}: {e}") from e
                proof_id = verify_private_proof(staged, expected_proof_id=source_proof_id)
                dest = object_root / proof_id.removeprefix(PROOF_ID_PREFIX)
                if dest != source_dest:
                    raise BenchEvalError("staged proof install path disagrees with verified source")
                _install_or_reuse(
                    staged,
                    dest,
                    expected_proof_id=proof_id,
                    object_root=object_root,
                    object_root_fd=object_root_fd,
                )
                _append_proof_index_row(
                    store_root,
                    proof_id,
                    source_run_id,
                    dest,
                    existing_rows=existing_rows,
                )
                return dest
        finally:
            os.close(object_root_fd)


def import_private_proof(source: Path, *, store_root: Path) -> Path:
    resolved = source.resolve()
    store = store_root.resolve()
    if resolved.is_dir():
        return _import_verified(resolved, store)
    with tempfile.TemporaryDirectory(prefix="bencheval-proof-") as tmp:
        return _import_verified(_unpack_archive(resolved, Path(tmp)), store)


def _proof_summary(root: Path, proof_id: str) -> PrivateProofSummary:
    metadata = _load_json_object(root / "proof.json", role="proof.json")
    run_id = metadata.get("run_id")
    if not isinstance(run_id, str):
        raise BenchEvalError("verified proof is missing run_id")
    plan_path = root / "run-plan.json"
    benchmark_id = None
    if plan_path.is_file() and not plan_path.is_symlink():
        benchmark_id = RunPlan.model_validate_json(
            plan_path.read_text(encoding="utf-8")
        ).benchmark_id
    return PrivateProofSummary(
        proof_id=proof_id,
        run_id=run_id,
        path=root,
        classification=str(metadata.get("classification", "unknown")),
        classification_reason=(
            str(metadata["classification_reason"])
            if metadata.get("classification_reason") is not None
            else None
        ),
        benchmark_id=benchmark_id,
    )


def inspect_private_proof(
    source: Path,
    *,
    expected_proof_id: str | None = None,
) -> PrivateProofSummary:
    """Verify and describe a proof directory or portable ``.tar.gz`` archive."""
    resolved = source.resolve()
    if resolved.is_dir():
        return _proof_summary(
            resolved,
            verify_private_proof(resolved, expected_proof_id=expected_proof_id),
        )
    with tempfile.TemporaryDirectory(prefix="bencheval-proof-inspect-") as tmp:
        unpacked = _unpack_archive(resolved, Path(tmp))
        summary = _proof_summary(
            unpacked,
            verify_private_proof(unpacked, expected_proof_id=expected_proof_id),
        )
        return PrivateProofSummary(
            proof_id=summary.proof_id,
            run_id=summary.run_id,
            path=resolved,
            classification=summary.classification,
            classification_reason=summary.classification_reason,
            benchmark_id=summary.benchmark_id,
        )


def scan_private_proofs(store_root: Path | None = None) -> tuple[PrivateProofScan, ...]:
    """Inspect each indexed proof without letting one corrupt object hide its siblings."""
    store = (store_root or default_proofs_dir()).resolve()
    index = store / "proofs.jsonl"
    if not index.exists():
        return ()
    scans: list[PrivateProofScan] = []
    for row in _load_proof_index_rows(index, validate_installed=False):
        path = store / str(row["installed_path"])
        proof_id = str(row["proof_id"])
        run_id = str(row["run_id"])
        try:
            if path.is_symlink() or not path.is_dir():
                raise BenchEvalError(f"installed proof is missing or redirected: {path}")
            verified_id = verify_private_proof(path, expected_proof_id=proof_id)
            summary = _proof_summary(path, verified_id)
            if summary.run_id != run_id:
                raise BenchEvalError(f"proof index run_id disagrees for {proof_id}")
        except (BenchEvalError, OSError, UnicodeError, ValueError) as exc:
            scans.append(
                PrivateProofScan(
                    proof_id=proof_id,
                    run_id=run_id,
                    path=path,
                    summary=None,
                    error=str(exc),
                ),
            )
            continue
        scans.append(
            PrivateProofScan(
                proof_id=proof_id,
                run_id=run_id,
                path=path,
                summary=summary,
                error=None,
            ),
        )
    return tuple(scans)


def list_private_proofs(store_root: Path | None = None) -> tuple[PrivateProofSummary, ...]:
    """Return the verified inventory, failing with the corrupt object's identity."""
    summaries: list[PrivateProofSummary] = []
    for scan in scan_private_proofs(store_root):
        if scan.error is not None or scan.summary is None:
            raise BenchEvalError(
                f"proof {scan.proof_id} at {scan.path} is corrupt: "
                f"{scan.error or 'verification produced no summary'}",
            )
        summaries.append(scan.summary)
    return tuple(summaries)


__all__ = [
    "INDEX_SCHEMA",
    "INVENTORY_SCHEMA",
    "PROOF_SCHEMA",
    "PrivateProofExport",
    "PrivateProofScan",
    "PrivateProofSummary",
    "default_proofs_dir",
    "export_private_proof",
    "import_private_proof",
    "inspect_private_proof",
    "list_private_proofs",
    "scan_private_proofs",
    "verify_private_proof",
]
