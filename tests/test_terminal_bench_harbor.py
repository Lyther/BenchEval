"""Terminal-Bench Harbor adapter unit tests (injected process runner)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError
from bencheval.terminal_bench_harbor import (
    HarborCliResult,
    build_harbor_run_command,
    harbor_agent_for_runtime,
    parse_harbor_instance_outcome,
    run_terminal_bench_instance,
)


def test_build_harbor_run_command_claude_code() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="runtime-default",
    )
    cmd = build_harbor_run_command(
        plan=plan,
        instance_id="tb-smoke-001",
        artifacts_dir=Path("/tmp/out"),
    )
    assert cmd[0:4] == ("harbor", "run", "--dataset", "terminal-bench@2.0")
    assert "--agent" in cmd and "claude-code" in cmd
    assert "--task" in cmd and "tb-smoke-001" in cmd


def test_parse_success_from_result_json(tmp_path: Path) -> None:
    repo = tmp_path
    art = tmp_path / "inst"
    art.mkdir()
    (art / "result.json").write_text(
        json.dumps({"resolved": True, "cost_usd": 1.5}),
        encoding="utf-8",
    )
    cli = HarborCliResult(
        returncode=0,
        stdout="ok",
        stderr="",
        latency_sec=2.0,
        command=("harbor", "run"),
    )
    out = parse_harbor_instance_outcome(
        instance_id="tb-smoke-001",
        cli=cli,
        artifacts_dir=art,
        repo_root=repo,
        harness_version="harbor-test",
    )
    assert out.primary_pass is True
    assert out.partial_score == 1.0
    assert out.cost_usd == 1.5
    assert out.native_score.get("resolved") is True


def test_parse_rc0_without_result_json_is_harness_failure(tmp_path: Path) -> None:
    art = tmp_path / "inst"
    art.mkdir()
    cli = HarborCliResult(0, "", "", 0.1, ("harbor", "run"))
    out = parse_harbor_instance_outcome(
        instance_id="tb-smoke-001",
        cli=cli,
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version=None,
    )
    assert out.primary_pass is False
    assert out.failure_class == "harness_failure"


def test_execute_control_plane_smoke_writes_evidence(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="runtime-default",
    )
    evidence_path = tmp_path / "evidence.jsonl"

    def fake_runner(
        command,
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> HarborCliResult:
        assert command[command.index("--agent") + 1] == harbor_agent_for_runtime("claude-code")
        task_id = command[command.index("--task") + 1]
        assert task_id.startswith("tb-smoke-")
        out_dir = Path(command[command.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text(
            json.dumps({"resolved": True}),
            encoding="utf-8",
        )
        return HarborCliResult(
            returncode=0,
            stdout="",
            stderr="",
            latency_sec=0.1,
            command=tuple(command),
        )

    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        harbor_process_runner=fake_runner,
        run_id="test-run-tb",
    )
    assert summary.instance_count == 5
    assert summary.passed_count == 5
    rows = read_evidence_jsonl(evidence_path)
    assert len(rows) == 5
    first = rows[0]
    assert first.benchmark_id == "terminal-bench"
    assert first.slice_id == "smoke-5"
    assert first.runtime_id == "claude-code"
    assert first.adapter_id == "terminal-bench-harbor"
    assert first.harness_kind == "harbor"
    assert first.interpretation_label == "adapter_smoke"


def test_per_instance_timeout_derived_from_plan(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="codex-cli",
        model_id="runtime-default",
    )
    seen_timeout: list[int] = []

    def capture_timeout(command, *, cwd, timeout_sec: int):
        seen_timeout.append(timeout_sec)
        out_dir = Path(command[command.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text('{"resolved": true}', encoding="utf-8")
        return HarborCliResult(0, "", "", 0.0, tuple(command))

    run_terminal_bench_instance(
        plan=plan,
        instance_id="tb-smoke-001",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=capture_timeout,
    )
    assert seen_timeout == [max(plan.max_wall_clock_sec // 5, 60)]


def test_run_terminal_bench_instance_timeout_raises_budget_exceeded(tmp_path: Path) -> None:
    import subprocess

    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="codex-cli",
        model_id="runtime-default",
    )

    def timeout_runner(command, *, cwd, timeout_sec: int):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout_sec)

    with pytest.raises(AdapterFailureError, match="timed out") as exc_info:
        run_terminal_bench_instance(
            plan=plan,
            instance_id="tb-smoke-001",
            artifacts_dir=tmp_path / "a",
            repo_root=tmp_path,
            process_runner=timeout_runner,
            timeout_sec=1,
        )
    assert exc_info.value.failure_label == "runtime_budget_exceeded"


def test_harbor_executor_adapter_failure_on_second_instance_writes_two_rows(
    tmp_path: Path,
) -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="runtime-default",
    )
    two_inst = plan.model_copy(update={"instances": plan.instances[:2]})
    evidence_path = tmp_path / "evidence.jsonl"
    call_count = 0

    def alternating_runner(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        nonlocal call_count
        call_count += 1
        out_dir = Path(command[command.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        if call_count == 1:
            (out_dir / "result.json").write_text(
                json.dumps({"resolved": True}),
                encoding="utf-8",
            )
            return HarborCliResult(0, "", "", 0.1, tuple(command))
        raise AdapterFailureError(
            "injected harbor failure",
            failure_label="harness_failure",
        )

    summary = execute_control_plane_run(
        plan=two_inst,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        harbor_process_runner=alternating_runner,
        run_id="tb-partial-fail",
    )
    assert summary.instance_count == 2
    assert summary.passed_count == 1
    assert summary.failed_count == 1
    rows = read_evidence_jsonl(evidence_path)
    assert len(rows) == 2
    assert rows[0].primary_pass is True
    assert rows[1].primary_pass is False
    assert "harness_failure" in rows[1].failure_labels


def test_run_instance_harness_failure(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="codex-cli",
        model_id="runtime-default",
    )

    def fail_runner(command, *, cwd, timeout_sec):
        out_dir = Path(command[command.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        return HarborCliResult(
            returncode=1,
            stdout="",
            stderr="boom",
            latency_sec=0.2,
            command=tuple(command),
        )

    out = run_terminal_bench_instance(
        plan=plan,
        instance_id="tb-smoke-001",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=fail_runner,
        timeout_sec=60,
    )
    assert out.primary_pass is False
    assert out.failure_class == "harness_failure"
