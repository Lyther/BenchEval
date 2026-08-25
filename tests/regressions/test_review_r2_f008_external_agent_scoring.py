"""F008: external-agent exit 0 is not a benchmark pass without verifier artifacts."""

from __future__ import annotations

from pathlib import Path

from bencheval.external_agent_adapter import (
    ExternalAgentCliResult,
    run_external_agent_instance,
)

# SUBSTITUTE_JUSTIFICATION
# - substitute: zero_exit_runner in test_exit_0_without_verifier_artifact_is_not_pass
# - replaces: an external agent returning success without trusted verifier output
# - necessity: the dishonest-success boundary must be deterministic
# - real-option: a real admitted agent cannot be required to violate its contract
# - proof-limit: proves local fail-closed scoring only, not real agent execution
# - real-proof: BLOCKED until an admitted external-agent live lane exists


def test_exit_0_without_verifier_artifact_is_not_pass(tmp_path: Path) -> None:
    from tests.factories import make_scaffold_agent_plan

    plan = make_scaffold_agent_plan()

    def zero_exit_runner(command, *, cwd, timeout_sec):
        return ExternalAgentCliResult(
            returncode=0,
            stdout="agent finished",
            stderr="",
            latency_sec=0.01,
            command=tuple(command),
        )

    outcome = run_external_agent_instance(
        plan=plan,
        instance_id="fix-git",
        artifacts_dir=tmp_path / "raw",
        repo_root=tmp_path,
        process_runner=zero_exit_runner,
    )

    assert outcome.primary_pass is False
    assert outcome.partial_score == 0.0
    assert outcome.failure_class == "harness_failure"
    assert outcome.adapter_metadata.get("scoring") == "missing_verifier_artifact"
