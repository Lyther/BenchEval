"""Implementation-phase contracts for ``private_proof_v1``.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed EvidenceRecord / LiveRunRecord rows and disposable
  artifact trees (`_write_source`, `_tb_evidence`, `_tb_history`)
- replaces: private evidence, run history, and raw output from a charged native
  benchmark run
- necessity: missing references, archive traversal, conflicting stores, mixed
  identities, sibling-run substitution, corrupt indexes, and source-checkout
  removal must be forced without mutating operator proof
- real-option: an operator proof cannot safely be rewritten into these negative
  states; a charged rerun cannot guarantee them
- proof-limit: diagnostic completeness/import/identity-coherence behavior only;
  it does not prove creator authenticity, benchmark truth, or live readiness
- real-proof: operator-host Terminal-Bench Codex
  `run-20260825-171829-685914-aa08dd1d` proof
  `sha256:fca2295d6844e4dda99799527561985885a90b59e01c865082510eaa63d90c06`
  and GPQA `run-20260825-160511-036214-304c2cee` proof
  `sha256:aa19d02b7d1457d0f43d9588b3d08c042e967a981ed8537068412e1797ff0eda`
  remain externally retained on the operator host, not in this checkout
- covered tests: every test in this module
"""

from __future__ import annotations

import io
import json
import os
import shutil
import stat
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.cli import main
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.live_run_manifest import LiveRunRecord, append_live_run
from bencheval.proof_bundle import (
    InventoryEntry,
    _canonical_inventory_bytes,
    _write_inventory,
    export_private_proof,
    import_private_proof,
    verify_private_proof,
)
from bencheval.run_bundle import export_run_bundle

_RUN_ID = "run-private-proof-v1"
_TS = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _tb_plan():
    return plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )


def _tb_evidence(artifact_paths: list[str]) -> EvidenceRecord:
    plan = _tb_plan()
    return EvidenceRecord(
        run_id=_RUN_ID,
        task_id="fix-git",
        model_id=plan.model_id,
        execution_profile="E2",
        backend="harbor",
        primary_pass=False,
        partial_score=0.0,
        cost_usd=0.0,
        latency_sec=1.0,
        artifact_paths=artifact_paths,
        created_at=_TS,
        benchmark_id=plan.benchmark_id,
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        runtime_id=plan.runtime_id,
        provider_id=plan.provider_id,
        instance_id="fix-git",
    )


def _tb_history(evidence_path: Path) -> LiveRunRecord:
    plan = _tb_plan()
    return LiveRunRecord(
        run_id=_RUN_ID,
        host="dev-box-cpu",
        benchmark=plan.benchmark_id,
        slice_id=plan.slice_id,
        runtime=plan.runtime_id,
        model_id=plan.model_id,
        evidence_path=str(evidence_path),
        status="completed",
        generated_at=_TS,
    )


def _write_source(root: Path, *, with_plan: bool = True) -> dict[str, Path]:
    raw = root / "raw"
    source = raw / "task" / "official.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"resolved": false}\n', encoding="utf-8")
    evidence = root / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, _tb_evidence(["task/official.json"]))
    if with_plan:
        (raw / "run-plan.json").write_text(_tb_plan().model_dump_json() + "\n", encoding="utf-8")
    manifest = root / "runs.jsonl"
    append_live_run(manifest, _tb_history(evidence))
    return {"raw": raw, "evidence": evidence, "manifest": manifest}


def test_export_resolves_repo_relative_paths_inside_raw_root(tmp_path: Path) -> None:
    repo = tmp_path / "checkout"
    raw = repo / "results" / "raw" / "tb-codex-cli-tag"
    official = raw / "fix-git" / "result.json"
    official.parent.mkdir(parents=True)
    official.write_text('{"resolved": false}\n', encoding="utf-8")
    evidence = repo / "results" / "evidence" / "tb.jsonl"
    evidence.parent.mkdir(parents=True)
    JsonlEvidenceSink().append_jsonl(
        evidence,
        _tb_evidence(["results/raw/tb-codex-cli-tag/fix-git/result.json"]),
    )
    (raw / "run-plan.json").write_text(_tb_plan().model_dump_json() + "\n", encoding="utf-8")
    manifest = repo / "results" / "manifests" / "runs.jsonl"
    manifest.parent.mkdir(parents=True)
    append_live_run(manifest, _tb_history(evidence))

    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=evidence,
        artifacts_dir=raw,
        manifest_path=manifest,
        output_dir=tmp_path / "proof",
    )
    assert exported.classification == "complete"
    retained = read_evidence_jsonl(exported.root / "evidence.jsonl")[0].artifact_paths[0]
    assert retained.startswith("artifacts/")
    assert (exported.root / retained).is_file()


@pytest.mark.parametrize(
    "artifact_path",
    [
        "../secret.json",
        "nested/../result.json",
        "results/raw/tb-codex-cli-tag/../../../secret.json",
        "results/raw/other-tag/result.json",
        "results/raw/other-tag/fix-git/result.json",
    ],
)
def test_export_rejects_parent_and_sibling_suffix_paths(
    tmp_path: Path,
    artifact_path: str,
) -> None:
    repo = tmp_path / "checkout"
    raw = repo / "results" / "raw" / "tb-codex-cli-tag"
    raw.mkdir(parents=True)
    (raw / "result.json").write_text('{"sibling": true}\n', encoding="utf-8")
    nested = raw / "fix-git"
    nested.mkdir()
    (nested / "result.json").write_text('{"current": true}\n', encoding="utf-8")
    secret = repo / "secret.json"
    secret.write_text('{"secret": true}\n', encoding="utf-8")
    evidence = repo / "results" / "evidence" / "tb.jsonl"
    evidence.parent.mkdir(parents=True)
    JsonlEvidenceSink().append_jsonl(evidence, _tb_evidence([artifact_path]))
    (raw / "run-plan.json").write_text(_tb_plan().model_dump_json() + "\n", encoding="utf-8")
    manifest = repo / "results" / "manifests" / "runs.jsonl"
    manifest.parent.mkdir(parents=True)
    append_live_run(manifest, _tb_history(evidence))

    with pytest.raises(BenchEvalError, match=r"missing referenced artifact|outside"):
        export_private_proof(
            run_id=_RUN_ID,
            evidence_path=evidence,
            artifacts_dir=raw,
            manifest_path=manifest,
            output_dir=tmp_path / "proof",
        )


def test_export_verifies_after_source_checkout_disappears(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    assert exported.proof_id.startswith("sha256:")
    assert exported.classification == "complete"
    assert (exported.root / "inventory.json").is_file()
    assert (exported.root / "run-plan.json").is_file()
    retained = read_evidence_jsonl(exported.root / "evidence.jsonl")[0].artifact_paths[0]
    assert retained.startswith("artifacts/")
    assert (exported.root / retained).is_file()

    for path in source.values():
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            for child in path.rglob("*"):
                if child.is_file():
                    child.unlink()

    assert verify_private_proof(exported.root, expected_proof_id=exported.proof_id) == (
        exported.proof_id
    )


def test_import_is_idempotent_and_preserves_a_conflicting_proof(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    store = tmp_path / "store"
    first = import_private_proof(exported.root, store_root=store)
    second = import_private_proof(exported.root, store_root=store)
    assert first == second
    index = (store / "proofs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(index) == 1

    occupant = first / "report.md"
    original = occupant.read_bytes()
    occupant.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(BenchEvalError, match=r"conflict|existing proof"):
        import_private_proof(exported.root, store_root=store)
    assert occupant.read_bytes() == b"tampered\n"
    occupant.write_bytes(original)


def test_import_rejects_archive_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar.gz"
    payload = b"escaped\n"
    info = tarfile.TarInfo(name="../escape.txt")
    info.size = len(payload)
    with tarfile.open(archive, "w:gz") as handle:
        handle.addfile(info, io.BytesIO(payload))
    with pytest.raises(BenchEvalError, match=r"archive|traversal|unsafe"):
        import_private_proof(archive, store_root=tmp_path / "store")
    assert not (tmp_path / "escape.txt").exists()


def test_verify_rejects_a_public_run_bundle(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    bundle = tmp_path / "public"
    export_run_bundle(
        evidence_path=source["evidence"],
        output_dir=bundle,
        raw_dir=source["raw"],
        redaction="public",
    )
    with pytest.raises(BenchEvalError, match=r"private_proof|public|redacted"):
        verify_private_proof(bundle)
    with pytest.raises(BenchEvalError, match=r"private_proof|public|redacted"):
        import_private_proof(bundle, store_root=tmp_path / "store")


def test_missing_run_plan_exports_as_legacy_unverifiable(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src", with_plan=False)
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    assert exported.classification == "legacy_unverifiable"
    assert exported.classification_reason == "run_plan_missing_legacy"
    assert not (exported.root / "run-plan.json").exists()
    assert verify_private_proof(exported.root) == exported.proof_id
    proof = json.loads((exported.root / "proof.json").read_text(encoding="utf-8"))
    assert proof["run_id"] == _RUN_ID
    assert proof["classification"] == "legacy_unverifiable"
    assert proof["classification_reason"] == "run_plan_missing_legacy"


def test_cli_proof_export_verify_import(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    proof = tmp_path / "proof"
    store = tmp_path / "store"
    export_code = main(
        [
            "proof",
            "export",
            "--run-id",
            _RUN_ID,
            "--evidence",
            str(source["evidence"]),
            "--artifacts",
            str(source["raw"]),
            "--manifest",
            str(source["manifest"]),
            "--output",
            str(proof),
        ],
    )
    assert export_code == 0
    verify_code = main(["proof", "verify", str(proof)])
    assert verify_code == 0
    import_code = main(["proof", "import", str(proof), "--store", str(store)])
    assert import_code == 0
    assert any((store / "sha256").iterdir())


def _rewrite_classification(root: Path, classification: str, reason: str | None) -> None:
    payload = json.loads((root / "proof.json").read_text(encoding="utf-8"))
    payload["classification"] = classification
    payload["classification_reason"] = reason
    (root / "proof.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _write_inventory(root)


def test_verify_rejects_extra_missing_digest_and_symlink(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    link = exported.root / "artifacts" / "raw" / "task" / "link.json"
    link.symlink_to("official.json")
    with pytest.raises(BenchEvalError, match=r"symlink"):
        verify_private_proof(exported.root)
    link.unlink()
    extra = exported.root / "extra.txt"
    extra.write_text("nope\n", encoding="utf-8")
    with pytest.raises(BenchEvalError, match=r"file-set|extra"):
        verify_private_proof(exported.root)
    extra.unlink()
    (exported.root / "report.md").write_text("tampered-report\n", encoding="utf-8")
    with pytest.raises(BenchEvalError, match=r"digest mismatch"):
        verify_private_proof(exported.root)
    (exported.root / "report.md").unlink()
    with pytest.raises(BenchEvalError, match=r"file-set|missing"):
        verify_private_proof(exported.root)


def test_verify_requires_report_after_canonical_inventory_rewrite(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    (exported.root / "report.md").unlink()
    _write_inventory(exported.root)

    with pytest.raises(BenchEvalError, match=r"required|report"):
        verify_private_proof(exported.root)


def test_verify_rejects_unknown_classification_and_expected_digest(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    with pytest.raises(BenchEvalError, match=r"expected"):
        verify_private_proof(exported.root, expected_proof_id="sha256:" + ("0" * 64))
    _rewrite_classification(exported.root, "forged", None)
    with pytest.raises(BenchEvalError, match=r"classification"):
        verify_private_proof(exported.root)


def test_export_rejects_symlink_run_plan_and_directory_escape(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    plan = source["raw"] / "run-plan.json"
    real_plan = tmp_path / "plan-elsewhere.json"
    real_plan.write_bytes(plan.read_bytes())
    plan.unlink()
    plan.symlink_to(real_plan)
    with pytest.raises(BenchEvalError, match=r"symlink"):
        export_private_proof(
            run_id=_RUN_ID,
            evidence_path=source["evidence"],
            artifacts_dir=source["raw"],
            manifest_path=source["manifest"],
            output_dir=tmp_path / "proof-symlink-plan",
        )

    escaped = tmp_path / "escaped"
    escaped.mkdir()
    (escaped / "official.json").write_text('{"escaped": true}\n', encoding="utf-8")
    leak = _write_source(tmp_path / "src-leak")
    task = leak["raw"] / "task"
    for child in task.iterdir():
        child.unlink()
    task.rmdir()
    task.symlink_to(escaped)
    with pytest.raises(BenchEvalError, match=r"outside|root|symlink"):
        export_private_proof(
            run_id=_RUN_ID,
            evidence_path=leak["evidence"],
            artifacts_dir=leak["raw"],
            manifest_path=leak["manifest"],
            output_dir=tmp_path / "proof-escape",
        )


def test_import_does_not_replay_history_into_local_runs(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    original = source["manifest"].read_text(encoding="utf-8")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    store = tmp_path / "store"
    import_private_proof(exported.root, store_root=store)
    assert not (store / "runs.jsonl").exists()
    assert source["manifest"].read_text(encoding="utf-8") == original


def test_export_rejects_mixed_plan_evidence_history_identities(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    official = raw / "task" / "official.json"
    official.parent.mkdir(parents=True)
    official.write_text('{"resolved": false}\n', encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, _tb_evidence(["task/official.json"]))
    gpqa = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    (raw / "run-plan.json").write_text(gpqa.model_dump_json() + "\n", encoding="utf-8")
    manifest = tmp_path / "runs.jsonl"
    append_live_run(
        manifest,
        LiveRunRecord(
            run_id=_RUN_ID,
            host="dev-box-cpu",
            benchmark="hle",
            slice_id="smoke",
            model_id="gpt-5.4-2026-03-05",
            evidence_path=str(evidence),
            status="completed",
            generated_at=_TS,
        ),
    )
    with pytest.raises(BenchEvalError, match=r"axis|disagrees|identity"):
        export_private_proof(
            run_id=_RUN_ID,
            evidence_path=evidence,
            artifacts_dir=raw,
            manifest_path=manifest,
            output_dir=tmp_path / "proof",
        )


def test_verify_rejects_complete_proof_after_plan_swap(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    gpqa = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    (exported.root / "run-plan.json").write_text(gpqa.model_dump_json() + "\n", encoding="utf-8")
    _write_inventory(exported.root)
    with pytest.raises(BenchEvalError, match=r"axis|disagrees|identity"):
        verify_private_proof(exported.root)


def test_export_rejects_nested_sibling_run_artifact(tmp_path: Path) -> None:
    repo = tmp_path / "checkout"
    raw = repo / "results" / "raw" / "current-tag"
    planted = raw / "fix-git" / "result.json"
    planted.parent.mkdir(parents=True)
    planted.write_text("CURRENT-RUN-BYTES\n", encoding="utf-8")
    evidence = repo / "results" / "evidence" / "tb.jsonl"
    evidence.parent.mkdir(parents=True)
    JsonlEvidenceSink().append_jsonl(
        evidence,
        _tb_evidence(["results/raw/other-tag/fix-git/result.json"]),
    )
    (raw / "run-plan.json").write_text(_tb_plan().model_dump_json() + "\n", encoding="utf-8")
    manifest = repo / "results" / "manifests" / "runs.jsonl"
    manifest.parent.mkdir(parents=True)
    append_live_run(manifest, _tb_history(evidence))
    with pytest.raises(BenchEvalError, match=r"missing referenced artifact|outside"):
        export_private_proof(
            run_id=_RUN_ID,
            evidence_path=evidence,
            artifacts_dir=raw,
            manifest_path=manifest,
            output_dir=tmp_path / "proof",
        )


def test_import_rejects_corrupt_index_without_installing(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "src")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    store = tmp_path / "store"
    store.mkdir()
    (store / "proofs.jsonl").write_text("{bad\n", encoding="utf-8")
    with pytest.raises(BenchEvalError, match=r"proof index|corrupt|index"):
        import_private_proof(exported.root, store_root=store)
    sha_root = store / "sha256"
    assert not sha_root.exists() or not any(sha_root.iterdir())


@pytest.mark.parametrize("record_count", [1, 2])
def test_complete_proof_requires_every_planned_instance_exactly_once(
    tmp_path: Path,
    record_count: int,
) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    assert len(plan.instances) == 2
    raw = tmp_path / "raw"
    artifact = raw / "task" / "official.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"accuracy": 0.0}\n', encoding="utf-8")
    (raw / "run-plan.json").write_text(plan.model_dump_json() + "\n", encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    instance_id = plan.instances[0].instance_id
    record = EvidenceRecord(
        run_id=_RUN_ID,
        task_id=instance_id,
        model_id=plan.model_id,
        execution_profile="E0",
        backend="inspect",
        primary_pass=False,
        partial_score=0.0,
        cost_usd=0.0,
        latency_sec=1.0,
        artifact_paths=["task/official.json"],
        created_at=_TS,
        benchmark_id=plan.benchmark_id,
        benchmark_version=plan.benchmark_version,
        slice_id=plan.slice_id,
        adapter_id=plan.adapter_id,
        harness_kind=plan.harness_kind,
        provider_id=plan.provider_id,
        instance_id=instance_id,
    )
    for _ in range(record_count):
        JsonlEvidenceSink().append_jsonl(evidence, record)
    manifest = tmp_path / "runs.jsonl"
    append_live_run(
        manifest,
        LiveRunRecord(
            run_id=_RUN_ID,
            host="dev-box-cpu",
            benchmark=plan.benchmark_id,
            slice_id=plan.slice_id,
            model_id=plan.model_id,
            evidence_path=str(evidence),
            status="completed",
            generated_at=_TS,
        ),
    )

    with pytest.raises(BenchEvalError, match=r"planned population|missing planned|duplicate"):
        export_private_proof(
            run_id=_RUN_ID,
            evidence_path=evidence,
            artifacts_dir=raw,
            manifest_path=manifest,
            output_dir=tmp_path / "proof",
        )


def test_complete_proof_accepts_an_exactly_bound_aggregate_population(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    raw = tmp_path / "raw"
    artifact = raw / "task" / "official.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"accuracy": 0.0}\n', encoding="utf-8")
    (raw / "run-plan.json").write_text(plan.model_dump_json() + "\n", encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    aggregate_id = f"{plan.benchmark_id}-{plan.slice_id}-aggregate"
    JsonlEvidenceSink().append_jsonl(
        evidence,
        EvidenceRecord(
            run_id=_RUN_ID,
            task_id=aggregate_id,
            model_id=plan.model_id,
            execution_profile="E0",
            backend="inspect",
            primary_pass=False,
            partial_score=0.0,
            cost_usd=0.0,
            latency_sec=1.0,
            artifact_paths=["task/official.json"],
            adapter_metadata={"evidence_shape": "aggregate_slice"},
            native_score={"planned_sample_slots": len(plan.instances)},
            created_at=_TS,
            benchmark_id=plan.benchmark_id,
            benchmark_version=plan.benchmark_version,
            slice_id=plan.slice_id,
            adapter_id=plan.adapter_id,
            harness_kind=plan.harness_kind,
            provider_id=plan.provider_id,
            instance_id=aggregate_id,
        ),
    )
    manifest = tmp_path / "runs.jsonl"
    append_live_run(
        manifest,
        LiveRunRecord(
            run_id=_RUN_ID,
            host="dev-box-cpu",
            benchmark=plan.benchmark_id,
            slice_id=plan.slice_id,
            model_id=plan.model_id,
            evidence_path=str(evidence),
            status="completed",
            generated_at=_TS,
        ),
    )

    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=evidence,
        artifacts_dir=raw,
        manifest_path=manifest,
        output_dir=tmp_path / "proof",
    )

    assert verify_private_proof(exported.root, expected_proof_id=exported.proof_id) == (
        exported.proof_id
    )


def test_complete_proof_accepts_later_history_rows_with_omitted_axes(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source")
    append_live_run(
        source["manifest"],
        LiveRunRecord(
            run_id=_RUN_ID,
            host="dev-box-cpu",
            model_id=_tb_plan().model_id,
            status="archived",
            generated_at=_TS + timedelta(minutes=1),
        ),
    )

    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )

    assert exported.classification == "complete"
    assert verify_private_proof(exported.root, expected_proof_id=exported.proof_id) == (
        exported.proof_id
    )


def test_failed_export_leaves_no_partial_private_payload_and_can_retry(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source")
    plan_path = source["raw"] / "run-plan.json"
    valid_plan = plan_path.read_text(encoding="utf-8")
    wrong_plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    plan_path.write_text(wrong_plan.model_dump_json() + "\n", encoding="utf-8")
    output = tmp_path / "proof"

    with pytest.raises(BenchEvalError, match=r"disagrees|identity|axis"):
        export_private_proof(
            run_id=_RUN_ID,
            evidence_path=source["evidence"],
            artifacts_dir=source["raw"],
            manifest_path=source["manifest"],
            output_dir=output,
        )
    assert not output.exists() or not any(output.iterdir())

    plan_path.write_text(valid_plan, encoding="utf-8")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=output,
    )
    assert verify_private_proof(exported.root) == exported.proof_id


def test_export_replaces_an_existing_empty_output_directory(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source")
    output = tmp_path / "proof"
    output.mkdir()

    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=output,
    )

    assert exported.root == output
    assert verify_private_proof(output) == exported.proof_id


def test_import_invalid_archive_uses_concise_cli_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    archive = tmp_path / "broken.tar.gz"
    archive.write_bytes(b"not a gzip archive")

    assert main(["proof", "import", str(archive), "--store", str(tmp_path / "store")]) == 1
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert "Traceback" not in captured.err


def test_import_rejects_semantically_corrupt_index_row(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    store = tmp_path / "store"
    store.mkdir()
    forged = {
        "installed_path": "../../outside",
        "proof_id": exported.proof_id,
        "run_id": "wrong-run",
        "schema_version": "evil",
    }
    (store / "proofs.jsonl").write_text(json.dumps(forged) + "\n", encoding="utf-8")

    with pytest.raises(BenchEvalError, match=r"proof index|schema|installed_path"):
        import_private_proof(exported.root, store_root=store)
    sha_root = store / "sha256"
    assert not sha_root.exists() or not any(sha_root.iterdir())


def test_import_rejects_a_conflicting_index_row_before_installing(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    digest = exported.proof_id.removeprefix("sha256:")
    store = tmp_path / "store"
    store.mkdir()
    conflicting = {
        "installed_path": f"sha256/{digest}",
        "proof_id": exported.proof_id,
        "run_id": "different-run",
        "schema_version": "proof_index_v1",
    }
    (store / "proofs.jsonl").write_text(json.dumps(conflicting) + "\n", encoding="utf-8")

    with pytest.raises(BenchEvalError, match=r"proof index|conflict|run_id|installed proof"):
        import_private_proof(exported.root, store_root=store)
    assert not (store / "sha256" / digest).exists()


def test_import_rejects_an_unrelated_dangling_index_row(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    dangling_digest = "0" * 64
    assert exported.proof_id != f"sha256:{dangling_digest}"
    store = tmp_path / "store"
    store.mkdir()
    dangling = {
        "installed_path": f"sha256/{dangling_digest}",
        "proof_id": f"sha256:{dangling_digest}",
        "run_id": "missing-run",
        "schema_version": "proof_index_v1",
    }
    (store / "proofs.jsonl").write_text(json.dumps(dangling) + "\n", encoding="utf-8")

    with pytest.raises(BenchEvalError, match=r"proof index|missing|installed proof"):
        import_private_proof(exported.root, store_root=store)
    imported_digest = exported.proof_id.removeprefix("sha256:")
    assert not (store / "sha256" / imported_digest).exists()


def test_import_rejects_a_symlinked_object_directory_without_writing_outside(
    tmp_path: Path,
) -> None:
    source = _write_source(tmp_path / "source")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    store = tmp_path / "store"
    outside = tmp_path / "outside"
    store.mkdir()
    outside.mkdir()
    (store / "sha256").symlink_to(outside, target_is_directory=True)

    with pytest.raises(BenchEvalError, match=r"sha256|object|symlink|store"):
        import_private_proof(exported.root, store_root=store)
    assert not any(outside.iterdir())


def test_import_rejects_a_symlinked_index_lock_without_touching_its_target(
    tmp_path: Path,
) -> None:
    source = _write_source(tmp_path / "source")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    store = tmp_path / "store"
    store.mkdir()
    outside_lock = tmp_path / "outside.lock"
    outside_lock.write_text("outside-owner\n", encoding="utf-8")
    outside_lock.chmod(0o644)
    (store / "proofs.jsonl.lock").symlink_to(outside_lock)

    with pytest.raises(BenchEvalError, match=r"lock|symlink"):
        import_private_proof(exported.root, store_root=store)
    assert outside_lock.read_text(encoding="utf-8") == "outside-owner\n"
    assert stat.S_IMODE(outside_lock.stat().st_mode) == 0o644
    assert not (store / "sha256").exists()


def test_import_rejects_a_hardlinked_index_without_mutating_its_peer(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    store = tmp_path / "store"
    store.mkdir()
    outside_index = tmp_path / "outside-index.jsonl"
    outside_index.write_bytes(b"")
    os.link(outside_index, store / "proofs.jsonl")

    with pytest.raises(BenchEvalError, match=r"index|hardlink|owned regular"):
        import_private_proof(exported.root, store_root=store)
    assert outside_index.read_bytes() == b""
    assert not (store / "sha256").exists()


def test_verify_rejects_duplicate_inventory_path(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    inventory_path = exported.root / "inventory.json"
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    entries = [InventoryEntry(**entry) for entry in payload["files"]]
    entries.append(entries[0])
    inventory_path.write_bytes(_canonical_inventory_bytes(entries))

    with pytest.raises(BenchEvalError, match=r"duplicate|collision"):
        verify_private_proof(exported.root)


def test_import_reverifies_the_exact_copied_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SUBSTITUTE_JUSTIFICATION
    # - substitute: monkeypatch wrapper around `proof_bundle.shutil.copytree`
    # - replaces: nondeterministic thread scheduling at the source-verify/copy boundary
    # - necessity: the exact mutation interleaving cannot be scheduled reliably in CI;
    #   the source files, copy operation, staged proof, verifier, and store remain real
    # - real-option: a polling thread was reproduced against the real filesystem in
    #   review, but storage speed makes that timing unsuitable as a deterministic test
    # - proof-limit: proves the staged-copy re-verification boundary, not arbitrary
    #   hostile filesystem scheduling
    # - real-proof: a post-fix real-thread disposable-directory probe mutated the
    #   source during copy; import rejected it and installed no proof
    # - covered tests: test_import_reverifies_the_exact_copied_snapshot
    source = _write_source(tmp_path / "source")
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / "proof",
    )
    real_copytree = shutil.copytree
    mutated = False

    def mutate_then_copy(source_root: Path, destination: Path, *args: object, **kwargs: object):
        nonlocal mutated
        if not mutated and Path(source_root) == exported.root:
            metadata_path = Path(source_root) / "proof.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["schema_version"] = "tampered-after-verify"
            metadata_path.write_text(json.dumps(metadata) + "\n", encoding="utf-8")
            mutated = True
        return real_copytree(source_root, destination, *args, **kwargs)

    monkeypatch.setattr("bencheval.proof_bundle.shutil.copytree", mutate_then_copy)
    with pytest.raises(BenchEvalError, match=r"digest|private_proof|proof"):
        import_private_proof(exported.root, store_root=tmp_path / "store")
