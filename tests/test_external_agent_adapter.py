"""External agent adapter: failed attempts still emit EvidenceRecord."""

from __future__ import annotations

from pathlib import Path

from bencheval.benchmark_plan import plan_control_plane
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError
from bencheval.external_agent_adapter import ExternalAgentCliResult, execute_external_agent_run

# SUBSTITUTE_JUSTIFICATION
# - substitute: failing_runner in test_failed_agent_attempt_writes_runtime_tool_failure and
#   test_agent_launch_failure_still_writes_evidence
# - replaces: controlled nonzero external-agent result and OS launch failure
# - necessity: the two distinct failure boundaries cannot be guaranteed by a real agent
# - real-option: a disposable process cannot deterministically reproduce OS launch failure
# - proof-limit: proves failure labeling/evidence emission only, not agent execution
# - real-proof: BLOCKED until a real admitted external-agent lane is provisioned


def test_failed_agent_attempt_writes_runtime_tool_failure(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id=None,
        agent_id="momo",
        model_id="kimi-k2.7-code",
    )
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
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id=None,
        agent_id="momo",
        model_id="kimi-k2.7-code",
    )
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
