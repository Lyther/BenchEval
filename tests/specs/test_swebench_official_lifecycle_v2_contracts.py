"""RED contracts for SWE-bench Verified's diagnostic two-phase lifecycle.

The selected route generates one prediction with the locked Inspect Evals /
Inspect SWE runtime integration and then invokes official ``swebench`` as the
sole scorer.  The catalog remains non-executable and this contract cannot
promote it.

SUBSTITUTE_JUSTIFICATION
- substitute: injected ``process_runner`` callables and planted
  ``predictions.jsonl`` / ``report.json`` files
- replaces: a charged Inspect/provider generation call and Docker-backed
  official SWE-bench evaluation
- necessity: exact phase ordering, missing-prediction fail-closed, official
  log materialize, exhausted-budget refusal, and command propagation require
  deterministic observation; a real model call is charged and cannot guarantee
  those outcomes
- real-option: a real pinned one-instance diagnostic on the dev-box is required
  after the identity/dependency contract is complete, but it cannot
  deterministically expose the orchestration boundary or negative states
- proof-limit: diagnostic command/orchestration contract only; it does not prove
  provider behavior, Inspect solver parity, Docker evaluation, dataset/image
  identity, score truth, live readiness, or catalog admission
- real-proof: uncharged official-evaluator dummy
  ``results/raw/swe-dummy-patch-20260825T1748Z/`` on the operator host. A
  charged diagnostic is still BLOCKED until dataset/revision/image identity is
  pinned and ``swebench`` is an explicit dependency
- covered tests: test_generation_command_uses_the_selected_inspect_runtime_solver,
  test_run_instance_orders_generation_before_official_scoring,
  test_missing_predictions_fail_closed_without_scoring_generate_report,
  test_run_instance_materializes_official_eval_report_from_logs,
  test_default_runner_is_disabled_until_identity_contract_complete,
  test_exhausted_generation_budget_does_not_launch_eval
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.swebench_adapter import (
    SwebenchCliResult,
    build_swebench_run_command,
    run_swebench_instance,
)

_INSTANCE_ID = "django__django-11099"


def _diagnostic_plan():
    return plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
        diagnostic=True,
    )


def test_generation_command_uses_the_selected_inspect_runtime_solver() -> None:
    plan = _diagnostic_plan()

    command = build_swebench_run_command(
        plan=plan,
        instance_id=_INSTANCE_ID,
        artifacts_dir=Path("run-owned"),
    )

    assert command[:3] == ("inspect", "eval", "inspect_evals/swe_bench")
    assert "--sample-id" in command
    assert command[command.index("--sample-id") + 1] == _INSTANCE_ID
    assert "--solver" in command
    assert command[command.index("--solver") + 1] == "inspect_swe/codex_cli"
    assert "version=0.148.0" in command
    assert "mini-extra" not in command
    assert "--instance" not in command
    assert "--output-dir" not in command


def test_run_instance_orders_generation_before_official_scoring(tmp_path: Path) -> None:
    plan = _diagnostic_plan()
    artifacts = tmp_path / "artifacts"
    commands: list[tuple[str, ...]] = []

    def _runner(
        command: object,
        *,
        cwd: object,
        timeout_sec: object,
    ) -> SwebenchCliResult:
        argv = tuple(str(part) for part in command)
        commands.append(argv)
        instance_root = artifacts / _INSTANCE_ID
        if len(commands) == 1:
            (instance_root / "predictions.jsonl").write_text(
                json.dumps(
                    {
                        "instance_id": _INSTANCE_ID,
                        "model_name_or_path": "kimi-k2.7-code",
                        "model_patch": "diff --git a/a b/a\n",
                    },
                )
                + "\n",
                encoding="utf-8",
            )
        elif len(commands) == 2:
            (instance_root / "report.json").write_text(
                json.dumps({_INSTANCE_ID: {"resolved": True}}),
                encoding="utf-8",
            )
        return SwebenchCliResult(
            returncode=0,
            stdout=f"phase-{len(commands)}",
            stderr="",
            latency_sec=1.0,
            command=argv,
        )

    outcome = run_swebench_instance(
        plan=plan,
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=_runner,
        timeout_sec=30,
        run_id="swe-eval-lifecycle",
    )

    assert len(commands) == 2
    assert commands[0][:3] == ("inspect", "eval", "inspect_evals/swe_bench")
    assert commands[1][:3] == ("swebench", "eval", "verified")
    assert "-p" in commands[1]
    assert "-i" in commands[1]
    assert commands[1][commands[1].index("-i") + 1] == _INSTANCE_ID
    assert "-j" in commands[1]
    assert commands[1][commands[1].index("-j") + 1] == "1"
    assert commands[1][commands[1].index("--run-id") + 1] == "swe-eval-lifecycle"
    assert commands[1][commands[1].index("--report-dir") + 1] == str(artifacts / _INSTANCE_ID)
    assert outcome.primary_pass is True
    assert outcome.adapter_metadata["interpretation_label"] == "diagnostic_only"


def test_missing_predictions_fail_closed_without_scoring_generate_report(
    tmp_path: Path,
) -> None:
    plan = _diagnostic_plan()
    artifacts = tmp_path / "artifacts"
    commands: list[tuple[str, ...]] = []

    def _runner(
        command: object,
        *,
        cwd: object,
        timeout_sec: object,
    ) -> SwebenchCliResult:
        argv = tuple(str(part) for part in command)
        commands.append(argv)
        instance_root = artifacts / _INSTANCE_ID
        instance_root.mkdir(parents=True, exist_ok=True)
        (instance_root / "report.json").write_text(
            json.dumps({_INSTANCE_ID: {"resolved": True}}),
            encoding="utf-8",
        )
        return SwebenchCliResult(
            returncode=0,
            stdout="inspect-eval-only",
            stderr="",
            latency_sec=1.0,
            command=argv,
        )

    outcome = run_swebench_instance(
        plan=plan,
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=_runner,
        timeout_sec=30,
        run_id="swe-eval-missing-preds",
    )

    assert commands == [commands[0]]
    assert commands[0][:3] == ("inspect", "eval", "inspect_evals/swe_bench")
    assert all(command[:2] != ("swebench", "eval") for command in commands)
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"
    assert outcome.adapter_metadata["missing_artifact"] == "predictions.jsonl"


def test_run_instance_materializes_official_eval_report_from_logs(tmp_path: Path) -> None:
    plan = _diagnostic_plan()
    artifacts = tmp_path / "artifacts"
    run_id = "swe-eval-logs"
    commands: list[tuple[str, ...]] = []

    def _runner(
        command: object,
        *,
        cwd: object,
        timeout_sec: object,
    ) -> SwebenchCliResult:
        argv = tuple(str(part) for part in command)
        commands.append(argv)
        instance_root = artifacts / _INSTANCE_ID
        if len(commands) == 1:
            (instance_root / "predictions.jsonl").write_text(
                json.dumps(
                    {
                        "instance_id": _INSTANCE_ID,
                        "model_name_or_path": "kimi-k2.7-code",
                        "model_patch": "diff --git a/a b/a\n",
                    },
                )
                + "\n",
                encoding="utf-8",
            )
        elif len(commands) == 2:
            official = (
                instance_root
                / "logs"
                / "run_evaluation"
                / run_id
                / "kimi-k2.7-code"
                / _INSTANCE_ID
                / "report.json"
            )
            official.parent.mkdir(parents=True)
            official.write_text(
                json.dumps({_INSTANCE_ID: {"resolved": True}}),
                encoding="utf-8",
            )
        return SwebenchCliResult(
            returncode=0,
            stdout=f"phase-{len(commands)}",
            stderr="",
            latency_sec=1.0,
            command=argv,
        )

    outcome = run_swebench_instance(
        plan=plan,
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=_runner,
        timeout_sec=30,
        run_id=run_id,
    )

    assert len(commands) == 2
    assert outcome.primary_pass is True
    assert (artifacts / _INSTANCE_ID / "report.json").is_file()


def test_default_runner_is_disabled_until_identity_contract_complete(tmp_path: Path) -> None:
    with pytest.raises(BenchEvalError, match="disabled until the diagnostic"):
        run_swebench_instance(
            plan=_diagnostic_plan(),
            instance_id=_INSTANCE_ID,
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
        )


def test_exhausted_generation_budget_does_not_launch_eval(tmp_path: Path) -> None:
    commands: list[tuple[str, ...]] = []

    def _runner(
        command: object,
        *,
        cwd: object,
        timeout_sec: object,
    ) -> SwebenchCliResult:
        argv = tuple(str(part) for part in command)
        commands.append(argv)
        instance_root = tmp_path / "artifacts" / _INSTANCE_ID
        instance_root.mkdir(parents=True, exist_ok=True)
        (instance_root / "predictions.jsonl").write_text("{}\n", encoding="utf-8")
        return SwebenchCliResult(0, "generate", "", 30.0, argv)

    with pytest.raises(AdapterFailureError, match="no remaining wall budget") as excinfo:
        run_swebench_instance(
            plan=_diagnostic_plan(),
            instance_id=_INSTANCE_ID,
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=_runner,
            timeout_sec=30,
            run_id="swe-eval-exhausted",
        )

    assert excinfo.value.failure_label == "runtime_budget_exceeded"
    assert commands == [commands[0]]
    assert commands[0][:3] == ("inspect", "eval", "inspect_evals/swe_bench")
