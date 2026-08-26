"""Round-5 qa-review regressions (REJECTED findings F001-F003 + nit N001).

Root contract under repair: an unchecked pathname write follows pre-planted
symlinks and hard links. BenchEval-owned writes must be anchored to directory
file descriptors using no-follow, exclusive-create primitives — a planted
directory entry is unlinked, never opened or truncated — and the capture tree
must live outside the agent-visible artifacts root (a hidden sibling is not a
capability boundary).

SUBSTITUTE_JUSTIFICATION (F001/F002 pre-planted link targets + stub runners)
- substitute: disposable script pairs and victim files with pre-planted
  symlink/hard-link directory entries, plus boundary `process_runner`
  callables authoring predictions/judged artifacts instead of real subprocesses
- replaces: the official CAIS HLE checkout + real harness subprocess (F001 and
  the F002 normal path) and the adapter attempt behind
  `_record_instance_failure` (F002 failure path)
- necessity: the assertions target BenchEval's write-anchoring boundary - a
  pre-planted symlink/hard link must never be opened, truncated, or followed;
  the planting must occur at the exact pre-write instant, which a real harness
  process cannot produce deterministically (and launching one is neither safe
  nor deterministic in a test environment)
- real-option: executing the real HLE harness against a disposable checkout -
  network/checkout dependent and cannot schedule the link planting on demand
- proof-limit: proves write anchoring and victim-inode preservation only; does
  not prove the real HLE harness executes or scores
- real-proof: BLOCKED - live HLE lane on dev-box with the official checkout
  (operator provisioning required); all HLE results remain diagnostic only

SUBSTITUTE_JUSTIFICATION (F003 stub agent runner + tampering write wrapper)
- substitute: boundary `process_runner` callables returning canned
  ExternalAgentCliResult, and a monkeypatched `write_text_at_exclusive`
  wrapper that performs the real dirfd-anchored write and then a
  dirfd-anchored forged replacement (fault injection; the write under test
  stays real)
- replaces: the real external-agent subprocess (momo) and a surviving
  same-uid child that mutates captured logs after BenchEval materializes them
- necessity: the assertions target where BenchEval-owned captures live and
  whether a post-write replacement is detected; a real agent process cannot
  schedule the mutation deterministically between write and read-back
- real-option: executing the real momo CLI against a disposable instance dir -
  cannot produce the post-write replacement window on demand and would perform
  uncontrolled outward effects
- proof-limit: proves capture location, victim preservation, and post-write
  forgery detection only; it does not prove agent execution or scoring
- real-proof: a live admitted external-agent lane (none admitted yet - BLOCKED
  on provisioning) plus inspection of this guard in code review
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import AdapterFailureError


def _agent_plan():
    from tests.factories import make_scaffold_agent_plan

    return make_scaffold_agent_plan()


def _hle_plan():
    return plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )


def _plain_hle_home(tmp_path: Path) -> Path:
    home = tmp_path / "hle-home"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# official predict\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# official judge\n", encoding="utf-8")
    return home


# --- F001: HLE script copies must never follow pre-planted links --------------


def _script_sources(tmp_path: Path) -> tuple[Path, Path]:
    src_dir = tmp_path / "hle_eval"
    src_dir.mkdir()
    predict = src_dir / "run_model_predictions.py"
    judge = src_dir / "run_judge_results.py"
    predict.write_text("# official predict\n", encoding="utf-8")
    judge.write_text("# official judge\n", encoding="utf-8")
    return predict, judge


def test_hle_script_copy_preplanted_symlink_cannot_overwrite_victim(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _materialize_hle_script_copies

    predict, judge = _script_sources(tmp_path)
    victim = tmp_path / "victim.py"
    victim.write_text("precious\n", encoding="utf-8")
    copy_dir = tmp_path / "hle-src"
    copy_dir.mkdir()
    (copy_dir / predict.name).symlink_to(victim)

    copies, expected = _materialize_hle_script_copies((predict, judge), copy_dir)

    assert victim.read_text(encoding="utf-8") == "precious\n"
    for copy, source in zip(copies, (predict, judge), strict=True):
        assert copy.is_symlink() is False
        assert copy.read_bytes() == source.read_bytes()
        assert expected[copy.name] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_hle_script_copy_preplanted_hardlink_cannot_overwrite_victim(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _materialize_hle_script_copies

    predict, judge = _script_sources(tmp_path)
    victim = tmp_path / "victim.py"
    victim.write_text("precious\n", encoding="utf-8")
    copy_dir = tmp_path / "hle-src"
    copy_dir.mkdir()
    os.link(victim, copy_dir / judge.name)

    copies, _expected = _materialize_hle_script_copies((predict, judge), copy_dir)

    # Unlink-and-recreate removes only the attacker's directory entry; the
    # hard-linked victim inode is never opened or truncated.
    assert victim.read_text(encoding="utf-8") == "precious\n"
    for copy, source in zip(copies, (predict, judge), strict=True):
        assert copy.read_bytes() == source.read_bytes()
        assert os.stat(copy).st_ino != os.stat(victim).st_ino


# --- F002: run logs and failure logs must never follow pre-planted links ------


def test_hle_run_log_write_never_follows_a_preplanted_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval.hle_adapter import HleCliResult, hle_run_paths, run_hle_slice

    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    plan = _hle_plan()
    artifacts_dir = tmp_path / "artifacts"
    victim = tmp_path / "victim.log"
    victim.write_text("precious\n", encoding="utf-8")
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id="hle-r5-symlink",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    calls: list[str] = []

    def planter(
        command: object,
        *,
        cwd: object,
        timeout_sec: object,
        env: object = None,
    ) -> object:
        calls.append("call")
        if len(calls) == 1:
            # The launched harness (cwd inside the artifacts tree) plants a
            # symlink at the BenchEval log target before returning success.
            (artifacts_dir / "stdout.log").symlink_to(victim)
            paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
        else:
            judged = {
                f"row-{index}": {"judge_response": {"correct": "yes"}}
                for index in range(len(plan.instances))
            }
            paths.judged_path.write_text(json.dumps(judged), encoding="utf-8")
        return HleCliResult(0, "harness-stdout", "", 0.1, tuple(command))

    outcomes = run_hle_slice(
        plan=plan,
        artifacts_dir=artifacts_dir,
        repo_root=tmp_path,
        process_runner=planter,
        run_id="hle-r5-symlink",
    )

    assert victim.read_text(encoding="utf-8") == "precious\n"
    planted = artifacts_dir / "stdout.log"
    assert planted.is_symlink() is False
    assert planted.read_text(encoding="utf-8") == "harness-stdout\nharness-stdout"
    assert outcomes
    assert outcomes[0].primary_pass is True
    assert outcomes[0].failure_class is None


def test_control_plane_failure_log_never_follows_a_preplanted_symlink(tmp_path: Path) -> None:
    from bencheval.control_plane_executor import _record_instance_failure

    victim = tmp_path / "victim.json"
    victim.write_text("precious\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts" / "inst-1"
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "adapter_failure.json").symlink_to(victim)
    error = AdapterFailureError(
        "agent exploded",
        failure_label="runtime_tool_failure",
        latency_sec=0.1,
        adapter_metadata={},
    )

    record = _record_instance_failure(
        plan=_agent_plan(),
        run_id="r5-failure-log",
        instance_id="inst-1",
        execution_profile="E1",
        error=error,
        artifacts_dir=artifacts_dir,
    )

    assert victim.read_text(encoding="utf-8") == "precious\n"
    planted = artifacts_dir / "adapter_failure.json"
    assert planted.is_symlink() is False
    payload = json.loads(planted.read_text(encoding="utf-8"))
    assert payload["message"] == "agent exploded"
    assert payload["failure_label"] == "runtime_tool_failure"
    assert record.task_id == "inst-1"


# --- F003: the capture tree must live outside the agent-visible root ----------


def _ok_runner(command: object, *, cwd: object, timeout_sec: object) -> object:
    from bencheval.external_agent_adapter import ExternalAgentCliResult

    return ExternalAgentCliResult(
        returncode=1,
        stdout="captured-stdout",
        stderr="captured-stderr",
        latency_sec=0.1,
        command=tuple(command),
    )


def test_capture_root_lives_outside_the_agent_visible_artifacts_tree(tmp_path: Path) -> None:
    from bencheval.external_agent_adapter import run_external_agent_instance

    root = tmp_path / "artifacts"
    outcome = run_external_agent_instance(
        plan=_agent_plan(),
        instance_id="inst-1",
        artifacts_dir=root,
        repo_root=tmp_path,
        process_runner=_ok_runner,
    )

    resolved_root = root.resolve()
    capture_root = resolved_root.parent / f"{resolved_root.name}.capture"
    assert outcome.stdout_path is not None
    assert outcome.stderr_path is not None
    stdout_path = Path(outcome.stdout_path)
    stderr_path = Path(outcome.stderr_path)
    # The agent is handed only <root>/<instance_id>; nothing BenchEval owns may
    # be published inside that agent-visible tree — not even in a hidden child.
    assert stdout_path.is_relative_to(capture_root)
    assert stderr_path.is_relative_to(capture_root)
    assert stdout_path.is_relative_to(resolved_root) is False
    assert stderr_path.is_relative_to(resolved_root) is False
    # Recorded digests of the verified captured bytes let downstream consumers
    # detect post-publication tampering by a same-uid mutator.
    expected_stdout = hashlib.sha256(b"captured-stdout").hexdigest()
    expected_stderr = hashlib.sha256(b"captured-stderr").hexdigest()
    assert outcome.adapter_metadata["stdout_sha256"] == expected_stdout
    assert outcome.adapter_metadata["stderr_sha256"] == expected_stderr


def test_preplanted_symlink_at_the_capture_path_cannot_overwrite_a_victim(
    tmp_path: Path,
) -> None:
    from bencheval.external_agent_adapter import run_external_agent_instance

    root = tmp_path / "artifacts"
    victim = tmp_path / "victim.log"
    victim.write_text("precious\n", encoding="utf-8")
    capture_dir = root.parent / f"{root.name}.capture" / "inst-1"
    capture_dir.mkdir(parents=True)
    (capture_dir / "stdout.log").symlink_to(victim)

    outcome = run_external_agent_instance(
        plan=_agent_plan(),
        instance_id="inst-1",
        artifacts_dir=root,
        repo_root=tmp_path,
        process_runner=_ok_runner,
    )

    assert victim.read_text(encoding="utf-8") == "precious\n"
    planted = capture_dir / "stdout.log"
    assert planted.is_symlink() is False
    assert planted.read_text(encoding="utf-8") == "captured-stdout"
    assert outcome.stdout_path == str(planted.resolve())


def test_post_write_capture_replacement_fails_closed_as_evidence_corrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval import external_agent_adapter
    from bencheval.run_isolation import write_text_at_exclusive

    root = tmp_path / "artifacts"
    fired = False
    real_write = write_text_at_exclusive

    def tampering_write(dir_fd: int, name: str, text: str) -> None:
        nonlocal fired
        real_write(dir_fd, name, text)
        if name != "stdout.log":
            return
        fired = True
        # A surviving same-uid child: atomically replace the captured log with
        # forged content immediately after BenchEval's real dirfd-anchored write.
        os.unlink(name, dir_fd=dir_fd)
        forged_fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o644,
            dir_fd=dir_fd,
        )
        with os.fdopen(forged_fd, "w", encoding="utf-8") as handle:
            handle.write("agent-forged")

    monkeypatch.setattr(external_agent_adapter, "write_text_at_exclusive", tampering_write)

    with pytest.raises(AdapterFailureError) as excinfo:
        external_agent_adapter.run_external_agent_instance(
            plan=_agent_plan(),
            instance_id="inst-1",
            artifacts_dir=root,
            repo_root=tmp_path,
            process_runner=_ok_runner,
        )

    assert fired is True
    assert excinfo.value.failure_label == "evidence_corrupt"


# --- N001: evidence reservations need an explicit release lifecycle -----------


def test_release_evidence_reservation_clears_the_registry(tmp_path: Path) -> None:
    from bencheval.run_isolation import (
        claim_exclusive_evidence_path,
        release_evidence_reservation,
        reserved_evidence_inode,
    )

    evidence = tmp_path / "evidence.jsonl"
    claim_exclusive_evidence_path(evidence)
    assert reserved_evidence_inode(evidence) is not None

    release_evidence_reservation(evidence)

    assert reserved_evidence_inode(evidence) is None
