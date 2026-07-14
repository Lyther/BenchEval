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
from bencheval.hle_adapter import HleCliResult, build_hle_run_commands
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

    def fake(command, *, cwd: Path | None, timeout_sec: int) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "official_scores.json").write_text(
            json.dumps({"accuracy": 1.0, "correct": 2, "total": 2}),
            encoding="utf-8",
        )
        return GpqaCliResult(0, "ok", "", 0.05, tuple(command))

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
    cmds = build_hle_run_commands(plan=plan, max_samples=2, artifacts_dir=tmp_path / "out")
    assert len(cmds) == 2

    evidence = tmp_path / "e.jsonl"

    def fake(command, *, cwd: Path | None, timeout_sec: int) -> HleCliResult:
        assert cwd is not None
        judged = Path(cwd) / "judged_hle_kimi-k2.7-code.json"
        judged.write_text(
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
        artifacts_dir=tmp_path / "art",
        hle_process_runner=fake,
        run_id="hle-test",
    )
    assert summary.instance_count == 1
    assert summary.passed_count == 1
    assert read_evidence_jsonl(evidence)[0].adapter_id == "hle"


@pytest.mark.parametrize("benchmark_id", ["swe-bench-pro", "cybergym", "exploitgym"])
def test_pending_benchmarks_do_not_plan_without_real_slice(benchmark_id: str) -> None:
    kwargs = {
        "benchmark_id": benchmark_id,
        "slice_id": "smoke",
        "runtime_id": "claude-code" if benchmark_id == "swe-bench-pro" else None,
        "agent_id": "momo" if benchmark_id != "swe-bench-pro" else None,
        "model_id": "kimi-k2.7-code",
    }
    with pytest.raises(BenchEvalError, match=r"slice .* not found"):
        plan_control_plane(**kwargs)
