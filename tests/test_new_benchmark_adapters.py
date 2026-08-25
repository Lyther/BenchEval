"""GPQA / HLE / CyberGym / ExploitGym / SWE-Pro adapter wiring (injected runners)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.adapter_admission import (
    assess_cybergym_admission,
    assess_exploitgym_admission,
    assess_gpqa_admission,
    assess_hle_admission,
    assess_swebench_pro_admission,
)
from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.gpqa_adapter import GpqaCliResult, build_gpqa_run_command
from bencheval.hle_adapter import HleCliResult, build_hle_run_commands, hle_run_paths
from bencheval.swebench_pro_harbor import SWEBENCH_PRO_ADAPTER_ID, SWEBENCH_PRO_HARBOR_DATASET
from bencheval.terminal_bench_harbor import HARBOR_DATASET


def test_admissions_pass() -> None:
    assert assess_swebench_pro_admission().passed is False
    assert assess_gpqa_admission().passed
    assert assess_hle_admission().passed
    assert assess_cybergym_admission().passed is False
    assert assess_exploitgym_admission().passed is False


def test_tb_dataset_pin_is_2_1() -> None:
    assert HARBOR_DATASET == "terminal-bench/terminal-bench-2-1"
    assert SWEBENCH_PRO_HARBOR_DATASET == "swebenchpro"
    assert SWEBENCH_PRO_ADAPTER_ID == "swebench-pro-harbor"


def test_gpqa_refuses_runtime() -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    with pytest.raises(BenchEvalError, match="model-only"):
        build_gpqa_run_command(
            plan=plan.model_copy(update={"runtime_id": "claude-code"}),
            sample_limit=1,
            log_dir=Path("/tmp/logs"),
        )


def test_execute_gpqa_slice(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    evidence = tmp_path / "e.jsonl"

    def fake(command, *, cwd: Path | None, timeout_sec: int, env=None) -> GpqaCliResult:
        # SUBSTITUTE_JUSTIFICATION
        # - substitute: synthetic Inspect eval log written by injected runner
        # - replaces: live Inspect eval log on disk
        # - necessity: exercise control-plane GPQA wiring without live Inspect
        # - real-option: live inspect eval; requires credentials + dataset
        # - proof-limit: parser-only diagnostic path through execute_control_plane_run
        # - real-proof: BLOCKED until live GPQA pilot
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "done.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "status": "success",
                    "eval": {
                        "created": "2024-01-01T00:00:00+00:00",
                        "task": "gpqa_diamond",
                        "task_id": "fixture",
                        "model": command[command.index("--model") + 1],
                    },
                    "results": {
                        "total_samples": 2,
                        "completed_samples": 2,
                        "scores": [
                            {
                                "name": "choice",
                                "scorer": "choice",
                                "metrics": {
                                    "accuracy": {"name": "accuracy", "value": 1.0},
                                },
                            },
                        ],
                    },
                },
            ),
            encoding="utf-8",
        )
        log_path = log_dir / "done.json"
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.05, tuple(command))

    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        gpqa_process_runner=fake,
        run_id="gpqa-test",
    )
    assert summary.instance_count == 1
    rows = read_evidence_jsonl(evidence)
    assert len(rows) == 1
    assert rows[0].adapter_id == "gpqa"
    assert rows[0].interpretation_label == "adapter_smoke"
    assert rows[0].instance_id.endswith("-aggregate")
    assert rows[0].provider_config_hash
    assert summary.passed_count == 1


def test_execute_hle_slice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "hle"
    (home / "hle_eval").mkdir(parents=True)
    (home / "hle_eval" / "run_model_predictions.py").write_text("# stub\n", encoding="utf-8")
    (home / "hle_eval" / "run_judge_results.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))

    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    art = tmp_path / "art"
    cmds = build_hle_run_commands(
        plan=plan,
        max_samples=2,
        artifacts_dir=art,
        run_id="hle-test",
    )
    assert len(cmds) == 2
    paths = hle_run_paths(
        artifacts_dir=art,
        run_id="hle-test",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )

    evidence = tmp_path / "e.jsonl"

    def fake(command, *, cwd: Path | None, timeout_sec: int, env=None) -> HleCliResult:
        # SUBSTITUTE_JUSTIFICATION
        # - substitute: injected process_runner writing run-local predict/judge JSON
        # - replaces: CAIS HLE scripts + model/judge API calls
        # - necessity: control-plane HLE wiring without live HF/API credentials
        # - real-option: live HLE smoke under BENCHEVAL_HLE_HOME
        # - proof-limit: diagnostic only — not live harness proof
        # - real-proof: BLOCKED until live HLE pilot
        assert cwd == paths.work_dir
        if "run_model_predictions.py" in " ".join(command):
            paths.default_predictions_path.write_text("{}", encoding="utf-8")
            return HleCliResult(0, "pred", "", 0.05, tuple(command))
        paths.judged_path.write_text(
            json.dumps(
                {
                    "q1": {"judge_response": {"correct": "yes", "confidence": 90}},
                    "q2": {"judge_response": {"correct": "yes", "confidence": 90}},
                },
            ),
            encoding="utf-8",
        )
        return HleCliResult(0, "Accuracy: 100.0% | n = 2\n", "", 0.05, tuple(command))

    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=art,
        hle_process_runner=fake,
        run_id="hle-test",
    )
    assert summary.instance_count == 1
    assert summary.passed_count == 1
    row = read_evidence_jsonl(evidence)[0]
    assert row.adapter_id == "hle"
    assert row.provider_config_hash
    assert row.judge_model_id == plan.judge_model_id


@pytest.mark.parametrize("benchmark_id", ["swe-bench-pro", "cybergym", "exploitgym"])
def test_pending_benchmarks_do_not_plan_without_real_slice(benchmark_id: str) -> None:
    kwargs = {
        "benchmark_id": benchmark_id,
        "slice_id": "smoke",
        "runtime_id": "claude-code" if benchmark_id == "swe-bench-pro" else None,
        "agent_id": "momo" if benchmark_id != "swe-bench-pro" else None,
        "model_id": "kimi-k2.7-code",
    }
    expected = (
        r"slice .* not found"
        if benchmark_id == "swe-bench-pro"
        else r"momo.*scaffold|scaffold.*momo"
    )
    with pytest.raises(BenchEvalError, match=expected):
        plan_control_plane(**kwargs)
