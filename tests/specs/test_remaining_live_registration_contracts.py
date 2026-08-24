"""RED contracts for durable live-run ``passed`` registration.

``passed`` is a proof-bearing status, not a synonym for "the JSONL parsed".
Non-passed lifecycle rows retain the existing permissive registration contract.

SUBSTITUTE_JUSTIFICATION
- substitute: ``_native_terminal_bench_record``/``_native_bfcl_record`` and the
  temporary native-verifier JSON/evidence JSONL files constructed by this module
- replaces: a real Terminal-Bench Harbor run, a real BFCL generate → evaluate
  lifecycle, their native verifier artifacts, and the evidence records emitted
  by the control-plane executor
- necessity: the assertions require deterministic identity mismatches and an
  infrastructure-failure-only row; a charged live run cannot safely guarantee
  those exact proof states on demand
- real-option: the provisioned dev-box Terminal-Bench pilot with Docker,
  Harbor, runtime/provider credentials, and native task images; it cannot
  deterministically manufacture every negative registration state
- proof-limit: proves only local ``evidence register --status passed``
  qualification, identity binding, and no-append failure behavior; it does not
  prove Harbor execution, verifier correctness, provider auth, or readiness
- real-proof: BLOCKED until the dev-box lane runs and registers its native
  evidence through ``docs/ops/dev-box-pilot.md``
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.cli import main
from bencheval.evidence import EvidenceRecord

_CREATED_AT = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)


def _native_terminal_bench_record(
    verifier_path: Path,
    **overrides: object,
) -> EvidenceRecord:
    values: dict[str, object] = {
        "run_id": "tb-live-run",
        "task_id": "terminal-bench/fix-git",
        "model_id": "kimi-k2.7-code",
        "execution_profile": "E2",
        "backend": "harbor",
        "primary_pass": True,
        "partial_score": 1.0,
        "cost_usd": 0.01,
        "latency_sec": 12.0,
        "artifact_paths": [str(verifier_path.resolve())],
        "verifier_log_path": str(verifier_path.resolve()),
        "created_at": _CREATED_AT,
        "benchmark_id": "terminal-bench",
        "benchmark_version": "terminal-bench@2.1",
        "slice_id": "smoke-5",
        "adapter_id": "terminal-bench-harbor",
        "harness_kind": "harbor",
        "harness_version": "harbor@0.1.0",
        "runtime_id": "codex-cli",
        "runtime_version": "codex-cli@1.0.0",
        "runtime_kind": "cli_agent",
        "runtime_config_hash": "sha256:runtime-config",
        "provider_id": "bytellm",
        "provider_config_hash": "sha256:provider-config",
        "instance_id": "fix-git",
        "interpretation_label": "adapter_smoke",
        "verifier_integrity_label": "native",
        "attempt_validity": "valid",
        "counts_toward_pass_at_k": True,
    }
    values.update(overrides)
    return EvidenceRecord(**values)


def _write_evidence(path: Path, record: EvidenceRecord) -> None:
    path.write_text(record.model_dump_json() + "\n", encoding="utf-8")


def _register_passed(
    *,
    manifest: Path,
    evidence: Path | None,
    include_identity: bool = True,
    allow_missing: bool = False,
    run_id: str = "tb-live-run",
    model_id: str = "kimi-k2.7-code",
    runtime_id: str | None = "codex-cli",
    benchmark: str = "terminal-bench",
    slice_id: str = "smoke-5",
) -> int:
    argv = [
        "evidence",
        "register",
        "--run-id",
        run_id,
        "--model",
        model_id,
        "--status",
        "passed",
        "--host",
        "dev-box",
        "--manifest-path",
        str(manifest),
    ]
    if runtime_id is not None:
        argv.extend(["--runtime", runtime_id])
    if include_identity:
        argv.extend(["--benchmark", benchmark, "--slice", slice_id])
    if evidence is not None:
        argv.extend(["--evidence", str(evidence)])
    if allow_missing:
        argv.append("--allow-missing-artifacts")
    return main(argv)


def test_passed_registration_rejects_infrastructure_failure_only_evidence(
    tmp_path: Path,
) -> None:
    verifier = tmp_path / "native-verifier.json"
    verifier.write_text('{"resolved": false}\n', encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    _write_evidence(
        evidence,
        _native_terminal_bench_record(
            verifier,
            primary_pass=False,
            partial_score=0.0,
            failure_class="runtime_launch_failure",
            failure_labels=["runtime_launch_failure"],
            attempt_validity="invalid",
            counts_toward_pass_at_k=False,
        ),
    )
    manifest = tmp_path / "runs.jsonl"

    code = _register_passed(manifest=manifest, evidence=evidence)

    assert code == 1
    assert not manifest.exists()


@pytest.mark.parametrize(
    "record_override",
    [
        pytest.param({"run_id": "other-run"}, id="run-id"),
        pytest.param({"model_id": "other-model"}, id="model"),
        pytest.param({"benchmark_id": "hle"}, id="benchmark"),
        pytest.param({"slice_id": "other-slice"}, id="slice"),
        pytest.param({"runtime_id": "claude-code"}, id="runtime"),
    ],
)
def test_passed_registration_binds_cli_identity_to_evidence(
    tmp_path: Path,
    record_override: dict[str, object],
) -> None:
    verifier = tmp_path / "native-verifier.json"
    verifier.write_text('{"resolved": true}\n', encoding="utf-8")
    valid_evidence = tmp_path / "valid-evidence.jsonl"
    _write_evidence(valid_evidence, _native_terminal_bench_record(verifier))
    valid_manifest = tmp_path / "valid-runs.jsonl"

    # Anti-cheat control: the implementation must qualify a real native row;
    # rejecting every passed registration cannot satisfy this RED contract.
    valid_code = _register_passed(manifest=valid_manifest, evidence=valid_evidence)
    assert valid_code == 0
    assert valid_manifest.is_file()

    evidence = tmp_path / "evidence.jsonl"
    _write_evidence(evidence, _native_terminal_bench_record(verifier, **record_override))
    manifest = tmp_path / "runs.jsonl"

    code = _register_passed(manifest=manifest, evidence=evidence)

    assert code == 1
    assert not manifest.exists()


def test_passed_registration_requires_explicit_benchmark_and_slice(tmp_path: Path) -> None:
    verifier = tmp_path / "native-verifier.json"
    verifier.write_text('{"resolved": true}\n', encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    _write_evidence(evidence, _native_terminal_bench_record(verifier))
    manifest = tmp_path / "runs.jsonl"

    code = _register_passed(
        manifest=manifest,
        evidence=evidence,
        include_identity=False,
    )

    assert code == 1
    assert not manifest.exists()


def test_passed_registration_cannot_bypass_evidence_with_dev_flag(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"

    code = _register_passed(
        manifest=manifest,
        evidence=tmp_path / "missing.jsonl",
        allow_missing=True,
    )

    assert code == 1
    assert not manifest.exists()


def _native_bfcl_record(score_path: Path, **overrides: object) -> EvidenceRecord:
    """bfcl-v4 row modeled on the qualified live run's evidence shape."""
    values: dict[str, object] = {
        "run_id": "bfcl-live-run",
        "task_id": "irrelevance",
        "model_id": "gpt-5.2-2025-12-11",
        "execution_profile": "E1",
        "backend": "inspect",
        "primary_pass": True,
        "partial_score": 1.0,
        "cost_usd": 0.0,
        "latency_sec": 60.0,
        "artifact_paths": [str(score_path.resolve())],
        "verifier_log_path": str(score_path.resolve()),
        "created_at": _CREATED_AT,
        "benchmark_id": "bfcl-v4",
        "benchmark_version": "bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b",
        "slice_id": "smoke-5",
        "adapter_id": "bfcl",
        "harness_kind": "bfcl-native",
        "harness_version": "bfcl-eval@2026.3.23",
        "provider_id": "bytellm",
        "provider_config_hash": "sha256:provider-config",
        "instance_id": "irrelevance",
        "interpretation_label": "diagnostic",
        "verifier_integrity_label": "native",
        "attempt_validity": "valid",
        "counts_toward_pass_at_k": True,
    }
    values.update(overrides)
    return EvidenceRecord(**values)


def test_passed_registration_rejects_diagnostic_bfcl_row_on_executable_benchmark(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The diagnostic-interpretation disqualifier is the ONLY barrier for bfcl.

    bfcl-v4 is now catalog-executable, so the executable re-check no longer
    stops a diagnostic bfcl row; only the diagnostic label disqualifier in
    ``live_proof._row_disqualifiers`` keeps it from registering ``passed``.
    """
    score = tmp_path / "BFCL_v4_irrelevance_score.json"
    score.write_text('{"accuracy": 1.0, "correct_count": 1, "total_count": 1}\n', encoding="utf-8")

    # Anti-cheat control: the same row without the diagnostic label must
    # qualify — rejecting every bfcl passed registration cannot satisfy this.
    valid_evidence = tmp_path / "valid-evidence.jsonl"
    _write_evidence(
        valid_evidence,
        _native_bfcl_record(score, interpretation_label="adapter_smoke"),
    )
    valid_manifest = tmp_path / "valid-runs.jsonl"
    valid_code = _register_passed(
        manifest=valid_manifest,
        evidence=valid_evidence,
        run_id="bfcl-live-run",
        model_id="gpt-5.2-2025-12-11",
        runtime_id=None,
        benchmark="bfcl-v4",
        slice_id="smoke-5",
    )
    assert valid_code == 0
    assert valid_manifest.is_file()

    evidence = tmp_path / "evidence.jsonl"
    _write_evidence(evidence, _native_bfcl_record(score))
    manifest = tmp_path / "runs.jsonl"

    code = _register_passed(
        manifest=manifest,
        evidence=evidence,
        run_id="bfcl-live-run",
        model_id="gpt-5.2-2025-12-11",
        runtime_id=None,
        benchmark="bfcl-v4",
        slice_id="smoke-5",
    )

    assert code == 1
    assert not manifest.exists()
    assert "diagnostic-interpretation" in capsys.readouterr().err
