"""Regressions for Round-1 native-runner honesty findings (F001–F012)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import execution_support_label, load_benchmark_catalog
from bencheval.bfcl_native_adapter import (
    BfclCliResult,
    bfcl_benchmark_version,
    parse_bfcl_instance_outcome,
)
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import BenchEvalError
from bencheval.gpqa_adapter import parse_gpqa_official_score
from bencheval.hle_adapter import parse_hle_official_score
from bencheval.lifecycle import cleanup_transient_artifacts
from bencheval.model_compare import assess_model_comparison_validity
from bencheval.provenance_gates import is_captured_axis, is_captured_harness_version
from bencheval.run_bundle import export_run_bundle
from bencheval.run_isolation import claim_exclusive_evidence_path
from bencheval.runtime_compare import assess_runtime_comparison_validity
from bencheval.swebench_adapter import SwebenchCliResult, parse_swebench_instance_outcome
from bencheval.terminal_bench_harbor import HarborCliResult, parse_harbor_instance_outcome

_TS = datetime(2026, 8, 6, tzinfo=UTC)


def test_f001_f002_swe_and_bfcl_demoted_from_executable() -> None:
    catalog = load_benchmark_catalog()
    swe = catalog.by_id_or_alias("swe-bench-verified")
    bfcl = catalog.by_id_or_alias("bfcl-v4")
    assert swe.executable is False
    assert bfcl.executable is False
    assert execution_support_label(swe) == "manifest_only"
    assert execution_support_label(bfcl) == "manifest_only"
    executable = {
        b.id for b in catalog.benchmarks if execution_support_label(b) == "executable_adapter"
    }
    assert executable == {"terminal-bench", "gpqa-diamond", "hle"}


def test_f001_f002_execute_refuses_demoted_adapters(tmp_path: Path) -> None:
    for benchmark_id, slice_id, runtime_id in (
        ("swe-bench-verified", "swe-bench-verified-smoke-10", "claude-code"),
        ("bfcl-v4", "smoke-5", None),
    ):
        plan = plan_control_plane(
            benchmark_id=benchmark_id,
            slice_id=slice_id,
            runtime_id=runtime_id,
            model_id="kimi-k2.7-code",
        )
        with pytest.raises(BenchEvalError, match="executable_adapter"):
            execute_control_plane_run(
                plan=plan,
                output_path=tmp_path / f"{benchmark_id}.jsonl",
                artifacts_dir=tmp_path / f"{benchmark_id}-art",
                run_id=f"demote-{benchmark_id}",
            )


def test_f003_bfcl_package_version_is_not_benchmark_identity() -> None:
    assert bfcl_benchmark_version() is None


def test_f004_process_failure_dominates_boolean_artifacts(tmp_path: Path) -> None:
    # SUBSTITUTE_JUSTIFICATION:
    # - necessity: official Harbor/SWE/BFCL CLIs unavailable here
    # - boundary: parser unit contract only (returncode vs artifact authority)
    # - proof limit: not live harness acceptance
    art = tmp_path / "inst"
    art.mkdir()
    (art / "result.json").write_text(
        json.dumps({"resolved": True, "success": True}),
        encoding="utf-8",
    )
    (art / "verdict.json").write_text(
        json.dumps({"primary_pass": True}),
        encoding="utf-8",
    )
    (art / "verifier.json").write_text(
        json.dumps({"resolved": True}),
        encoding="utf-8",
    )

    harbor = parse_harbor_instance_outcome(
        instance_id="tb-1",
        cli=HarborCliResult(17, "", "", 0.1, ("harbor", "run")),
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="harbor@test",
    )
    assert harbor.primary_pass is False
    assert harbor.failure_class == "harness_failure"

    swe = parse_swebench_instance_outcome(
        instance_id="swe-1",
        cli=SwebenchCliResult(17, "", "", 0.1, ("mini-extra", "swebench")),
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="swe@test",
    )
    assert swe.primary_pass is False
    assert swe.failure_class == "harness_failure"

    bfcl = parse_bfcl_instance_outcome(
        instance_id="simple",
        cli=BfclCliResult(17, "", "", 0.1, ("bfcl", "generate")),
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="bfcl@test",
    )
    assert bfcl.primary_pass is False
    assert bfcl.failure_class == "harness_failure"


def test_f005_exclusive_evidence_path_rejects_reuse(tmp_path: Path) -> None:
    path = tmp_path / "evidence.jsonl"
    path.write_text("{}\n", encoding="utf-8")
    with pytest.raises(BenchEvalError, match="already exists"):
        claim_exclusive_evidence_path(path)


def test_f005_gpqa_does_not_scan_stale_logs(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "old.json").write_text(
        json.dumps(
            {
                "status": "success",
                "results": {
                    "scores": {"accuracy": {"metrics": {"accuracy": {"value": 1.0}}}},
                    "completed_samples": 2,
                    "total_samples": 2,
                },
            },
        ),
        encoding="utf-8",
    )
    assert parse_gpqa_official_score(log_dir, stdout="", stderr="") is None


def test_f006_hle_incomplete_judged_set_rejected(tmp_path: Path) -> None:
    judged = tmp_path / "judged_hle_model.json"
    judged.write_text(
        json.dumps(
            {
                "q1": {"judge_response": {"correct": "yes"}},
                "q2": {"prompt": "missing judge"},
            },
        ),
        encoding="utf-8",
    )
    assert (
        parse_hle_official_score(
            eval_dir=tmp_path,
            model_id="provider/model",
            judge_stdout="",
            max_samples=2,
            work_dir=tmp_path,
            judged_path=judged,
        )
        is None
    )


def test_f006_hle_partial_count_rejected(tmp_path: Path) -> None:
    judged = tmp_path / "judged_hle_model.json"
    judged.write_text(
        json.dumps({"q1": {"judge_response": {"correct": "yes"}}}),
        encoding="utf-8",
    )
    assert (
        parse_hle_official_score(
            eval_dir=tmp_path,
            model_id="provider/model",
            judge_stdout="",
            max_samples=2,
            work_dir=tmp_path,
            judged_path=judged,
        )
        is None
    )


def test_f007_cleanup_refuses_symlinked_run_root(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    (victim / "agent-workspace").mkdir(parents=True)
    keep = victim / "agent-workspace" / "keep.txt"
    keep.write_text("keep", encoding="utf-8")
    link = tmp_path / "run-instance"
    link.symlink_to(victim)
    report = cleanup_transient_artifacts(link, policy="always", primary_pass=True)
    assert report.removed_paths == ()
    assert keep.is_file()


def test_f008_whitespace_provenance_rejected() -> None:
    assert is_captured_axis("   ") is False
    assert is_captured_harness_version("   ") is False

    def _row(
        *,
        runtime_id: str,
        model_id: str = "m",
        interpretation_label: str = "adapter_smoke",
    ) -> EvidenceRecord:
        return EvidenceRecord(
            run_id="lane-run",
            task_id="i1",
            model_id=model_id,
            execution_profile="E2",
            backend="harbor",
            primary_pass=True,
            partial_score=1.0,
            cost_usd=0.0,
            latency_sec=0.1,
            created_at=_TS,
            benchmark_id="terminal-bench",
            slice_id="smoke-5",
            adapter_id="terminal-bench-harbor",
            harness_kind="harbor",
            provider_id="   ",
            benchmark_version="   ",
            harness_version="harbor@1",
            runtime_id=runtime_id,
            runtime_version="   ",
            runtime_config_hash="   ",
            interpretation_label=interpretation_label,
            counts_toward_pass_at_k=True,
            instance_id="i1",
        )

    runtime_verdict = assess_runtime_comparison_validity(
        [_row(runtime_id="claude-code")],
        [_row(runtime_id="codex-cli")],
    )
    assert runtime_verdict.valid is False
    assert any(
        "captured" in r or "harness_version" in r or "provider" in r
        for r in runtime_verdict.reasons
    )

    model_verdict = assess_model_comparison_validity(
        [
            _row(
                runtime_id="claude-code",
                model_id="model-a",
                interpretation_label="model_comparison",
            ),
        ],
        [
            _row(
                runtime_id="claude-code",
                model_id="model-b",
                interpretation_label="model_comparison",
            ),
        ],
    )
    assert model_verdict.valid is False
    assert any(
        "captured" in r or "provider" in r or "benchmark_version" in r
        for r in model_verdict.reasons
    )


def test_f009_gpqa_hle_plan_marks_cost_unenforced() -> None:
    for benchmark_id, slice_id in (("gpqa-diamond", "smoke"), ("hle", "smoke")):
        plan = plan_control_plane(
            benchmark_id=benchmark_id,
            slice_id=slice_id,
            runtime_id=None,
            model_id="kimi-k2.7-code",
        )
        assert "max_cost_usd_unenforced_estimate" in plan.caveats


def test_f010_bundle_copies_compare_evidence(tmp_path: Path) -> None:
    def _row(run_id: str) -> EvidenceRecord:
        return EvidenceRecord(
            run_id=run_id,
            task_id="t1",
            model_id="m",
            execution_profile="E0",
            backend="inspect",
            primary_pass=True,
            partial_score=1.0,
            cost_usd=0.0,
            latency_sec=0.1,
            created_at=_TS,
            benchmark_id="gpqa-diamond",
            slice_id="smoke",
            adapter_id="gpqa",
            harness_kind="inspect-evals",
            provider_id="bytellm",
            benchmark_version="gpqa@test",
            harness_version="inspect-evals@1",
            interpretation_label="adapter_smoke",
            counts_toward_pass_at_k=True,
            instance_id="i1",
        )

    sink = JsonlEvidenceSink()
    evidence = tmp_path / "evidence.jsonl"
    baseline = tmp_path / "baseline.jsonl"
    current = tmp_path / "current.jsonl"
    sink.append_jsonl(evidence, _row("e1"))
    sink.append_jsonl(baseline, _row("b1"))
    sink.append_jsonl(current, _row("c1"))
    out = tmp_path / "bundle"
    export_run_bundle(
        evidence_path=evidence,
        output_dir=out,
        compare_baseline=baseline,
        compare_current=current,
    )
    assert (out / "baseline.jsonl").is_file()
    assert (out / "current.jsonl").is_file()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["compare"] == {"baseline": "baseline.jsonl", "current": "current.jsonl"}


def test_f012_coverage_gate_is_package_wide_but_not_global_pytest_state() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "fail_under = 80" not in text
    domain = Path("scripts/check-domain-coverage.sh").read_text(encoding="utf-8")
    assert "coverage report" in domain
    assert "--source=src/bencheval" in domain
    assert "--include=" not in domain
    assert "--fail-under=80" in domain
