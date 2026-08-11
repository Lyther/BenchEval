"""Round-4 qa-review regressions (REJECTED findings F001-F006).

Root contract under repair: a pathname BenchEval merely *looked at* proves
nothing against a same-uid mutator. Ownership must be bound to file
descriptors, inode identity, or pinned content — never to a path string.

F007 is a documentation correction verified by inspection; N001/N002 ride
along with the F004 sink repair and dependency bounds.

SUBSTITUTE_JUSTIFICATION (F001 tamper fixtures)
- substitute: a boundary `process_runner` callable plus a pre-planted symlink
  at the BenchEval capture path instead of the real agent CLI
- replaces: the real external-agent subprocess (momo) and a surviving child
  process that mutates outputs after BenchEval materializes them
- necessity: the assertions target where BenchEval-owned captures live and
  whether a post-write replacement can forge the returned evidence; a real
  agent process cannot schedule the mutation deterministically
- real-option: executing the real momo CLI against a disposable instance dir -
  cannot produce the post-write replacement window on demand and would perform
  uncontrolled outward effects
- proof-limit: proves capture location and post-write forgery resistance only;
  it does not prove agent execution or scoring
- real-proof: a live admitted external-agent lane (none admitted yet - BLOCKED
  on provisioning) plus inspection of this guard in code review

SUBSTITUTE_JUSTIFICATION (F002/F003 synthetic HLE checkout + injected pin)
- substitute: disposable git repository with two comment-only marker scripts,
  plus a test-authored HleHarnessPin naming that repository's revision and
  content digests
- replaces: the official CAIS HLE checkout and the shipped upstream pin
- necessity: the assertions target pin-verification and execution-binding
  mechanics (commit/content equality, byte-verified copies, drift detection),
  which require controlled revisions and contents a network clone cannot
  deterministically produce; injecting the pin exercises the identical
  verification path the shipped constant takes
- real-option: cloning the real HLE repo - network-dependent, single fixed
  revision, and cannot produce mismatch/tamper states on demand
- proof-limit: proves pin mechanics and copy binding only; does not prove the
  real HLE harness executes or scores, or that the shipped pin matches a live
  checkout
- real-proof: BLOCKED - live HLE lane on dev-box with the official checkout
  (operator provisioning required); all HLE results remain diagnostic only
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import AdapterFailureError, BenchEvalError

_GIT_REQUIRED = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


def _evidence_row(task_id: str = "inst-1"):
    from datetime import UTC, datetime

    from bencheval.evidence import EvidenceRecord

    return EvidenceRecord(
        run_id="round4-contract",
        task_id=task_id,
        model_id="provider/model",
        execution_profile="E0",
        primary_pass=False,
        partial_score=0.0,
        cost_usd=0.0,
        latency_sec=1.0,
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )


def _agent_plan():
    return plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id=None,
        agent_id="momo",
        model_id="kimi-k2.7-code",
    )


# --- F001: BenchEval-owned captures must live outside the agent output root --


def test_captured_logs_live_outside_the_agent_output_root(tmp_path: Path) -> None:
    from bencheval.external_agent_adapter import (
        ExternalAgentCliResult,
        run_external_agent_instance,
    )

    root = tmp_path / "artifacts"

    def _ok(command: object, *, cwd: object, timeout_sec: object) -> object:
        return ExternalAgentCliResult(
            returncode=1,
            stdout="captured-stdout",
            stderr="captured-stderr",
            latency_sec=0.1,
            command=tuple(command),
        )

    outcome = run_external_agent_instance(
        plan=_agent_plan(),
        instance_id="inst-1",
        artifacts_dir=root,
        repo_root=tmp_path,
        process_runner=_ok,
    )

    instance_dir = root / "inst-1"
    assert outcome.stdout_path is not None
    assert outcome.stderr_path is not None
    # The returned evidence binds to a host-owned capture location; nothing
    # BenchEval owns is published inside the agent-writable output root.
    assert Path(outcome.stdout_path).is_relative_to(instance_dir) is False
    assert Path(outcome.stderr_path).is_relative_to(instance_dir) is False
    assert Path(outcome.stdout_path).read_text(encoding="utf-8") == "captured-stdout"
    assert Path(outcome.stderr_path).read_text(encoding="utf-8") == "captured-stderr"
    assert not (instance_dir / "stdout.log").exists()
    assert not (instance_dir / "stderr.log").exists()


def test_post_write_replacement_cannot_forge_returned_log_content(tmp_path: Path) -> None:
    from bencheval.external_agent_adapter import (
        ExternalAgentCliResult,
        run_external_agent_instance,
    )

    root = tmp_path / "artifacts"
    victim = tmp_path / "victim.log"
    victim.write_text("precious\n", encoding="utf-8")
    # The actual capture stdout path for the current layout: a sibling root
    # derived from the artifacts root name, outside the agent-visible tree.
    # Pre-planting a symlink there is the deterministic stand-in for a
    # surviving same-uid child swapping the capture after publication.
    target = root.parent / f"{root.name}.capture" / "inst-1" / "stdout.log"
    target.parent.mkdir(parents=True)
    target.symlink_to(victim)

    def _ok(command: object, *, cwd: object, timeout_sec: object) -> object:
        return ExternalAgentCliResult(
            returncode=1,
            stdout="captured-stdout",
            stderr="captured-stderr",
            latency_sec=0.1,
            command=tuple(command),
        )

    outcome = run_external_agent_instance(
        plan=_agent_plan(),
        instance_id="inst-1",
        artifacts_dir=root,
        repo_root=tmp_path,
        process_runner=_ok,
    )

    # The planted entry was unlinked without being opened or followed: the
    # victim is untouched and the published path holds the captured bytes.
    assert victim.read_text(encoding="utf-8") == "precious\n"
    assert target.is_symlink() is False
    assert outcome.stdout_path is not None
    assert Path(outcome.stdout_path).read_text(encoding="utf-8") == "captured-stdout"


# --- F002: HLE provenance requires a pinned revision + content identity ------


def _git_hle_checkout(home: Path, *, remote: str | None = None) -> str:
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# official script\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# official script\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=home, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=home, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=spec@example.test", "-c", "user.name=spec", "commit", "-m", "i"],
        cwd=home,
        check=True,
        capture_output=True,
    )
    if remote is not None:
        subprocess.run(
            ["git", "remote", "add", "origin", remote],
            cwd=home,
            check=True,
            capture_output=True,
        )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=home,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _synthetic_pin(home: Path, sha: str):
    import hashlib

    from bencheval.hle_adapter import HleHarnessPin

    digests = {}
    for name in ("run_model_predictions.py", "run_judge_results.py"):
        digests[name] = hashlib.sha256((home / "hle_eval" / name).read_bytes()).hexdigest()
    return HleHarnessPin(commit=sha, script_sha256=digests)


@_GIT_REQUIRED
def test_hle_arbitrary_repo_with_a_cais_looking_remote_is_uncaptured(tmp_path: Path) -> None:
    """A self-asserted remote URL is metadata, not source identity."""
    from bencheval.hle_adapter import _hle_harness_version

    home = tmp_path / "forged-checkout"
    _git_hle_checkout(home, remote="https://github.com/centerforaisafety/hle.git")

    assert _hle_harness_version(home) is None


@_GIT_REQUIRED
def test_hle_checkout_matching_the_pin_is_captured(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _hle_harness_version
    from bencheval.provenance_gates import is_captured_harness_version

    home = tmp_path / "pinned-checkout"
    sha = _git_hle_checkout(home)
    pin = _synthetic_pin(home, sha)

    version = _hle_harness_version(home, pin=pin)

    assert version is not None
    assert sha in version
    assert is_captured_harness_version(version)


@_GIT_REQUIRED
def test_hle_checkout_drifting_from_the_pin_is_uncaptured(tmp_path: Path) -> None:
    from bencheval.hle_adapter import HleHarnessPin, _hle_harness_version

    home = tmp_path / "drifted-checkout"
    sha = _git_hle_checkout(home)
    pin = _synthetic_pin(home, sha)

    # Content drift: same commit string, different script bytes.
    (home / "hle_eval" / "run_model_predictions.py").write_text("# tampered\n", encoding="utf-8")
    assert _hle_harness_version(home, pin=pin) is None

    # Revision drift: matching bytes, wrong commit.
    other = HleHarnessPin(commit="0" * 40, script_sha256=pin.script_sha256)
    subprocess.run(["git", "checkout", "."], cwd=home, check=True, capture_output=True)
    assert _hle_harness_version(home, pin=other) is None


@_GIT_REQUIRED
def test_hle_dirty_pinned_checkout_is_rejected_by_the_gate(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _hle_harness_version
    from bencheval.provenance_gates import is_captured_harness_version

    home = tmp_path / "pinned-checkout"
    sha = _git_hle_checkout(home)
    pin = _synthetic_pin(home, sha)
    (home / "notes.txt").write_text("local edits\n", encoding="utf-8")

    version = _hle_harness_version(home, pin=pin)

    assert version is not None
    assert version.endswith("-dirty")
    assert is_captured_harness_version(version) is False


# --- F003: the executed HLE bytes must be the captured bytes ------------------


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


def test_hle_executes_byte_verified_copies_not_the_checkout_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval.hle_adapter import HleCliResult, run_hle_slice

    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    original = (home / "hle_eval" / "run_model_predictions.py").read_bytes()
    executed: dict[str, object] = {}

    def observer(
        command: object, *, cwd: object, timeout_sec: object, env: object = None
    ) -> object:
        script = Path(command[1])
        executed["path"] = script
        executed["bytes"] = script.read_bytes()
        return HleCliResult(1, "", "stop-after-observe", 0.1, tuple(command))

    outcomes = run_hle_slice(
        plan=_hle_plan(),
        artifacts_dir=tmp_path / "artifacts",
        repo_root=tmp_path,
        process_runner=observer,
        run_id="hle-copy-binding",
    )

    script = executed["path"]
    assert isinstance(script, Path)
    # The harness must not execute the mutable checkout pathname.
    assert not script.is_relative_to(home)
    # …but the bytes it executes are exactly the captured ones.
    assert executed["bytes"] == original
    assert outcomes  # failure outcome returned, no crash


def test_hle_copy_tampering_during_the_run_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval.hle_adapter import HleCliResult, run_hle_slice

    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))

    def tamperer(
        command: object, *, cwd: object, timeout_sec: object, env: object = None
    ) -> object:
        # The launched harness (same uid) rewrites the script copy mid-run.
        Path(command[1]).write_text("# pwned\n", encoding="utf-8")
        return HleCliResult(1, "", "boom", 0.1, tuple(command))

    with pytest.raises(AdapterFailureError) as excinfo:
        run_hle_slice(
            plan=_hle_plan(),
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=tamperer,
            run_id="hle-copy-tamper",
        )

    assert excinfo.value.failure_label == "evidence_corrupt"


# --- F004: appends must bind to the reserved inode, not the pathname ---------


def test_reserved_evidence_path_replaced_by_symlink_rejects_append(tmp_path: Path) -> None:
    from bencheval.evidence import JsonlEvidenceSink
    from bencheval.run_isolation import claim_exclusive_evidence_path

    victim = tmp_path / "victim.jsonl"
    victim.write_text("precious\n", encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    claim_exclusive_evidence_path(evidence)
    evidence.unlink()
    evidence.symlink_to(victim)

    row = _evidence_row()
    with pytest.raises(BenchEvalError):
        JsonlEvidenceSink().append_jsonl(evidence, row)

    assert victim.read_text(encoding="utf-8") == "precious\n"


def test_reserved_evidence_path_recreated_by_attacker_rejects_append(tmp_path: Path) -> None:
    from bencheval.evidence import JsonlEvidenceSink
    from bencheval.run_isolation import claim_exclusive_evidence_path

    evidence = tmp_path / "evidence.jsonl"
    claim_exclusive_evidence_path(evidence)
    evidence.unlink()
    evidence.write_text("attacker-controlled\n", encoding="utf-8")

    row = _evidence_row()
    with pytest.raises(BenchEvalError, match="replaced"):
        JsonlEvidenceSink().append_jsonl(evidence, row)

    # The attacker's file received nothing from BenchEval.
    assert evidence.read_text(encoding="utf-8") == "attacker-controlled\n"


def test_reserved_evidence_path_accepts_honest_appends(tmp_path: Path) -> None:
    from bencheval.evidence import JsonlEvidenceSink, read_evidence_jsonl
    from bencheval.run_isolation import claim_exclusive_evidence_path

    # Positive control: an untouched reservation appends both rows.
    evidence = tmp_path / "evidence.jsonl"
    claim_exclusive_evidence_path(evidence)
    sink = JsonlEvidenceSink()
    sink.append_jsonl(evidence, _evidence_row())
    sink.append_jsonl(evidence, _evidence_row("inst-2"))

    assert len(read_evidence_jsonl(evidence)) == 2


def test_unreserved_evidence_path_keeps_standalone_sink_behavior(tmp_path: Path) -> None:
    from bencheval.evidence import JsonlEvidenceSink, read_evidence_jsonl

    # Positive control: no reservation -> legacy standalone append still works.
    evidence = tmp_path / "standalone.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, _evidence_row())

    assert len(read_evidence_jsonl(evidence)) == 1


# --- F005: an artifacts claim must be atomic and exclusive --------------------


def test_artifacts_dir_cannot_be_claimed_twice(tmp_path: Path) -> None:
    from bencheval.run_isolation import claim_exclusive_run_artifacts

    first = tmp_path / "fresh"
    assert claim_exclusive_run_artifacts(first) is True
    with pytest.raises(BenchEvalError):
        claim_exclusive_run_artifacts(first)

    preexisting = tmp_path / "preexisting"
    preexisting.mkdir()
    assert claim_exclusive_run_artifacts(preexisting) is False
    with pytest.raises(BenchEvalError, match=r"claimed|empty"):
        claim_exclusive_run_artifacts(preexisting)


# --- F006: output-path type failures surface as BenchEvalError ----------------


def test_export_run_bundle_rejects_a_regular_file_output_path(tmp_path: Path) -> None:
    from bencheval.evidence import JsonlEvidenceSink
    from bencheval.run_bundle import export_run_bundle

    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, _evidence_row())
    output = tmp_path / "bundle-out"
    output.write_text("i am a regular file\n", encoding="utf-8")

    with pytest.raises(BenchEvalError, match=r"not a directory|output"):
        export_run_bundle(evidence_path=evidence, output_dir=output)


def test_export_run_cli_reports_a_stable_error_for_a_file_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from bencheval.cli import main
    from bencheval.evidence import JsonlEvidenceSink

    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, _evidence_row())
    output = tmp_path / "bundle-out"
    output.write_text("i am a regular file\n", encoding="utf-8")

    rc = main(["export-run", "--evidence", str(evidence), "--output", str(output)])

    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err


def test_preflight_write_failure_surfaces_as_bencheval_error(tmp_path: Path) -> None:
    from bencheval.preflight_report import write_preflight_report

    blocker = tmp_path / "blocker"
    blocker.write_text("regular file\n", encoding="utf-8")

    with pytest.raises(BenchEvalError, match="preflight"):
        write_preflight_report(
            output_path=blocker / "preflight.json",
            benchmark_id="terminal-bench",
            slice_id="smoke-5",
            runtime_id="claude-code",
            model_id="provider/model",
            ok=False,
        )
