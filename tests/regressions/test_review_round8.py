"""Round-8 qa-review regressions (REJECTED finding F113 + parity gaps F112-F117).

Root contract under repair: the invariant guard's allowlist codified the last
raw post-launch write (the codex provider config, F113); the terminal-bench
scoring read of ``result.json`` is unpinned (F112, the F107 sibling); GPQA
lacks the F108-style final re-check before outcome stamping (F115); and the
GPQA fd pair can leak ``artifacts_fd`` when the ``log_fd`` open raises (F117).

SUBSTITUTE_JUSTIFICATION (F113 stub Harbor runner + pre-planted symlink)
- substitute: a boundary ``process_runner`` callable authoring a synthetic
  Harbor ``result.json``, plus a symlink pre-planted at the codex config path
  before ``run_terminal_bench_instance`` (the "second instance" position: a
  prior instance's toolchain code had its chance to plant)
- replaces: the real Harbor CLI subprocess and a surviving same-uid mutator
  planting the link between ``prepare_instance_artifacts_dir`` and the config
  write
- necessity: the assertion targets BenchEval's write-anchoring boundary - a
  pre-planted symlink must never be opened, truncated, or followed; the
  planting must exist at the exact pre-write instant, which a real subprocess
  chain cannot produce deterministically
- real-option: executing two real ``harbor run`` instances against a
  disposable jobs dir - Docker/Harbor dependent and cannot schedule the plant
- proof-limit: proves write anchoring and victim-inode preservation only; does
  not prove Harbor executes or scores
- real-proof: BLOCKED - live terminal-bench lane on dev-box (operator
  provisioning required); all Harbor results remain diagnostic only

SUBSTITUTE_JUSTIFICATION (F112/F115 stub runners + white-box swap hooks)
- substitute: boundary ``process_runner`` callables authoring synthetic
  Harbor/Inspect artifacts, with rename-and-recreate swaps of the instance
  dir / ``inspect-logs`` hooked to the ``write_text_at_exclusive`` instant
  that follows each adapter's post-run identity check
- replaces: the real Harbor/Inspect subprocesses and a same-uid mutator
  swapping directories between the post-run check and the scored read /
  outcome stamping
- necessity: the swaps must occur at exact post-check instants, which real
  harness processes cannot produce deterministically
- real-option: executing the real harnesses against disposable dirs -
  provider/Docker dependent and cannot schedule the swaps on demand
- proof-limit: proves directory-identity fail-closed behavior only; does not
  prove the real harnesses execute or score, and (per the documented honest
  residual) cannot detect in-place rewrites of harness-authored score files
- real-proof: BLOCKED - live terminal-bench/GPQA lanes on dev-box (operator
  provisioning required); all results remain diagnostic only

SUBSTITUTE_JUSTIFICATION (F117 open_owned_dir_fd spy)
- substitute: ``spy_open()`` monkeypatched over
  ``gpqa_adapter.open_owned_dir_fd`` in
  test_gpqa_failed_log_fd_open_does_not_leak_artifacts_fd
- replaces: nothing - it delegates to the real ``open_owned_dir_fd`` and only
  records the returned descriptor; the interception observes the boundary
- necessity: the assertion is about a descriptor's lifetime (artifacts_fd must
  be closed when the log_fd open raises); the fd is a function local that
  never crosses the adapter boundary, so without interception the leak is
  observable only via fd-table exhaustion heuristics - statistical and
  nondeterministic, not an exact assertion
- real-option: drive thousands of real Inspect runs with a planted symlink and
  count open fds - provider/network dependent and nondeterministic
- proof-limit: proves the failure path closes the first descriptor; does not
  prove Inspect executes or scores
- real-proof: BLOCKED - live GPQA lane on dev-box (operator provisioning
  required); all GPQA results remain diagnostic only
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.runtime_registry import load_runtime_catalog
from bencheval.terminal_bench_harbor import harbor_agent_for_runtime


def _legacy_pass_result(runtime_id: str) -> str:
    """Legacy-verdict result.json carrying the agent_info identity the run path requires."""
    pin = load_runtime_catalog().by_id(runtime_id).versioning.agent_version_pin
    return json.dumps(
        {
            "resolved": True,
            "agent_info": {
                "name": harbor_agent_for_runtime(runtime_id),
                "version": pin,
                "model_info": None,
            },
        },
    )


def _gpqa_plan():
    return plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )


def _gpqa_done_payload(*, model: str, samples: int, accuracy: float) -> str:
    return json.dumps(
        {
            "version": 2,
            "status": "success",
            "eval": {
                "created": "2024-01-01T00:00:00+00:00",
                "task": "gpqa_diamond",
                "task_id": "fixture",
                "model": model,
            },
            "results": {
                "total_samples": samples,
                "completed_samples": samples,
                "scores": [
                    {
                        "name": "choice",
                        "scorer": "choice",
                        "metrics": {"accuracy": {"name": "accuracy", "value": accuracy}},
                    },
                ],
            },
        },
    )


def _harbor_plan():
    return plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )


# --- F113: the codex provider config write must never follow planted links ----


def test_codex_provider_config_write_never_follows_a_preplanted_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval.terminal_bench_harbor import HarborCliResult, run_terminal_bench_instance

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    plan = _harbor_plan()
    instance_dir = tmp_path / "a" / "tb-smoke-001"
    instance_dir.mkdir(parents=True)
    victim = tmp_path / "victim.toml"
    victim.write_text("precious\n", encoding="utf-8")
    # A prior instance's toolchain code planted a symlink at the config path;
    # it survives prepare_instance_artifacts_dir (not an authoritative name).
    (instance_dir / ".bencheval-codex-config.toml").symlink_to(victim)

    def runner(command, *, cwd, timeout_sec):
        out_dir = Path(command[command.index("--jobs-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text(_legacy_pass_result("codex-cli"), encoding="utf-8")
        return HarborCliResult(0, "", "", 0.1, tuple(command))

    outcome = run_terminal_bench_instance(
        plan=plan,
        instance_id="tb-smoke-001",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=runner,
        timeout_sec=60,
    )

    assert victim.read_text(encoding="utf-8") == "precious\n"
    config = instance_dir / ".bencheval-codex-config.toml"
    assert config.is_symlink() is False
    assert "model_provider" in config.read_text(encoding="utf-8")
    assert outcome.primary_pass is True


# --- F112: the scored harbor result.json must be read from the pinned inode ---


def test_harbor_result_read_swap_after_post_run_check_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bencheval.terminal_bench_harbor as harbor
    from bencheval.terminal_bench_harbor import HarborCliResult, run_terminal_bench_instance

    plan = _harbor_plan()
    captured: dict[str, Path] = {}

    def runner(command, *, cwd, timeout_sec):
        out_dir = Path(command[command.index("--jobs-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        captured["dir"] = out_dir
        (out_dir / "result.json").write_text('{"resolved": false}', encoding="utf-8")
        return HarborCliResult(0, "", "", 0.1, tuple(command))

    real_write = harbor.write_text_at_exclusive

    def tampering_write(dir_fd, name, text):
        if name == "stderr.log":
            # White-box hook: the post-run identity check already passed; a
            # same-uid mutator swaps the instance dir before the scored read
            # and plants a forged PASS verdict.
            target = captured["dir"]
            target.rename(target.parent / "tb-smoke-001-moved")
            target.mkdir()
            (target / "result.json").write_text('{"resolved": true}', encoding="utf-8")
        return real_write(dir_fd, name, text)

    monkeypatch.setattr(harbor, "write_text_at_exclusive", tampering_write)

    with pytest.raises(AdapterFailureError) as excinfo:
        run_terminal_bench_instance(
            plan=plan,
            instance_id="tb-smoke-001",
            artifacts_dir=tmp_path / "a",
            repo_root=tmp_path,
            process_runner=runner,
            timeout_sec=60,
        )

    assert excinfo.value.failure_label == "evidence_corrupt"


# --- F115: GPQA needs the F108-style final re-check before stamping -----------


def test_gpqa_log_dir_swap_at_summary_write_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bencheval.gpqa_adapter as gpqa_adapter
    from bencheval.gpqa_adapter import GpqaCliResult, run_gpqa_slice

    plan = _gpqa_plan()
    artifacts_dir = tmp_path / "artifacts"
    log_dir = artifacts_dir / "inspect-logs"

    def runner(command, *, cwd, timeout_sec, env=None):
        model = command[command.index("--model") + 1]
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "done.json").write_text(
            _gpqa_done_payload(model=model, samples=len(plan.instances), accuracy=1.0),
            encoding="utf-8",
        )
        return GpqaCliResult(0, f"Log: {log_dir / 'done.json'}\n", "", 0.05, tuple(command))

    real_write = gpqa_adapter.write_text_at_exclusive

    def tampering_write(dir_fd, name, text):
        if name == "gpqa_summary.json":
            # White-box hook: the scored read already happened from the pinned
            # inode; a same-uid mutator swaps inspect-logs before the outcome
            # stamps native-labeled log paths.
            log_dir.rename(artifacts_dir / "inspect-logs-moved")
            log_dir.mkdir()
        return real_write(dir_fd, name, text)

    monkeypatch.setattr(gpqa_adapter, "write_text_at_exclusive", tampering_write)

    with pytest.raises(AdapterFailureError) as excinfo:
        run_gpqa_slice(
            plan=plan,
            artifacts_dir=artifacts_dir,
            repo_root=tmp_path,
            process_runner=runner,
        )

    assert excinfo.value.failure_label == "evidence_corrupt"


# --- F117: a failed log_fd open must not leak artifacts_fd --------------------


def test_gpqa_failed_log_fd_open_does_not_leak_artifacts_fd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bencheval.gpqa_adapter as gpqa_adapter
    from bencheval.gpqa_adapter import run_gpqa_slice

    plan = _gpqa_plan()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    real_log_target = tmp_path / "real-logs"
    real_log_target.mkdir()
    # A pre-planted symlink makes the log_fd open raise BenchEvalError.
    (artifacts_dir / "inspect-logs").symlink_to(real_log_target, target_is_directory=True)

    opened: list[int] = []
    real_open = gpqa_adapter.open_owned_dir_fd

    def spy_open(path, *, role):
        fd = real_open(path, role=role)
        opened.append(fd)
        return fd

    monkeypatch.setattr(gpqa_adapter, "open_owned_dir_fd", spy_open)

    with pytest.raises(BenchEvalError):
        run_gpqa_slice(
            plan=plan,
            artifacts_dir=artifacts_dir,
            repo_root=tmp_path,
            process_runner=None,
        )

    assert opened, "artifacts_fd should have been opened before the failure"
    for fd in opened:
        # A leaked descriptor would still be open here.
        with pytest.raises(OSError):
            os.fstat(fd)
