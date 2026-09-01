"""Regressions for the first hosted review of the operator console.

SUBSTITUTE_JUSTIFICATION
- substitute: ``executor_probe`` installed at
  ``bencheval.application.operations.execute_control_plane_run``
- replaces: the charged native benchmark executor after application-layer confirmation
- necessity: stale confirmation and symlink-output rejection must prove that no charged launch is
  reached; a real provider run would be billable and cannot deterministically expose a call counter
- real-option: a dry run never crosses the launch boundary, while a live run could spend money
  before the assertion observes the defect
- proof-limit: proves application-layer fail-before-launch behavior only; it does not prove a
  benchmark harness, provider, scoring, or live cancellation
- real-proof: BLOCKED on a future deliberately charged console run with retained launch evidence
- covered tests: ``test_start_rejects_changed_output_confirmation_before_executor`` and
  ``test_start_rejects_symlinked_output_before_executor``

SUBSTITUTE_JUSTIFICATION
- substitute: constructed 201-row ``EvidenceRecord`` JSONL and disposable ``LiveRunRecord``
- replaces: a large retained benchmark run and its append-only local registration
- necessity: the detail projection must exercise its exact display bound without creating a
  charged 201-instance run or mutating the operator manifest
- real-option: current retained proofs are smaller and permanent operator state is not safe test
  data
- proof-limit: proves projection count/truncation metadata only, not native evidence truth
- real-proof: BLOCKED on a retained real run with more than 200 evidence records
- covered tests: ``test_run_detail_marks_bounded_evidence_projection``

SUBSTITUTE_JUSTIFICATION
- substitute: constructed ``hle_eval/`` script tree and monkeypatched ``BENCHEVAL_HLE_HOME``
- replaces: the official pinned CAIS HLE checkout selected for native preflight
- necessity: the test must make one script leaf unreadable without changing the operator's official
  checkout; no official HLE checkout is guaranteed on the local/CI host
- real-option: chmod on the operator checkout is unsafe, and a disposable pinned upstream clone is
  not an available repository test prerequisite
- proof-limit: proves conversion of a local script-inspection failure into a typed doctor check
  only; it does not prove CAIS script identity, dataset access, judge execution, or live readiness
- real-proof: BLOCKED on a disposable clone of CAIS HLE at the shipped pin; clone it, make a copied
  official script unreadable, and run ``OperatorOperations.doctor(backend='hle-native', ...)``
- covered tests: ``test_hle_preflight_converts_unreadable_script_to_failed_check``
"""

from __future__ import annotations

import http.client
import os
import select
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from bencheval.application import OperatorOperations, PlanRequestDTO
from bencheval.control_plane_executor import ControlPlaneRunSummary
from bencheval.evidence import EvidenceRecord
from bencheval.exceptions import BenchEvalError
from bencheval.live_run_manifest import LiveRunRecord, append_live_run


def _free_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _gpqa_request(*, output_path: str | None = None, artifacts_dir: str | None = None):
    return PlanRequestDTO(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        model_id="gpt-5.4-2026-03-05",
        provider_id="bytellm",
        output_path=output_path,
        artifacts_dir=artifacts_dir,
    )


def test_confirmation_fingerprint_binds_operator_output_paths(tmp_path: Path) -> None:
    operations = OperatorOperations()
    first = operations.plan(
        _gpqa_request(
            output_path=str(tmp_path / "first.jsonl"),
            artifacts_dir=str(tmp_path / "first-artifacts"),
        ),
    )
    changed_output = operations.plan(
        _gpqa_request(
            output_path=str(tmp_path / "second.jsonl"),
            artifacts_dir=str(tmp_path / "first-artifacts"),
        ),
    )
    changed_artifacts = operations.plan(
        _gpqa_request(
            output_path=str(tmp_path / "first.jsonl"),
            artifacts_dir=str(tmp_path / "second-artifacts"),
        ),
    )
    assert first.fingerprint != changed_output.fingerprint
    assert first.fingerprint != changed_artifacts.fingerprint
    equivalent = operations.plan(
        _gpqa_request(
            output_path=os.path.relpath(tmp_path / "first.jsonl", Path.cwd()),
            artifacts_dir=os.path.relpath(tmp_path / "first-artifacts", Path.cwd()),
        ),
    )
    assert first.fingerprint == equivalent.fingerprint


def test_start_rejects_changed_output_confirmation_before_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations = OperatorOperations()
    original = _gpqa_request(output_path=str(tmp_path / "reviewed.jsonl"))
    changed = _gpqa_request(output_path=str(tmp_path / "changed.jsonl"))
    reviewed = operations.plan(original)
    calls: list[bool] = []

    def executor_probe(**kwargs) -> ControlPlaneRunSummary:
        calls.append(True)
        return ControlPlaneRunSummary(
            run_id=str(kwargs["run_id"]),
            instance_count=1,
            passed_count=0,
            failed_count=1,
            output_path=Path(kwargs["output_path"]),
        )

    monkeypatch.setattr(
        "bencheval.application.operations.execute_control_plane_run",
        executor_probe,
    )
    with pytest.raises(BenchEvalError, match="run plan changed"):
        operations.start(changed, expected_fingerprint=reviewed.fingerprint)
    assert calls == []


@pytest.mark.parametrize("redirected_field", ["output_path", "artifacts_dir"])
def test_start_rejects_symlinked_output_before_executor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    redirected_field: str,
) -> None:
    target = tmp_path / "redirect-target"
    target.mkdir()
    link = tmp_path / "redirect"
    link.symlink_to(target, target_is_directory=True)
    values = {
        "output_path": str(tmp_path / "evidence.jsonl"),
        "artifacts_dir": str(tmp_path / "artifacts"),
    }
    values[redirected_field] = str(
        link / ("evidence.jsonl" if redirected_field == "output_path" else "artifacts"),
    )
    request = _gpqa_request(**values)
    operations = OperatorOperations()
    preview = operations.plan(request)
    calls: list[bool] = []

    def executor_probe(**kwargs) -> ControlPlaneRunSummary:
        calls.append(True)
        return ControlPlaneRunSummary(
            run_id=str(kwargs["run_id"]),
            instance_count=1,
            passed_count=0,
            failed_count=1,
            output_path=Path(kwargs["output_path"]),
        )

    monkeypatch.setattr(
        "bencheval.application.operations.execute_control_plane_run",
        executor_probe,
    )
    with pytest.raises(BenchEvalError, match="symlink"):
        operations.start(request, expected_fingerprint=preview.fingerprint)
    assert calls == []
    assert list(target.iterdir()) == []


@pytest.mark.parametrize(
    ("plan_request", "expected_backend", "expected_check"),
    [
        (
            PlanRequestDTO(
                benchmark_id="bfcl-v4",
                slice_id="smoke-5",
                model_id="gpt-5.2-2025-12-11",
            ),
            "bfcl-native",
            "bfcl_harness",
        ),
        (
            PlanRequestDTO(
                benchmark_id="hle",
                slice_id="smoke",
                model_id="gpt-5.4-2026-03-05",
            ),
            "hle-native",
            "hle_harness",
        ),
        (
            PlanRequestDTO(
                benchmark_id="swe-bench-verified",
                slice_id="swe-bench-verified-diagnostic-1",
                model_id="gpt-5.4-2026-03-05",
                runtime_id="codex-cli",
                diagnostic=True,
            ),
            "swebench-native",
            "docker",
        ),
    ],
)
def test_native_plans_use_native_preflight(
    plan_request: PlanRequestDTO,
    expected_backend: str,
    expected_check: str,
) -> None:
    operations = OperatorOperations()
    preview = operations.plan(plan_request)
    assert preview.backend == expected_backend
    report = operations.doctor(
        backend=preview.backend,
        profile=preview.execution_profile,
        model_id=preview.model_id,
    )
    assert report.backend == expected_backend
    assert expected_check in {check.name for check in report.checks}


def test_hle_preflight_converts_unreadable_script_to_failed_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hle_root = tmp_path / "hle"
    eval_dir = hle_root / "hle_eval"
    eval_dir.mkdir(parents=True)
    prediction = eval_dir / "run_model_predictions.py"
    prediction.write_text("print('prediction')\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("print('judge')\n", encoding="utf-8")
    prediction.chmod(0)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(hle_root))
    try:
        report = OperatorOperations().doctor(
            backend="hle-native",
            profile="E3",
            model_id="gpt-5.4-2026-03-05",
        )
    finally:
        prediction.chmod(0o600)
    harness = next(check for check in report.checks if check.name == "hle_harness")
    assert harness.status == "fail"
    assert "cannot inspect" in harness.message


def test_bfcl_preflight_rejects_model_outside_pinned_manifest() -> None:
    report = OperatorOperations().doctor(
        backend="bfcl-native",
        profile="E3",
        model_id="gpt-5.4-2026-03-05",
    )
    support = next(check for check in report.checks if check.name == "bfcl_model_support")
    assert support.status == "fail"
    assert "not supported" in support.message


def test_run_detail_marks_bounded_evidence_projection(tmp_path: Path) -> None:
    run_id = "run-large-detail"
    model_id = "gpt-5.4-2026-03-05"
    evidence = tmp_path / "evidence.jsonl"
    rows = [
        EvidenceRecord(
            run_id=run_id,
            task_id=f"task-{index:03d}",
            model_id=model_id,
            backend="inspect",
            execution_profile="E3",
            primary_pass=False,
            partial_score=0.0,
            cost_usd=0.0,
            latency_sec=1.0,
            created_at=datetime.now(tz=UTC),
        )
        for index in range(201)
    ]
    evidence.write_text(
        "".join(row.model_dump_json() + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest = tmp_path / "runs.jsonl"
    append_live_run(
        manifest,
        LiveRunRecord(
            run_id=run_id,
            host="local-test",
            model_id=model_id,
            evidence_path=str(evidence),
            status="completed",
            generated_at=datetime.now(tz=UTC),
        ),
    )
    detail = OperatorOperations().run_detail(run_id, manifest)
    assert len(detail.evidence) == 200
    assert detail.evidence_total == 201
    assert detail.evidence_truncated is True


def test_corrupt_proof_index_renders_durable_page_error(tmp_path: Path) -> None:
    checkout = Path(__file__).resolve().parents[2]
    home = tmp_path / "home"
    shutil.copytree(checkout / "config", home / "config")
    proof_store = home / "results" / "proofs"
    proof_store.mkdir(parents=True)
    (proof_store / "proofs.jsonl").write_text("{bad\n", encoding="utf-8")
    port = _free_loopback_port()
    env = os.environ.copy()
    env.pop("PYTEST_CURRENT_TEST", None)
    env["BENCHEVAL_HOME"] = str(home)
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "bencheval.cli",
            "ui",
            "--port",
            str(port),
            "--no-open",
        ],
        cwd=checkout,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        assert process.stdout is not None
        ready, _, _ = select.select([process.stdout], [], [], 20)
        assert ready, "console did not print its capability URL"
        line = process.stdout.readline().strip()
        assert line.startswith("BenchEval operator console: "), line
        launch_url = line.removeprefix("BenchEval operator console: ")
        parsed = urlsplit(launch_url)
        deadline = time.monotonic() + 20
        while True:
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            try:
                connection.connect()
                break
            except ConnectionRefusedError:
                connection.close()
                if process.poll() is not None:
                    assert process.stderr is not None
                    pytest.fail(process.stderr.read())
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        connection.request("GET", f"/?{parsed.query}")
        exchange = connection.getresponse()
        exchange.read()
        assert exchange.status == 200
        cookie = exchange.getheader("Set-Cookie")
        assert cookie is not None
        cookie = cookie.split(";", maxsplit=1)[0]
        for route in ("/proofs", "/readiness"):
            connection.request("GET", route, headers={"Cookie": cookie})
            response = connection.getresponse()
            body = response.read().decode("utf-8", errors="replace")
            assert response.status == 200
            assert "Integrity state unavailable" in body
        connection.close()
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=10)
