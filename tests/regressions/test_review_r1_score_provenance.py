"""Round-1 score/provenance contracts: qualify, harness, verdicts, BFCL/HLE/proxy."""

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
        ("bfcl", "verdict.json", "primary_pass", "false"),
        ("bfcl", "verdict.json", "correct", "false"),
        ("bfcl", "verdict.json", "resolved", "false"),
        ("bfcl", "verdict.json", "primary_pass", 1),
        ("bfcl", "verdict.json", "primary_pass", None),
        ("bfcl", "verdict.json", "primary_pass", ["false"]),
        ("bfcl", "verdict.json", "primary_pass", {"v": False}),
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
    if adapter == "bfcl":
        out = parse_bfcl_instance_outcome(
            instance_id="bfcl_smoke_001",
            cli=BfclCliResult(0, "", "", 0.1, ("bfcl", "generate")),
            artifacts_dir=art,
            repo_root=tmp_path,
            harness_version="bfcl@test",
        )
    elif adapter == "swe":
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


def test_f004_bfcl_execute_demoted_and_benchmark_version_not_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SUBSTITUTE_JUSTIFICATION: N/A — no process runner; asserts demotion + identity helper.
    from bencheval.bfcl_native_adapter import bfcl_benchmark_version

    monkeypatch.setattr(
        "bencheval.bfcl_native_adapter.bfcl_harness_version",
        lambda: "bfcl version: 9.9.9",
    )
    assert bfcl_benchmark_version() is None
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_MODEL,
    )
    assert (plan.benchmark_version or "").startswith("provisional:")
    with pytest.raises(BenchEvalError, match="executable_adapter"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "unused-bfcl.jsonl",
            artifacts_dir=tmp_path / "unused-bfcl-art",
            run_id="bfcl-demoted",
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
        ("bfcl", "verdict.json"),
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
    if adapter == "bfcl":
        out = parse_bfcl_instance_outcome(
            instance_id="bfcl_smoke_001",
            cli=BfclCliResult(0, "", "", 0.1, ("bfcl", "generate")),
            artifacts_dir=art,
            repo_root=tmp_path,
            harness_version="bfcl@test",
        )
    elif adapter == "swe":
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
