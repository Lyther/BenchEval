"""RED contracts for lifecycle controls across the remaining execution lanes.

SUBSTITUTE_JUSTIFICATION
- substitute: injected external-agent, Inspect, and HLE process runners
- replaces: provider-charged MOMO, Inspect, and CAIS HLE subprocess effects
- necessity: exact elapsed-budget exhaustion and controlled transient filesystem state cannot be
  produced safely and deterministically by the real charged services
- real-option: real dev-box pilots require unavailable harness scripts, datasets, and credentials
- proof-limit: these tests prove only BenchEval's local run-control and cleanup response; they do
  not prove the external agents, benchmark harnesses, providers, or scorers
- real-proof: BLOCKED until equivalent disposable dev-box pilots inspect both evidence and the
  post-run artifact tree
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.external_agent_adapter import ExternalAgentCliResult
from bencheval.gpqa_adapter import GpqaCliResult
from bencheval.hle_adapter import HleCliResult, hle_run_paths


def test_external_agent_stops_before_launching_past_the_wall_budget(tmp_path: Path) -> None:
    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id=None,
        agent_id="momo",
        model_id="kimi-k2.7-code",
    )
    plan = base_plan.model_copy(
        update={"instances": base_plan.instances[:3], "max_wall_clock_sec": 1},
    )
    calls: list[str] = []

    def slow_agent(command, *, cwd: Path | None, timeout_sec: int) -> ExternalAgentCliResult:
        calls.append(command[command.index("--instance") + 1])
        return ExternalAgentCliResult(1, "", "agent failed", 2.0, tuple(command))

    evidence_path = tmp_path / "evidence.jsonl"
    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        agent_process_runner=slow_agent,
        run_id="external-agent-wall-budget-contract",
    )

    rows = read_evidence_jsonl(evidence_path)
    assert calls == [plan.instances[0].instance_id]
    assert (summary.instance_count, summary.passed_count, summary.failed_count) == (3, 0, 3)
    assert rows[0].failure_class == "runtime_tool_failure"
    assert [row.instance_id for row in rows[1:]] == [
        inst.instance_id for inst in plan.instances[1:]
    ]
    assert all(row.failure_class == "runtime_budget_exceeded" for row in rows[1:])


def test_external_agent_applies_cleanup_policy_and_preserves_logs(tmp_path: Path) -> None:
    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id=None,
        agent_id="momo",
        model_id="kimi-k2.7-code",
        cleanup_policy="always",
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    transient_paths: list[Path] = []

    def failed_agent(command, *, cwd: Path | None, timeout_sec: int) -> ExternalAgentCliResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        transient_path = output_dir / "agent-workspace"
        transient_path.mkdir(parents=True)
        (transient_path / "scratch.txt").write_text("ephemeral\n", encoding="utf-8")
        transient_paths.append(transient_path)
        return ExternalAgentCliResult(1, "kept stdout", "kept stderr", 0.1, tuple(command))

    evidence_path = tmp_path / "evidence.jsonl"
    execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        agent_process_runner=failed_agent,
        run_id="external-agent-cleanup-contract",
    )

    row = read_evidence_jsonl(evidence_path)[0]
    assert row.cleanup_result == "success"
    assert all(Path(path).is_file() for path in row.artifact_paths)
    assert not transient_paths[0].exists()


def test_gpqa_applies_cleanup_policy_and_preserves_official_log(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
        cleanup_policy="always",
    )
    official_logs: list[Path] = []
    transient_paths: list[Path] = []

    def inspect_runner(
        command,
        *,
        cwd: Path | None,
        timeout_sec: int,
        env=None,
    ) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_dir.mkdir(parents=True, exist_ok=True)
        official_log = log_dir / "gpqa.json"
        official_log.write_text(
            json.dumps(
                {
                    "status": "success",
                    "eval": {
                        "task": "gpqa_diamond",
                        "model": command[command.index("--model") + 1],
                    },
                    "results": {
                        "total_samples": 2,
                        "completed_samples": 2,
                        "scores": [
                            {
                                "name": "choice",
                                "metrics": {"accuracy": {"value": 1.0}},
                            },
                        ],
                    },
                },
            )
            + "\n",
            encoding="utf-8",
        )
        transient_path = log_dir.parent / "materialized-workspace"
        transient_path.mkdir()
        (transient_path / "scratch.txt").write_text("ephemeral\n", encoding="utf-8")
        official_logs.append(official_log)
        transient_paths.append(transient_path)
        done = {
            "type": "done",
            "status": "success",
            "tasks": [{"status": "success", "log_location": str(official_log)}],
        }
        return GpqaCliResult(0, json.dumps(done) + "\n", "", 0.1, tuple(command))

    evidence_path = tmp_path / "evidence.jsonl"
    execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        gpqa_process_runner=inspect_runner,
        run_id="gpqa-cleanup-contract",
    )

    row = read_evidence_jsonl(evidence_path)[0]
    assert row.primary_pass is True
    assert row.cleanup_result == "success"
    assert official_logs[0].is_file()
    assert not transient_paths[0].exists()


def test_hle_applies_cleanup_policy_and_preserves_judged_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "hle-home"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# entry point\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# entry point\n", encoding="utf-8")
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
        cleanup_policy="always",
    )
    run_id = "hle-cleanup-contract"
    artifacts = tmp_path / "artifacts"
    paths = hle_run_paths(
        artifacts_dir=artifacts,
        run_id=run_id,
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    transient = artifacts / "materialized-workspace"
    calls = 0

    def hle_runner(command, *, cwd: Path | None, timeout_sec: int, env=None) -> HleCliResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
            transient.mkdir()
            (transient / "scratch.txt").write_text("ephemeral\n", encoding="utf-8")
            return HleCliResult(0, "", "", 0.1, tuple(command))
        paths.judged_path.write_text(
            json.dumps(
                {
                    "q1": {"judge_response": {"correct": "yes"}},
                    "q2": {"judge_response": {"correct": "yes"}},
                },
            )
            + "\n",
            encoding="utf-8",
        )
        return HleCliResult(0, "Accuracy: 100.0% | n = 2", "", 0.1, tuple(command))

    evidence_path = tmp_path / "evidence.jsonl"
    execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=artifacts,
        hle_process_runner=hle_runner,
        run_id=run_id,
    )

    row = read_evidence_jsonl(evidence_path)[0]
    assert row.primary_pass is True
    assert row.cleanup_result == "success"
    assert paths.judged_path.is_file()
    assert not transient.exists()
