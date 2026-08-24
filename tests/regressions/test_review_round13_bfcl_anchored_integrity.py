"""Round-13 RED regressions: BFCL score/log symlink + post-launch data integrity.

The BFCL run path consumed the official score artifact and wrote stdout/stderr
logs through raw pathnames, and never re-verified the mutable package data the
evaluate phase consumes. These tests pin the fail-closed contract: anchored,
no-follow reads/writes and inode-bound identity re-checks around both phases.

SUBSTITUTE_JUSTIFICATION
- substitute: injected ``process_runner`` callables (subprocess boundary), the
  monkeypatched ``_bfcl_package_root`` + ``catalog_benchmark_identity`` in the
  drift test, and the locate-wrapper interposition in the swap test
- replaces: the real ``bfcl`` CLI subprocess, the installed bfcl_eval package
  location, and the unschedulable locate→read race window
- necessity: the assertions require planted symlink/hardlink/inode-swap states
  and mid-run byte drift that a real harness run cannot deterministically
  produce on demand; all filesystem state is real tmp_path content — the
  injected runner only replaces the subprocess call
- real-option: a dev-box bfcl-eval install with a same-uid mutator racing the
  run; it cannot deterministically manufacture each tamper state
- proof-limit: proves BenchEval-side anchored-write/identity fail-closed
  behavior only, not bfcl execution, scorer correctness, or live readiness
- real-proof: run-20260824-045622-854659-a46ae44d (registered `passed` real
  lifecycle); run-20260824-040631-228703-4756f857 (diagnostic-labeled
  demonstration) ran the same lifecycle over a clean artifact tree earlier;
  the tamper states remain test-only by construction
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

import bencheval.bfcl_native_adapter as adapter
from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import (
    BfclCliResult,
    run_bfcl_instance,
)
from bencheval.exceptions import AdapterFailureError

_MODEL = "gpt-5.2-2025-12-11"
_HARNESS_PIN = "bfcl-eval@2026.3.23"
_BFCL_IDENTITY = "bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b"
_UPSTREAM_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
_SCORE_NAME = "BFCL_v4_simple_python_score.json"
_PERFECT = '{"accuracy": 1.0, "correct_count": 1, "total_count": 1}\n'
_FAILING = (
    '{"accuracy": 0.0, "correct_count": 0, "total_count": 1}\n'
    '{"id": "case-1", "valid": false, "error": ["wrong"]}\n'
)


def _plan():
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_MODEL,
    )
    return plan.model_copy(update={"instances": plan.instances[:1]})


def _option(command: Sequence[str], name: str) -> str:
    return command[list(command).index(name) + 1]


def _score_target(command: Sequence[str]) -> Path:
    score_root = Path(_option(command, "--score-dir"))
    return score_root / _MODEL / "non_live" / _SCORE_NAME


def _run(plan, tmp_path: Path, runner, **kwargs):
    return run_bfcl_instance(
        plan=plan,
        instance_id="simple_python",
        artifacts_dir=tmp_path / "art",
        repo_root=tmp_path,
        process_runner=runner,
        harness_version=_HARNESS_PIN,
        benchmark_identity=_BFCL_IDENTITY,
        **kwargs,
    )


def test_symlinked_score_file_cannot_grant_pass(tmp_path: Path) -> None:
    """A symlink at the exact score name must never be followed to a forgery."""
    plan = _plan()
    outside = tmp_path / "outside-perfect.json"
    outside.write_text(_PERFECT, encoding="utf-8")

    def runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        call = tuple(command)
        if call[1] == "evaluate":
            target = _score_target(call)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(outside)
        return BfclCliResult(0, "", "", 0.1, call)

    outcome = _run(plan, tmp_path, runner)

    assert outcome.primary_pass is False
    assert outcome.failure_class in ("runtime_output_unparseable", "evidence_corrupt")


def test_score_directory_swap_between_phases_fails_closed(tmp_path: Path) -> None:
    """Replacing the pinned score directory mid-run must fail, never be scored."""
    plan = _plan()
    forged_root = tmp_path / "forged-scores"
    forged_target = forged_root / _MODEL / "non_live" / _SCORE_NAME
    forged_target.parent.mkdir(parents=True)
    forged_target.write_text(_PERFECT, encoding="utf-8")

    def runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        call = tuple(command)
        if call[1] == "evaluate":
            score_root = Path(_option(call, "--score-dir"))
            score_root.rename(tmp_path / "real-scores")
            score_root.symlink_to(forged_root)
        return BfclCliResult(0, "", "", 0.1, call)

    with pytest.raises(AdapterFailureError, match="replaced") as excinfo:
        _run(plan, tmp_path, runner)
    assert excinfo.value.failure_label == "evidence_corrupt"


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_planted_log_link_does_not_overwrite_outside_file(
    tmp_path: Path,
    link_kind: str,
) -> None:
    """A planted stdout.log symlink/hardlink must not redirect our bytes."""
    plan = _plan()
    victim = tmp_path / "victim.log"
    victim.write_text("precious\n", encoding="utf-8")
    instance_dir = tmp_path / "art" / "simple_python"
    instance_dir.mkdir(parents=True)
    planted = instance_dir / "stdout.log"
    if link_kind == "symlink":
        planted.symlink_to(victim)
    else:
        os.link(victim, planted)

    def runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        # Generate-phase failure: the adapter writes its logs for the attempt.
        return BfclCliResult(1, "agent-out\n", "", 0.1, tuple(command))

    outcome = _run(plan, tmp_path, runner)

    assert victim.read_text(encoding="utf-8") == "precious\n"
    assert outcome.failure_class == "harness_failure"
    rewritten = instance_dir / "stdout.log"
    assert not rewritten.is_symlink()
    assert rewritten.read_text(encoding="utf-8") == "agent-out\n"


def test_score_file_swapped_between_locate_and_read_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inode swap inside the locate→read window must fail closed."""
    plan = _plan()

    def runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        call = tuple(command)
        if call[1] == "evaluate":
            target = _score_target(call)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_FAILING, encoding="utf-8")
        return BfclCliResult(0, "", "", 0.1, call)

    real_find = adapter._find_official_score_candidates

    def swapped_find(**kwargs):  # type: ignore[no-untyped-def]
        located = real_find(**kwargs)
        # Attacker replaces the just-located artifact with a perfect-score
        # forgery (new inode) before the adapter reads it.
        victim = getattr(located[0], "path", located[0])
        victim.unlink()
        victim.write_text(_PERFECT, encoding="utf-8")
        return located

    monkeypatch.setattr(adapter, "_find_official_score_candidates", swapped_find)

    outcome = _run(plan, tmp_path, runner)

    assert outcome.primary_pass is False
    assert outcome.failure_class in ("runtime_output_unparseable", "evidence_corrupt")


def test_possible_answer_drift_between_phases_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The evaluate phase consumes mutable possible_answer bytes; drift = drift."""
    from bencheval.benchmark_registry import BfclPackageDataIdentity
    from bencheval.identity_strings import bfcl_benchmark_identity, file_sha256

    package_root = tmp_path / "bfcl_eval"
    answer = package_root / "data" / "possible_answer" / "BFCL_v4_simple_python.json"
    answer.parent.mkdir(parents=True)
    answer.write_bytes(b'{"answer": ["original"]}\n')
    identity = BfclPackageDataIdentity(
        kind="bfcl-package-data",
        bfcl_eval_version="2026.3.23",
        upstream_commit=_UPSTREAM_COMMIT,
        files={
            "data/possible_answer/BFCL_v4_simple_python.json": (f"sha256:{file_sha256(answer)}"),
        },
    )
    monkeypatch.setattr(
        "bencheval.identity_strings.catalog_benchmark_identity",
        lambda benchmark_id: identity,
    )
    monkeypatch.setattr(adapter, "_bfcl_package_root", lambda: package_root)

    def runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        call = tuple(command)
        if call[1] == "evaluate":
            # Same-uid mutator rewrites the judge input mid-phase, then the
            # harness writes a perfect score computed from the tampered key.
            answer.write_bytes(b'{"answer": ["tampered"]}\n')
            target = _score_target(call)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_PERFECT, encoding="utf-8")
        return BfclCliResult(0, "", "", 0.1, call)

    plan = _plan()
    with pytest.raises(AdapterFailureError, match=r"(?i)drift") as excinfo:
        run_bfcl_instance(
            plan=plan,
            instance_id="simple_python",
            artifacts_dir=tmp_path / "art",
            repo_root=tmp_path,
            process_runner=runner,
            harness_version=_HARNESS_PIN,
            benchmark_identity=bfcl_benchmark_identity(identity),
        )
    assert excinfo.value.failure_label == "runtime_config_drift"
