"""Behavioral contracts for run-level exposure-study artifact retention (X1.6).

SUBSTITUTE_JUSTIFICATION
- substitute: an injected ``bfcl`` process runner that writes official-shaped
  result/score files, plus disposable proof/bundle trees
- replaces: the pinned `bfcl generate`/`bfcl evaluate` subprocesses and a
  charged provider call
- necessity: study-artifact idempotence, cross-instance drift, symlink/
  hardlink/missing/digest-changed retention failures, and public omission of
  ``study/private`` must be forced deterministically without provider spend
- real-option: an official bfcl-eval install plus provider credentials; not
  available in the Tier-0 environment
- proof-limit: proves BenchEval-side retention only, never BFCL execution,
  scores, freshness, or exposure results
- real-proof: the X2.3 dev-box BFCL Live plumbing run and its imported proofs
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import BfclPackageDataIdentity, load_benchmark_catalog
from bencheval.bfcl_native_adapter import (
    STUDY_ACCESS_FILE,
    STUDY_ARTIFACT_DIR,
    STUDY_IDENTITY_FILE,
    BfclCliResult,
    bfcl_pinned_harness_version,
    run_bfcl_instance,
)
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.domain import RunPlan
from bencheval.evidence import JsonlEvidenceSink, read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.identity_strings import bfcl_benchmark_identity
from bencheval.live_run_manifest import LiveRunRecord, append_live_run
from bencheval.proof_bundle import export_private_proof, verify_private_proof
from bencheval.run_bundle import export_run_bundle

_MODEL = "gpt-5.2-2025-12-11"
_TS = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
_TRANSCRIPT_SENTINEL = "PRIVATE-RETRIEVAL-TRANSCRIPT-9f3c"


def _canonical_plan(instances: int = 2) -> RunPlan:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="exposure-plumbing-5",
        runtime_id=None,
        model_id=_MODEL,
    )
    return plan.model_copy(update={"instances": plan.instances[:instances]})


def _canonical_identity() -> str:
    entry = load_benchmark_catalog().by_id_or_alias("bfcl-v4")
    assert isinstance(entry.identity, BfclPackageDataIdentity)
    return bfcl_benchmark_identity(entry.identity, benchmark_id="bfcl-v4")


def _runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
    env: Mapping[str, str],
) -> BfclCliResult:
    """Official-shaped generate/evaluate outputs for one exact canonical case."""
    del cwd, timeout_sec
    call = tuple(command)
    ids = json.loads(
        (Path(env["BFCL_PROJECT_ROOT"]) / "test_case_ids_to_generate.json").read_text()
    )
    category, (instance_id,) = next(iter(ids.items()))
    if call[1] == "generate":
        root = Path(call[call.index("--result-dir") + 1])
        result = root / _MODEL / "non_live" / f"BFCL_v4_{category}_result.json"
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(json.dumps({"id": instance_id, "result": [[]]}) + "\n", encoding="utf-8")
    else:
        root = Path(call[call.index("--score-dir") + 1])
        score = root / _MODEL / "non_live" / f"BFCL_v4_{category}_score.json"
        score.parent.mkdir(parents=True, exist_ok=True)
        score.write_text(
            json.dumps({"accuracy": 1.0, "correct_count": 1, "total_count": 1}) + "\n",
            encoding="utf-8",
        )
    return BfclCliResult(0, "", "", 0.1, call)


def _run_instance(plan: RunPlan, instance_id: str, root: Path):
    return run_bfcl_instance(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=root / "art",
        repo_root=root,
        process_runner=_runner,
        harness_version=bfcl_pinned_harness_version(),
        benchmark_identity=_canonical_identity(),
    )


def _execute(root: Path, *, run_id: str = "run-study-artifacts") -> Path:
    evidence = root / "evidence.jsonl"
    execute_control_plane_run(
        plan=_canonical_plan(),
        output_path=evidence,
        artifacts_dir=root / "art",
        run_id=run_id,
        bfcl_process_runner=_runner,
        bfcl_benchmark_identity=_canonical_identity(),
    )
    return evidence


def _manifest_for(root: Path, evidence: Path, run_id: str) -> Path:
    manifest = root / "runs.jsonl"
    rows = read_evidence_jsonl(evidence)
    append_live_run(
        manifest,
        LiveRunRecord(
            run_id=run_id,
            host="test-host",
            benchmark=rows[0].benchmark_id,
            slice_id=rows[0].slice_id,
            model_id=rows[0].model_id,
            evidence_path=str(evidence),
            status="completed",
            generated_at=_TS,
        ),
    )
    return manifest


def _export_proof(root: Path, evidence: Path, *, run_id: str = "run-study-artifacts") -> Path:
    return export_private_proof(
        run_id=run_id,
        evidence_path=evidence,
        artifacts_dir=root / "art",
        manifest_path=_manifest_for(root, evidence, run_id),
        output_dir=root / "proof",
    ).root


# --- adapter: idempotent run-level declarations --------------------------------


def test_study_artifacts_are_written_once_and_verified_by_later_instances(
    tmp_path: Path,
) -> None:
    plan = _canonical_plan()
    first = _run_instance(plan, "simple_python_0", tmp_path)
    second = _run_instance(plan, "multiple_0", tmp_path)

    study_dir = tmp_path / "art" / STUDY_ARTIFACT_DIR
    assert first.study_artifact_paths == second.study_artifact_paths
    assert set(first.study_artifact_paths) == {
        f"art/{STUDY_ARTIFACT_DIR}/{STUDY_ACCESS_FILE}",
        f"art/{STUDY_ARTIFACT_DIR}/{STUDY_IDENTITY_FILE}",
    }
    identity = json.loads((study_dir / STUDY_IDENTITY_FILE).read_text(encoding="utf-8"))
    entry = load_benchmark_catalog().by_id_or_alias("bfcl-v4")
    assert isinstance(entry.identity, BfclPackageDataIdentity)
    assert identity["benchmark_id"] == "bfcl-v4"
    assert identity["benchmark_version"] == _canonical_identity()
    assert identity["harness_version"] == bfcl_pinned_harness_version()
    assert identity["identity"]["files"] == entry.identity.files
    access = json.loads((study_dir / STUDY_ACCESS_FILE).read_text(encoding="utf-8"))
    assert access["access_control_source"] == "not_applicable"
    assert access["egress_control"] == "not_applicable"
    assert access["repository_history"] == "not_applicable"
    assert access["retrieval_audit"] == "not_run"
    assert access["requested_network_policy"] == plan.network_policy
    assert first.access_evidence.egress_control == access["egress_control"]


def test_study_artifact_drift_or_link_between_instances_fails_closed(tmp_path: Path) -> None:
    plan = _canonical_plan(3)
    _run_instance(plan, "simple_python_0", tmp_path)
    identity = tmp_path / "art" / STUDY_ARTIFACT_DIR / STUDY_IDENTITY_FILE
    original = identity.read_text(encoding="utf-8")

    identity.write_text(original.replace("bfcl-v4", "bfcl-v4-forged", 1), encoding="utf-8")
    with pytest.raises(AdapterFailureError) as drift:
        _run_instance(plan, "multiple_0", tmp_path)
    assert drift.value.failure_label == "evidence_corrupt"

    identity.unlink()
    identity.symlink_to(tmp_path / "elsewhere.json")
    (tmp_path / "elsewhere.json").write_text(original, encoding="utf-8")
    with pytest.raises(AdapterFailureError) as link:
        _run_instance(plan, "parallel_0", tmp_path)
    assert link.value.failure_label == "evidence_corrupt"
    assert (tmp_path / "elsewhere.json").read_text(encoding="utf-8") == original


# --- executor + private proof --------------------------------------------------


def test_evidence_rows_reference_study_artifacts_and_proof_retains_them(tmp_path: Path) -> None:
    evidence = _execute(tmp_path)
    rows = read_evidence_jsonl(evidence)
    assert len(rows) == 2
    # The executor stamps paths relative to the real repo root, so a tmp run root
    # stays absolute, exactly like the stdout/stderr/score paths beside it.
    for row in rows:
        assert any(
            p.endswith(f"/{STUDY_ARTIFACT_DIR}/{STUDY_IDENTITY_FILE}") for p in row.artifact_paths
        )
        assert any(
            p.endswith(f"/{STUDY_ARTIFACT_DIR}/{STUDY_ACCESS_FILE}") for p in row.artifact_paths
        )
        assert row.access_control_source == "not_applicable"

    proof = _export_proof(tmp_path, evidence)
    retained = proof / "artifacts" / "raw" / STUDY_ARTIFACT_DIR
    assert (retained / STUDY_IDENTITY_FILE).is_file()
    assert (retained / STUDY_ACCESS_FILE).is_file()
    proof_rows = read_evidence_jsonl(proof / "evidence.jsonl")
    assert all(
        f"artifacts/raw/{STUDY_ARTIFACT_DIR}/{STUDY_IDENTITY_FILE}" in r.artifact_paths
        for r in proof_rows
    )
    inventory = json.loads((proof / "inventory.json").read_text(encoding="utf-8"))
    roles = {entry["path"]: entry["role"] for entry in inventory["files"]}
    assert roles[f"artifacts/raw/{STUDY_ARTIFACT_DIR}/{STUDY_IDENTITY_FILE}"] == "artifact"
    assert (proof / "proof.json").read_text(encoding="utf-8").find('"complete"') >= 0

    # Source-checkout removal: the copied proof still verifies on its own bytes.
    copied = tmp_path / "copied"
    shutil.copytree(proof, copied)
    shutil.rmtree(tmp_path / "art")
    evidence.unlink()
    assert verify_private_proof(copied).startswith("sha256:")


def test_retained_study_artifacts_reject_digest_change_hardlink_and_symlink(
    tmp_path: Path,
) -> None:
    evidence = _execute(tmp_path)
    proof = _export_proof(tmp_path, evidence)
    retained = proof / "artifacts" / "raw" / STUDY_ARTIFACT_DIR / STUDY_IDENTITY_FILE

    tampered = tmp_path / "tampered"
    shutil.copytree(proof, tampered)
    target = tampered / "artifacts" / "raw" / STUDY_ARTIFACT_DIR / STUDY_IDENTITY_FILE
    target.write_text(target.read_text(encoding="utf-8").replace("bfcl-v4", "bfcl-v4-x", 1))
    with pytest.raises(BenchEvalError, match="digest"):
        verify_private_proof(tampered)

    linked = tmp_path / "linked"
    shutil.copytree(proof, linked)
    target = linked / "artifacts" / "raw" / STUDY_ARTIFACT_DIR / STUDY_IDENTITY_FILE
    target.unlink()
    os.link(linked / "artifacts" / "raw" / STUDY_ARTIFACT_DIR / STUDY_ACCESS_FILE, target)
    with pytest.raises(BenchEvalError):
        verify_private_proof(linked)

    symlinked = tmp_path / "symlinked"
    shutil.copytree(proof, symlinked)
    target = symlinked / "artifacts" / "raw" / STUDY_ARTIFACT_DIR / STUDY_IDENTITY_FILE
    target.unlink()
    target.symlink_to(retained)
    with pytest.raises(BenchEvalError):
        verify_private_proof(symlinked)
    assert retained.is_file()


def test_export_rejects_missing_symlinked_or_escaping_study_artifacts(tmp_path: Path) -> None:
    evidence = _execute(tmp_path)
    identity = tmp_path / "art" / STUDY_ARTIFACT_DIR / STUDY_IDENTITY_FILE
    original = identity.read_bytes()

    identity.unlink()
    with pytest.raises(BenchEvalError, match="missing"):
        _export_proof(tmp_path, evidence)
    assert not (tmp_path / "proof").exists()

    outside = tmp_path / "outside.json"
    outside.write_bytes(original)
    identity.symlink_to(outside)
    with pytest.raises(BenchEvalError):
        _export_proof(tmp_path, evidence)
    assert not (tmp_path / "proof").exists()
    identity.unlink()
    identity.write_bytes(original)

    # A row that points a study artifact outside the declared raw root escapes.
    rows = read_evidence_jsonl(evidence)
    escaped = rows[0].model_copy(
        update={"artifact_paths": [*rows[0].artifact_paths, "../outside.json"]},
    )
    hostile = tmp_path / "hostile.jsonl"
    sink = JsonlEvidenceSink()
    sink.append_jsonl(hostile, escaped)
    sink.append_jsonl(hostile, rows[1])
    with pytest.raises(BenchEvalError):
        export_private_proof(
            run_id=rows[0].run_id,
            evidence_path=hostile,
            artifacts_dir=tmp_path / "art",
            manifest_path=_manifest_for(tmp_path, evidence, rows[0].run_id),
            output_dir=tmp_path / "proof-hostile",
        )
    assert not (tmp_path / "proof-hostile").exists()


# --- public redaction ----------------------------------------------------------


def test_public_bundle_omits_private_study_material_while_private_retains_it(
    tmp_path: Path,
) -> None:
    evidence = _execute(tmp_path)
    private_dir = tmp_path / "art" / STUDY_ARTIFACT_DIR / "private"
    private_dir.mkdir()
    transcript = private_dir / "retrieval-transcript.jsonl"
    transcript.write_text(json.dumps({"prompt": _TRANSCRIPT_SENTINEL}) + "\n", encoding="utf-8")
    rows = read_evidence_jsonl(evidence)
    with_transcript = tmp_path / "with-transcript.jsonl"
    sink = JsonlEvidenceSink()
    for row in rows:
        sink.append_jsonl(
            with_transcript,
            row.model_copy(
                update={
                    "artifact_paths": [
                        *row.artifact_paths,
                        f"art/{STUDY_ARTIFACT_DIR}/private/retrieval-transcript.jsonl",
                    ],
                },
            ),
        )

    public = export_run_bundle(
        evidence_path=with_transcript,
        output_dir=tmp_path / "public",
        raw_dir=tmp_path / "art",
        redaction="public",
    )
    assert public.is_file()
    assert not (tmp_path / "public" / "raw").exists()
    for path in (tmp_path / "public").rglob("*"):
        if path.is_file() and path.suffix != ".gz":
            assert _TRANSCRIPT_SENTINEL not in path.read_text(encoding="utf-8", errors="ignore")

    export_run_bundle(
        evidence_path=with_transcript,
        output_dir=tmp_path / "private",
        raw_dir=tmp_path / "art",
        redaction="private",
    )
    kept = (
        tmp_path / "private" / "raw" / STUDY_ARTIFACT_DIR / "private" / "retrieval-transcript.jsonl"
    )
    assert _TRANSCRIPT_SENTINEL in kept.read_text(encoding="utf-8")
    assert (tmp_path / "private" / "raw" / STUDY_ARTIFACT_DIR / STUDY_IDENTITY_FILE).is_file()
