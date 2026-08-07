"""Regression tests for swarm-identified bugs (2026-06-18)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import (
    control_plane_interpretation_label,
    execute_control_plane_run,
)
from bencheval.domain import RunPlan
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.gpqa_adapter import GpqaCliResult, build_gpqa_run_command
from bencheval.path_safety import ensure_resolved_under_root
from bencheval.terminal_bench_harbor import build_harbor_run_command

# SUBSTITUTE_JUSTIFICATION
# - substitute: injected GPQA runners and monkeypatched run_gpqa_slice in
#   test_run_execute_payload_interpretation_not_comparison_validity_key and
#   test_cli_run_execute_writes_interpretation_on_evidence
# - replaces: charged Inspect GPQA call while retaining planning/scoring/evidence/CLI code
# - necessity: exact deterministic score and a non-dry CLI run are required without charge
# - real-option: live Inspect GPQA cannot guarantee the score fixture
# - proof-limit: proves interpretation propagation only, not live GPQA acceptance
# - real-proof: BLOCKED until a real GPQA dev-box pilot retains its Inspect artifact


def test_run_execute_payload_interpretation_not_comparison_validity_key(
    tmp_path: Path,
) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    assert plan.comparison_validity == "adapter_smoke"
    assert control_plane_interpretation_label(plan) == "adapter_smoke"

    evidence_path = tmp_path / "evidence.jsonl"

    def fake_runner(command, *, cwd: Path | None, timeout_sec: int, env=None) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "done.json"
        log_path.write_text(
            json.dumps(
                {
                    "version": 2,
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
            ),
            encoding="utf-8",
        )
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.1, tuple(command))

    execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "art",
        gpqa_process_runner=fake_runner,
        run_id="regression-run",
    )
    row = read_evidence_jsonl(evidence_path)[0]
    assert row.interpretation_label == "adapter_smoke"


def test_cli_run_dry_run_includes_comparison_validity(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from bencheval.cli import main

    assert main(["run", "gpqa-diamond/smoke", "--model", "kimi-k2.7-code", "--dry-run"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["comparison_validity"] == "adapter_smoke"
    assert payload["runtime_id"] is None


def test_cli_run_execute_writes_interpretation_on_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval.cli import main
    from bencheval.gpqa_adapter import run_gpqa_slice

    monkeypatch.setenv("BYTELLM_API_KEY", "diagnostic-provider-key")

    def fake_runner(command, *, cwd: Path | None, timeout_sec: int, env=None) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "done.json"
        log_path.write_text(
            json.dumps(
                {
                    "version": 2,
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
            ),
            encoding="utf-8",
        )
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.1, tuple(command))

    def patched_run(
        *,
        plan: RunPlan,
        artifacts_dir: Path,
        repo_root: Path,
        process_runner=None,
        timeout_sec: int | None = None,
    ):
        return run_gpqa_slice(
            plan=plan,
            artifacts_dir=artifacts_dir,
            repo_root=repo_root,
            process_runner=fake_runner,
            timeout_sec=timeout_sec,
        )

    monkeypatch.setattr(
        "bencheval.control_plane_executor.run_gpqa_slice",
        patched_run,
    )
    out = tmp_path / "evidence.jsonl"
    assert (
        main(
            [
                "run",
                "gpqa-diamond/smoke",
                "--model",
                "kimi-k2.7-code",
                "--output",
                str(out),
                "-y",
            ],
        )
        == 0
    )
    rows = read_evidence_jsonl(out)
    assert rows
    assert rows[0].interpretation_label == "adapter_smoke"


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
        model_id="kimi-k2.7-code",
    )
    with pytest.raises(BenchEvalError, match="invalid instance_id"):
        build_harbor_run_command(
            plan=plan,
            instance_id="../evil",
            artifacts_dir=tmp_path / "art",
        )


def test_build_gpqa_run_command_rejects_unsafe_instance_id() -> None:
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


def test_execute_control_plane_run_unknown_adapter_raises(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    bad_plan = plan.model_copy(update={"adapter_id": "not-a-real-adapter"})
    with pytest.raises(BenchEvalError, match="no executor for adapter_id"):
        execute_control_plane_run(
            plan=bad_plan,
            output_path=tmp_path / "out.jsonl",
            gpqa_process_runner=lambda *a, **k: None,
        )


def test_ensure_resolved_under_root_accepts_child_path(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    child = root / "tasks" / "t.yaml"
    child.parent.mkdir(parents=True)
    child.touch()
    resolved = ensure_resolved_under_root(child, root, what="task")
    assert resolved == child.resolve()
