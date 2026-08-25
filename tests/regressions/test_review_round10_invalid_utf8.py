"""Regression coverage for malformed UTF-8 at executable adapter boundaries."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _invalid_utf8_command() -> tuple[str, ...]:
    return (
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(b'\\xff')",
    )


def test_terminal_bench_invalid_utf8_result_is_unparseable(tmp_path: Path) -> None:
    from bencheval.terminal_bench_harbor import (
        HarborCliResult,
        parse_harbor_instance_outcome,
    )

    artifacts_dir = tmp_path / "terminal-bench"
    artifacts_dir.mkdir()
    (artifacts_dir / "result.json").write_bytes(b"\xff")

    outcome = parse_harbor_instance_outcome(
        instance_id="tb-smoke-001",
        cli=HarborCliResult(0, "", "", 0.1, ("harbor", "run")),
        artifacts_dir=artifacts_dir,
        repo_root=tmp_path,
        harness_version="harbor@test",
    )

    assert outcome.primary_pass is False
    assert outcome.partial_score == 0.0
    assert outcome.failure_class == "runtime_output_unparseable"


def test_gpqa_invalid_utf8_inspect_log_is_unparseable(tmp_path: Path) -> None:
    from bencheval.gpqa_adapter import parse_gpqa_official_score

    log_dir = tmp_path / "inspect-logs"
    log_dir.mkdir()
    log_path = log_dir / "done.json"
    log_path.write_bytes(b"\xff")

    score = parse_gpqa_official_score(
        log_dir,
        expected_model="openai/test-model",
        stdout=f"Log: {log_path}\n",
    )

    assert score is None


def test_hle_invalid_utf8_judged_artifact_is_unparseable(tmp_path: Path) -> None:
    from bencheval.hle_adapter import parse_hle_official_score

    judged_path = tmp_path / "judged_hle_test-model.json.json"
    judged_path.write_bytes(b"\xff")

    score = parse_hle_official_score(
        eval_dir=tmp_path,
        model_id="test-model",
        judge_stdout="",
        max_samples=1,
        work_dir=tmp_path,
        judged_path=judged_path,
    )

    assert score is None


def test_bfcl_invalid_utf8_score_artifact_is_unparseable(tmp_path: Path) -> None:
    from bencheval.bfcl_native_adapter import BfclCliResult, parse_bfcl_instance_outcome

    score_dir = tmp_path / "scores"
    score_file = score_dir / "gpt-5.2-2025-12-11" / "non_live" / "BFCL_v4_simple_python_score.json"
    score_file.parent.mkdir(parents=True)
    score_file.write_bytes(b"\xff")

    outcome = parse_bfcl_instance_outcome(
        instance_id="simple_python",
        cli=BfclCliResult(0, "", "", 0.1, ("bfcl", "evaluate")),
        artifacts_dir=tmp_path / "artifacts",
        repo_root=tmp_path,
        harness_version="bfcl-eval@test",
        score_dir=score_dir,
        model_id="gpt-5.2-2025-12-11",
    )

    assert outcome.primary_pass is False
    assert outcome.partial_score == 0.0
    assert outcome.failure_class == "runtime_output_unparseable"


def test_terminal_bench_process_capture_replaces_invalid_utf8(tmp_path: Path) -> None:
    from bencheval.terminal_bench_harbor import _default_process_runner

    result = _default_process_runner(
        _invalid_utf8_command(),
        cwd=tmp_path,
        timeout_sec=10,
    )

    assert result.returncode == 0
    assert result.stdout == "\ufffd"


def test_gpqa_process_capture_replaces_invalid_utf8(tmp_path: Path) -> None:
    from bencheval.gpqa_adapter import _default_process_runner

    result = _default_process_runner(
        _invalid_utf8_command(),
        cwd=tmp_path,
        timeout_sec=10,
        env=os.environ,
    )

    assert result.returncode == 0
    assert result.stdout == "\ufffd"


def test_hle_process_capture_replaces_invalid_utf8(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _default_process_runner

    result = _default_process_runner(
        _invalid_utf8_command(),
        cwd=tmp_path,
        timeout_sec=10,
        env=os.environ,
    )

    assert result.returncode == 0
    assert result.stdout == "\ufffd"


def test_bfcl_process_capture_replaces_invalid_utf8(tmp_path: Path) -> None:
    from bencheval.bfcl_native_adapter import _default_process_runner

    result = _default_process_runner(
        _invalid_utf8_command(),
        cwd=tmp_path,
        timeout_sec=10,
        env=os.environ,
    )

    assert result.returncode == 0
    assert result.stdout == "\ufffd"


def test_external_agent_process_capture_replaces_invalid_utf8(tmp_path: Path) -> None:
    from bencheval.external_agent_adapter import _default_process_runner

    result = _default_process_runner(
        _invalid_utf8_command(),
        cwd=tmp_path,
        timeout_sec=10,
    )

    assert result.returncode == 0
    assert result.stdout == "\ufffd"


def test_runtime_version_capture_replaces_invalid_utf8() -> None:
    from bencheval.control_plane_executor import _run_version_command

    assert _run_version_command(_invalid_utf8_command()) == "\ufffd"
