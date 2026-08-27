"""RED contracts for adapter-owned cleanup replay.

SUBSTITUTE_JUSTIFICATION
- substitute: injected Harbor runners that write official-shaped artifacts;
  default-runner RED monkeypatches ``subprocess.run`` to write then raise
  ``TimeoutExpired`` so ``_default_process_runner`` performs its production
  conversion to ``AdapterFailureError(runtime_budget_exceeded)``
- replaces: charged Harbor subprocesses and a wall-clock kill after Harbor
  has already written ``result.json``
- necessity: the assertion is that BenchEval retains official bytes and removes
  a named transient; a live Harbor run cannot deterministically plant the exact
  jobs-tree versus retained-copy split or a timeout-after-write
- real-option: live TB cleanup-replay on dev-box-cpu
- proof-limit: software-gate only; does not prove Harbor truth or Tier-2
- real-proof: TB `run-20260826-104126-417176-facd93a7` /
  `sha256:cd681305651cb985feccacb5e99f38edc8ac210b6e52c20dce3462a99f6e29c7`
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError
from bencheval.lifecycle import cleanup_transient_artifacts
from bencheval.runtime_registry import load_runtime_catalog
from bencheval.terminal_bench_harbor import (
    HARBOR_JOBS_DIR_NAME,
    HARBOR_OFFICIAL_RESULT_NAME,
    HarborCliResult,
    build_harbor_run_command,
    harbor_agent_for_runtime,
    run_terminal_bench_instance,
)


def _legacy_pass_result(runtime_id: str) -> str:
    pin = load_runtime_catalog().by_id(runtime_id).versioning.agent_version_pin
    return json.dumps(
        {
            "resolved": True,
            "agent_info": {
                "name": harbor_agent_for_runtime(runtime_id),
                "version": pin,
                "model_info": None,
            },
        },
    )


def test_harbor_jobs_dir_is_the_named_transient(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    cmd = build_harbor_run_command(
        plan=plan,
        instance_id="fix-git",
        artifacts_dir=tmp_path,
    )
    jobs_dir = Path(cmd[cmd.index("--jobs-dir") + 1])
    assert jobs_dir == tmp_path / HARBOR_JOBS_DIR_NAME
    assert jobs_dir.name == "harbor-package"


def test_harbor_cleanup_removes_jobs_tree_and_keeps_retained_result(
    tmp_path: Path,
) -> None:
    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
        cleanup_policy="always",
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    planted: list[Path] = []
    planted_bytes: list[bytes] = []

    def artifact_runner(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        jobs_dir = Path(command[command.index("--jobs-dir") + 1])
        jobs_dir.mkdir(parents=True, exist_ok=True)
        nested = jobs_dir / "2026-08-26__cleanup" / "fix-git__trial"
        nested.mkdir(parents=True)
        result_path = nested / "result.json"
        payload = (_legacy_pass_result("claude-code") + "\n").encode("utf-8")
        result_path.write_bytes(payload)
        planted.append(result_path)
        planted_bytes.append(payload)
        return HarborCliResult(0, "", "", 0.1, tuple(command))

    artifacts = tmp_path / "artifacts"
    execute_control_plane_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=artifacts,
        harbor_process_runner=artifact_runner,
        run_id="cleanup-replay-tb",
    )

    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert len(rows) == 1
    assert rows[0].primary_pass is True
    assert rows[0].cleanup_result == "success"
    instance_dir = artifacts / "fix-git"
    retained = instance_dir / HARBOR_OFFICIAL_RESULT_NAME
    assert retained.is_file()
    assert json.loads(retained.read_text(encoding="utf-8"))["resolved"] is True
    assert rows[0].verifier_log_path is not None
    assert rows[0].verifier_log_path.endswith(HARBOR_OFFICIAL_RESULT_NAME)
    assert not (instance_dir / HARBOR_JOBS_DIR_NAME).exists()
    assert planted[0].exists() is False
    assert retained.read_bytes() == planted_bytes[0]


def test_harbor_timeout_after_write_still_retains_official_result(
    tmp_path: Path,
) -> None:
    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
        cleanup_policy="always",
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    planted_bytes = (_legacy_pass_result("claude-code") + "\n").encode("utf-8")

    def timeout_after_write(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        jobs_dir = Path(command[command.index("--jobs-dir") + 1])
        nested = jobs_dir / "2026-08-26__timeout" / "fix-git__trial"
        nested.mkdir(parents=True)
        (nested / "result.json").write_bytes(planted_bytes)
        raise subprocess.TimeoutExpired(cmd=list(command), timeout=timeout_sec)

    artifacts = tmp_path / "artifacts"
    execute_control_plane_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=artifacts,
        harbor_process_runner=timeout_after_write,
        run_id="cleanup-replay-tb-timeout",
    )

    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert len(rows) == 1
    assert rows[0].primary_pass is False
    assert "runtime_budget_exceeded" in rows[0].failure_labels
    instance_dir = artifacts / "fix-git"
    retained = instance_dir / HARBOR_OFFICIAL_RESULT_NAME
    assert retained.is_file()
    assert retained.read_bytes() == planted_bytes
    assert not (instance_dir / HARBOR_JOBS_DIR_NAME).exists()


def test_harbor_budget_error_after_write_still_retains_official_result(
    tmp_path: Path,
) -> None:
    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
        cleanup_policy="always",
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    planted_bytes = (_legacy_pass_result("claude-code") + "\n").encode("utf-8")

    def budget_error_after_write(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        jobs_dir = Path(command[command.index("--jobs-dir") + 1])
        nested = jobs_dir / "2026-08-26__budget" / "fix-git__trial"
        nested.mkdir(parents=True)
        (nested / "result.json").write_bytes(planted_bytes)
        raise AdapterFailureError(
            f"harbor CLI timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=0.2,
            adapter_metadata={"harbor_command": "harbor run"},
        )

    artifacts = tmp_path / "artifacts"
    execute_control_plane_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=artifacts,
        harbor_process_runner=budget_error_after_write,
        run_id="cleanup-replay-tb-budget",
    )

    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert len(rows) == 1
    assert rows[0].primary_pass is False
    assert "runtime_budget_exceeded" in rows[0].failure_labels
    instance_dir = artifacts / "fix-git"
    retained = instance_dir / HARBOR_OFFICIAL_RESULT_NAME
    assert retained.is_file()
    assert retained.read_bytes() == planted_bytes
    assert not (instance_dir / HARBOR_JOBS_DIR_NAME).exists()


def test_default_process_runner_timeout_after_write_retains_official_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bencheval import terminal_bench_harbor as harbor

    planted_bytes = (_legacy_pass_result("claude-code") + "\n").encode("utf-8")

    def fake_run(command: list[str], **kwargs: object) -> object:
        jobs_dir = Path(command[command.index("--jobs-dir") + 1])
        nested = jobs_dir / "2026-08-26__default-timeout" / "fix-git__trial"
        nested.mkdir(parents=True)
        (nested / "result.json").write_bytes(planted_bytes)
        timeout = kwargs.get("timeout", 1)
        if not isinstance(timeout, (int, float)):
            timeout = 1
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(harbor, "harbor_revision", lambda: "test-harbor")
    monkeypatch.setattr(harbor.subprocess, "run", fake_run)

    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
        cleanup_policy="always",
    )
    artifacts = tmp_path / "artifacts"
    with pytest.raises(AdapterFailureError) as exc_info:
        run_terminal_bench_instance(
            plan=plan,
            instance_id="fix-git",
            artifacts_dir=artifacts,
            repo_root=tmp_path,
            process_runner=None,
            timeout_sec=1,
        )
    assert exc_info.value.failure_label == "runtime_budget_exceeded"
    instance_dir = artifacts / "fix-git"
    retained = instance_dir / HARBOR_OFFICIAL_RESULT_NAME
    assert retained.is_file()
    assert retained.read_bytes() == planted_bytes
    cleanup_transient_artifacts(instance_dir, policy="always", primary_pass=False)
    assert not (instance_dir / HARBOR_JOBS_DIR_NAME).exists()
    assert retained.read_bytes() == planted_bytes
