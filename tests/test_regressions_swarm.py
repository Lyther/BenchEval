"""Regression tests for swarm-identified bugs (2026-06-18)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import build_bfcl_run_command
from bencheval.control_plane_executor import (
    control_plane_interpretation_label,
    execute_control_plane_run,
)
from bencheval.domain import RunPlan
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError, TaskContractError
from bencheval.path_safety import ensure_resolved_under_root
from bencheval.task_registry import resolve_task_path
from bencheval.terminal_bench_harbor import build_harbor_run_command


def test_resolve_task_path_rejects_path_outside_tasks_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside-task.yaml"
    outside.write_text("task: {}\n", encoding="utf-8")
    with pytest.raises(TaskContractError, match="outside tasks root"):
        resolve_task_path(str(outside))


def test_run_execute_payload_interpretation_not_comparison_validity_key(
    tmp_path: Path,
) -> None:
    from bencheval.bfcl_native_adapter import BfclCliResult

    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id="native-api",
        model_id="openai/gpt-test",
    )
    assert plan.comparison_validity == "model_comparison"
    assert control_plane_interpretation_label(plan) == "model_comparison"

    evidence_path = tmp_path / "evidence.jsonl"

    def fake_runner(command, *, cwd: Path | None, timeout_sec: int) -> BfclCliResult:
        out_dir = Path(command[command.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "verdict.json").write_text(
            json.dumps({"primary_pass": True}),
            encoding="utf-8",
        )
        return BfclCliResult(0, "", "", 0.1, tuple(command))

    execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "art",
        bfcl_process_runner=fake_runner,
        run_id="regression-run",
    )
    row = read_evidence_jsonl(evidence_path)[0]
    assert row.interpretation_label == "model_comparison"


def test_cli_run_stdout_includes_interpretation_and_comparison_validity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from bencheval.bfcl_native_adapter import BfclCliResult, run_bfcl_instance
    from bencheval.cli import main

    def fake_runner(command, *, cwd: Path | None, timeout_sec: int) -> BfclCliResult:
        out_dir = Path(command[command.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "verdict.json").write_text(
            json.dumps({"primary_pass": True}),
            encoding="utf-8",
        )
        return BfclCliResult(0, "", "", 0.1, tuple(command))

    def patched_run(
        *,
        plan: RunPlan,
        instance_id: str,
        artifacts_dir: Path,
        repo_root: Path,
        process_runner=None,
        timeout_sec: int | None = None,
        harness_version: str | None = None,
    ):
        return run_bfcl_instance(
            plan=plan,
            instance_id=instance_id,
            artifacts_dir=artifacts_dir,
            repo_root=repo_root,
            process_runner=fake_runner,
            timeout_sec=timeout_sec,
            harness_version=harness_version,
        )

    monkeypatch.setattr(
        "bencheval.control_plane_executor.run_bfcl_instance",
        patched_run,
    )
    out = tmp_path / "evidence.jsonl"
    assert (
        main(
            [
                "run",
                "--benchmark",
                "bfcl-v4",
                "--slice",
                "smoke-5",
                "--runtime",
                "native-api",
                "--model",
                "openai/gpt-test",
                "--output",
                str(out),
            ],
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["comparison_validity"] == "model_comparison"
    assert payload["interpretation_label"] == "model_comparison"


def test_ensure_resolved_under_root_rejects_embedded_null(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(BenchEvalError, match="invalid"):
        ensure_resolved_under_root(root / "\x00", root, what="workspace")


def test_ensure_resolved_under_root_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "escape"
    outside.mkdir()
    with pytest.raises(BenchEvalError, match="escapes repository root"):
        ensure_resolved_under_root(outside, root, what="workspace")


def test_build_harbor_run_command_rejects_unsafe_instance_id(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="runtime-default",
    )
    with pytest.raises(BenchEvalError, match="invalid instance_id"):
        build_harbor_run_command(
            plan=plan,
            instance_id="../evil",
            artifacts_dir=tmp_path / "art",
        )


def test_build_bfcl_run_command_rejects_unsafe_instance_id() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id="native-api",
        model_id="openai/gpt-test",
    )
    with pytest.raises(BenchEvalError, match="invalid instance_id"):
        build_bfcl_run_command(
            plan=plan,
            instance_id="../etc/passwd",
            artifacts_dir=Path("/tmp/out"),
        )


def test_execute_control_plane_run_unknown_adapter_raises(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id="native-api",
        model_id="openai/gpt-test",
    )
    bad_plan = plan.model_copy(update={"adapter_id": "not-a-real-adapter"})
    with pytest.raises(BenchEvalError, match="no executor for adapter_id"):
        execute_control_plane_run(
            plan=bad_plan,
            output_path=tmp_path / "out.jsonl",
            bfcl_process_runner=lambda *a, **k: None,
        )


def test_ensure_resolved_under_root_accepts_child_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    child = root / "tasks" / "t.yaml"
    child.parent.mkdir(parents=True)
    child.touch()
    resolved = ensure_resolved_under_root(child, root, what="task")
    assert resolved == child.resolve()


def test_cybench_catalog_not_manifest_available() -> None:
    from bencheval.benchmark_registry import load_benchmark_catalog

    catalog = load_benchmark_catalog()
    entry = next(b for b in catalog.benchmarks if b.id == "cybench")
    assert entry.adapter_status != "manifest_available"
