"""SWE-bench adapter unit tests (injected process runner)."""

from __future__ import annotations

import json
from pathlib import Path

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError
from bencheval.swebench_adapter import (
    SWEBENCH_ADAPTER_ID,
    SwebenchCliResult,
    build_swebench_run_command,
    parse_swebench_instance_outcome,
    run_swebench_instance,
)


def test_build_swebench_run_command() -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="mini-swe-agent",
        model_id="openai/gpt-test",
    )
    cmd = build_swebench_run_command(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=Path("/tmp/out"),
    )
    assert cmd[:2] == ("mini-extra", "swebench")
    assert "django__django-11099" in cmd
    assert "--model" in cmd and "openai/gpt-test" in cmd


def test_parse_verifier_and_diff(tmp_path: Path) -> None:
    art = tmp_path / "inst"
    art.mkdir()
    (art / "verifier.json").write_text(
        json.dumps({"resolved": True, "tests_passed": True, "cost_usd": 0.25}),
        encoding="utf-8",
    )
    (art / "workspace.diff").write_text("diff --git a/foo b/foo\n", encoding="utf-8")
    cli = SwebenchCliResult(0, "ok", "", 1.0, ("mini-swe-agent", "run"))
    out = parse_swebench_instance_outcome(
        instance_id="django__django-11099",
        cli=cli,
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="swebench-test",
    )
    assert out.primary_pass is True
    assert out.workspace_diff_path is not None
    assert out.verifier_log_path is not None
    assert out.native_score.get("resolved") is True


def test_execute_swebench_smoke_writes_evidence(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="mini-swe-agent",
        model_id="openai/gpt-test",
    )
    assert plan.adapter_id == SWEBENCH_ADAPTER_ID
    evidence_path = tmp_path / "evidence.jsonl"

    def fake_runner(command, *, cwd: Path | None, timeout_sec: int) -> SwebenchCliResult:
        out_dir = Path(command[command.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "verifier.json").write_text(
            json.dumps({"resolved": True}),
            encoding="utf-8",
        )
        (out_dir / "workspace.diff").write_text("patch\n", encoding="utf-8")
        return SwebenchCliResult(0, "", "", 0.5, tuple(command))

    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        swebench_process_runner=fake_runner,
        run_id="test-run-swe",
    )
    assert summary.instance_count == 10
    assert summary.passed_count == 10
    rows = read_evidence_jsonl(evidence_path)
    assert len(rows) == 10
    first = rows[0]
    assert first.benchmark_id == "swe-bench-verified"
    assert first.interpretation_label == "contaminated_or_legacy"
    assert first.contamination_label == "public_possible"
    assert first.adapter_id == SWEBENCH_ADAPTER_ID
    assert first.harness_kind == "swebench-native"
    assert any("workspace.diff" in p or "verifier" in p for p in first.artifact_paths)


def test_run_instance_single(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="mini-swe-agent",
        model_id="openai/gpt-test",
    )

    def fake_runner(command, *, cwd, timeout_sec):
        out_dir = Path(command[command.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text('{"resolved": false}', encoding="utf-8")
        return SwebenchCliResult(0, "", "", 0.1, tuple(command))

    out = run_swebench_instance(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=fake_runner,
    )
    assert out.primary_pass is False
    assert out.failure_class == "model_wrong_solution"


def test_parse_missing_verifier_on_success_rc_fails(tmp_path: Path) -> None:
    art = tmp_path / "empty"
    art.mkdir()
    cli = SwebenchCliResult(0, "", "", 0.1, ("mini-swe-agent",))
    out = parse_swebench_instance_outcome(
        instance_id="x",
        cli=cli,
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="v",
    )
    assert out.primary_pass is False
    assert out.failure_class == "harness_failure"


def test_swebench_adapter_failure_record_labels(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="mini-swe-agent",
        model_id="openai/gpt-test",
    )
    evidence_path = tmp_path / "evidence.jsonl"

    def fail_runner(command, *, cwd, timeout_sec):
        raise AdapterFailureError("boom", failure_label="harness_failure")

    execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "art",
        swebench_process_runner=fail_runner,
        run_id="fail-run",
    )
    row = read_evidence_jsonl(evidence_path)[0]
    assert row.backend == "inspect"
    assert row.interpretation_label == "contaminated_or_legacy"
    assert row.contamination_label == "public_possible"
