"""Round-6 qa-review regressions (REJECTED findings F101-F103 + nit F105).

Root contract under repair: the GPQA adapter has the exact unchecked-pathname
write defect fixed for HLE in round 5 (F101); the HLE scoring-authority judged
JSON is read via a bare pathname under a never-pinned work dir (F102); the
anchored helpers leak raw OSError across the adapter boundary (F103); and the
HLE dataset identity is re-read at stamp time instead of captured once (F105).

SUBSTITUTE_JUSTIFICATION (F101 stub Inspect runner + pre-planted link targets)
- substitute: boundary `process_runner` callables authoring a synthetic Inspect
  done-log and pre-planting symlink/hard-link entries at BenchEval log targets
  instead of launching `inspect eval`
- replaces: the real Inspect Evals subprocess and a surviving same-uid mutator
  planting links before the post-exit writes
- necessity: the assertions target BenchEval's write-anchoring boundary - a
  pre-planted symlink/hard link must never be opened, truncated, or followed;
  the planting must occur at the exact pre-write instant, which a real
  subprocess cannot produce deterministically
- real-option: executing the real `inspect eval` against a disposable log dir -
  provider/network dependent and cannot schedule the link planting on demand
- proof-limit: proves write anchoring and victim-inode preservation only; does
  not prove Inspect executes or scores
- real-proof: BLOCKED - live GPQA lane on dev-box (operator provisioning
  required); all GPQA results remain diagnostic only

SUBSTITUTE_JUSTIFICATION (F102/F105 stub HLE runner + synthetic checkout)
- substitute: disposable script pairs and predictions/judged artifacts authored
  by a boundary `process_runner`, including a rename-and-recreate swap of
  `hle-work` and a mid-run environment flip of BENCHEVAL_HLE_DATASET
- replaces: the official CAIS HLE checkout + real harness subprocess, a
  same-uid mutator swapping the work dir between judge exit and the scored
  read, and a concurrent config edit
- necessity: the swap and the env flip must occur at the exact post-launch
  instant, which a real harness process cannot produce deterministically
- real-option: executing the real HLE harness against a disposable checkout -
  network/checkout dependent and cannot schedule the swap on demand
- proof-limit: proves directory-identity fail-closed behavior, dirfd-pinned
  judged reads, and dataset-identity consistency only; does not prove the real
  HLE harness executes or scores
- real-proof: BLOCKED - live HLE lane on dev-box with the official checkout
  (operator provisioning required); all HLE results remain diagnostic only
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import AdapterFailureError, BenchEvalError


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


# --- F101: GPQA run logs must never follow pre-planted links ------------------


def _gpqa_plan():
    return plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )


def _gpqa_done_payload(*, model: str, samples: int) -> str:
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
                        "metrics": {"accuracy": {"name": "accuracy", "value": 1.0}},
                    },
                ],
            },
        },
    )


def _run_gpqa_with_plant(
    tmp_path: Path,
    plant: Callable[[Path, Path], None],
) -> tuple[Path, Path, list[object]]:
    from bencheval.gpqa_adapter import GpqaCliResult, run_gpqa_slice

    plan = _gpqa_plan()
    artifacts_dir = tmp_path / "artifacts"
    victim = tmp_path / "victim.log"
    victim.write_text("precious\n", encoding="utf-8")

    def runner(
        command: object,
        *,
        cwd: object,
        timeout_sec: object,
        env: object = None,
    ) -> object:
        # The launched subprocess receives --log-dir under the artifacts tree
        # and can derive the parent: it plants a link at the BenchEval log
        # target before returning success.
        plant(artifacts_dir / "stdout.log", victim)
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_dir.mkdir(parents=True, exist_ok=True)
        done = log_dir / "done.json"
        done.write_text(
            _gpqa_done_payload(
                model=command[command.index("--model") + 1],
                samples=len(plan.instances),
            ),
            encoding="utf-8",
        )
        return GpqaCliResult(0, f"Log: {done}\n", "", 0.05, tuple(command))

    outcomes = run_gpqa_slice(
        plan=plan,
        artifacts_dir=artifacts_dir,
        repo_root=tmp_path,
        process_runner=runner,
    )
    return victim, artifacts_dir / "stdout.log", outcomes


def test_gpqa_run_log_write_never_follows_a_preplanted_symlink(tmp_path: Path) -> None:
    victim, planted, outcomes = _run_gpqa_with_plant(
        tmp_path,
        lambda target, source: target.symlink_to(source),
    )

    assert victim.read_text(encoding="utf-8") == "precious\n"
    assert planted.is_symlink() is False
    assert outcomes
    assert outcomes[0].primary_pass is True


def test_gpqa_run_log_write_never_truncates_a_preplanted_hardlink(tmp_path: Path) -> None:
    victim, planted, outcomes = _run_gpqa_with_plant(
        tmp_path,
        lambda target, source: os.link(source, target),
    )

    assert victim.read_text(encoding="utf-8") == "precious\n"
    assert os.stat(planted).st_ino != os.stat(victim).st_ino
    assert outcomes
    assert outcomes[0].primary_pass is True


# --- F102: the scored HLE judged JSON must be read from the pinned inode ------


def test_hle_work_dir_rename_recreate_with_forged_judged_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval.hle_adapter import HleCliResult, hle_run_paths, run_hle_slice

    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    plan = _hle_plan()
    artifacts_dir = tmp_path / "artifacts"
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id="hle-r6-swap",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    calls: list[str] = []

    def swapper(
        command: object,
        *,
        cwd: object,
        timeout_sec: object,
        env: object = None,
    ) -> object:
        calls.append("call")
        if len(calls) == 1:
            paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
        else:
            rows = {
                f"row-{index}": {"judge_response": {"correct": "no"}}
                for index in range(len(plan.instances))
            }
            paths.judged_path.write_text(json.dumps(rows), encoding="utf-8")
            # A same-uid mutator swaps the work dir between judge exit and the
            # scored read, planting a forged all-"yes" judged artifact.
            paths.work_dir.rename(paths.work_dir.parent / "hle-work-moved")
            paths.work_dir.mkdir()
            forged = {
                f"row-{index}": {"judge_response": {"correct": "yes"}}
                for index in range(len(plan.instances))
            }
            (paths.work_dir / paths.judged_path.name).write_text(
                json.dumps(forged),
                encoding="utf-8",
            )
        return HleCliResult(0, "", "", 0.1, tuple(command))

    with pytest.raises(AdapterFailureError) as excinfo:
        run_hle_slice(
            plan=plan,
            artifacts_dir=artifacts_dir,
            repo_root=tmp_path,
            process_runner=swapper,
            run_id="hle-r6-swap",
        )

    assert excinfo.value.failure_label == "evidence_corrupt"


def test_parse_hle_official_score_reads_the_pinned_inode_via_dirfd(tmp_path: Path) -> None:
    from bencheval.hle_adapter import parse_hle_official_score

    work = tmp_path / "hle-work"
    work.mkdir()
    judged = work / "judged_hle_run.json.json"
    real_rows = {
        "row-0": {"judge_response": {"correct": "no"}},
        "row-1": {"judge_response": {"correct": "yes"}},
    }
    judged.write_text(json.dumps(real_rows), encoding="utf-8")
    work_fd = os.open(work, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        # A same-uid mutator swaps the directory after the fd was pinned.
        work.rename(tmp_path / "hle-work-moved")
        work.mkdir()
        forged_rows = {
            "row-0": {"judge_response": {"correct": "yes"}},
            "row-1": {"judge_response": {"correct": "yes"}},
        }
        (work / judged.name).write_text(json.dumps(forged_rows), encoding="utf-8")

        score = parse_hle_official_score(
            eval_dir=tmp_path,
            model_id="kimi-k2.7-code",
            judge_stdout="",
            max_samples=2,
            work_dir=work,
            judged_path=judged,
            judged_dir_fd=work_fd,
        )
    finally:
        os.close(work_fd)

    assert score is not None
    assert (score.correct, score.total) == (1, 2)


# --- F103: anchored helpers must surface BenchEvalError, never raw OSError ----


def test_write_text_at_exclusive_converts_oserror_to_bencheval_error(tmp_path: Path) -> None:
    from bencheval.run_isolation import open_owned_dir_fd, write_text_at_exclusive

    target_dir = tmp_path / "logs"
    target_dir.mkdir()
    # A directory squats at the write target: the unlink step raises
    # IsADirectoryError, which must cross the adapter boundary as
    # BenchEvalError (the CLI catches nothing else).
    (target_dir / "stdout.log").mkdir()
    dir_fd = open_owned_dir_fd(target_dir, role="test directory")
    try:
        with pytest.raises(BenchEvalError) as excinfo:
            write_text_at_exclusive(dir_fd, "stdout.log", "content")
    finally:
        os.close(dir_fd)

    assert isinstance(excinfo.value.__cause__, OSError)


def test_write_bytes_at_exclusive_converts_oserror_to_bencheval_error(tmp_path: Path) -> None:
    from bencheval.run_isolation import open_owned_dir_fd, write_bytes_at_exclusive

    target_dir = tmp_path / "logs"
    target_dir.mkdir()
    (target_dir / "run_model_predictions.py").mkdir()
    dir_fd = open_owned_dir_fd(target_dir, role="test directory")
    try:
        with pytest.raises(BenchEvalError) as excinfo:
            write_bytes_at_exclusive(dir_fd, "run_model_predictions.py", b"bytes")
    finally:
        os.close(dir_fd)

    assert isinstance(excinfo.value.__cause__, OSError)


def test_open_owned_dir_fd_rejects_a_symlink_path_with_bencheval_error(tmp_path: Path) -> None:
    # Evidence record (nit F111): round 6 was 7 red->green plus this one
    # pre-existing guard - the explicit symlink rejection already raised
    # BenchEvalError before the F103 patch; the test is kept as a guard.
    from bencheval.run_isolation import open_owned_dir_fd

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    with pytest.raises(BenchEvalError):
        open_owned_dir_fd(link, role="test directory")


# --- F105: the stamped dataset identity must be the launched one --------------


def test_hle_dataset_identity_is_captured_once_per_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Contract (pinned OFFICIAL dataset identity, product option (a) after the
    # review-F002 mirror revert): the launched dataset is the pinned catalog
    # repo ``cais/hle``. The capture-once guard is preserved — a concurrent env
    # edit must not change the launched or stamped identity; the flipped value
    # is drift that would fail closed if it were re-resolved (see the
    # divergence tests in test_benchmark_identity_contracts).
    from bencheval.hle_adapter import HleCliResult, hle_run_paths, run_hle_slice

    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    monkeypatch.delenv("BENCHEVAL_HLE_DATASET", raising=False)
    plan = _hle_plan()
    artifacts_dir = tmp_path / "artifacts"
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id="hle-r6-dataset",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    argv_datasets: list[str] = []

    def flipper(
        command: object,
        *,
        cwd: object,
        timeout_sec: object,
        env: object = None,
    ) -> object:
        argv_datasets.append(command[command.index("--dataset") + 1])
        # A concurrent config edit flips the env between build and stamp time.
        monkeypatch.setenv("BENCHEVAL_HLE_DATASET", "mirror/hle-v2")
        if len(argv_datasets) == 1:
            paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
        else:
            judged = {
                f"row-{index}": {"judge_response": {"correct": "yes"}}
                for index in range(len(plan.instances))
            }
            paths.judged_path.write_text(json.dumps(judged), encoding="utf-8")
        return HleCliResult(0, "", "", 0.1, tuple(command))

    outcomes = run_hle_slice(
        plan=plan,
        artifacts_dir=artifacts_dir,
        repo_root=tmp_path,
        process_runner=flipper,
        run_id="hle-r6-dataset",
    )

    assert argv_datasets == ["cais/hle", "cais/hle"]
    assert outcomes
    assert outcomes[0].adapter_metadata["hle_dataset"] == "cais/hle"
