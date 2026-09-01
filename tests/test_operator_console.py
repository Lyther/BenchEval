"""Deterministic contracts for the optional local operator console.

SUBSTITUTE_JUSTIFICATION
- substitute: ``asgi_ok`` in ``test_capability_middleware_exchanges_cookie_and_rejects_remote``
- replaces: NiceGUI's downstream ASGI application after the BenchEval middleware boundary
- necessity: the assertion must deterministically observe whether a request reaches the downstream
  app without starting a network server; a live browser/server journey separately exercises NiceGUI
- real-option: the real server cannot expose a deterministic downstream-call counter
- proof-limit: this test does not prove NiceGUI rendering, browser cookie behavior, or WebSocket use
- real-proof: ``bencheval ui --no-open`` plus the browser acceptance scenario in the feature handoff

SUBSTITUTE_JUSTIFICATION
- substitute: locally constructed EvidenceRecord in the report and warehouse tests
- replaces: charged benchmark execution needed to create an evidence row
- necessity: exclusive report output handling needs deterministic valid input without provider cost
- real-option: a live benchmark is charged and would test the harness rather than exclusive output
- proof-limit: this test does not prove a benchmark harness or live evidence provenance
- real-proof: registered Tier-1 proofs documented in ``docs/ops/dev-box-pilot.md``

SUBSTITUTE_JUSTIFICATION
- substitute: per-instance ``proofs`` and ``runs`` method replacements in
  ``test_diagnostic_proof_does_not_claim_tier1``
- replaces: the permanent local proof index and append-only run manifest readers
- necessity: the classification needs a deterministic demoted diagnostic proof without mutating
  the operator's permanent proof store or live-run history
- real-option: the current operator store has such a SWE proof, but it is machine-local and cannot
  be safely added or removed by a portable regression
- proof-limit: proves readiness-state mapping only, not proof integrity or live qualification
- real-proof: the real local proof/readiness inventory exercised by the independent review
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.application import OperatorOperations, PlanRequestDTO, ProofViewDTO
from bencheval.cli import main
from bencheval.evidence import EvidenceRecord
from bencheval.exceptions import BenchEvalError
from bencheval.live_run_manifest import LiveRunRecord, append_live_run
from bencheval.proof_bundle import list_private_proofs
from bencheval.ui.security import LoopbackCapabilityMiddleware


def test_core_import_does_not_load_nicegui() -> None:
    script = "import bencheval,sys;print('nicegui' in sys.modules)"
    result = __import__("subprocess").run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    assert result.stdout.strip() == "False"


def test_catalog_and_plan_use_real_registries() -> None:
    operations = OperatorOperations()
    catalog = operations.catalog()
    assert catalog.benchmark_count == 8
    assert catalog.executable_count == 4
    assert any(item.id == "momo" and item.status == "scaffold" for item in catalog.items)

    request = PlanRequestDTO(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        model_id="gpt-5.4-2026-03-05",
        provider_id="bytellm",
    )
    first = operations.plan(request)
    second = operations.plan(request)
    assert first.fingerprint == second.fingerprint
    assert first.instance_count == 2
    assert first.adapter_id == "gpqa"


def test_plan_preserves_cli_diagnostic_admission_boundary() -> None:
    operations = OperatorOperations()
    with pytest.raises(BenchEvalError, match="only valid for a demoted"):
        operations.plan(
            PlanRequestDTO(
                benchmark_id="gpqa-diamond",
                slice_id="smoke",
                model_id="gpt-5.4-2026-03-05",
                diagnostic=True,
            ),
        )
    with pytest.raises(BenchEvalError, match="no wired diagnostic lifecycle"):
        operations.plan(
            PlanRequestDTO(
                benchmark_id="cybergym",
                slice_id="smoke-5",
                model_id="gpt-5.4-2026-03-05",
                diagnostic=True,
            ),
        )
    diagnostic = operations.plan(
        PlanRequestDTO(
            benchmark_id="swe-bench-verified",
            slice_id="swe-bench-verified-diagnostic-1",
            model_id="gpt-5.4-2026-03-05",
            runtime_id="codex-cli",
            diagnostic=True,
        ),
    )
    assert diagnostic.diagnostic is True
    assert diagnostic.executable is False


def test_catalog_page_filters_and_binds_cursor_to_source() -> None:
    operations = OperatorOperations()
    first = operations.catalog_page(kind="benchmark", query="swe", limit=1)
    assert len(first.items) == 1
    assert first.next_cursor is not None
    second = operations.catalog_page(
        kind="benchmark",
        query="swe",
        cursor=first.next_cursor,
        limit=1,
    )
    assert second.items[0].id != first.items[0].id
    with pytest.raises(BenchEvalError, match="refresh required"):
        operations.catalog_page(kind="benchmark", query="gpqa", cursor=first.next_cursor, limit=1)


def test_report_is_exclusive_and_real(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    record = EvidenceRecord(
        run_id="run-test",
        task_id="task-1",
        model_id="gpt-5.4-2026-03-05",
        backend="inspect",
        execution_profile="E3",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.0,
        latency_sec=1.0,
        verifier_log_path=None,
        failure_labels=[],
        created_at=datetime.now(tz=UTC),
    )
    evidence.write_text(record.model_dump_json() + "\n", encoding="utf-8")
    output = tmp_path / "report.md"
    result = OperatorOperations().report(evidence, output)
    assert result.path == str(output.resolve())
    assert result.sha256.startswith("sha256:")
    assert "# BenchEval Evidence Report" in output.read_text(encoding="utf-8")
    with pytest.raises(BenchEvalError, match="exclusive output"):
        OperatorOperations().report(evidence, output)


def test_parquet_directory_is_returned_as_a_bounded_artifact(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    record = EvidenceRecord(
        run_id="run-test",
        task_id="task-1",
        model_id="gpt-5.4-2026-03-05",
        backend="inspect",
        execution_profile="E3",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.0,
        latency_sec=1.0,
        verifier_log_path=None,
        failure_labels=[],
        created_at=datetime.now(tz=UTC),
    )
    evidence.write_text(record.model_dump_json() + "\n", encoding="utf-8")
    result = OperatorOperations().warehouse(evidence, tmp_path / "parquet", fmt="parquet")
    assert Path(result.path).is_dir()
    assert result.size > 0
    assert result.sha256.startswith("sha256:")
    with pytest.raises(BenchEvalError, match="empty or missing"):
        OperatorOperations().warehouse(evidence, tmp_path / "parquet", fmt="parquet")

    redirected = tmp_path / "redirected"
    redirected.mkdir()
    symlink_output = tmp_path / "warehouse-link"
    symlink_output.symlink_to(redirected, target_is_directory=True)
    with pytest.raises(BenchEvalError, match="symlink"):
        OperatorOperations().warehouse(evidence, symlink_output, fmt="parquet")

    ancestor_target = tmp_path / "ancestor-target"
    ancestor_target.mkdir()
    ancestor_link = tmp_path / "ancestor-link"
    ancestor_link.symlink_to(ancestor_target, target_is_directory=True)
    with pytest.raises(BenchEvalError, match="symlink"):
        OperatorOperations().warehouse(
            evidence,
            ancestor_link / "warehouse",
            fmt="parquet",
        )


def test_run_detail_projects_history_evidence_and_qualification(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    record = EvidenceRecord(
        run_id="run-detail",
        task_id="task-1",
        model_id="gpt-5.4-2026-03-05",
        backend="inspect",
        execution_profile="E3",
        primary_pass=False,
        partial_score=0.0,
        cost_usd=0.0,
        latency_sec=1.0,
        verifier_log_path=None,
        failure_labels=[],
        artifact_paths=["official.json"],
        created_at=datetime.now(tz=UTC),
    )
    evidence.write_text(record.model_dump_json() + "\n", encoding="utf-8")
    manifest = tmp_path / "runs.jsonl"
    append_live_run(
        manifest,
        LiveRunRecord(
            run_id="run-detail",
            host="local-test",
            model_id=record.model_id,
            status="completed",
            evidence_path=str(evidence),
            generated_at=datetime.now(tz=UTC),
        ),
    )
    detail = OperatorOperations().run_detail("run-detail", manifest)
    assert detail.summary.status == "completed"
    assert detail.history[0]["status"] == "completed"
    assert detail.evidence[0].artifacts == ("official.json",)
    assert detail.qualification is not None


def test_qualification_uses_slice_population_not_candidate_rows(tmp_path: Path) -> None:
    artifact = tmp_path / "result.json"
    artifact.write_text("official\n", encoding="utf-8")
    evidence = tmp_path / "partial.jsonl"
    record = EvidenceRecord(
        run_id="lane-run",
        task_id="fix-git",
        model_id="kimi-k2.7-code",
        execution_profile="E2",
        backend="harbor",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.0,
        latency_sec=1.0,
        artifact_paths=[str(artifact)],
        verifier_log_path=str(artifact),
        created_at=datetime.now(tz=UTC),
        benchmark_id="terminal-bench",
        benchmark_version="terminal-bench@2.1",
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@0.17.1",
        runtime_id="codex-cli",
        runtime_version="0.148.0",
        runtime_config_hash="sha256:test",
        provider_id="bytellm",
        provider_config_hash="sha256:provider",
        instance_id="fix-git",
        interpretation_label="adapter_smoke",
        verifier_integrity_label="native",
        attempt_validity="valid",
        counts_toward_pass_at_k=True,
        adapter_metadata={
            "producer_content_sha256": "sha256:" + ("a" * 64),
        },
    )
    evidence.write_text(record.model_dump_json() + "\n", encoding="utf-8")
    qualification = OperatorOperations().qualify(evidence)
    assert not qualification.ok
    assert any("expected" in reason or "population" in reason for reason in qualification.reasons)
    with pytest.raises(BenchEvalError, match="not live-proof qualified"):
        OperatorOperations().register(
            run_id=record.run_id,
            model_id=record.model_id,
            status="passed",
            benchmark_id="terminal-bench",
            slice_id="smoke-5",
            runtime_id="codex-cli",
            evidence_path=evidence,
            manifest_path=tmp_path / "runs.jsonl",
        )


def _asgi_scope(*, host: str, query: bytes = b"", cookie: str = "") -> dict[str, object]:
    headers = [(b"host", host.encode())]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": query,
        "headers": headers,
        "client": ("127.0.0.1", 51000),
    }


def test_capability_middleware_exchanges_cookie_and_rejects_remote() -> None:
    reached: list[bool] = []

    async def asgi_ok(scope, receive, send) -> None:
        reached.append(True)
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def request(scope: dict[str, object]) -> list[dict[str, object]]:
        sent: list[dict[str, object]] = []

        async def send(message: dict[str, object]) -> None:
            sent.append(message)

        middleware = LoopbackCapabilityMiddleware(asgi_ok, capability="secret", port=8090)
        await middleware(scope, receive, send)
        return sent

    exchange = asyncio.run(request(_asgi_scope(host="127.0.0.1:8090", query=b"cap=secret")))
    assert exchange[0]["status"] == 200
    cookie_header = dict(exchange[0]["headers"])[b"set-cookie"].decode()
    assert "HttpOnly" in cookie_header and "SameSite=Strict" in cookie_header
    assert b"history.replaceState" in exchange[1]["body"]
    assert reached == []

    authorized = asyncio.run(
        request(_asgi_scope(host="127.0.0.1:8090", cookie="bencheval_ui=secret")),
    )
    assert authorized[0]["status"] == 200
    assert reached == [True]

    malformed_host = _asgi_scope(
        host="127.0.0.1:99999",
        cookie="bencheval_ui=secret",
    )
    malformed = asyncio.run(request(malformed_host))
    assert malformed[0]["status"] == 403

    for hostile_host in ("[::1", "[gggg]"):
        malformed_bracket = _asgi_scope(
            host=hostile_host,
            cookie="bencheval_ui=secret",
        )
        rejected_bracket = asyncio.run(request(malformed_bracket))
        assert rejected_bracket[0]["status"] == 403

    malformed_origin = _asgi_scope(
        host="127.0.0.1:8090",
        cookie="bencheval_ui=secret",
    )
    malformed_origin["headers"].append((b"origin", b"http://127.0.0.1:99999"))
    rejected_origin = asyncio.run(request(malformed_origin))
    assert rejected_origin[0]["status"] == 403

    for hostile_origin in (b"http://[::1", b"http://[gggg]"):
        malformed_bracket_origin = _asgi_scope(
            host="127.0.0.1:8090",
            cookie="bencheval_ui=secret",
        )
        malformed_bracket_origin["headers"].append((b"origin", hostile_origin))
        rejected_bracket_origin = asyncio.run(request(malformed_bracket_origin))
        assert rejected_bracket_origin[0]["status"] == 403

    denied = asyncio.run(request(_asgi_scope(host="attacker.invalid:8090")))
    assert denied[0]["status"] == 403
    assert reached == [True]

    forwarded = _asgi_scope(host="127.0.0.1:8090", cookie="bencheval_ui=secret")
    forwarded["headers"].append((b"x-forwarded-host", b"attacker.invalid"))
    rejected_proxy = asyncio.run(request(forwarded))
    assert rejected_proxy[0]["status"] == 403
    assert reached == [True]


def test_ui_rejects_privileged_port_without_starting_server(capsys) -> None:
    assert main(["ui", "--port", "80", "--no-open"]) == 1
    assert "UI port must be between" in capsys.readouterr().err


def test_empty_proof_store_is_a_valid_inventory(tmp_path: Path) -> None:
    assert list_private_proofs(tmp_path) == ()


def test_diagnostic_proof_does_not_claim_tier1(monkeypatch: pytest.MonkeyPatch) -> None:
    operations = OperatorOperations()
    proof = ProofViewDTO(
        proof_id="sha256:" + ("b" * 64),
        run_id="run-swe-diagnostic",
        path="/local/proof",
        classification="complete",
        classification_reason=None,
        verified=True,
        benchmark_id="swe-bench-verified",
    )
    monkeypatch.setattr(operations, "proofs", lambda store=None: (proof,))
    monkeypatch.setattr(operations, "runs", lambda manifest_path=None: ())
    readiness = {row.benchmark_id: row for row in operations.readiness()}
    assert readiness["swe-bench-verified"].tier1_state == "proof-present-not-tier1"


@pytest.mark.parametrize("decoded", ["null", "[1, 2]"])
def test_catalog_cursor_rejects_non_object_payload(decoded: str) -> None:
    import base64

    cursor = base64.urlsafe_b64encode(decoded.encode()).decode()
    with pytest.raises(BenchEvalError, match="catalog cursor is invalid"):
        OperatorOperations().catalog_page(cursor=cursor)
