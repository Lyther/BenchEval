"""RED contracts for GPQA result identity and external-agent scorer ownership.

SUBSTITUTE_JUSTIFICATION
- substitute: deterministic process runners in the GPQA and external-agent tests
- replaces: provider-charged Inspect/MOMO subprocess effects at the narrow process boundary
- necessity: the assertions require an explicit result/decoy conflict and malicious agent
  self-attestation; real services cannot expose those adversarial states safely and
  deterministically
- real-option: real Inspect and MOMO runs require unavailable datasets/credentials and cannot safely
  manufacture the scorer-ownership violation
- proof-limit: these tests exercise production command, parsing, evidence, and orchestration code,
  but do not prove the replaced harness/provider boundaries or live benchmark correctness
- real-proof: BLOCKED on the dev-box harness setup and an authorized disposable provider credential
"""

from __future__ import annotations

import json
from importlib.metadata import version as distribution_version
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.external_agent_adapter import (
    ExternalAgentCliResult,
    execute_external_agent_run,
    run_external_agent_instance,
)
from bencheval.gpqa_adapter import (
    GpqaCliResult,
    build_gpqa_run_command,
    run_gpqa_slice,
)


def _gpqa_plan():
    return plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )


def _external_agent_plan():
    from tests.factories import make_scaffold_agent_plan

    return make_scaffold_agent_plan()


def test_gpqa_requests_machine_readable_inspect_launch_output(tmp_path: Path) -> None:
    command = build_gpqa_run_command(
        plan=_gpqa_plan(),
        sample_limit=2,
        log_dir=tmp_path / "logs",
    )

    assert "--json" in command


def test_gpqa_uses_only_the_inspect_done_log_as_verifier(tmp_path: Path) -> None:
    plan = _gpqa_plan()
    selected_log: Path | None = None

    def inspect_runner(
        command,
        *,
        cwd: Path | None,
        timeout_sec: int,
        env=None,
    ) -> GpqaCliResult:
        nonlocal selected_log
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_dir.mkdir(parents=True, exist_ok=True)
        selected_log = log_dir / "2026-08-06T140000_gpqa_diamond.json"
        selected_log.write_text(
            json.dumps(
                {
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
                                "metrics": {"accuracy": {"value": 0.5}},
                            },
                        ],
                    },
                },
            )
            + "\n",
            encoding="utf-8",
        )
        # A newer, valid-looking decoy proves explicit done-result ownership wins
        # over directory scanning and favorable-score selection.
        (log_dir / "unrelated.json").write_text(
            json.dumps(
                {
                    "status": "success",
                    "eval": {"task": "decoy", "model": "openai/decoy"},
                    "results": {
                        "scores": [
                            {
                                "name": "choice",
                                "metrics": {"accuracy": {"value": 1.0}},
                            },
                        ],
                    },
                },
            )
            + "\n",
            encoding="utf-8",
        )
        stdout = json.dumps(
            {
                "type": "done",
                "status": "success",
                "tasks": [{"status": "success", "log_location": str(selected_log)}],
            },
        )
        return GpqaCliResult(0, stdout + "\n", "", 0.25, tuple(command))

    outcome = run_gpqa_slice(
        plan=plan,
        artifacts_dir=tmp_path / "run",
        repo_root=tmp_path,
        process_runner=inspect_runner,
        timeout_sec=5,
    )[0]

    assert selected_log is not None
    assert outcome.partial_score == pytest.approx(0.5)
    assert outcome.primary_pass is False
    assert outcome.failure_class == "model_wrong_solution"
    assert outcome.counts_toward_pass_at_k is True
    retained = Path(outcome.verifier_log_path or "")
    assert retained.name == "gpqa-official-log.json"
    assert retained.read_bytes() == selected_log.read_bytes()
    assert outcome.native_score["score_source"] == str(selected_log)


def test_gpqa_evidence_captures_the_executed_inspect_evals_version(tmp_path: Path) -> None:
    """Harness provenance comes from the installed executable distribution."""
    plan = _gpqa_plan()

    def inspect_runner(
        command,
        *,
        cwd: Path | None,
        timeout_sec: int,
        env=None,
    ) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "gpqa.json"
        log_path.write_text(
            json.dumps(
                {
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
                                "metrics": {"accuracy": {"value": 0.5}},
                            },
                        ],
                    },
                },
            )
            + "\n",
            encoding="utf-8",
        )
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.25, tuple(command))

    evidence_path = tmp_path / "evidence.jsonl"
    execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "run",
        gpqa_process_runner=inspect_runner,
        run_id="gpqa-harness-version-contract",
    )

    row = read_evidence_jsonl(evidence_path)[0]
    assert row.harness_version == f"inspect-evals@{distribution_version('inspect-evals')}"


@pytest.mark.parametrize("filename", ["result.json", "verifier.json", "verdict.json"])
def test_external_agent_cannot_self_attest_with_named_json(
    tmp_path: Path,
    filename: str,
) -> None:
    """An agent-writable filename cannot turn agent output into a trusted verdict."""

    def self_attesting_runner(
        command,
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> ExternalAgentCliResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / filename).write_text(
            json.dumps({"success": True}) + "\n",
            encoding="utf-8",
        )
        return ExternalAgentCliResult(0, "agent says it passed", "", 0.1, tuple(command))

    outcome = run_external_agent_instance(
        plan=_external_agent_plan(),
        instance_id="fix-git",
        artifacts_dir=tmp_path / "run",
        repo_root=tmp_path,
        process_runner=self_attesting_runner,
        timeout_sec=5,
    )

    assert outcome.primary_pass is False
    assert outcome.partial_score == 0.0
    assert outcome.failure_class == "harness_failure"


def test_external_agent_evidence_preserves_benchmark_owned_axes(tmp_path: Path) -> None:
    """Agent identity is a scaffold axis; it must not replace benchmark provenance."""
    plan = _external_agent_plan().model_copy(
        update={"instances": _external_agent_plan().instances[:1]}
    )

    def failed_agent_runner(
        command,
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> ExternalAgentCliResult:
        return ExternalAgentCliResult(1, "", "agent failed", 0.1, tuple(command))

    evidence_path = tmp_path / "evidence.jsonl"
    execute_external_agent_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "run",
        process_runner=failed_agent_runner,
        run_id="external-agent-axis-contract",
    )

    row = read_evidence_jsonl(evidence_path)[0]
    assert (
        row.benchmark_id,
        row.benchmark_version,
        row.slice_id,
        row.adapter_id,
        row.harness_kind,
        row.agent_id,
        row.provider_id,
    ) == (
        plan.benchmark_id,
        plan.benchmark_version,
        plan.slice_id,
        plan.adapter_id,
        plan.harness_kind,
        plan.agent_id,
        plan.provider_id,
    )
