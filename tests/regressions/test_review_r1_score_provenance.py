"""Round-1 score/provenance contracts: qualify, harness, verdicts, BFCL/HLE/proxy.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed ``SwebenchCliResult``/``HarborCliResult``/``BfclCliResult``
  process results and the synthetic artifact payloads written below (including
  official-format BFCL ``BFCL_v4_*_score.json`` JSONL artifacts, Harbor
  result.json files, SWE verifier.json files, HLE judged-output files, and GPQA
  inspect log payloads); and the proxy-env monkeypatching in
  ``test_f006_proxy_route_identity_in_runtime_hash``
- replaces: the external mini-SWE-agent/Harbor/BFCL/inspect harness processes,
  the artifacts they would author and the host proxy environment
- necessity: the assertions require deterministic malformed/incoherent artifact
  states and controlled env identities that the real harnesses and host cannot
  safely and deterministically produce on demand
- real-option: the dev-box live lanes for each harness; not available in the
  local Tier-0 environment
- proof-limit: proves BenchEval-side parser fail-closed behavior, provenance
  stamping, and CLI error surfaces only — not harness execution, scorer
  correctness, or live readiness
- real-proof: BLOCKED until the dev-box pilot lanes re-qualify
  (docs/ops/dev-box-pilot.md)
"""

from __future__ import annotations

import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import BfclCliResult, parse_bfcl_instance_outcome
from bencheval.control_plane_executor import (
    _hash_effective_runtime_options,
    execute_control_plane_run,
)
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import BenchEvalError
from bencheval.hle_adapter import parse_hle_official_score
from bencheval.live_proof import qualify_lane
from bencheval.model_compare import assess_model_comparison_validity
from bencheval.run_bundle import export_run_bundle
from bencheval.swebench_adapter import SwebenchCliResult, parse_swebench_instance_outcome
from bencheval.terminal_bench_harbor import HarborCliResult, parse_harbor_instance_outcome

_TS = datetime(2026, 6, 1, tzinfo=UTC)
_MODEL = "kimi-k2.7-code"


def _touch(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("native-verifier\n", encoding="utf-8")
    return str(path.resolve())


def _eligible_row(
    *,
    instance_id: str,
    verifier: Path,
    benchmark_id: str = "terminal-bench",
    slice_id: str = "smoke-5",
) -> EvidenceRecord:
    log = _touch(verifier)
    return EvidenceRecord(
        run_id="lane-run",
        task_id=instance_id,
        model_id=_MODEL,
        execution_profile="E2",
        backend="harbor",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.0,
        latency_sec=1.0,
        created_at=_TS,
        benchmark_id=benchmark_id,
        benchmark_version="terminal-bench@2.1",
        slice_id=slice_id,
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@test",
        runtime_id="claude-code",
        runtime_version="claude@test",
        runtime_config_hash="sha256:test-config",
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm-test",
        instance_id=instance_id,
        interpretation_label="adapter_smoke",
        verifier_integrity_label="native",
        verifier_log_path=log,
        artifact_paths=[log],
        attempt_validity="valid",
        counts_toward_pass_at_k=True,
    )


def test_f001_duplicate_instance_ids_fail_expected_instances(tmp_path: Path) -> None:
    evidence = tmp_path / "dup.jsonl"
    sink = JsonlEvidenceSink()
    log = tmp_path / "v.json"
    for _ in range(5):
        sink.append_jsonl(evidence, _eligible_row(instance_id="same-task", verifier=log))
    result = qualify_lane(
        evidence,
        expected_instances=5,
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        require_runtime=True,
        repo_root=tmp_path,
    )
    assert result.ok is False
    assert any("unique" in r or "duplicate" in r for r in result.reasons)


def test_f001_five_distinct_instance_ids_qualify(tmp_path: Path) -> None:
    evidence = tmp_path / "ok.jsonl"
    sink = JsonlEvidenceSink()
    for i in range(5):
        sink.append_jsonl(
            evidence,
            _eligible_row(instance_id=f"task-{i:02d}", verifier=tmp_path / f"v{i}.json"),
        )
    result = qualify_lane(
        evidence,
        expected_instances=5,
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        require_runtime=True,
        repo_root=tmp_path,
    )
    assert result.ok is True
    assert result.reasons == ()


def test_f002_model_compare_rejects_missing_harness_version() -> None:
    def row(model_id: str) -> EvidenceRecord:
        return EvidenceRecord(
            run_id=f"run-{model_id}",
            task_id="tb-001",
            model_id=model_id,
            execution_profile="E0",
            backend="inspect",
            primary_pass=True,
            partial_score=1.0,
            cost_usd=0.0,
            latency_sec=1.0,
            created_at=_TS,
            benchmark_id="terminal-bench",
            benchmark_version="terminal-bench@2.1",
            slice_id="smoke-5",
            adapter_id="terminal-bench-harbor",
            harness_kind="harbor",
            harness_version=None,
            runtime_id="claude-code",
            runtime_version="claude@test",
            runtime_config_hash="sha256:cfg",
            provider_id="bytellm",
            instance_id="tb-001",
            interpretation_label="model_comparison",
        )

    verdict = assess_model_comparison_validity([row("openai/a")], [row("openai/b")])
    assert verdict.valid is False
    assert any("harness" in r for r in verdict.reasons)


@pytest.mark.parametrize(
    ("adapter", "filename", "key", "bad"),
    [
        ("swe", "verifier.json", "resolved", "false"),
        ("swe", "verifier.json", "tests_passed", "false"),
        ("swe", "verifier.json", "resolved", 0),
        ("swe", "verifier.json", "resolved", None),
        ("swe", "verifier.json", "resolved", []),
        ("swe", "verifier.json", "resolved", {}),
        ("tb", "result.json", "resolved", "false"),
        ("tb", "result.json", "success", "false"),
        ("tb", "result.json", "resolved", 1),
        ("tb", "result.json", "resolved", None),
        ("tb", "result.json", "resolved", []),
        ("tb", "result.json", "resolved", {}),
    ],
)
def test_f003_non_boolean_verdicts_fail_closed(
    tmp_path: Path,
    adapter: str,
    filename: str,
    key: str,
    bad: object,
) -> None:
    art = tmp_path / "inst"
    art.mkdir()
    (art / filename).write_text(json.dumps({key: bad}), encoding="utf-8")
    if adapter == "swe":
        out = parse_swebench_instance_outcome(
            instance_id="swe-001",
            cli=SwebenchCliResult(0, "", "", 0.1, ("mini-extra", "swebench")),
            artifacts_dir=art,
            repo_root=tmp_path,
            harness_version="swe@test",
        )
    else:
        out = parse_harbor_instance_outcome(
            instance_id="tb-001",
            cli=HarborCliResult(0, "", "", 0.1, ("harbor", "run")),
            artifacts_dir=art,
            repo_root=tmp_path,
            harness_version="harbor@test",
        )
    assert out.primary_pass is False
    assert out.partial_score == 0.0
    assert out.failure_class == "runtime_output_unparseable"


def _bfcl_score_jsonl(rows: list[object]) -> str:
    return "".join(json.dumps(row) + "\n" for row in rows)


_BFCL_HEADER_PERFECT = {"accuracy": 1.0, "correct_count": 1, "total_count": 1}
_BFCL_HEADER_PARTIAL = {"accuracy": 0.5, "correct_count": 1, "total_count": 2}
_BFCL_FAILURE_ROW = {
    "id": "bfcl_smoke_001_0",
    "valid": False,
    "error": ["mismatch"],
    "error_type": "ast:exec_output_mismatch",
}


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(
            _bfcl_score_jsonl([{"accuracy": "1.0", "correct_count": 1, "total_count": 1}]),
            id="accuracy-str",
        ),
        pytest.param(
            _bfcl_score_jsonl([{"accuracy": True, "correct_count": 1, "total_count": 1}]),
            id="accuracy-bool",
        ),
        pytest.param(
            _bfcl_score_jsonl([{"accuracy": 1.5, "correct_count": 1, "total_count": 1}]),
            id="accuracy-out-of-range",
        ),
        pytest.param(
            _bfcl_score_jsonl([{"accuracy": float("nan"), "correct_count": 1, "total_count": 1}]),
            id="accuracy-nan",
        ),
        pytest.param(
            _bfcl_score_jsonl([{"accuracy": float("inf"), "correct_count": 1, "total_count": 1}]),
            id="accuracy-infinity",
        ),
        pytest.param(
            _bfcl_score_jsonl(
                [{"accuracy": 1.0, "correct_count": 0, "total_count": 1}, _BFCL_FAILURE_ROW],
            ),
            id="accuracy-incoherent-with-counts",
        ),
        pytest.param(
            _bfcl_score_jsonl([{"accuracy": 0.5, "correct_count": 2, "total_count": 1}]),
            id="correct-count-exceeds-total",
        ),
        pytest.param(
            _bfcl_score_jsonl([{"accuracy": 1.0, "correct_count": 1, "total_count": "1"}]),
            id="total_count-str",
        ),
        pytest.param(
            _bfcl_score_jsonl([{"accuracy": 1.0, "correct_count": True, "total_count": 1}]),
            id="correct_count-bool",
        ),
        pytest.param(
            _bfcl_score_jsonl([{"accuracy": 1.0, "total_count": 1}]),
            id="correct_count-missing",
        ),
        pytest.param(
            _bfcl_score_jsonl([_BFCL_HEADER_PARTIAL, {**_BFCL_FAILURE_ROW, "valid": True}]),
            id="failure-row-valid-true",
        ),
        pytest.param(
            _bfcl_score_jsonl([_BFCL_HEADER_PARTIAL, {**_BFCL_FAILURE_ROW, "valid": "false"}]),
            id="failure-row-valid-str",
        ),
        pytest.param(
            _bfcl_score_jsonl(
                [{"accuracy": 0.0, "correct_count": 0, "total_count": 2}, _BFCL_FAILURE_ROW],
            ),
            id="failure-row-count-mismatch",
        ),
        pytest.param(
            _bfcl_score_jsonl(
                [
                    {"accuracy": 0.0, "correct_count": 0, "total_count": 2},
                    _BFCL_FAILURE_ROW,
                    {**_BFCL_FAILURE_ROW, "error": ["other mismatch"]},
                ],
            ),
            id="failure-row-duplicate-ids",
        ),
        pytest.param(
            _bfcl_score_jsonl([_BFCL_HEADER_PARTIAL]) + "[1, 2]\n",
            id="failure-row-not-an-object",
        ),
        pytest.param(
            _bfcl_score_jsonl([_BFCL_HEADER_PARTIAL]) + "not-json\n",
            id="failure-row-invalid-json",
        ),
        pytest.param(
            json.dumps([_BFCL_HEADER_PERFECT]) + "\n",
            id="legacy-json-array",
        ),
    ],
)
def test_f003_malformed_bfcl_official_score_fails_closed(
    tmp_path: Path,
    content: str,
) -> None:
    """BFCL scoring authority moved to the official evaluate score artifact; the
    malformed-verdict fail-closed contract applies there with equal force. The
    artifact is JSONL (header first, failure rows only) at the pinned upstream
    commit — see tests/specs/test_bfcl_official_score_contracts.py."""
    art = tmp_path / "inst"
    art.mkdir()
    score_dir = art / "scores"
    score_file = score_dir / _MODEL / "non_live" / "BFCL_v4_bfcl_smoke_001_score.json"
    score_file.parent.mkdir(parents=True)
    score_file.write_text(content, encoding="utf-8")
    out = parse_bfcl_instance_outcome(
        instance_id="bfcl_smoke_001",
        cli=BfclCliResult(0, "", "", 0.1, ("bfcl", "evaluate")),
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="bfcl@test",
        score_dir=score_dir,
        model_id=_MODEL,
    )
    assert out.primary_pass is False
    assert out.partial_score == 0.0
    assert out.failure_class == "runtime_output_unparseable"


def test_f004_bfcl_planning_version_and_swe_demotion_refusal(tmp_path: Path) -> None:
    # Planning metadata remains provisional until the adapter verifies the
    # pinned package data and replaces it with captured benchmark evidence.
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_MODEL,
    )
    assert (plan.benchmark_version or "").startswith("provisional:")

    swe_plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id=_MODEL,
    )
    with pytest.raises(BenchEvalError, match="executable_adapter"):
        execute_control_plane_run(
            plan=swe_plan,
            output_path=tmp_path / "unused-swe.jsonl",
            artifacts_dir=tmp_path / "unused-swe-art",
            run_id="swe-demoted",
        )


def test_f005_hle_rejects_uppercase_yes_and_stdout_only(tmp_path: Path) -> None:
    judged = tmp_path / "judged_hle_model.json"
    judged.write_text(
        json.dumps({"q": {"judge_response": {"correct": "YES"}}}),
        encoding="utf-8",
    )
    assert (
        parse_hle_official_score(
            eval_dir=tmp_path,
            model_id="provider/model",
            judge_stdout="",
            max_samples=1,
            work_dir=tmp_path,
            judged_path=judged,
        )
        is None
    )
    assert (
        parse_hle_official_score(
            eval_dir=tmp_path,
            model_id="provider/missing",
            judge_stdout="Accuracy: 100% | n = 1",
            max_samples=1,
            work_dir=tmp_path,
        )
        is None
    )


def test_f005_hle_rejects_judged_outside_work_dir(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "outside" / "judged_hle_model.json"
    outside.parent.mkdir()
    outside.write_text(
        json.dumps({"q": {"judge_response": {"correct": "yes"}}}),
        encoding="utf-8",
    )
    assert (
        parse_hle_official_score(
            eval_dir=tmp_path,
            model_id="provider/model",
            judge_stdout="",
            max_samples=1,
            work_dir=work,
            judged_path=outside,
        )
        is None
    )


def test_f006_proxy_route_identity_in_runtime_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id=_MODEL,
    ).model_copy(update={"instances": []})

    monkeypatch.setenv("HTTP_PROXY", "http://user:secret-a@proxy.invalid:8118")
    hash_a = _hash_effective_runtime_options(plan=plan)
    monkeypatch.setenv("HTTP_PROXY", "http://user:secret-b@proxy.invalid:8118")
    hash_b = _hash_effective_runtime_options(plan=plan)
    assert hash_a == hash_b

    monkeypatch.setenv("HTTP_PROXY", "http://user:secret-a@proxy.invalid:9999")
    hash_port = _hash_effective_runtime_options(plan=plan)
    assert hash_port != hash_a

    monkeypatch.setenv("HTTP_PROXY", "http://user:secret-a@proxy.invalid:8118")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    hash_np1 = _hash_effective_runtime_options(plan=plan)
    monkeypatch.setenv("NO_PROXY", "localhost,.example.com")
    hash_np2 = _hash_effective_runtime_options(plan=plan)
    assert hash_np1 != hash_np2


def test_f009_bundle_refuses_existing_archive(tmp_path: Path) -> None:
    evidence = tmp_path / "e.jsonl"
    JsonlEvidenceSink().append_jsonl(
        evidence,
        _eligible_row(instance_id="tb-001", verifier=tmp_path / "v.json"),
    )
    out = tmp_path / "bundle"
    archive = tmp_path / "bundle.tar.gz"
    archive.write_bytes(b"operator-owned")
    with pytest.raises(BenchEvalError, match="already exists"):
        export_run_bundle(evidence_path=evidence, output_dir=out)
    assert archive.read_bytes() == b"operator-owned"
    assert not tarfile.is_tarfile(archive)


def test_f010_compare_missing_evidence_is_cli_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from bencheval.cli import main

    missing = tmp_path / "missing.jsonl"
    other = tmp_path / "other.jsonl"
    JsonlEvidenceSink().append_jsonl(
        other,
        _eligible_row(instance_id="tb-001", verifier=tmp_path / "v.json"),
    )
    code = main(
        [
            "compare",
            str(missing),
            str(other),
            "--output",
            str(tmp_path / "out.md"),
        ],
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err


def test_f010_compare_empty_evidence_is_cli_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from bencheval.cli import main

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    other = tmp_path / "other.jsonl"
    JsonlEvidenceSink().append_jsonl(
        other,
        _eligible_row(instance_id="tb-001", verifier=tmp_path / "v.json"),
    )
    code = main(
        [
            "compare",
            str(empty),
            str(other),
            "--output",
            str(tmp_path / "out.md"),
        ],
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.startswith("error:")
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("adapter", "filename"),
    [
        ("swe", "verifier.json"),
        ("tb", "result.json"),
    ],
)
def test_r2_f012_keyless_result_json_fails_closed(
    tmp_path: Path,
    adapter: str,
    filename: str,
) -> None:
    art = tmp_path / "inst"
    art.mkdir()
    (art / filename).write_text(json.dumps({"cost_usd": 0.1}), encoding="utf-8")
    if adapter == "swe":
        out = parse_swebench_instance_outcome(
            instance_id="swe-001",
            cli=SwebenchCliResult(0, "", "", 0.1, ("mini-extra", "swebench")),
            artifacts_dir=art,
            repo_root=tmp_path,
            harness_version="swe@test",
        )
    else:
        out = parse_harbor_instance_outcome(
            instance_id="tb-001",
            cli=HarborCliResult(0, "", "", 0.1, ("harbor", "run")),
            artifacts_dir=art,
            repo_root=tmp_path,
            harness_version="harbor@test",
        )
    assert out.primary_pass is False
    assert out.partial_score == 0.0
    assert out.failure_class == "runtime_output_unparseable"


def test_r2_f012_keyless_bfcl_official_score_fails_closed(tmp_path: Path) -> None:
    """Keyless summary header (no accuracy verdict) in the official score artifact."""
    art = tmp_path / "inst"
    art.mkdir()
    score_dir = art / "scores"
    score_file = score_dir / _MODEL / "non_live" / "BFCL_v4_bfcl_smoke_001_score.json"
    score_file.parent.mkdir(parents=True)
    score_file.write_text(
        json.dumps({"correct_count": 1, "total_count": 1}) + "\n",
        encoding="utf-8",
    )
    out = parse_bfcl_instance_outcome(
        instance_id="bfcl_smoke_001",
        cli=BfclCliResult(0, "", "", 0.1, ("bfcl", "evaluate")),
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="bfcl@test",
        score_dir=score_dir,
        model_id=_MODEL,
    )
    assert out.primary_pass is False
    assert out.partial_score == 0.0
    assert out.failure_class == "runtime_output_unparseable"


def test_f007_gpqa_counts_match_completed_samples(tmp_path: Path) -> None:
    from bencheval.gpqa_adapter import parse_gpqa_official_score

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    payload = {
        "version": 2,
        "status": "success",
        "eval": {"task": "gpqa_diamond", "model": "openai/gpt-4"},
        "results": {
            "total_samples": 4,
            "completed_samples": 4,
            "scores": [
                {
                    "name": "choice",
                    "metrics": {"accuracy": {"name": "accuracy", "value": 0.75}},
                },
            ],
        },
    }
    (log_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")
    log_path = log_dir / "run.json"
    score = parse_gpqa_official_score(
        log_dir,
        expected_model="openai/gpt-4",
        stdout=f"Log: {log_path}\n",
    )
    assert score is not None
    assert score.accuracy == pytest.approx(0.75)
    assert score.correct == 3
    assert score.total == 4


def test_f008_shim_drops_mixed_case_capability_header() -> None:
    from bencheval.anthropic_role_shim import _forward_headers

    forwarded = _forward_headers(
        {
            "X-Bencheval-Shim-Token": "capability-secret",
            "Authorization": "Bearer inbound",
            "X-Api-Key": "inbound-key",
            "Content-Type": "application/json",
        },
        auth_token=None,
    )
    lowered = {k.lower() for k in forwarded}
    assert "x-bencheval-shim-token" not in lowered
    assert "authorization" not in lowered
    assert "x-api-key" not in lowered
