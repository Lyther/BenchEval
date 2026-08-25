"""Round-3 qa-review regressions (REJECTED findings F001-F006).

F007-F012 are test-residue, documentation, and dependency-manifest corrections
verified by the existing gates and inspection; the code contracts live here.

SUBSTITUTE_JUSTIFICATION (F001/F002 tamper runners)
- substitute: boundary `process_runner` callables that mutate the instance
  directory (hard link, rename/recreate) instead of launching a process
- replaces: the real external-agent CLI subprocess (momo)
- necessity: the assertions target BenchEval's write-anchoring boundary; the
  mutations must occur at the exact post-launch instant, which a real agent
  process cannot produce deterministically (and launching one is neither safe
  nor deterministic in a test environment)
- real-option: executing the real momo CLI against a disposable instance dir -
  cannot schedule the tamper between launch and log materialization and would
  perform uncontrolled outward effects
- proof-limit: proves only that BenchEval-owned writes stay anchored to the
  approved inode, that external victims are never touched, and that inode
  substitution fails closed; it does not prove agent execution or scoring
- real-proof: a live admitted external-agent lane (none admitted yet - BLOCKED
  on provisioning) plus inspection of this guard in code review

SUBSTITUTE_JUSTIFICATION (F004 synthetic HLE checkout + injected pin)
- substitute: disposable git repository with two comment-only marker scripts
  created by `_git_hle_checkout`, a test-authored HleHarnessPin naming that
  repository's revision and content digests, and tamper `process_runner`s
- replaces: the official CAIS HLE checkout (github.com/centerforaisafety/hle),
  the shipped upstream pin, and the real harness subprocess
- necessity: the assertions target provenance mechanics (pin commit/content
  equality, dirty-state rejection, mid-run source-drift fail-closed), which
  require controlled git states a network clone cannot deterministically
  produce; injecting the pin exercises the identical verification path the
  shipped constant takes, and the runners must stop before executing a
  benchmark or incurring provider cost
- real-option: cloning the real HLE repo - network-dependent, single fixed
  revision, and cannot produce the mismatch/dirty/tamper fault states on
  demand
- proof-limit: proves provenance mechanics only; does not prove the real HLE
  harness executes or scores, or that the shipped pin matches a live checkout
- real-proof: BLOCKED - live HLE lane on dev-box with the official checkout
  (operator provisioning required); all HLE results remain diagnostic only
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import AdapterFailureError

_GIT_REQUIRED = pytest.mark.skipif(shutil.which("git") is None, reason="git required")
_CAIS_HTTPS = "https://github.com/centerforaisafety/hle.git"


def _agent_plan():
    from tests.factories import make_scaffold_agent_plan

    return make_scaffold_agent_plan()


# --- F001: hard-linked log targets must never overwrite external files -------


def test_external_agent_hardlinked_log_target_cannot_overwrite_external_victim(
    tmp_path: Path,
) -> None:
    from bencheval.external_agent_adapter import (
        ExternalAgentCliResult,
        run_external_agent_instance,
    )

    victim = tmp_path / "victim.txt"
    victim.write_text("precious\n", encoding="utf-8")
    root = tmp_path / "artifacts"
    root.mkdir()

    def _hardlinker(command: object, *, cwd: object, timeout_sec: object) -> object:
        # The evaluated agent locates the BenchEval capture tree and replaces
        # both log targets with hard links to an external same-user file
        # before BenchEval materializes its captures.
        capture = root.parent / f"{root.name}.capture" / "inst-1"
        os.link(victim, capture / "stdout.log")
        os.link(victim, capture / "stderr.log")
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
        process_runner=_hardlinker,
    )

    # The victim inode is never opened for writing: unlink-and-recreate only
    # removes the attacker's directory entry.
    assert victim.read_text(encoding="utf-8") == "precious\n"
    capture = root.parent / f"{root.name}.capture" / "inst-1"
    assert (capture / "stdout.log").read_text(encoding="utf-8") == "captured-stdout"
    assert (capture / "stderr.log").read_text(encoding="utf-8") == "captured-stderr"
    assert outcome.stdout_path == str((capture / "stdout.log").resolve())
    # Nothing BenchEval-owned is published inside the agent-writable root.
    assert not (root / "inst-1" / "stdout.log").exists()


def test_external_agent_failure_log_hardlink_cannot_overwrite_external_victim(
    tmp_path: Path,
) -> None:
    from bencheval.external_agent_adapter import execute_external_agent_run

    victim = tmp_path / "victim.txt"
    victim.write_text("precious\n", encoding="utf-8")
    plan = _agent_plan().model_copy(update={"instances": _agent_plan().instances[:1]})

    def _hardlink_then_fail(command: object, *, cwd: object, timeout_sec: object) -> object:
        capture = tmp_path / "artifacts.capture" / plan.instances[0].instance_id
        os.link(victim, capture / "adapter_failure.json")
        raise AdapterFailureError(
            "agent exploded",
            failure_label="runtime_tool_failure",
            latency_sec=0.1,
            adapter_metadata={},
        )

    execute_external_agent_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=tmp_path / "artifacts",
        process_runner=_hardlink_then_fail,
    )

    capture_dir = tmp_path / "artifacts.capture" / plan.instances[0].instance_id
    assert victim.read_text(encoding="utf-8") == "precious\n"
    failure_log = (capture_dir / "adapter_failure.json").read_text(encoding="utf-8")
    assert "agent exploded" in failure_log


# --- F002: rename-and-recreate substitution must fail closed -----------------


def test_external_agent_rename_recreate_swap_fails_closed(tmp_path: Path) -> None:
    from bencheval.external_agent_adapter import (
        ExternalAgentCliResult,
        run_external_agent_instance,
    )

    root = tmp_path / "artifacts"
    root.mkdir()

    def _renamer(command: object, *, cwd: object, timeout_sec: object) -> object:
        target = root / "inst-1"
        target.rename(root / "inst-1-moved")
        target.mkdir()
        (target / "stdout.log").write_text("agent-forged", encoding="utf-8")
        (target / "stderr.log").write_text("agent-forged", encoding="utf-8")
        return ExternalAgentCliResult(
            returncode=0,
            stdout="bencheval-captured",
            stderr="bencheval-captured-err",
            latency_sec=0.1,
            command=tuple(command),
        )

    with pytest.raises(AdapterFailureError) as excinfo:
        run_external_agent_instance(
            plan=_agent_plan(),
            instance_id="inst-1",
            artifacts_dir=root,
            repo_root=tmp_path,
            process_runner=_renamer,
        )

    assert excinfo.value.failure_label == "evidence_corrupt"
    # Captured bytes live in the BenchEval-owned capture tree, never in the
    # agent-writable instance directory — renamed or recreated. The forged
    # replacement directory at the approved path was never adopted as evidence.
    capture = root.parent / f"{root.name}.capture" / "inst-1"
    assert (capture / "stdout.log").read_text(encoding="utf-8") == "bencheval-captured"
    assert (capture / "stderr.log").read_text(encoding="utf-8") == "bencheval-captured-err"
    assert (root / "inst-1" / "stdout.log").read_text(encoding="utf-8") == "agent-forged"
    assert not (root / "inst-1-moved" / "stdout.log").exists()


# --- F003: public redaction must not leak credential fragments ---------------


def test_redaction_strips_multi_at_uri_userinfo_to_the_last_delimiter() -> None:
    from bencheval.redaction import redact_string

    out = redact_string("https://alice@corp:p4ssw0rd@example.test/v1")

    assert "p4ssw0rd" not in out
    assert "alice" not in out
    assert out == "https://example.test/v1"


def test_redaction_strips_percent_encoded_uri_userinfo() -> None:
    from bencheval.redaction import redact_string

    out = redact_string("https://user%40name:p%40ss@host.example/")

    assert "p%40ss" not in out
    assert out == "https://host.example/"


def test_redaction_keeps_ordinary_uris_and_emails_intact() -> None:
    from bencheval.redaction import redact_string

    # Positive control: no userinfo, no redaction.
    assert redact_string("https://example.test/v1") == "https://example.test/v1"
    assert redact_string("contact alice@corp.example") == "contact alice@corp.example"
    # A benign "@" in the query is not userinfo and must survive.
    assert redact_string("https://host.example?q=a@b") == "https://host.example?q=a@b"


def test_redaction_scrubs_overlapping_env_secrets_longest_first() -> None:
    from bencheval.redaction import redact_string

    out = redact_string(
        "credential value abcdefghXYZ123",
        extra_secrets=("abcdefgh", "abcdefghXYZ123"),
    )

    assert out == "credential value [redacted]"
    assert "XYZ123" not in out


def test_redaction_secret_scrub_tolerates_duplicates_and_unicode() -> None:
    from bencheval.redaction import redact_string

    # Positive controls: duplicate and non-ASCII secrets still scrub.
    assert (
        redact_string("v abcdefghXYZ123", extra_secrets=("abcdefghXYZ123",) * 2) == "v [redacted]"
    )
    assert redact_string("v tøken-value-123", extra_secrets=("tøken-value-123",)) == "v [redacted]"


# --- F004: HLE provenance must name the official source that actually ran -----


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
def test_hle_checkout_without_any_remote_is_uncaptured(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _hle_harness_version

    home = tmp_path / "hle-checkout"
    _git_hle_checkout(home)

    assert _hle_harness_version(home) is None


@_GIT_REQUIRED
def test_hle_checkout_with_a_non_cais_remote_is_uncaptured(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _hle_harness_version

    home = tmp_path / "not-cais"
    _git_hle_checkout(home, remote="https://github.com/example/not-hle.git")

    assert _hle_harness_version(home) is None


@_GIT_REQUIRED
def test_hle_checkout_matching_a_pin_is_captured(tmp_path: Path) -> None:
    # The CAIS-looking remote is present but irrelevant: capture is decided by
    # the pin's commit and content digests, never by self-asserted git metadata.
    from bencheval.hle_adapter import _hle_harness_version
    from bencheval.provenance_gates import is_captured_harness_version

    home = tmp_path / "hle-checkout"
    sha = _git_hle_checkout(home, remote=_CAIS_HTTPS)
    pin = _synthetic_pin(home, sha)

    version = _hle_harness_version(home, pin=pin)

    assert version is not None
    assert version.startswith(f"hle@{sha}+scripts-")
    assert is_captured_harness_version(version)


@_GIT_REQUIRED
def test_hle_drift_from_the_pin_breaks_capture(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _hle_harness_version
    from bencheval.provenance_gates import (
        is_captured_harness_version,
        is_uncaptured_harness_version,
    )

    home = tmp_path / "hle-checkout"
    sha = _git_hle_checkout(home, remote=_CAIS_HTTPS)
    pin = _synthetic_pin(home, sha)
    clean = _hle_harness_version(home, pin=pin)
    assert clean is not None and is_captured_harness_version(clean)

    # Untracked local edits stamp the captured identity as mutable; the gate
    # rejects it.
    (home / "notes.txt").write_text("local edits\n", encoding="utf-8")
    dirty = _hle_harness_version(home, pin=pin)
    assert dirty is not None and dirty.endswith("-dirty")
    assert is_captured_harness_version(dirty) is False
    assert is_uncaptured_harness_version(dirty) is True

    # Drift in an executed script yields no identity at all — fail closed.
    (home / "hle_eval" / "run_model_predictions.py").write_text("# tampered\n", encoding="utf-8")
    assert _hle_harness_version(home, pin=pin) is None


@_GIT_REQUIRED
def test_hle_checkout_tampering_during_the_run_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval.hle_adapter import HleCliResult, _hle_harness_version, run_hle_slice

    home = tmp_path / "hle-checkout"
    sha = _git_hle_checkout(home, remote=_CAIS_HTTPS)
    pin = _synthetic_pin(home, sha)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    pre_run_identity = _hle_harness_version(home, pin=pin)
    assert pre_run_identity is not None

    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )

    def _dirtying_runner(
        command: object,
        *,
        cwd: object,
        timeout_sec: object,
        env: object = None,
    ) -> object:
        # The harness process mutates the checkout after launch; the post-run
        # source-identity re-check must catch the drift and fail closed.
        (home / "hle_eval" / "run_model_predictions.py").write_text(
            "# tampered mid-run\n",
            encoding="utf-8",
        )
        return HleCliResult(1, "", "boom", 0.1, tuple(command))

    with pytest.raises(AdapterFailureError) as excinfo:
        run_hle_slice(
            plan=plan,
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=_dirtying_runner,
            run_id="hle-provenance-order",
            harness_pin=pin,
        )

    assert excinfo.value.failure_label == "evidence_corrupt"


# --- F006: schema "0.3" RunPlan payloads predate the per-instance field ------


def test_runplan_payload_without_per_instance_wall_derives_from_run_total() -> None:
    from bencheval.domain import RunPlan

    base = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    legacy_payload = base.model_dump(mode="python")
    del legacy_payload["max_wall_clock_sec_per_instance"]

    restored = RunPlan(**legacy_payload)

    # Pre-field contract: one attempt could consume the whole run envelope.
    assert restored.max_wall_clock_sec_per_instance == base.max_wall_clock_sec


def test_runplan_explicit_per_instance_wall_is_preserved() -> None:
    from bencheval.domain import RunPlan

    base = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )

    restored = RunPlan(**base.model_dump(mode="python"))

    assert restored.max_wall_clock_sec_per_instance == base.max_wall_clock_sec_per_instance
