"""F009: HLE outputs are run-isolated under artifacts_dir; timeout is cumulative."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.hle_adapter import (
    HleCliResult,
    build_hle_run_commands,
    hle_output_stem,
    hle_run_paths,
    remaining_timeout_sec,
    run_hle_slice,
)


def _install_hle_scripts(home: Path) -> None:
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# stub\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# stub\n", encoding="utf-8")


def test_hle_commands_target_artifacts_work_dir_with_run_and_model_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "hle-home"
    _install_hle_scripts(home)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))

    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
        provider_id="bytellm",
    )
    # Full identity must retain provider + model_id (not basename-only).
    plan = plan.model_copy(update={"model_id": "org/kimi-k2.7-code"})
    artifacts = tmp_path / "art" / "run-artifacts"
    run_id = "run-abc-123"
    pred_cmd, judge_cmd = build_hle_run_commands(
        plan=plan,
        max_samples=2,
        artifacts_dir=artifacts,
        run_id=run_id,
    )
    paths = hle_run_paths(
        artifacts_dir=artifacts,
        run_id=run_id,
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    stem = hle_output_stem(
        run_id=run_id,
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    assert "run-abc-123" in stem
    assert "bytellm" in stem
    assert "org_kimi-k2.7-code" in stem
    assert paths.work_dir == artifacts.resolve() / "hle-work"
    assert paths.predictions_path.parent == paths.work_dir
    assert paths.predictions_path.name == f"hle_{stem}.json"
    assert paths.judged_path.name == f"judged_hle_{stem}.json.json"
    assert Path(judge_cmd[judge_cmd.index("--predictions") + 1]) == paths.predictions_path
    assert pred_cmd[pred_cmd.index("--model") + 1] == "org/kimi-k2.7-code"


def test_remaining_timeout_sec_is_cumulative() -> None:
    assert remaining_timeout_sec(1000.0, now_monotonic=900.0) == 100
    assert remaining_timeout_sec(1000.0, now_monotonic=1000.0) == 0
    assert remaining_timeout_sec(1000.0, now_monotonic=1000.4) == 0
    assert remaining_timeout_sec(1000.0, now_monotonic=999.1) == 1


def test_run_hle_slice_writes_under_artifacts_and_passes_remaining_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "hle-home"
    _install_hle_scripts(home)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))

    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
        provider_id="bytellm",
    )
    artifacts = tmp_path / "art"
    run_id = "iso-run-1"
    paths = hle_run_paths(
        artifacts_dir=artifacts,
        run_id=run_id,
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    seen_timeouts: list[int] = []
    clock = {"t": 1_000.0}

    def mono() -> float:
        return clock["t"]

    def fake(command, *, cwd: Path | None, timeout_sec: int, env=None) -> HleCliResult:
        # SUBSTITUTE_JUSTIFICATION
        # - substitute: injected process_runner + monotonic_clock
        # - replaces: real CAIS predict/judge subprocesses and wall clock
        # - necessity: prove artifact paths and cumulative timeout without live HF/API calls
        # - real-option: live HLE smoke; requires BENCHEVAL_HLE_HOME + credentials
        # - proof-limit: diagnostic for path/timeout wiring only
        # - real-proof: BLOCKED until live HLE pilot under docs/ops/dev-box-pilot.md
        assert cwd == paths.work_dir
        seen_timeouts.append(timeout_sec)
        if "run_model_predictions.py" in " ".join(command):
            paths.default_predictions_path.write_text("{}", encoding="utf-8")
            clock["t"] += 40.0
            return HleCliResult(0, "pred-ok", "", 40.0, tuple(command))
        assert Path(command[command.index("--predictions") + 1]) == paths.predictions_path
        assert paths.predictions_path.is_file()
        paths.judged_path.write_text(
            json.dumps(
                {
                    "q1": {"judge_response": {"correct": "yes"}},
                    "q2": {"judge_response": {"correct": "yes"}},
                },
            ),
            encoding="utf-8",
        )
        clock["t"] += 5.0
        return HleCliResult(0, "Accuracy: 100.0% | n = 2\n", "", 5.0, tuple(command))

    outcomes = run_hle_slice(
        plan=plan,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=fake,
        timeout_sec=100,
        run_id=run_id,
        monotonic_clock=mono,
    )
    assert seen_timeouts == [100, 60]
    assert paths.predictions_path.is_file()
    assert paths.judged_path.is_file()
    assert paths.judged_path.is_relative_to(artifacts.resolve())
    assert outcomes[0].partial_score == pytest.approx(1.0)
    assert str(paths.judged_path) in (outcomes[0].native_score.get("score_source") or "")
