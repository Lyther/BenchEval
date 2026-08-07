"""Regressions for review Round 1 identity, provider, and gate findings.

SUBSTITUTE_JUSTIFICATION
- substitute: Inspect-shaped GPQA log and injected GPQA/HLE process runners in the
  adapter tests below
- replaces: charged external model calls through Inspect Evals and CAIS HLE
- necessity: the assertions require hostile task/model identity and exact child
  environment capture; real provider calls cannot safely and deterministically
  produce those conditions without charging or admitting intentionally wrong evidence
- real-option: installed Inspect/HLE harnesses were considered, but their live calls
  cannot deterministically emit a mismatched task identity or expose the child env
- proof-limit: these tests prove local admission and launch contracts only, not live
  provider reachability or official benchmark acceptance
- real-proof: BLOCKED until a provisioned dev-box runs GPQA/HLE with real credentials
  and retains the official log/judged artifacts
"""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.gpqa_adapter import GpqaCliResult, build_gpqa_run_command
from bencheval.hle_adapter import HleCliResult, hle_run_paths, run_hle_slice


def _gpqa_log(*, task: str, model: str) -> dict[str, object]:
    return {
        "version": 2,
        "status": "success",
        "eval": {
            "task": task,
            "task_id": "review-task",
            "model": model,
        },
        "results": {
            "total_samples": 2,
            "completed_samples": 2,
            "scores": [
                {
                    "name": "choice",
                    "scorer": "choice",
                    "metrics": {
                        "accuracy": {
                            "name": "accuracy",
                            "value": 1.0,
                        },
                    },
                },
            ],
        },
    }


def test_gpqa_rejects_complete_log_for_unrelated_task(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    evidence = tmp_path / "evidence.jsonl"

    def wrong_task_runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str] | None = None,
    ) -> GpqaCliResult:
        del cwd, timeout_sec, env
        model = command[command.index("--model") + 1]
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_path = log_dir / "wrong-task.json"
        log_path.write_text(
            json.dumps(_gpqa_log(task="unrelated_eval", model=model)),
            encoding="utf-8",
        )
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.01, tuple(command))

    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "artifacts",
        gpqa_process_runner=wrong_task_runner,
        run_id="wrong-task",
    )

    row = read_evidence_jsonl(evidence)[0]
    assert row.primary_pass is False
    assert row.counts_toward_pass_at_k is False
    assert row.verifier_integrity_label is None
    assert row.failure_class == "runtime_output_unparseable"


def test_gpqa_rejects_log_path_outside_claimed_log_dir(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    evidence = tmp_path / "evidence.jsonl"

    def external_log_runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str] | None = None,
    ) -> GpqaCliResult:
        del cwd, timeout_sec, env
        model = command[command.index("--model") + 1]
        log_path = tmp_path / "outside" / "gpqa.json"
        log_path.parent.mkdir()
        log_path.write_text(
            json.dumps(_gpqa_log(task="gpqa_diamond", model=model)),
            encoding="utf-8",
        )
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.01, tuple(command))

    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "artifacts",
        gpqa_process_runner=external_log_runner,
        run_id="external-log",
    )

    row = read_evidence_jsonl(evidence)[0]
    assert row.primary_pass is False
    assert row.counts_toward_pass_at_k is False
    assert row.verifier_integrity_label is None


def test_gpqa_rejects_model_override_that_changes_planned_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    monkeypatch.setenv("BENCHEVAL_INSPECT_MODEL", "openai/unrelated-model")

    with pytest.raises(BenchEvalError, match="planned model"):
        build_gpqa_run_command(plan=plan, sample_limit=2, log_dir=tmp_path)


def test_gpqa_runner_receives_provider_bound_openai_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    monkeypatch.setenv("BYTELLM_API_KEY", "review-provider-key")
    monkeypatch.setenv("BYTELLM_BASE_URL", "http://127.0.0.1:4400")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    captured: dict[str, str] = {}

    def capture_env_runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> GpqaCliResult:
        del cwd, timeout_sec
        captured.update(env)
        model = command[command.index("--model") + 1]
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_path = log_dir / "gpqa.json"
        log_path.write_text(
            json.dumps(_gpqa_log(task="gpqa_diamond", model=model)),
            encoding="utf-8",
        )
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.01, tuple(command))

    execute_control_plane_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=tmp_path / "artifacts",
        gpqa_process_runner=capture_env_runner,
        run_id="provider-env",
    )

    assert captured["OPENAI_API_KEY"] == "review-provider-key"
    assert captured["OPENAI_BASE_URL"] == "http://127.0.0.1:4400/v1"
    assert "OPENAI_API_KEY" not in os.environ
    assert "OPENAI_BASE_URL" not in os.environ


def test_hle_runner_receives_provider_bound_openai_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "hle"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# test entrypoint\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# test entrypoint\n", encoding="utf-8")
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    monkeypatch.setenv("BYTELLM_API_KEY", "review-provider-key")
    monkeypatch.setenv("BYTELLM_BASE_URL", "http://127.0.0.1:4400/")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    artifacts = tmp_path / "artifacts"
    paths = hle_run_paths(
        artifacts_dir=artifacts,
        run_id="provider-env",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    captured: list[Mapping[str, str]] = []

    def capture_env_runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> HleCliResult:
        del timeout_sec
        captured.append(env)
        assert cwd == paths.work_dir
        if "run_model_predictions.py" in command[1]:
            paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
        else:
            paths.judged_path.write_text(
                json.dumps(
                    {
                        "0": {"judge_response": {"correct": "yes"}},
                        "1": {"judge_response": {"correct": "yes"}},
                    },
                ),
                encoding="utf-8",
            )
        return HleCliResult(0, "", "", 0.01, tuple(command))

    run_hle_slice(
        plan=plan,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=capture_env_runner,
        run_id="provider-env",
    )

    assert len(captured) == 2
    assert all(env["OPENAI_API_KEY"] == "review-provider-key" for env in captured)
    assert all(env["OPENAI_BASE_URL"] == "http://127.0.0.1:4400/v1" for env in captured)
    assert "OPENAI_API_KEY" not in os.environ
    assert "OPENAI_BASE_URL" not in os.environ


@pytest.mark.parametrize(
    "relative_path",
    [
        "tests/test_doctor.py",
        "tests/test_production_v1_cli.py",
        "tests/test_terminal_bench_harbor.py",
        "tests/test_swebench_adapter.py",
        "tests/test_external_agent_adapter.py",
        "tests/test_regressions_swarm.py",
    ],
)
def test_gate_counted_substitute_files_have_traceable_justification(relative_path: str) -> None:
    content = Path(relative_path).read_text(encoding="utf-8")
    assert "SUBSTITUTE_JUSTIFICATION" in content, relative_path


def test_domain_coverage_gate_is_executable_wired_and_scoped() -> None:
    coverage_path = Path("scripts/check-domain-coverage.sh")
    production_gate = Path("scripts/check-production-v1.sh").read_text(encoding="utf-8")
    coverage_gate = coverage_path.read_text(encoding="utf-8")

    assert coverage_path.stat().st_mode & stat.S_IXUSR
    assert "check-domain-coverage.sh" in production_gate
    assert "coverage report" in coverage_gate
    assert "--include=" not in coverage_gate


def test_scripts_readme_matches_terminal_bench_only_live_matrix() -> None:
    scripts_readme = Path("scripts/README.md").read_text(encoding="utf-8")
    assert "Phase B live Terminal-Bench runtime matrix" in scripts_readme
    assert "live TB/BFCL/SWE matrix" not in scripts_readme
