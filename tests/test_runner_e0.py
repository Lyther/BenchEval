from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.runner import HarnessReferenceProvider, RunResult, new_run_id, run_single_task

_CORE8_HARNESS_TASKS = (
    ("be-core-t1-single-structured-call", "E0"),
    ("be-core-t2-multi-tool-join", "E0"),
    ("be-core-c1-small-logic-patch", "E1"),
    ("be-core-c2-regression-test-authoring", "E1"),
    ("be-core-a1-multi-file-repo-fix", "E1"),
    ("be-core-a2-build-log-triage", "E1"),
    ("be-core-s1-secure-input-boundary-patch", "E1"),
    ("be-core-s4-local-prompt-injection-resistance", "E1"),
)


def test_c1_negative_provider_fails(tmp_path: Path) -> None:
    class NegativeProvider(HarnessReferenceProvider):
        def produce_candidate(self, *, workspace: Path, contract, reference_name: str):
            del contract, reference_name
            return workspace / "negative.patch.json", 0.0, 0.0

    out = tmp_path / "evidence.jsonl"
    result = run_single_task(
        task_id="be-core-c1-small-logic-patch",
        model_id="local/harness",
        output_path=out,
        provider=NegativeProvider(),
        run_artifacts_dir=tmp_path / "c1-negative",
    )
    assert result.evidence.primary_pass is False
    assert result.evidence.model_id == "local/harness"


def test_s4_negative_provider_fails(tmp_path: Path) -> None:
    class NegativeProvider(HarnessReferenceProvider):
        def produce_candidate(self, *, workspace: Path, contract, reference_name: str):
            del contract, reference_name
            return workspace / "negative.json", 0.0, 0.0

    out = tmp_path / "evidence.jsonl"
    result = run_single_task(
        task_id="be-core-s4-local-prompt-injection-resistance",
        model_id="local/harness",
        output_path=out,
        provider=NegativeProvider(),
        run_artifacts_dir=tmp_path / "s4-negative",
    )
    assert result.evidence.primary_pass is False
    assert result.evidence.model_id == "local/harness"


def test_e0_run_writes_evidence(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    result = run_single_task(
        task_id="be-core-t1-single-structured-call",
        model_id="local/harness",
        output_path=out,
        run_id="run-test-001",
        run_artifacts_dir=artifacts,
    )
    assert result.evidence.primary_pass is True
    assert result.evidence.model_id == "local/harness"
    assert result.evidence.execution_profile == "E0"
    rows = read_evidence_jsonl(out)
    assert len(rows) == 1
    assert rows[0].task_id == "be-core-t1-single-structured-call"
    assert rows[0].run_id == "run-test-001"
    assert result.verifier_log_path == artifacts / "verifier.json"
    assert result.verifier_log_path.is_file()
    log = json.loads(result.verifier_log_path.read_text(encoding="utf-8"))
    assert log["primary_pass"] is True


def test_unsupported_task_rejected() -> None:
    with pytest.raises(BenchEvalError, match="not supported"):
        run_single_task(
            task_id="be-core-not-a-real-task",
            model_id="local/harness",
            output_path=Path("ignored.jsonl"),
        )


@pytest.mark.parametrize(("task_id", "profile"), _CORE8_HARNESS_TASKS)
def test_local_harness_run_writes_evidence(
    tmp_path: Path,
    task_id: str,
    profile: str,
) -> None:
    out = tmp_path / f"{task_id}-evidence.jsonl"
    artifacts = tmp_path / f"{task_id}-artifacts"
    result = run_single_task(
        task_id=task_id,
        model_id="local/harness",
        output_path=out,
        run_artifacts_dir=artifacts,
    )
    assert result.evidence.primary_pass is True
    assert result.evidence.model_id == "local/harness"
    assert result.evidence.execution_profile == profile
    assert result.verifier_log_path == artifacts / "verifier.json"
    assert result.verifier_log_path.is_file()


def test_t2_run_writes_evidence(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "t2-artifacts"
    result = run_single_task(
        task_id="be-core-t2-multi-tool-join",
        model_id="local/harness",
        output_path=out,
        run_artifacts_dir=artifacts,
    )
    assert result.evidence.primary_pass is True
    assert result.evidence.execution_profile == "E0"
    assert result.evidence.model_id == "local/harness"
    assert result.verifier_log_path == artifacts / "verifier.json"


def test_c1_e1_run_writes_evidence(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "c1-artifacts"
    result = run_single_task(
        task_id="be-core-c1-small-logic-patch",
        model_id="local/harness",
        output_path=out,
        run_artifacts_dir=artifacts,
    )
    assert result.evidence.primary_pass is True
    assert result.evidence.execution_profile == "E1"
    assert result.evidence.model_id == "local/harness"


def test_t2_negative_provider_fails(tmp_path: Path) -> None:
    class NegativeProvider(HarnessReferenceProvider):
        def produce_candidate(self, *, workspace: Path, contract, reference_name: str):
            del contract
            return workspace / "negative.json", 0.0, 0.0

    out = tmp_path / "evidence.jsonl"
    result = run_single_task(
        task_id="be-core-t2-multi-tool-join",
        model_id="local/harness",
        output_path=out,
        provider=NegativeProvider(),
        run_artifacts_dir=tmp_path / "t2-negative",
    )
    assert result.evidence.primary_pass is False


def test_non_harness_model_rejected_without_provider(tmp_path: Path) -> None:
    with pytest.raises(BenchEvalError, match="local runs require|local backend requires"):
        run_single_task(
            task_id="be-core-t1-single-structured-call",
            model_id="anthropic/claude-test",
            output_path=tmp_path / "evidence.jsonl",
        )


def test_provider_boundary_negative_control_fails(tmp_path: Path) -> None:
    class NegativeProvider(HarnessReferenceProvider):
        def produce_candidate(self, *, workspace: Path, contract, reference_name: str):
            del contract, reference_name
            return workspace / "negative.json", 0.0, 0.0

    out = tmp_path / "evidence.jsonl"
    result = run_single_task(
        task_id="be-core-t1-single-structured-call",
        model_id="local/harness",
        output_path=out,
        provider=NegativeProvider(),
        run_id="run-test-002",
        run_artifacts_dir=tmp_path / "artifacts",
    )
    assert result.evidence.primary_pass is False
    assert result.evidence.failure_labels == ["wrong_solution"]
    assert result.evidence.model_id == "local/harness"


def test_new_run_id_is_unique_on_consecutive_calls() -> None:
    ids = [new_run_id() for _ in range(100)]
    assert len(set(ids)) == 100


def test_consecutive_automatic_runs_have_unique_run_ids(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    r1 = run_single_task(
        task_id="be-core-t1-single-structured-call",
        model_id="local/harness",
        output_path=out,
        run_artifacts_dir=tmp_path / "run-a",
    )
    r2 = run_single_task(
        task_id="be-core-t1-single-structured-call",
        model_id="local/harness",
        output_path=out,
        run_artifacts_dir=tmp_path / "run-b",
    )
    assert r1.run_id != r2.run_id
    assert r1.verifier_log_path != r2.verifier_log_path


def test_run_single_task_rejects_existing_verifier_log(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    out = tmp_path / "evidence.jsonl"
    run_single_task(
        task_id="be-core-t1-single-structured-call",
        model_id="local/harness",
        output_path=out,
        run_id="run-dup-test",
        run_artifacts_dir=artifacts,
    )
    with pytest.raises(BenchEvalError, match="run artifacts already exist"):
        run_single_task(
            task_id="be-core-t1-single-structured-call",
            model_id="local/harness",
            output_path=out,
            run_id="run-dup-test",
            run_artifacts_dir=artifacts,
        )


def test_run_single_task_returns_runner_run_result_type(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    result = run_single_task(
        task_id="be-core-t1-single-structured-call",
        model_id="local/harness",
        output_path=out,
    )
    assert isinstance(result, RunResult)


def test_injected_provider_cannot_spoof_model_id(tmp_path: Path) -> None:
    class SpoofedProvider(HarnessReferenceProvider):
        model_id = "anthropic/claude-test"

    with pytest.raises(BenchEvalError, match="evidence model_id must be"):
        run_single_task(
            task_id="be-core-t1-single-structured-call",
            model_id="local/harness",
            output_path=tmp_path / "evidence.jsonl",
            provider=SpoofedProvider(),
        )
