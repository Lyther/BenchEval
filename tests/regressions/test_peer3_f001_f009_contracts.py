"""Peer#3 F003/F004/F007/F008 regressions for the v1 closeout batch.

SUBSTITUTE_JUSTIFICATION
- substitute: injected SWE process runners, monkeypatched
  ``run_swebench_instance`` / ``subprocess.run``, and planted official-report
  files (including hardlinks/symlinks)
- replaces: charged Inspect generation, Docker-backed official evaluation, and
  a live provider child process
- necessity: hardlinked/symlink reports, ambient vs selected provider routes,
  and producer-identity stamping must be forced without a charged diagnostic
- real-option: a live SWE diagnostic cannot safely guarantee an outside
  hardlink or a conflicting OPENAI_BASE_URL; producer identity is stamped on
  every real evidence row
- proof-limit: local filesystem and executor-wrap contracts only; not official
  score truth or catalog admission
- real-proof: post-fix one-instance SWE diagnostic on the operator host
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.lifecycle import TRANSIENT_ARTIFACT_DIR_NAMES, cleanup_transient_artifacts
from bencheval.provider_registry import resolve_openai_compatible_launch
from bencheval.swebench_adapter import (
    SwebenchCliResult,
    SwebenchInstanceOutcome,
    _inspect_log_solver_version,
    default_swebench_process_runner,
    parse_swebench_instance_outcome,
    run_swebench_instance,
)

_INSTANCE_ID = "django__django-11099"


def _diagnostic_plan():
    return plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-diagnostic-1",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
        diagnostic=True,
    )


def _prediction() -> str:
    return (
        json.dumps(
            {
                "instance_id": _INSTANCE_ID,
                "model_name_or_path": "kimi-k2.7-code",
                "model_patch": "diff --git a/a b/a\n",
            },
        )
        + "\n"
    )


def _schema_v2(run_id: str) -> str:
    return json.dumps(
        {
            "schema_version": 2,
            "resolved_ids": [_INSTANCE_ID],
            "unresolved_ids": [],
            "empty_patch_ids": [],
            "error_ids": [],
            "infra_failure_ids": [],
            "ambiguous_failure_ids": [],
        },
    )


def test_swe_nested_hardlinked_report_is_not_pass_authority(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    run_id = "swe-hardlink-report"
    outside = tmp_path / "outside-report.json"
    outside.write_text(json.dumps({_INSTANCE_ID: {"resolved": True}}), encoding="utf-8")

    def _runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> SwebenchCliResult:
        del cwd, timeout_sec
        instance_root = artifacts / _INSTANCE_ID
        instance_root.mkdir(parents=True, exist_ok=True)
        argv = tuple(command)
        if argv[:2] == ("inspect", "eval"):
            (instance_root / "predictions.jsonl").write_text(_prediction(), encoding="utf-8")
            official = instance_root / "official-dataset"
            official.mkdir()
            (official / "test.jsonl").write_text("{}\n", encoding="utf-8")
        else:
            nested = (
                instance_root
                / "logs"
                / "run_evaluation"
                / run_id
                / "kimi-k2.7-code"
                / _INSTANCE_ID
                / "report.json"
            )
            nested.parent.mkdir(parents=True)
            os.link(outside, nested)
            (instance_root / f"kimi-k2.7-code.{run_id}.json").write_text(
                _schema_v2(run_id),
                encoding="utf-8",
            )
        return SwebenchCliResult(0, "ok", "", 0.1, argv)

    with pytest.raises(AdapterFailureError, match="hardlink"):
        run_swebench_instance(
            plan=_diagnostic_plan(),
            instance_id=_INSTANCE_ID,
            artifacts_dir=artifacts,
            repo_root=tmp_path,
            process_runner=_runner,
            timeout_sec=30,
            run_id=run_id,
        )
    owned = artifacts / _INSTANCE_ID / "report.json"
    assert not owned.is_file() or owned.read_bytes() != outside.read_bytes()


def test_swe_nested_symlinked_report_is_not_pass_authority(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    run_id = "swe-symlink-report"
    outside = tmp_path / "outside-report.json"
    outside.write_text(json.dumps({_INSTANCE_ID: {"resolved": True}}), encoding="utf-8")

    def _runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> SwebenchCliResult:
        del cwd, timeout_sec
        instance_root = artifacts / _INSTANCE_ID
        instance_root.mkdir(parents=True, exist_ok=True)
        argv = tuple(command)
        if argv[:2] == ("inspect", "eval"):
            (instance_root / "predictions.jsonl").write_text(_prediction(), encoding="utf-8")
            official = instance_root / "official-dataset"
            official.mkdir()
            (official / "test.jsonl").write_text("{}\n", encoding="utf-8")
        else:
            nested = (
                instance_root
                / "logs"
                / "run_evaluation"
                / run_id
                / "kimi-k2.7-code"
                / _INSTANCE_ID
                / "report.json"
            )
            nested.parent.mkdir(parents=True)
            nested.symlink_to(outside)
            (instance_root / f"kimi-k2.7-code.{run_id}.json").write_text(
                _schema_v2(run_id),
                encoding="utf-8",
            )
        return SwebenchCliResult(0, "ok", "", 0.1, argv)

    outcome = run_swebench_instance(
        plan=_diagnostic_plan(),
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=_runner,
        timeout_sec=30,
        run_id=run_id,
    )
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"


def test_swe_owned_hardlinked_report_is_not_pass_authority(tmp_path: Path) -> None:
    artifacts = tmp_path / "instance"
    artifacts.mkdir()
    outside = tmp_path / "outside-owned.json"
    outside.write_text(json.dumps({_INSTANCE_ID: {"resolved": True}}), encoding="utf-8")
    os.link(outside, artifacts / "report.json")
    cli = SwebenchCliResult(
        returncode=0,
        stdout="planted",
        stderr="",
        latency_sec=0.1,
        command=("swebench", "eval", "ignored"),
    )
    outcome = parse_swebench_instance_outcome(
        instance_id=_INSTANCE_ID,
        cli=cli,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        harness_version="swebench==5.0.1",
    )
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"


def test_swe_default_runner_rejects_ambient_os_environ(
    tmp_path: Path,
) -> None:
    with pytest.raises(BenchEvalError, match="explicit provider environment"):
        default_swebench_process_runner(
            ("swebench", "eval", str(tmp_path / "official-dataset")),
            cwd=tmp_path,
            timeout_sec=1,
        )


def test_swe_default_runner_uses_explicit_env_not_ambient_openai(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ambient.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key")
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> object:
        captured["env"] = dict(kwargs.get("env") or {})
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("bencheval.swebench_adapter.subprocess.run", fake_run)
    default_swebench_process_runner(
        ("swebench", "eval", str(tmp_path / "official-dataset")),
        cwd=tmp_path,
        timeout_sec=1,
        env={
            "OPENAI_BASE_URL": "http://127.0.0.1:4400/v1",
            "OPENAI_API_KEY": "review-provider-key",
        },
    )
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["OPENAI_BASE_URL"] == "http://127.0.0.1:4400/v1"
    assert env["OPENAI_API_KEY"] == "review-provider-key"


def test_swe_execute_binds_provider_route_not_ambient_openai(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BYTELLM_API_KEY", "review-provider-key")
    monkeypatch.setenv("BYTELLM_BASE_URL", "http://127.0.0.1:4400")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://ambient.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key")
    captured: dict[str, str] = {}

    def fake_run(*args: object, **kwargs: object) -> object:
        env = kwargs.get("env") or {}
        captured.update({k: str(v) for k, v in dict(env).items()})
        return type("Proc", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr("bencheval.swebench_adapter.subprocess.run", fake_run)

    def fake_run_instance(
        *,
        process_runner: object,
        **kwargs: object,
    ) -> SwebenchInstanceOutcome:
        del kwargs
        assert callable(process_runner)
        process_runner(
            ("inspect", "eval", "inspect_evals/swe_bench"),
            cwd=tmp_path,
            timeout_sec=1,
        )
        return SwebenchInstanceOutcome(
            instance_id=_INSTANCE_ID,
            primary_pass=False,
            partial_score=0.0,
            cost_usd=0.0,
            latency_sec=0.1,
            native_score={"backend": "inspect"},
            failure_class="model_wrong_solution",
            stdout_path=None,
            stderr_path=None,
            verifier_log_path=None,
            workspace_diff_path=None,
            adapter_metadata={
                "adapter_id": "swebench",
                "harness_version": "swebench==5.0.1",
                "benchmark_version": "swe-bench-verified@78f471bf655a3137+data-030cfd7f2a704c4c",
                "inspect_runtime_version": "0.148.0",
            },
        )

    monkeypatch.setattr(
        "bencheval.control_plane_executor.run_swebench_instance",
        fake_run_instance,
    )
    output = tmp_path / "evidence.jsonl"
    execute_control_plane_run(
        plan=_diagnostic_plan(),
        output_path=output,
        artifacts_dir=tmp_path / "artifacts",
        swebench_process_runner=default_swebench_process_runner,
        run_id="swe-provider-env",
    )
    rows = read_evidence_jsonl(output)
    assert captured["OPENAI_BASE_URL"] == "http://127.0.0.1:4400/v1"
    assert captured["OPENAI_API_KEY"] == "review-provider-key"
    launch = resolve_openai_compatible_launch("bytellm", require_api_key=False)
    assert rows[0].provider_config_hash == launch.config_hash
    assert rows[0].runtime_version == "0.148.0"
    assert rows[0].adapter_metadata["producer_package_version"]
    assert rows[0].adapter_metadata["producer_content_sha256"].startswith("sha256:")
    assert rows[0].adapter_metadata["producer_content_sha256"] != "sha256:unknown"
    if "producer_git_commit" in rows[0].adapter_metadata:
        assert rows[0].adapter_metadata["producer_git_commit"] != "unknown"
        assert rows[0].adapter_metadata["producer_dirty"] in {"0", "1"}


def test_inspect_runtime_version_prefers_executed_sandbox_codex_binary() -> None:
    from types import SimpleNamespace

    configured = SimpleNamespace(
        solver_args={"version": "0.9.0"},
        solver_args_passed={"version": "0.9.0"},
        revision=None,
        task_version=3,
        metadata={},
    )
    event = SimpleNamespace(file="/var/tmp/x/codex-0.148.0-linux-x64", cmd=None)
    log = SimpleNamespace(eval=configured, samples=[SimpleNamespace(events=[event])])
    assert _inspect_log_solver_version(log) == "0.148.0"


def test_inspect_runtime_version_ignores_inspect_task_metadata() -> None:
    from types import SimpleNamespace

    ev = SimpleNamespace(
        solver_args={},
        solver_args_passed={},
        revision="inspect-task-rev",
        task_version="3-C",
        metadata={"full_task_version": "3-C", "version": "not-a-runtime"},
    )
    log = SimpleNamespace(eval=ev, samples=[SimpleNamespace(events=[])])
    assert _inspect_log_solver_version(log) is None


def test_inspect_runtime_version_falls_back_to_solver_args() -> None:
    from types import SimpleNamespace

    ev = SimpleNamespace(
        solver_args={"version": "0.148.0"},
        solver_args_passed={"version": "0.148.0"},
        revision=None,
        task_version=3,
        metadata={},
    )
    log = SimpleNamespace(eval=ev, samples=[SimpleNamespace(events=[])])
    assert _inspect_log_solver_version(log) == "0.148.0"


def test_bfcl_results_and_scores_are_retained_evidence_not_transients(
    tmp_path: Path,
) -> None:
    assert "results" not in TRANSIENT_ARTIFACT_DIR_NAMES
    assert "scores" not in TRANSIENT_ARTIFACT_DIR_NAMES
    instance = tmp_path / "simple_python"
    (instance / "results").mkdir(parents=True)
    (instance / "scores").mkdir()
    (instance / "results" / "score.json").write_text("{}", encoding="utf-8")
    (instance / "scores" / "official.json").write_text("{}", encoding="utf-8")
    report = cleanup_transient_artifacts(instance, policy="always", primary_pass=True)
    assert (instance / "results" / "score.json").is_file()
    assert (instance / "scores" / "official.json").is_file()
    assert report.removed_paths == ()
