from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bencheval.cli import main
from bencheval.evidence import read_evidence_jsonl
from tests.selftest_paths import core8_dir


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "bencheval.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )


def test_task_validate_valid_path_exits_0() -> None:
    Path(__file__).resolve().parents[1]
    path = core8_dir() / "t1-single-structured-call.yaml"
    r = _run("task", "validate", str(path))
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["ok"] is True
    assert payload["task_id"] == "be-core-t1-single-structured-call"


def test_invalid_yaml_exits_non_zero(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("task: [", encoding="utf-8")
    r = _run("task", "validate", str(bad))
    assert r.returncode != 0


def test_task_id_resolution_works() -> None:
    r = _run("task", "validate", "be-core-c1-small-logic-patch")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["task_id"] == "be-core-c1-small-logic-patch"


def test_dry_run_smoke_exits_0() -> None:
    r = _run("run", "--dry-run", "--suite", "smoke", "--model", "anthropic/claude-test")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["task_count"] == 8


def test_run_rejects_provider_model_on_local_backend(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    r = _run(
        "run",
        "--task",
        "be-core-t1-single-structured-call",
        "--model",
        "openai/gpt-test",
        "--backend",
        "local",
        "--output",
        str(out),
    )
    assert r.returncode == 1
    assert "local backend requires" in r.stderr


def test_main_direct_call_dry_run() -> None:
    code = main(["run", "--dry-run", "--suite", "core-8", "--model", "openai/gpt-test"])
    assert code == 0


def test_task_audit_t1_json() -> None:
    r = _run("task", "audit", "be-core-t1-single-structured-call")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["task_id"] == "be-core-t1-single-structured-call"
    assert payload["automated_pass"] is True
    assert payload["admitted"] is True


def test_run_single_task_writes_evidence(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    r = _run(
        "run",
        "--task",
        "be-core-t1-single-structured-call",
        "--model",
        "local/harness",
        "--output",
        str(out),
        "--artifacts-dir",
        str(artifacts),
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["primary_pass"] is True
    assert out.is_file()
    assert Path(payload["verifier_log_path"]) == artifacts / "verifier.json"


def test_run_without_task_exits_2() -> None:
    r = _run("run", "--model", "local/harness", "--output", "out.jsonl")
    assert r.returncode == 2


def test_run_rejects_non_harness_model(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    r = _run(
        "run",
        "--task",
        "be-core-t1-single-structured-call",
        "--model",
        "anthropic/claude-test",
        "--output",
        str(out),
    )
    assert r.returncode == 1
    assert "local/harness" in r.stderr
    assert not out.is_file()


def test_task_audit_core8_exits_0() -> None:
    r = _run("task", "audit", "core-8")
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["admitted"] is True
    assert payload["admitted_count"] == 8
    assert payload["failed_count"] == 0


@pytest.mark.parametrize(
    "task_id",
    (
        "be-core-c2-regression-test-authoring",
        "be-core-a1-multi-file-repo-fix",
        "be-core-a2-build-log-triage",
        "be-core-s1-secure-input-boundary-patch",
        "be-core-s4-local-prompt-injection-resistance",
    ),
)
def test_run_remaining_core8_tasks_write_evidence(tmp_path: Path, task_id: str) -> None:
    out = tmp_path / f"{task_id}.jsonl"
    artifacts = tmp_path / f"{task_id}-artifacts"
    r = _run(
        "run",
        "--task",
        task_id,
        "--model",
        "local/harness",
        "--output",
        str(out),
        "--artifacts-dir",
        str(artifacts),
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["primary_pass"] is True
    assert payload["model_id"] == "local/harness"
    assert out.is_file()
    assert Path(payload["verifier_log_path"]) == artifacts / "verifier.json"


def test_run_suite_smoke_with_artifacts_dir_writes_distinct_verifier_logs(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    r = _run(
        "run",
        "--suite",
        "smoke",
        "--model",
        "local/harness",
        "--output",
        str(out),
        "--artifacts-dir",
        str(artifacts),
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["task_count"] == 8
    assert payload["passed_count"] == 8
    assert payload["failed_count"] == 0
    assert payload["failed_tasks"] == []
    verifier_logs = sorted(artifacts.rglob("verifier.json"))
    assert len(verifier_logs) == 8
    assert len({log.parent for log in verifier_logs}) == 8


def test_run_manifest_single_mode_writes_one_evidence_row_per_task(tmp_path: Path) -> None:
    manifest = tmp_path / "native-smoke.txt"
    manifest.write_text(
        "\n".join(
            (
                "be-core-t2-multi-tool-join",
                "be-core-t1-single-structured-call",
            ),
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    r = _run(
        "run",
        "--manifest",
        str(manifest),
        "--mode",
        "single",
        "--cleanup",
        "never",
        "--model",
        "local/harness",
        "--output",
        str(out),
        "--artifacts-dir",
        str(artifacts),
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["mode"] == "single"
    assert payload["benchmark"] == "native-smoke"
    assert len(payload["task_manifest_hash"]) == 64
    assert payload["task_count"] == 2
    assert payload["passed_count"] == 2
    assert payload["manifest_order_preserved"] is True
    assert payload["cleanup"]["policy"] == "never"
    assert payload["cleanup"]["removed_path_count"] == 0
    rows = read_evidence_jsonl(out)
    assert [row.task_id for row in rows] == [
        "be-core-t2-multi-tool-join",
        "be-core-t1-single-structured-call",
    ]
    verifier_logs = sorted(artifacts.rglob("verifier.json"))
    assert len(verifier_logs) == 2


def test_single_mode_cleanup_removes_agent_workspace_for_inspect_mockllm(
    tmp_path: Path,
) -> None:
    out = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    r = _run(
        "run",
        "--task",
        "be-core-t1-single-structured-call",
        "--mode",
        "single",
        "--cleanup",
        "always",
        "--model",
        "mockllm/model",
        "--backend",
        "inspect",
        "--output",
        str(out),
        "--artifacts-dir",
        str(artifacts),
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["cleanup"]["policy"] == "always"
    assert payload["cleanup"]["removed_path_count"] == 1
    assert not (artifacts / "agent-workspace").exists()
    assert (artifacts / "reference.json").is_file()
    assert (artifacts / "verifier.json").is_file()


def test_cleanup_rejected_outside_single_mode(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    r = _run(
        "run",
        "--suite",
        "smoke",
        "--cleanup",
        "always",
        "--model",
        "local/harness",
        "--output",
        str(out),
    )
    assert r.returncode == 2
    assert "--mode single" in r.stderr
    assert not out.exists()


def test_single_mode_cleanup_always_runs_after_execution_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval.exceptions import BenchEvalError

    artifacts = tmp_path / "artifacts"

    def fake_execute_task(*, run_artifacts_dir: Path, **kwargs: object):
        del kwargs
        (run_artifacts_dir / "agent-workspace").mkdir(parents=True)
        raise BenchEvalError("boom")

    monkeypatch.setattr("bencheval.cli.execute_task", fake_execute_task)
    code = main(
        [
            "run",
            "--task",
            "be-core-t1-single-structured-call",
            "--mode",
            "single",
            "--cleanup",
            "always",
            "--model",
            "local/harness",
            "--output",
            str(tmp_path / "evidence.jsonl"),
            "--artifacts-dir",
            str(artifacts),
        ],
    )
    assert code == 1
    assert not (artifacts / "agent-workspace").exists()


def test_suite_run_exits_nonzero_when_any_task_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval.evidence import EvidenceRecord
    from bencheval.run_result import RunResult

    out = tmp_path / "evidence.jsonl"

    def fake_execute_task(*, task_id: str, **kwargs):
        del kwargs
        primary_pass = task_id != "be-core-t2-multi-tool-join"
        evidence = EvidenceRecord(
            run_id=f"run-{task_id}",
            task_id=task_id,
            model_id="local/harness",
            execution_profile="E0",
            backend="local",
            primary_pass=primary_pass,
            partial_score=1.0 if primary_pass else 0.0,
            cost_usd=0.0,
            latency_sec=0.0,
            failure_labels=[] if primary_pass else ["wrong_solution"],
            artifact_paths=[],
            verifier_log_path=None,
            adapter_metadata={},
            created_at=__import__("datetime").datetime.now(tz=__import__("datetime").UTC),
        )
        return RunResult(
            run_id=evidence.run_id,
            evidence=evidence,
            verifier_log_path=tmp_path / f"{task_id}-verifier.json",
        )

    monkeypatch.setattr("bencheval.cli.execute_task", fake_execute_task)
    monkeypatch.setattr(
        "bencheval.cli.tasks_for_suite",
        lambda _suite: (
            "be-core-t1-single-structured-call",
            "be-core-t2-multi-tool-join",
            "be-core-c1-small-logic-patch",
        ),
    )
    code = main(
        [
            "run",
            "--suite",
            "smoke",
            "--model",
            "local/harness",
            "--output",
            str(out),
        ],
    )
    assert code == 1


def test_run_t2_writes_evidence(tmp_path: Path) -> None:
    out = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    r = _run(
        "run",
        "--task",
        "be-core-t2-multi-tool-join",
        "--model",
        "local/harness",
        "--output",
        str(out),
        "--artifacts-dir",
        str(artifacts),
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["primary_pass"] is True
    assert payload["model_id"] == "local/harness"
    assert Path(payload["verifier_log_path"]) == artifacts / "verifier.json"
