"""Regression coverage for PR #6 external-agent capture bundle portability."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

from bencheval.evidence import JsonlEvidenceSink
from bencheval.run_bundle import export_run_bundle
from tests.factories import make_control_plane_evidence_record


def test_private_bundle_copies_agent_capture_tree_and_rewrites_paths(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "run-1"
    raw.mkdir(parents=True)
    (raw / "agent-output.txt").write_text("agent artifact\n", encoding="utf-8")

    capture = raw.parent / f"{raw.name}.capture" / "instance-1"
    capture.mkdir(parents=True)
    stdout = capture / "stdout.log"
    stderr = capture / "stderr.log"
    stdout.write_text("captured stdout\n", encoding="utf-8")
    stderr.write_text("captured stderr\n", encoding="utf-8")

    evidence = tmp_path / "evidence.jsonl"
    record = make_control_plane_evidence_record(instance_id="instance-1").model_copy(
        update={"artifact_paths": [str(stdout.resolve()), str(stderr.resolve())]},
    )
    JsonlEvidenceSink().append_jsonl(evidence, record)

    bundle = tmp_path / "bundle"
    archive = export_run_bundle(
        evidence_path=evidence,
        output_dir=bundle,
        raw_dir=raw,
        redaction="private",
    )

    bundled_stdout = bundle / "capture" / "instance-1" / "stdout.log"
    bundled_stderr = bundle / "capture" / "instance-1" / "stderr.log"
    assert bundled_stdout.read_text(encoding="utf-8") == "captured stdout\n"
    assert bundled_stderr.read_text(encoding="utf-8") == "captured stderr\n"

    bundled_record = json.loads((bundle / "evidence.jsonl").read_text(encoding="utf-8"))
    assert bundled_record["artifact_paths"] == [
        "capture/instance-1/stdout.log",
        "capture/instance-1/stderr.log",
    ]
    assert all(not Path(path).is_absolute() for path in bundled_record["artifact_paths"])

    with tarfile.open(archive, "r:gz") as handle:
        names = set(handle.getnames())
    assert "bundle/capture/instance-1/stdout.log" in names
    assert "bundle/capture/instance-1/stderr.log" in names


def test_public_bundle_omits_agent_capture_tree_and_paths(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "run-1"
    raw.mkdir(parents=True)
    capture = raw.parent / f"{raw.name}.capture" / "instance-1"
    capture.mkdir(parents=True)
    stdout = capture / "stdout.log"
    stdout.write_text("private output\n", encoding="utf-8")

    evidence = tmp_path / "evidence.jsonl"
    record = make_control_plane_evidence_record(instance_id="instance-1").model_copy(
        update={"artifact_paths": [str(stdout.resolve())]},
    )
    JsonlEvidenceSink().append_jsonl(evidence, record)

    bundle = tmp_path / "public-bundle"
    export_run_bundle(
        evidence_path=evidence,
        output_dir=bundle,
        raw_dir=raw,
        redaction="public",
    )

    bundled_record = json.loads((bundle / "evidence.jsonl").read_text(encoding="utf-8"))
    assert bundled_record["artifact_paths"] == []
    assert not (bundle / "capture").exists()
    assert "private output" not in (bundle / "evidence.jsonl").read_text(encoding="utf-8")


def test_private_bundle_does_not_copy_an_unreferenced_capture_sibling(tmp_path: Path) -> None:
    raw = tmp_path / "raw" / "run-1"
    raw.mkdir(parents=True)
    unrelated_capture = raw.parent / f"{raw.name}.capture"
    unrelated_capture.mkdir()
    (unrelated_capture / "unrelated.txt").write_text("not part of this run\n", encoding="utf-8")

    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(
        evidence,
        make_control_plane_evidence_record(instance_id="instance-1"),
    )

    bundle = tmp_path / "private-bundle"
    export_run_bundle(
        evidence_path=evidence,
        output_dir=bundle,
        raw_dir=raw,
        redaction="private",
    )

    assert not (bundle / "capture").exists()
