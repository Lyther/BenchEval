"""Regressions for the actionable automated review on PR #5."""

from __future__ import annotations

import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import _claim_control_plane_outputs
from bencheval.evidence import JsonlEvidenceSink, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.run_isolation import (
    claim_exclusive_evidence_path,
    claim_exclusive_run_outputs,
    release_evidence_reservation,
    reserved_evidence_inode,
    rollback_claimed_run_outputs,
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


def test_failed_output_claim_preserves_preexisting_empty_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    evidence.write_bytes(b"")

    with pytest.raises(BenchEvalError, match="already exists"):
        claim_exclusive_run_outputs(
            evidence_path=evidence,
            artifacts_path=tmp_path / "artifacts",
        )

    assert evidence.is_file()
    assert evidence.read_bytes() == b""
    assert not (tmp_path / "artifacts").exists()


def test_second_output_claim_does_not_release_first_evidence_owner(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    claim_exclusive_evidence_path(evidence)
    first_identity = reserved_evidence_inode(evidence)
    assert first_identity is not None
    try:
        with pytest.raises(BenchEvalError, match="already reserved"):
            claim_exclusive_run_outputs(
                evidence_path=evidence,
                artifacts_path=tmp_path / "second-artifacts",
            )

        assert reserved_evidence_inode(evidence) == first_identity
        assert evidence.is_file()
        record = make_control_plane_evidence_record(instance_id="first-owner")
        JsonlEvidenceSink().append_jsonl(evidence, record)
        assert read_evidence_jsonl(evidence) == [record]
        assert not (tmp_path / "second-artifacts").exists()
    finally:
        release_evidence_reservation(evidence)


def test_rollback_preserves_a_replacement_at_the_claimed_evidence_path(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    artifacts_created = claim_exclusive_run_outputs(
        evidence_path=evidence,
        artifacts_path=artifacts,
    )
    moved_claim = tmp_path / "moved-claim.jsonl"
    evidence.rename(moved_claim)
    evidence.write_bytes(b"")

    rollback_claimed_run_outputs(
        evidence_path=evidence,
        artifacts_path=artifacts,
        artifacts_created=artifacts_created,
        evidence_claimed=True,
    )

    assert evidence.is_file()
    assert evidence.read_bytes() == b""
    assert moved_claim.is_file()
    assert reserved_evidence_inode(evidence) is None
    assert not artifacts.exists()


def test_frozen_plan_write_failure_releases_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SUBSTITUTE_JUSTIFICATION
    # - substitute: monkeypatch of `_persist_frozen_run_plan` (`boom`)
    # - replaces: a real exclusive plan write that fails after evidence reservation
    # - necessity: force persist failure after a successful claim; a real disk
    #   error cannot be produced safely and deterministically on this host
    # - real-option: filling the volume or chmodding the owned tree is unsafe
    #   and races other tests
    # - proof-limit: diagnostic reservation-rollback only; does not prove a
    #   specific filesystem errno
    # - real-proof: BLOCKED: no disposable volume-fault injector in this checkout
    # - covered tests: test_frozen_plan_write_failure_releases_claim
    evidence = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )

    def boom(*_args: object, **_kwargs: object) -> None:
        raise BenchEvalError("plan write failed")

    monkeypatch.setattr(
        "bencheval.control_plane_executor._persist_frozen_run_plan",
        boom,
    )
    with pytest.raises(BenchEvalError, match="plan write failed"):
        _claim_control_plane_outputs(
            output_path=evidence,
            artifacts_dir=artifacts,
            rid="claim-rollback",
            root=tmp_path,
            plan=plan,
        )
    assert not evidence.exists()
    assert not artifacts.exists()

    monkeypatch.undo()
    claimed = _claim_control_plane_outputs(
        output_path=evidence,
        artifacts_dir=artifacts,
        rid="claim-rollback",
        root=tmp_path,
        plan=plan,
    )
    try:
        assert claimed == artifacts
        assert (artifacts / "run-plan.json").is_file()
    finally:
        rollback_claimed_run_outputs(
            evidence_path=evidence,
            artifacts_path=artifacts,
            artifacts_created=True,
            evidence_claimed=True,
        )
