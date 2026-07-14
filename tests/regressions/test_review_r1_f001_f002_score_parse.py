"""Regressions: GPQA/HLE must not treat harness exit 0 as benchmark pass."""

from __future__ import annotations

import json
from pathlib import Path

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.domain import RunPlan
from bencheval.evidence import read_evidence_jsonl
from bencheval.exploitgym_adapter import ExploitgymCliResult, run_exploitgym_instance
from bencheval.gpqa_adapter import GpqaCliResult, build_gpqa_run_command
from bencheval.hle_adapter import HleCliResult, build_hle_run_commands


def test_gpqa_exit_0_with_zero_accuracy_does_not_pass(tmp_path: Path) -> None:
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
            json.dumps({"accuracy": 0.0, "correct": 0, "total": 2}),
            encoding="utf-8",
        )
        return GpqaCliResult(0, "ok", "", 0.05, tuple(command))

    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        gpqa_process_runner=fake,
        run_id="gpqa-zero",
    )
    rows = read_evidence_jsonl(evidence)
    assert summary.instance_count == 1
    assert all(not r.primary_pass for r in rows)
    assert all(r.partial_score == 0.0 for r in rows)
    assert any(r.counts_toward_pass_at_k is True for r in rows)
    assert rows[0].instance_id.endswith("-aggregate")


def test_gpqa_exit_0_with_half_accuracy_sets_partial_not_full(tmp_path: Path) -> None:
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
            json.dumps({"accuracy": 0.5, "correct": 1, "total": 2}),
            encoding="utf-8",
        )
        return GpqaCliResult(0, "ok", "", 0.05, tuple(command))

    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        gpqa_process_runner=fake,
        run_id="gpqa-half",
    )
    rows = read_evidence_jsonl(evidence)
    assert len(rows) == 1
    assert all(abs(r.partial_score - 0.5) < 1e-9 for r in rows)
    assert all(not r.primary_pass for r in rows)


def test_gpqa_exit_0_without_official_scores_excluded_from_pass_at_k(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    evidence = tmp_path / "e.jsonl"

    def fake(command, *, cwd: Path | None, timeout_sec: int) -> GpqaCliResult:
        return GpqaCliResult(0, "ok", "", 0.05, tuple(command))

    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        gpqa_process_runner=fake,
        run_id="gpqa-noscore",
    )
    rows = read_evidence_jsonl(evidence)
    assert all(not r.primary_pass for r in rows)
    assert all(r.partial_score == 0.0 for r in rows)
    assert all(r.counts_toward_pass_at_k is False for r in rows)


def test_gpqa_command_requests_json_logs_for_parser_contract(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    command = build_gpqa_run_command(
        plan=plan,
        sample_limit=2,
        log_dir=tmp_path / "inspect-logs",
    )
    assert "--log-format" in command
    assert command[command.index("--log-format") + 1] == "json"


def test_exploitgym_exit_0_without_verdict_does_not_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "exploitgym"
    (home / "examples").mkdir(parents=True)
    (home / "examples" / "run_agent.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("BENCHEVAL_EXPLOITGYM_HOME", str(home))
    plan = RunPlan(
        schema_version="0.3",
        benchmark_id="exploitgym",
        slice_id="host-official-task",
        adapter_id="exploitgym",
        harness_kind="exploitgym-native",
        agent_id="momo",
        provider_id="bytellm",
        model_id="kimi-k2.7-code",
        model_binding="runtime_configured",
        instances=({"instance_id": "official-task-1"},),
        budget_class="B3",
        max_cost_usd=25.0,
        max_wall_clock_sec=3000,
        requires_harbor=False,
        requires_sandbox=True,
        network_policy="benchmark_required",
        cleanup_policy="always",
        comparison_validity="adapter_smoke",
    )

    def fake(command, *, cwd: Path | None, timeout_sec: int) -> ExploitgymCliResult:
        return ExploitgymCliResult(0, "completed without verdict", "", 0.05, tuple(command))

    outcome = run_exploitgym_instance(
        plan=plan,
        artifacts_dir=tmp_path / "art",
        instance_id="official-task-1",
        repo_root=tmp_path,
        process_runner=fake,
    )
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"
    assert outcome.verifier_log_path is None
    assert outcome.counts_toward_pass_at_k is False


def test_hle_predictions_path_matches_official_cwd_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "hle"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# stub\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))

    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    pred_cmd, judge_cmd = build_hle_run_commands(
        plan=plan,
        max_samples=2,
        artifacts_dir=tmp_path / "out",
    )
    assert "--num_workers" in pred_cmd
    assert int(pred_cmd[pred_cmd.index("--num_workers") + 1]) >= 2
    # Official script writes hle_<basename(model)>.json relative to hle_eval cwd.
    assert any(part.endswith("hle_kimi-k2.7-code.json") for part in judge_cmd)
    pred_path = Path(judge_cmd[judge_cmd.index("--predictions") + 1])
    assert pred_path.parent == eval_dir.resolve()


def test_hle_exit_0_parses_judged_metrics_not_returncode(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "hle"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# stub\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))

    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    evidence = tmp_path / "e.jsonl"

    def fake(command, *, cwd: Path | None, timeout_sec: int) -> HleCliResult:
        assert cwd is not None
        assert Path(cwd).name == "hle_eval"
        if "run_model_predictions.py" in " ".join(command):
            pred = Path(cwd) / "hle_kimi-k2.7-code.json"
            pred.write_text("{}", encoding="utf-8")
            return HleCliResult(0, "pred", "", 0.05, tuple(command))
        judged = Path(cwd) / "judged_hle_kimi-k2.7-code.json"
        judged.write_text(
            json.dumps(
                {
                    "q1": {"judge_response": {"correct": "yes", "confidence": 80}},
                    "q2": {"judge_response": {"correct": "no", "confidence": 40}},
                },
            ),
            encoding="utf-8",
        )
        return HleCliResult(
            0,
            "*** Metrics ***\nAccuracy: 50.0% +/- 69.3% | n = 2\n",
            "",
            0.05,
            tuple(command),
        )

    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        hle_process_runner=fake,
        run_id="hle-half",
    )
    rows = read_evidence_jsonl(evidence)
    assert len(rows) == 1
    assert all(abs(r.partial_score - 0.5) < 1e-9 for r in rows)
    assert all(not r.primary_pass for r in rows)
    assert all(r.counts_toward_pass_at_k is True for r in rows)
