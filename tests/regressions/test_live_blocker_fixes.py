"""Regressions for blockers found by Linux and live HLE verification.

SUBSTITUTE_JUSTIFICATION (pinned HLE post-artifact failure runner)
- substitute: a disposable git checkout with two inert HLE script files, an
  injected content/revision pin, and a boundary process runner that writes the
  same predictions/judged artifact shape as the official scripts before
  returning the pinned judge's observed calibration traceback
- replaces: the CAIS HLE subprocesses and paid candidate/judge API calls
- necessity: the contract must deterministically distinguish the exact
  post-artifact calibration failure from an arbitrary nonzero judge exit; a
  real paid run cannot safely or deterministically produce both branches
- real-option: the pinned official checkout on dev-box-cpu; it produced the
  calibration traceback after materializing a complete two-row judged artifact
- proof-limit: proves only local classification and artifact authority; it does
  not prove provider compatibility, the shipped upstream pin, or live scoring
- real-proof: rerun the two-sample HLE smoke on dev-box-cpu with the pinned CAIS
  checkout and retain its evidence and exact judged artifact
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.hle_adapter import HleCliResult, HleHarnessPin, hle_run_paths, run_hle_slice

_GIT_REQUIRED = pytest.mark.skipif(shutil.which("git") is None, reason="git required")

_PINNED_SMALL_SLICE_TRACEBACK = """Traceback (most recent call last):
  File "/run/hle-src/run_judge_results.py", line 217, in <module>
    dump_metrics(judged_predictions)
  File "/run/hle-src/run_judge_results.py", line 165, in dump_metrics
    \"calib_err\": calib_err(results),
  File "/run/hle-src/run_judge_results.py", line 151, in calib_err
    bins[-1].extend(sorted_confidence_scores[100 * len(bins) :])
IndexError: list index out of range
"""


def test_hle_smoke_uses_the_measured_45_minute_aggregate_envelope() -> None:
    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )

    # The official aggregate predictor exceeded the former 2 x 600s envelope
    # on dev-box-cpu. Keep the pilot's established 45-minute cap explicit: the
    # adapter enforces this run-total deadline across prediction and judging.
    assert plan.max_wall_clock_sec_per_instance == 1350
    assert plan.max_wall_clock_sec == 2700


def test_hle_smoke_pins_a_live_structured_output_compatible_judge() -> None:
    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="gpt-5.4-2026-03-05",
    )

    # The official CAIS judge uses beta.chat.completions.parse. The ByteLLM
    # GPT-5.4 Responses route currently drops Chat Completions response_format,
    # while the direct-chat GPT-5.3 route has passed the same live parse call.
    assert plan.judge_model_id == "gpt-5.3-chat-2026-03-03"


def _git_checkout_and_pin(root: Path) -> HleHarnessPin:
    eval_dir = root / "hle_eval"
    eval_dir.mkdir(parents=True)
    scripts = {
        "run_model_predictions.py": b"# pinned predict\n",
        "run_judge_results.py": b"# pinned judge\n",
    }
    for name, content in scripts.items():
        (eval_dir / name).write_bytes(content)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "hle_eval"], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=BenchEval Test",
            "-c",
            "user.email=bencheval-test@example.invalid",
            "commit",
            "-qm",
            "pin",
        ],
        cwd=root,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return HleHarnessPin(
        commit=commit,
        script_sha256={
            name: hashlib.sha256(content).hexdigest() for name, content in scripts.items()
        },
    )


def _run_two_sample_judge_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    judge_stderr: str,
):
    home = tmp_path / "hle"
    pin = _git_checkout_and_pin(home)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    artifacts = tmp_path / "artifacts"
    paths = hle_run_paths(
        artifacts_dir=artifacts,
        run_id="hle-small-slice",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )

    def runner(command, *, cwd: Path | None, timeout_sec: int, env=None) -> HleCliResult:
        assert cwd == paths.work_dir
        if Path(command[1]).name == "run_model_predictions.py":
            paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
            return HleCliResult(0, "predictions complete", "", 0.1, tuple(command))
        paths.judged_path.write_text(
            json.dumps(
                {
                    "q1": {"judge_response": {"correct": "yes", "confidence": 90}},
                    "q2": {"judge_response": {"correct": "no", "confidence": 70}},
                },
            ),
            encoding="utf-8",
        )
        return HleCliResult(1, "", judge_stderr, 0.1, tuple(command))

    return run_hle_slice(
        plan=plan,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=runner,
        run_id="hle-small-slice",
        harness_pin=pin,
    )[0]


@_GIT_REQUIRED
def test_pinned_hle_small_slice_uses_complete_judged_artifact_after_metrics_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = _run_two_sample_judge_failure(
        tmp_path,
        monkeypatch,
        judge_stderr=_PINNED_SMALL_SLICE_TRACEBACK,
    )

    assert outcome.partial_score == 0.5
    assert outcome.primary_pass is False
    assert outcome.failure_class == "model_wrong_solution"
    assert outcome.counts_toward_pass_at_k is True
    assert outcome.verifier_log_path is not None
    assert outcome.native_score["returncode"] == 1
    assert outcome.native_score["correct"] == 1
    assert outcome.native_score["total"] == 2
    assert (
        outcome.adapter_metadata["judge_exit_interpretation"]
        == "known_post_artifact_small_slice_calibration_failure"
    )


@_GIT_REQUIRED
def test_hle_arbitrary_nonzero_judge_exit_remains_harness_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome = _run_two_sample_judge_failure(
        tmp_path,
        monkeypatch,
        judge_stderr="ValueError: provider response was malformed\n",
    )

    assert outcome.partial_score == 0.0
    assert outcome.failure_class == "harness_failure"
    assert outcome.counts_toward_pass_at_k is False
    assert outcome.verifier_log_path is None
    assert "judge_exit_interpretation" not in outcome.adapter_metadata
