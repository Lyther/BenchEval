from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.backends import INSPECT_BACKEND
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError
from bencheval.executor import execute_task
from bencheval.inspect_adapter import (
    MOCKLLM_MODEL_ID,
    InspectAdapterConfig,
    _extract_json_object,
    default_inspect_invoke,
)

_ROOT = Path(__file__).resolve().parents[1]
_T1_WS = _ROOT / "config/tasks/core-8/workspaces/be-core-t1-single-structured-call"


def test_extract_json_from_fenced_prose() -> None:
    text = (
        "Here is the answer:\n```json\n"
        '{"tool": "mock_calendar", "arguments": {"title": "x"}}\n```\n'
    )
    payload = _extract_json_object(text)
    assert payload["tool"] == "mock_calendar"


def test_extract_json_from_embedded_object() -> None:
    payload = _extract_json_object('Sure: {"tool": "x", "arguments": {}} thanks')
    assert payload["tool"] == "x"


def test_extract_json_invalid_raises_adapter_failure() -> None:
    with pytest.raises(AdapterFailureError, match="not valid JSON") as exc:
        _extract_json_object("plain text only")
    assert exc.value.failure_label == "model_output_invalid"


def test_mockllm_e0_writes_passing_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bencheval.doctor._try_import_inspect_ai",
        lambda: (None, "inspect_ai import failed: ImportError: broken dependency"),
    )
    out = tmp_path / "evidence.jsonl"
    result = execute_task(
        task_id="be-core-t1-single-structured-call",
        model_id=MOCKLLM_MODEL_ID,
        backend=INSPECT_BACKEND,
        output_path=out,
        run_artifacts_dir=tmp_path / "artifacts",
    )
    assert result.evidence.primary_pass is True
    assert result.evidence.adapter_metadata["invocation_mode"] == "mockllm_deterministic"
    assert result.evidence.adapter_metadata["inspect_ai_version"] == "not_required"
    assert len(read_evidence_jsonl(out)) == 1


def test_non_json_provider_output_records_adapter_failure(tmp_path: Path) -> None:
    def bad_invoke(config: InspectAdapterConfig):
        del config
        raise AdapterFailureError(
            "model output is not valid JSON: Expecting value",
            failure_label="model_output_invalid",
            cost_usd=0.01,
            latency_sec=0.5,
            adapter_metadata={"inspect_ai_version": "test"},
        )

    out = tmp_path / "evidence.jsonl"
    result = execute_task(
        task_id="be-core-t1-single-structured-call",
        model_id="openai/gpt-test",
        backend=INSPECT_BACKEND,
        output_path=out,
        run_artifacts_dir=tmp_path / "artifacts",
        inspect_invoke=bad_invoke,
        skip_doctor=True,
    )
    assert result.evidence.primary_pass is False
    assert result.evidence.failure_labels == ["model_output_invalid"]
    assert result.verifier_log_path.name == "adapter_failure.json"


def test_cli_inspect_mockllm_exits_zero_with_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "bencheval.doctor._try_import_inspect_ai",
        lambda: (None, "inspect_ai import failed: ImportError: broken dependency"),
    )
    from contextlib import redirect_stdout
    from io import StringIO

    from bencheval.cli import main

    out = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    buf = StringIO()
    with redirect_stdout(buf):
        code = main(
            [
                "run",
                "--task",
                "be-core-t1-single-structured-call",
                "--model",
                MOCKLLM_MODEL_ID,
                "--backend",
                "inspect",
                "--output",
                str(out),
                "--artifacts-dir",
                str(artifacts),
            ],
        )
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["primary_pass"] is True
    assert payload["backend"] == INSPECT_BACKEND
    records = read_evidence_jsonl(out)
    assert len(records) == 1
    assert records[0].adapter_metadata["invocation_mode"] == "mockllm_deterministic"


def test_cli_inspect_mockllm_subprocess_smoke(tmp_path: Path) -> None:
    import subprocess
    import sys

    out = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "bencheval.cli",
            "run",
            "--task",
            "be-core-t1-single-structured-call",
            "--model",
            MOCKLLM_MODEL_ID,
            "--backend",
            "inspect",
            "--output",
            str(out),
            "--artifacts-dir",
            str(artifacts),
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["primary_pass"] is True
    assert payload["model_id"] == MOCKLLM_MODEL_ID
    record = read_evidence_jsonl(out)[0]
    assert record.adapter_metadata["invocation_mode"] == "mockllm_deterministic"


def test_default_inspect_invoke_mockllm_skips_generate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("generate should not run for mockllm E0")

    monkeypatch.setattr("bencheval.inspect_adapter.asyncio.run", boom)
    config = InspectAdapterConfig(
        task_id="be-core-t1-single-structured-call",
        model_id=MOCKLLM_MODEL_ID,
        execution_profile="E0",
        workspace=_T1_WS,
        reference_artifact_name="reference.json",
        artifacts_dir=tmp_path / "artifacts",
    )
    result = default_inspect_invoke(config)
    assert result.candidate_path.is_file()
    assert result.adapter_metadata["inspect_ai_version"] == "not_required"
