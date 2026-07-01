from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bencheval.backends import HARBOR_BACKEND, INSPECT_BACKEND, LOCAL_BACKEND
from bencheval.doctor import run_doctor
from bencheval.exceptions import BenchEvalError
from bencheval.executor import execute_task
from bencheval.harbor_adapter import (
    HarborAdapterConfig,
    HarborInvokeResult,
    HarborPackage,
    export_harbor_task,
)
from bencheval.inspect_adapter import InspectAdapterConfig, InspectInvokeResult
from bencheval.workspace_staging import stage_agent_workspace
from tests.selftest_paths import core8_workspace

_ROOT = Path(__file__).resolve().parents[1]
_T1_WS = core8_workspace("be-core-t1-single-structured-call")
_S4_WS = core8_workspace("be-core-s4-local-prompt-injection-resistance")


def test_doctor_inspect_e0_skips_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bencheval.doctor._try_import_inspect_ai", lambda: ("0.3.0", None))
    report = run_doctor(INSPECT_BACKEND, model_id="mockllm/model", execution_profile="E0")
    docker = next(check for check in report.checks if check.name == "docker")
    assert docker.status == "skip"
    assert "E0" in docker.message


def test_doctor_inspect_e1_requires_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bencheval.doctor._try_import_inspect_ai", lambda: ("0.3.0", None))
    monkeypatch.setattr("bencheval.doctor.docker_available", lambda: False)
    report = run_doctor(INSPECT_BACKEND, model_id="openai/gpt-test", execution_profile="E1")
    docker = next(check for check in report.checks if check.name == "docker")
    assert docker.status == "fail"


def test_cli_doctor_profile_e0_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bencheval.doctor._try_import_inspect_ai", lambda: ("0.3.0", None))
    from contextlib import redirect_stdout
    from io import StringIO

    from bencheval.cli import main

    buf = StringIO()
    with redirect_stdout(buf):
        code = main(
            ["doctor", "--backend", "inspect", "--model", "mockllm/model", "--profile", "E0"],
        )
    assert code in (0, 1)
    payload = json.loads(buf.getvalue())
    docker = next(check for check in payload["checks"] if check["name"] == "docker")
    assert docker["status"] == "skip"


def test_doctor_docker_timeout_returns_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    monkeypatch.setattr("shutil.which", lambda cmd: "docker" if cmd == "docker" else None)

    def timeout_run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="docker info", timeout=15)

    monkeypatch.setattr("subprocess.run", timeout_run)
    report = run_doctor(HARBOR_BACKEND, model_id="mockllm/model")
    docker = next(check for check in report.checks if check.name == "docker")
    assert docker.status == "fail"
    assert report.ok is False


def test_doctor_inspect_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bencheval.doctor._try_import_inspect_ai",
        lambda: (None, None),
    )
    report = run_doctor(INSPECT_BACKEND, model_id="mockllm/model")
    assert report.ok is False
    assert any(
        check.name == "inspect_ai_import" and check.status == "fail" for check in report.checks
    )


def test_doctor_reports_env_names_without_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bencheval.doctor._try_import_inspect_ai", lambda: ("0.3.0", None))
    monkeypatch.setattr("bencheval.doctor.docker_available", lambda: True)
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-value")
    report = run_doctor(INSPECT_BACKEND, model_id="openai/gpt-test")
    cred = next(check for check in report.checks if check.name == "provider_credentials")
    assert cred.status == "pass"
    assert "OPENAI_API_KEY" in cred.message
    assert "super-secret-value" not in cred.message


def test_doctor_missing_provider_env_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bencheval.doctor._try_import_inspect_ai", lambda: ("0.3.0", None))
    monkeypatch.setattr("bencheval.doctor.docker_available", lambda: True)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = run_doctor(INSPECT_BACKEND, model_id="anthropic/claude-test")
    assert report.ok is False


def test_doctor_broken_inspect_import_returns_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bencheval.doctor._try_import_inspect_ai",
        lambda: (None, "inspect_ai import failed: ImportError: Missing socksio"),
    )
    report = run_doctor(INSPECT_BACKEND, model_id="mockllm/model")
    assert report.ok is False
    check = next(item for item in report.checks if item.name == "inspect_ai_import")
    assert check.status == "fail"
    assert "import failed" in check.message
    assert "socksio" not in check.message or "Missing socksio" in check.message


def test_cli_doctor_broken_inspect_import_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "bencheval.doctor._try_import_inspect_ai",
        lambda: (None, "inspect_ai import failed: ImportError: Missing dependency"),
    )
    from contextlib import redirect_stdout
    from io import StringIO

    from bencheval.cli import main

    buf = StringIO()
    with redirect_stdout(buf):
        code = main(["doctor", "--backend", "inspect", "--model", "mockllm/model"])
    assert code == 1
    payload = json.loads(buf.getvalue())
    assert payload["backend"] == "inspect"
    assert payload["ok"] is False
    assert any(
        check["name"] == "inspect_ai_import" and check["status"] == "fail"
        for check in payload["checks"]
    )


def test_inspect_invoke_converts_to_evidence(tmp_path: Path) -> None:
    def fake_invoke(config: InspectAdapterConfig) -> InspectInvokeResult:
        config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        candidate = config.artifacts_dir / "reference.json"
        candidate.write_text(
            (_T1_WS / "reference.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return InspectInvokeResult(
            candidate_path=candidate,
            cost_usd=0.01,
            latency_sec=1.0,
            adapter_metadata={"inspect_ai_version": "test"},
        )

    out = tmp_path / "evidence.jsonl"
    result = execute_task(
        task_id="be-core-t1-single-structured-call",
        model_id="openai/gpt-test",
        backend=INSPECT_BACKEND,
        output_path=out,
        run_artifacts_dir=tmp_path / "artifacts",
        inspect_invoke=fake_invoke,
        skip_doctor=True,
    )
    assert result.evidence.primary_pass is True
    assert result.evidence.model_id == "openai/gpt-test"
    assert result.evidence.backend == INSPECT_BACKEND
    assert result.evidence.adapter_metadata["inspect_ai_version"] == "test"


def test_inspect_unsupported_task_rejected(tmp_path: Path) -> None:
    with pytest.raises(BenchEvalError, match="does not support task"):
        execute_task(
            task_id="be-core-c2-regression-test-authoring",
            model_id="openai/gpt-test",
            backend=INSPECT_BACKEND,
            output_path=tmp_path / "evidence.jsonl",
            skip_doctor=True,
        )


def test_harbor_export_copies_verify_from_verifier_workspace(tmp_path: Path) -> None:
    if shutil.which("harbor") is None:
        pytest.skip("harbor CLI not available")
    staged = stage_agent_workspace(_S4_WS, tmp_path / "agent-workspace")
    assert not (staged / "verify.py").exists()
    config = HarborAdapterConfig(
        task_id="be-core-s4-local-prompt-injection-resistance",
        model_id="openai/gpt-test",
        workspace=staged,
        verifier_workspace=_S4_WS,
        reference_artifact_name="reference.json",
        package_dir=tmp_path / "pkg",
        artifacts_dir=tmp_path / "artifacts",
    )
    export_harbor_task(config)
    assert (config.package_dir / "verify.py").is_file()


def test_harbor_export_is_deterministic(tmp_path: Path) -> None:
    if shutil.which("harbor") is None:
        pytest.skip("harbor CLI not available")
    config = HarborAdapterConfig(
        task_id="be-core-s4-local-prompt-injection-resistance",
        model_id="openai/gpt-test",
        workspace=_S4_WS,
        reference_artifact_name="reference.json",
        package_dir=tmp_path / "pkg-a",
        artifacts_dir=tmp_path / "artifacts-a",
    )
    first = export_harbor_task(config)
    config_b = config.model_copy(update={"package_dir": tmp_path / "pkg-b"})
    second = export_harbor_task(config_b)
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.harbor_revision == second.harbor_revision


def test_harbor_export_rejects_unmarked_directory(tmp_path: Path) -> None:
    if shutil.which("harbor") is None:
        pytest.skip("harbor CLI not available")
    existing = tmp_path / "pkg"
    existing.mkdir()
    (existing / "important.txt").write_text("keep me\n", encoding="utf-8")
    config = HarborAdapterConfig(
        task_id="be-core-s4-local-prompt-injection-resistance",
        model_id="openai/gpt-test",
        workspace=_S4_WS,
        reference_artifact_name="reference.json",
        package_dir=existing,
        artifacts_dir=tmp_path / "artifacts",
    )
    with pytest.raises(BenchEvalError, match="refusing to delete"):
        export_harbor_task(config)
    assert (existing / "important.txt").read_text(encoding="utf-8") == "keep me\n"


def test_harbor_reexport_replaces_marked_directory(tmp_path: Path) -> None:
    if shutil.which("harbor") is None:
        pytest.skip("harbor CLI not available")
    config = HarborAdapterConfig(
        task_id="be-core-s4-local-prompt-injection-resistance",
        model_id="openai/gpt-test",
        workspace=_S4_WS,
        reference_artifact_name="reference.json",
        package_dir=tmp_path / "pkg",
        artifacts_dir=tmp_path / "artifacts",
    )
    first = export_harbor_task(config)
    second = export_harbor_task(config)
    assert second.manifest_sha256 == first.manifest_sha256
    assert (config.package_dir / ".bencheval-harbor-export").is_file()


def test_harbor_runner_maps_to_evidence(tmp_path: Path) -> None:
    def fake_export(config: HarborAdapterConfig) -> HarborPackage:
        return HarborPackage(
            root=config.package_dir,
            manifest_sha256="test-manifest",
            harbor_revision="test-revision",
            task_id=config.task_id,
        )

    def fake_runner(config, package):
        config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        candidate = config.artifacts_dir / "reference.json"
        candidate.write_text(
            (_S4_WS / "reference.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return HarborInvokeResult(
            candidate_path=candidate,
            cost_usd=0.02,
            latency_sec=2.0,
            adapter_metadata={
                "harbor_revision": package.harbor_revision,
                "harbor_package_manifest_sha256": package.manifest_sha256,
            },
            package=package,
        )

    out = tmp_path / "evidence.jsonl"
    result = execute_task(
        task_id="be-core-s4-local-prompt-injection-resistance",
        model_id="openai/gpt-test",
        backend=HARBOR_BACKEND,
        output_path=out,
        run_artifacts_dir=tmp_path / "artifacts",
        harbor_runner=fake_runner,
        harbor_export=fake_export,
        skip_doctor=True,
    )
    assert result.evidence.primary_pass is True
    assert result.evidence.backend == HARBOR_BACKEND
    assert "harbor_revision" in result.evidence.adapter_metadata


def test_harbor_without_runner_reports_not_wired(tmp_path: Path) -> None:
    if shutil.which("harbor") is None:
        pytest.skip("harbor CLI not available")
    with pytest.raises(BenchEvalError, match="not wired"):
        execute_task(
            task_id="be-core-s4-local-prompt-injection-resistance",
            model_id="openai/gpt-test",
            backend=HARBOR_BACKEND,
            output_path=tmp_path / "evidence.jsonl",
            run_artifacts_dir=tmp_path / "artifacts",
            skip_doctor=True,
        )


def test_inspect_adapter_model_id_spoof_rejected(tmp_path: Path) -> None:
    def spoof_invoke(config: InspectAdapterConfig) -> InspectInvokeResult:
        config.artifacts_dir.mkdir(parents=True, exist_ok=True)
        candidate = config.artifacts_dir / "reference.json"
        candidate.write_text(
            (_T1_WS / "reference.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        return InspectInvokeResult(
            candidate_path=candidate,
            cost_usd=0.0,
            latency_sec=0.0,
            adapter_metadata={"model_id": "anthropic/claude-spoof"},
        )

    with pytest.raises(BenchEvalError, match="spoof model_id"):
        execute_task(
            task_id="be-core-t1-single-structured-call",
            model_id="openai/gpt-test",
            backend=INSPECT_BACKEND,
            output_path=tmp_path / "evidence.jsonl",
            run_artifacts_dir=tmp_path / "artifacts",
            inspect_invoke=spoof_invoke,
            skip_doctor=True,
        )


def test_local_backend_still_requires_harness_model(tmp_path: Path) -> None:
    with pytest.raises(BenchEvalError, match=r"local runs require|local backend requires"):
        execute_task(
            task_id="be-core-t1-single-structured-call",
            model_id="openai/gpt-test",
            backend=LOCAL_BACKEND,
            output_path=tmp_path / "evidence.jsonl",
        )


def test_cli_doctor_inspect_json() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "bencheval.cli", "doctor", "--backend", "inspect"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(proc.stdout)
    assert payload["backend"] == "inspect"
    assert "checks" in payload
