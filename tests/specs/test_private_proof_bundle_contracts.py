"""RED contracts for the existing private export's portable-proof boundary.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed ``EvidenceRecord`` rows and disposable raw artifact
  trees in every test here
- replaces: private evidence and raw output from a charged native benchmark run
- necessity: missing and outside-root references must be forced without
  deleting or disclosing operator proof; export, hashing, copying, and archive
  creation still use the real production implementation and real filesystem
- real-option: an operator proof cannot safely be mutated into the required
  negative states and a charged rerun cannot guarantee them
- proof-limit: diagnostic path-completeness behavior only; it does not prove
  creator authenticity, benchmark execution, or cross-host durability
- real-proof: operator-host Terminal-Bench Codex
  ``run-20260825-171829-685914-aa08dd1d`` proof
  ``sha256:fca2295d6844e4dda99799527561985885a90b59e01c865082510eaa63d90c06``
  and GPQA ``run-20260825-160511-036214-304c2cee`` proof
  ``sha256:aa19d02b7d1457d0f43d9588b3d08c042e967a981ed8537068412e1797ff0eda``
  remain externally retained on the operator host, not in this checkout
- covered tests: every test in this module
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.run_bundle import export_run_bundle


def _evidence(path: Path, artifact: str) -> None:
    JsonlEvidenceSink().append_jsonl(
        path,
        EvidenceRecord(
            run_id="run-private-proof-contract",
            task_id="terminal-bench/fix-git",
            model_id="gpt-5.2-2025-12-11",
            execution_profile="E2",
            backend="harbor",
            primary_pass=False,
            partial_score=0.0,
            cost_usd=0.0,
            latency_sec=1.0,
            artifact_paths=[artifact],
            created_at=datetime(2026, 8, 25, tzinfo=UTC),
        ),
    )


def test_relative_raw_reference_is_rewritten_to_an_existing_bundle_file(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    source = raw / "task" / "official.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"resolved": false}\n', encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    _evidence(evidence, "task/official.json")
    bundle = tmp_path / "bundle"

    export_run_bundle(evidence_path=evidence, output_dir=bundle, raw_dir=raw)

    retained = read_evidence_jsonl(bundle / "evidence.jsonl")[0].artifact_paths
    assert len(retained) == 1
    reference = Path(retained[0])
    assert not reference.is_absolute()
    assert (bundle / reference).is_file()
    assert (bundle / reference).read_bytes() == source.read_bytes()


def test_private_export_rejects_a_missing_referenced_artifact(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    evidence = tmp_path / "evidence.jsonl"
    _evidence(evidence, "task/missing.json")

    with pytest.raises(BenchEvalError, match=r"missing|referenced|artifact"):
        export_run_bundle(
            evidence_path=evidence,
            output_dir=tmp_path / "bundle",
            raw_dir=raw,
        )


def test_private_export_rejects_an_absolute_outside_root_reference(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"forged": true}\n', encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    _evidence(evidence, str(outside.resolve()))

    with pytest.raises(BenchEvalError, match=r"outside|root|artifact"):
        export_run_bundle(
            evidence_path=evidence,
            output_dir=tmp_path / "bundle",
            raw_dir=raw,
        )


def test_absolute_in_root_reference_remains_portable(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    source = raw / "task" / "official.json"
    source.parent.mkdir(parents=True)
    source.write_text('{"resolved": false}\n', encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    _evidence(evidence, str(source.resolve()))
    bundle = tmp_path / "bundle"

    export_run_bundle(evidence_path=evidence, output_dir=bundle, raw_dir=raw)

    reference = Path(read_evidence_jsonl(bundle / "evidence.jsonl")[0].artifact_paths[0])
    assert not reference.is_absolute()
    assert (bundle / reference).read_bytes() == source.read_bytes()
