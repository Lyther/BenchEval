"""Regressions for the actionable automated review on PR #5."""

from __future__ import annotations

import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from bencheval.evidence import JsonlEvidenceSink, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.run_isolation import (
    claim_exclusive_evidence_path,
    claim_exclusive_run_outputs,
)
from tests.factories import make_control_plane_evidence_record


def test_terminal_bench_scored_failure_reaches_lane_qualification() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "run-live-pilot-matrix.sh"
    content = script.read_text(encoding="utf-8")
    run_tb = content.split("run_tb() {", maxsplit=1)[1].split(
        "\nprintf 'Pilot matrix",
        maxsplit=1,
    )[0]
    nonzero_status_block = run_tb.split(
        "if [[ ${run_status} -ne 0 ]]; then",
        maxsplit=1,
    )[1].split("if ! require_qualified_lane", maxsplit=1)[0]

    assert "checking evidence completeness" in nonzero_status_block
    assert "FAILED=" not in nonzero_status_block
    assert "return 1" not in nonzero_status_block


def test_evidence_path_claim_is_atomic_and_remains_appendable(tmp_path: Path) -> None:
    evidence = tmp_path / "run" / "evidence.jsonl"
    start = Barrier(2)

    def attempt_claim() -> str:
        start.wait()
        try:
            claim_exclusive_evidence_path(evidence)
        except BenchEvalError:
            return "rejected"
        return "claimed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: attempt_claim(), range(2)))

    assert sorted(outcomes) == ["claimed", "rejected"]
    assert evidence.is_file()
    assert stat.S_IMODE(evidence.stat().st_mode) & 0o077 == 0

    record = make_control_plane_evidence_record(instance_id="atomic-claim")
    JsonlEvidenceSink().append_jsonl(evidence, record)
    assert read_evidence_jsonl(evidence) == [record]


def test_run_output_claim_rolls_back_only_new_empty_artifact_tree(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    evidence.write_text("owned\n", encoding="utf-8")
    new_artifacts = tmp_path / "new-artifacts"

    try:
        claim_exclusive_run_outputs(
            evidence_path=evidence,
            artifacts_path=new_artifacts,
        )
    except BenchEvalError:
        pass
    else:
        raise AssertionError("an existing evidence path must reject a second run")

    assert evidence.read_text(encoding="utf-8") == "owned\n"
    assert not new_artifacts.exists()

    occupied_artifacts = tmp_path / "occupied-artifacts"
    occupied_artifacts.mkdir()
    (occupied_artifacts / "owner").write_text("other run\n", encoding="utf-8")
    missing_evidence = tmp_path / "missing.jsonl"

    try:
        claim_exclusive_run_outputs(
            evidence_path=missing_evidence,
            artifacts_path=occupied_artifacts,
        )
    except BenchEvalError:
        pass
    else:
        raise AssertionError("a nonempty artifacts path must reject a second run")

    assert not missing_evidence.exists()
    assert (occupied_artifacts / "owner").read_text(encoding="utf-8") == "other run\n"
