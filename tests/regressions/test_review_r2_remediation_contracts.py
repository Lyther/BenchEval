"""Round-2 contracts for the independent remediation review findings.

SUBSTITUTE_JUSTIFICATION
- substitute: temporary CAIS-script entrypoints, provider-free evidence rows, and
  monkeypatched host discovery for the pilot doctor
- replaces: charged HLE model/judge calls, historical evidence files, and mutable
  Docker/PATH state
- necessity: these tests require deterministic missing/drifted identities and both
  present/absent host states that a single live host cannot safely expose together
- real-option: the real CAIS HLE and dev-box pilot require unavailable credentials,
  dataset access, Docker, and installed external harnesses
- proof-limit: proves local planning, command, parsing, provenance, and preflight
  decisions only; it does not prove a live provider or harness run
- real-proof: BLOCKED until the provisioned dev-box retains official HLE/GPQA/Harbor
  artifacts and provider-backed evidence
- covered tests: test_f002_hle_plan_binds_registered_judge_model,
  test_f004_model_compare_rejects_provider_config_drift,
  test_f005_pilot_doctor_requires_only_active_terminal_bench_dependencies, and
  test_n001_gpqa_jsonl_log_is_identity_checked_and_parsed
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.doctor import run_pilot_doctor
from bencheval.evidence import EvidenceRecord
from bencheval.gpqa_adapter import parse_gpqa_official_score
from bencheval.hle_adapter import build_hle_run_commands, hle_run_paths
from bencheval.model_compare import assess_model_comparison_validity
from bencheval.model_registry import load_model_registry


def _install_hle_entrypoints(root: Path) -> None:
    eval_dir = root / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# test entrypoint\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# test entrypoint\n", encoding="utf-8")


def test_f001_hle_judged_path_matches_official_double_json_suffix(tmp_path: Path) -> None:
    paths = hle_run_paths(
        artifacts_dir=tmp_path,
        run_id="official-name",
        provider_id="bytellm",
        model_id="kimi-k2.7-code",
    )

    # CAIS uses: f"judged_{os.path.basename(args.predictions)}.json".
    assert paths.judged_path.name == f"judged_{paths.predictions_path.name}.json"


def test_f002_hle_plan_binds_registered_judge_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hle_home = tmp_path / "hle"
    _install_hle_entrypoints(hle_home)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(hle_home))

    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    assert plan.judge_model_id
    judge = load_model_registry().by_id(plan.judge_model_id)
    assert judge.provider_route == plan.provider_id

    _, judge_command = build_hle_run_commands(
        plan=plan,
        max_samples=2,
        artifacts_dir=tmp_path / "artifacts",
        run_id="judge-bound",
    )
    assert judge_command[judge_command.index("--judge") + 1] == plan.judge_model_id


def _model_comparison_row(*, model_id: str, provider_hash: str) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"run-{model_id}",
        task_id="q1",
        model_id=model_id,
        execution_profile="E0",
        backend="inspect",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.1,
        latency_sec=1.0,
        created_at=datetime(2026, 8, 7, tzinfo=UTC),
        benchmark_id="gpqa-diamond",
        benchmark_version="gpqa-diamond@official",
        slice_id="compare",
        adapter_id="gpqa",
        harness_kind="inspect-evals",
        harness_version="inspect-evals@0.8.0",
        runtime_id=None,
        provider_id="bytellm",
        provider_config_hash=provider_hash,
        instance_id="q1",
        interpretation_label="model_comparison",
        verifier_integrity_label="native",
        counts_toward_pass_at_k=True,
    )


def test_f004_model_compare_rejects_provider_config_drift() -> None:
    assert "provider_config_hash" in EvidenceRecord.model_fields
    baseline = [_model_comparison_row(model_id="model-a", provider_hash="sha256:a")]
    current = [_model_comparison_row(model_id="model-b", provider_hash="sha256:b")]

    verdict = assess_model_comparison_validity(baseline, current)

    assert verdict.valid is False
    assert any("provider_config_hash" in reason for reason in verdict.reasons)


def test_f005_pilot_doctor_requires_only_active_terminal_bench_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bencheval.doctor.binary_on_path", lambda name: name == "harbor")
    monkeypatch.setattr("bencheval.doctor._version_line", lambda _binary: "0.9.0")
    monkeypatch.setattr("bencheval.doctor.docker_available", lambda: True)

    report = run_pilot_doctor()

    assert report.ok is True
    assert [check.name for check in report.checks] == ["harbor_cli", "docker"]


def test_f006_coverage_gate_measures_production_package_by_default() -> None:
    script = Path("scripts/check-domain-coverage.sh").read_text(encoding="utf-8")
    assert "--source=src/bencheval" in script
    assert "--include=" not in script
    assert "--fail-under=80" in script


def test_n001_gpqa_jsonl_log_is_identity_checked_and_parsed(tmp_path: Path) -> None:
    log = tmp_path / "gpqa.jsonl"
    log.write_text(
        json.dumps(
            {
                "status": "success",
                "eval": {"task": "inspect_evals/gpqa_diamond", "model": "openai/model-a"},
                "results": {"scores": [{"name": "accuracy", "value": 1.0}]},
            },
        )
        + "\n",
        encoding="utf-8",
    )

    score = parse_gpqa_official_score(
        tmp_path,
        expected_model="openai/model-a",
        stdout=f"Log: {log}\n",
    )

    assert score is not None
    assert score.accuracy == 1.0


def test_n002_internal_docs_match_three_executable_adapter_surface() -> None:
    contracts = Path("docs/api/internal-contracts.md").read_text(encoding="utf-8")
    architecture = Path("docs/architecture.md").read_text(encoding="utf-8")

    assert "runnable benchmarks (default: 3)" in contracts
    assert "GPQA" in architecture and "HLE" in architecture
    assert "SWE/BFCL diagnostic modules" in architecture
