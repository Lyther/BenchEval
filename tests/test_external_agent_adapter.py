"""External agent adapter: failed attempts still emit EvidenceRecord."""

from __future__ import annotations

from pathlib import Path

import pytest

from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.external_agent_adapter import ExternalAgentCliResult, execute_external_agent_run
from tests.factories import make_scaffold_agent_plan

# SUBSTITUTE_JUSTIFICATION
# - substitute: failing_runner in test_failed_agent_attempt_writes_runtime_tool_failure and
#   test_agent_launch_failure_still_writes_evidence
# - replaces: controlled nonzero external-agent result and OS launch failure
# - necessity: the two distinct failure boundaries cannot be guaranteed by a real agent
# - real-option: a disposable process cannot deterministically reproduce OS launch failure
# - proof-limit: proves failure labeling/evidence emission only, not agent execution
# - real-proof: BLOCKED until a real admitted external-agent lane is provisioned


def test_failed_agent_attempt_writes_runtime_tool_failure(tmp_path: Path) -> None:
    plan = make_scaffold_agent_plan()
    out = tmp_path / "evidence.jsonl"

    def failing_runner(command, *, cwd, timeout_sec):
        return ExternalAgentCliResult(
            returncode=1,
            stdout="",
            stderr="boom",
            latency_sec=0.01,
            command=tuple(command),
        )

    summary = execute_external_agent_run(
        plan=plan,
        output_path=out,
        artifacts_dir=tmp_path / "raw",
        process_runner=failing_runner,
        run_id="run-agent-fail",
    )
    assert summary.failed_count == summary.instance_count
    rows = list(read_evidence_jsonl(out))
    assert len(rows) == summary.instance_count
    assert all(not r.primary_pass for r in rows)
    assert all(r.failure_class == "runtime_tool_failure" for r in rows)
    assert all(r.agent_id == "momo" for r in rows)


def test_agent_launch_failure_still_writes_evidence(tmp_path: Path) -> None:
    plan = make_scaffold_agent_plan()
    out = tmp_path / "evidence.jsonl"

    def failing_runner(command, *, cwd, timeout_sec):
        raise AdapterFailureError(
            "agent launch failed",
            failure_label="runtime_launch_failure",
            latency_sec=0.01,
            adapter_metadata={"agent_command": " ".join(command)},
        )

    summary = execute_external_agent_run(
        plan=plan,
        output_path=out,
        artifacts_dir=tmp_path / "raw",
        process_runner=failing_runner,
        run_id="run-agent-launch-fail",
    )
    assert summary.failed_count == summary.instance_count
    rows = list(read_evidence_jsonl(out))
    assert len(rows) == summary.instance_count
    assert all(r.failure_class == "runtime_launch_failure" for r in rows)
    assert all(not r.primary_pass for r in rows)


def test_control_plane_rejects_scaffold_agent_before_outputs(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "raw"
    with pytest.raises(BenchEvalError, match=r"momo.*scaffold|scaffold.*momo"):
        execute_control_plane_run(
            plan=make_scaffold_agent_plan(),
            output_path=evidence,
            artifacts_dir=artifacts,
            run_id="must-not-launch",
        )
    assert not evidence.exists()
    assert not artifacts.exists()
