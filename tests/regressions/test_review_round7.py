"""Round-7 qa-review regressions (REJECTED findings F107-F110 + nit F111).

Root contract under repair: terminal-bench Harbor has the exact
unchecked-post-launch-write class fixed for GPQA/HLE in rounds 5-6 (F110); the
GPQA scoring read of the Inspect done-log runs under a never-pinned
``inspect-logs`` inode (F107, the F102 sibling); the HLE stamped verifier path
is resolved across a post-check window (F108); and two raw-OSError escapes
plus pre-launch mkdir hygiene remain from the F103 sweep (F109).

SUBSTITUTE_JUSTIFICATION (F110 stub Harbor runner + pre-planted link targets)
- substitute: boundary ``process_runner`` callables authoring a synthetic
  Harbor ``result.json`` and pre-planting symlink/hard-link entries at the
  BenchEval log targets instead of launching ``harbor run``
- replaces: the real Harbor CLI subprocess and a surviving same-uid mutator
  planting links before the post-exit writes
- necessity: the assertions target BenchEval's write-anchoring boundary - a
  pre-planted symlink/hard link must never be opened, truncated, or followed;
  the planting must occur at the exact pre-write instant, which a real
  subprocess cannot produce deterministically
- real-option: executing the real ``harbor run`` against a disposable jobs dir
  - Docker/Harbor dependent and cannot schedule the link planting on demand
- proof-limit: proves write anchoring and victim-inode preservation only; does
  not prove Harbor executes or scores
- real-proof: BLOCKED - live terminal-bench lane on dev-box (operator
  provisioning required); all Harbor results remain diagnostic only

SUBSTITUTE_JUSTIFICATION (F107/F108 stub runners + synthetic checkout)
- substitute: disposable Inspect done-logs and HLE script pairs/artifacts
  authored by boundary ``process_runner`` callables, including
  rename-and-recreate swaps of ``inspect-logs`` and a white-box swap of
  ``hle-work`` hooked to the summary-write instant
- replaces: the real Inspect/HLE harness subprocesses and a same-uid mutator
  swapping directories between harness exit and the scored read / outcome
  stamping
- necessity: the swaps must occur at exact post-launch instants (post-exit and
  summary-write time), which real harness processes cannot produce
  deterministically
- real-option: executing the real harnesses against disposable log/work dirs -
  provider/network/checkout dependent and cannot schedule the swaps on demand
- proof-limit: proves directory-identity fail-closed behavior and dirfd-pinned
  scoring reads only; does not prove the real harnesses execute or score
- real-proof: BLOCKED - live GPQA/HLE lanes on dev-box (operator provisioning
  required); all GPQA/HLE results remain diagnostic only
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


# --- F110: terminal-bench instance logs must never follow pre-planted links ---


def _run_harbor_with_plant(
    tmp_path: Path,
    plant: object,
) -> tuple[Path, Path, object]:
    from bencheval.terminal_bench_harbor import HarborCliResult, run_terminal_bench_instance

    plan = _harbor_plan()
    victim = tmp_path / "victim.log"
    victim.write_text("precious\n", encoding="utf-8")
    planted: dict[str, Path] = {}

    def runner(command, *, cwd, timeout_sec):
        out_dir = Path(command[command.index("--jobs-dir") + 1])
        # The launched Harbor CLI receives --jobs-dir and plants a link at the
        # BenchEval log target before returning success.
        plant(out_dir / "stdout.log", victim)
        planted["path"] = out_dir / "stdout.log"
        (out_dir / "result.json").write_text(_legacy_pass_result("codex-cli"), encoding="utf-8")
        return HarborCliResult(0, "harbor-stdout", "", 0.1, tuple(command))

    outcome = run_terminal_bench_instance(
        plan=plan,
        instance_id="tb-smoke-001",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=runner,
        timeout_sec=60,
    )
    return victim, planted["path"], outcome


def test_harbor_instance_log_write_never_follows_a_preplanted_symlink(
    tmp_path: Path,
) -> None:
    victim, planted, outcome = _run_harbor_with_plant(
        tmp_path,
        lambda target, source: target.symlink_to(source),
    )

    assert victim.read_text(encoding="utf-8") == "precious\n"
    assert planted.is_symlink() is False
    assert planted.read_text(encoding="utf-8") == "harbor-stdout"
    assert outcome.primary_pass is True


def test_harbor_instance_log_write_never_truncates_a_preplanted_hardlink(
    tmp_path: Path,
) -> None:
    victim, planted, outcome = _run_harbor_with_plant(
        tmp_path,
        lambda target, source: os.link(source, target),
    )

    assert victim.read_text(encoding="utf-8") == "precious\n"
    assert os.stat(planted).st_ino != os.stat(victim).st_ino
    assert planted.read_text(encoding="utf-8") == "harbor-stdout"
    assert outcome.primary_pass is True


# --- F107: the scored GPQA done-log must be read from the pinned inode --------


def test_gpqa_inspect_log_dir_swap_with_forged_done_log_fails_closed(
    tmp_path: Path,
) -> None:
    from bencheval.gpqa_adapter import GpqaCliResult, run_gpqa_slice

    plan = _gpqa_plan()
    artifacts_dir = tmp_path / "artifacts"
    log_dir = artifacts_dir / "inspect-logs"

    def swapper(command, *, cwd, timeout_sec, env=None):
        model = command[command.index("--model") + 1]
        log_dir.mkdir(parents=True, exist_ok=True)
        real_done = log_dir / "done.json"
        real_done.write_text(
            _gpqa_done_payload(model=model, samples=len(plan.instances), accuracy=0.0),
            encoding="utf-8",
        )
        # A same-uid mutator swaps inspect-logs between Inspect exit and the
        # scored read, planting a forged perfect-score done-log.
        log_dir.rename(artifacts_dir / "inspect-logs-moved")
        log_dir.mkdir()
        (log_dir / "done.json").write_text(
            _gpqa_done_payload(model=model, samples=len(plan.instances), accuracy=1.0),
            encoding="utf-8",
        )
        return GpqaCliResult(0, f"Log: {log_dir / 'done.json'}\n", "", 0.05, tuple(command))

    with pytest.raises(AdapterFailureError) as excinfo:
        run_gpqa_slice(
            plan=plan,
            artifacts_dir=artifacts_dir,
            repo_root=tmp_path,
            process_runner=swapper,
        )

    assert excinfo.value.failure_label == "evidence_corrupt"


def test_parse_gpqa_official_score_reads_the_pinned_inode_via_dirfd(
    tmp_path: Path,
) -> None:
    from bencheval.gpqa_adapter import parse_gpqa_official_score

    log_dir = tmp_path / "inspect-logs"
    log_dir.mkdir()
    done = log_dir / "done.json"
    done.write_text(
        _gpqa_done_payload(model="kimi-k2.7-code", samples=2, accuracy=0.5),
        encoding="utf-8",
    )
    log_fd = os.open(log_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # A same-uid mutator swaps the directory after the fd was pinned.
        log_dir.rename(tmp_path / "inspect-logs-moved")
        log_dir.mkdir()
        (log_dir / "done.json").write_text(
            _gpqa_done_payload(model="kimi-k2.7-code", samples=2, accuracy=1.0),
            encoding="utf-8",
        )

        score = parse_gpqa_official_score(
            log_dir,
            expected_model="kimi-k2.7-code",
            stdout=f"Log: {done}\n",
            log_dir_fd=log_fd,
        )
    finally:
        os.close(log_fd)

    assert score is not None
    assert score.accuracy == 0.5


# --- F108: the stamped HLE verifier path must survive a post-check swap -------


def test_hle_work_dir_swap_at_summary_write_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bencheval.hle_adapter as hle_adapter
    from bencheval.hle_adapter import HleCliResult, hle_run_paths, run_hle_slice

    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    plan = _hle_plan()
    artifacts_dir = tmp_path / "artifacts"
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id="hle-r7-swap",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    calls: list[str] = []

    def runner(command, *, cwd, timeout_sec, env=None):
        calls.append("call")
        if len(calls) == 1:
            paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
        else:
            rows = {
                f"row-{index}": {"judge_response": {"correct": "yes"}}
                for index in range(len(plan.instances))
            }
            paths.judged_path.write_text(json.dumps(rows), encoding="utf-8")
        return HleCliResult(0, "", "", 0.1, tuple(command))

    real_write = hle_adapter.write_text_at_exclusive

    def tampering_write(dir_fd, name, text):
        if name == "hle_summary.json":
            # White-box hook: the judge exited cleanly and every per-subprocess
            # identity check already passed; a same-uid mutator swaps hle-work
            # in the window before outcome stamping and plants a replacement.
            paths.work_dir.rename(paths.work_dir.parent / "hle-work-moved")
            paths.work_dir.mkdir()
            (paths.work_dir / paths.judged_path.name).write_text(
                "{}\n",
                encoding="utf-8",
            )
        return real_write(dir_fd, name, text)

    monkeypatch.setattr(hle_adapter, "write_text_at_exclusive", tampering_write)

    with pytest.raises(AdapterFailureError) as excinfo:
        run_hle_slice(
            plan=plan,
            artifacts_dir=artifacts_dir,
            repo_root=tmp_path,
            process_runner=runner,
            run_id="hle-r7-swap",
        )

    assert excinfo.value.failure_label == "evidence_corrupt"


# --- F109: remaining raw-OSError escapes surface as BenchEvalError ------------


def test_open_instance_dir_fd_rejects_a_symlink_path_with_bencheval_error(
    tmp_path: Path,
) -> None:
    # Evidence record (nit F118): this test was green pre-F109 (the explicit
    # symlink guard always raised BenchEvalError); it is kept as a guard,
    # matching the annotation style at test_review_round6.py.
    from bencheval.external_agent_adapter import _open_instance_dir_fd

    artifacts_root = tmp_path / "artifacts"
    artifacts_root.mkdir()
    real = tmp_path / "real"
    real.mkdir()
    (artifacts_root / "inst-1").symlink_to(real, target_is_directory=True)

    with pytest.raises(BenchEvalError):
        _open_instance_dir_fd(artifacts_root, "inst-1")


def test_record_instance_failure_converts_oserror_when_instance_dir_is_a_file(
    tmp_path: Path,
) -> None:
    from bencheval.control_plane_executor import _record_instance_failure

    plan = _harbor_plan()
    instance_dir = tmp_path / "artifacts" / "tb-smoke-001"
    instance_dir.parent.mkdir(parents=True)
    # The agent swapped its instance dir to a regular file before the executor
    # recorded the failure: the failure-log write must surface BenchEvalError,
    # never a raw FileExistsError traceback out of the handler.
    instance_dir.write_text("swapped", encoding="utf-8")
    error = AdapterFailureError("injected harbor failure", failure_label="harness_failure")

    with pytest.raises(BenchEvalError) as excinfo:
        _record_instance_failure(
            plan=plan,
            run_id="tb-r7-swap",
            instance_id="tb-smoke-001",
            execution_profile="E2",
            error=error,
            artifacts_dir=instance_dir,
        )

    assert isinstance(excinfo.value.__cause__, OSError) or "not a directory" in str(
        excinfo.value,
    )
