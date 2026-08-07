"""RED contracts preventing provisional planning labels from becoming proof.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed evidence rows, a disposable verifier artifact, and one injected Harbor
  process result
- replaces: real native benchmark runs used as inputs to proof qualification and comparison
- necessity: the exact provisional-versus-captured provenance conflict must be deterministic;
  charged live runs cannot safely guarantee that adversarial input state
- real-option: real Harbor/provider pilots require unavailable Docker, Harbor, and credentials
- proof-limit: these tests prove local evidence production and fail-closed qualification only; they
  do not prove that any benchmark or scorer ran
- real-proof: BLOCKED until the dev-box executes the native pilot matrix and records source-owned
  revisions from every harness
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink, read_evidence_jsonl
from bencheval.live_proof import qualify_lane
from bencheval.model_compare import assess_model_comparison_validity
from bencheval.runtime_compare import assess_runtime_comparison_validity
from bencheval.terminal_bench_harbor import HarborCliResult

_NOW = datetime(2026, 8, 6, tzinfo=UTC)
_PROVISIONAL_VERSION = "provisional:terminal-bench/2.1"


def _comparison_record(
    *,
    run_id: str,
    runtime_id: str | None,
    model_id: str,
    interpretation_label: str,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=run_id,
        task_id="fix-git",
        model_id=model_id,
        execution_profile="E2",
        backend="harbor",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.1,
        latency_sec=1.0,
        created_at=_NOW,
        benchmark_id="terminal-bench",
        benchmark_version=_PROVISIONAL_VERSION,
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@0.3.1",
        runtime_id=runtime_id,
        runtime_kind="cli_agent" if runtime_id is not None else None,
        runtime_version=f"{runtime_id}@1" if runtime_id is not None else None,
        runtime_config_hash=f"sha256:{runtime_id}" if runtime_id is not None else None,
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm-test",
        instance_id="fix-git",
        interpretation_label=interpretation_label,
        counts_toward_pass_at_k=True,
    )


def test_live_proof_rejects_provisional_benchmark_identity(tmp_path: Path) -> None:
    verifier = tmp_path / "verifier.json"
    verifier.write_text('{"resolved": true}\n', encoding="utf-8")
    record = _comparison_record(
        run_id="provisional-live-proof",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
        interpretation_label="adapter_smoke",
    ).model_copy(
        update={
            "artifact_paths": [str(verifier)],
            "verifier_log_path": str(verifier),
            "verifier_integrity_label": "native",
            "attempt_validity": "valid",
        },
    )
    evidence_path = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence_path, record)

    qualification = qualify_lane(
        evidence_path,
        expected_instances=1,
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        require_runtime=True,
        repo_root=tmp_path,
    )

    assert qualification.ok is False
    assert "provisional" in " ".join(qualification.reasons).lower()


def test_comparisons_reject_matching_provisional_benchmark_identity() -> None:
    runtime_verdict = assess_runtime_comparison_validity(
        [
            _comparison_record(
                run_id="runtime-baseline",
                runtime_id="claude-code",
                model_id="kimi-k2.7-code",
                interpretation_label="runtime_comparison",
            ),
        ],
        [
            _comparison_record(
                run_id="runtime-current",
                runtime_id="codex-cli",
                model_id="kimi-k2.7-code",
                interpretation_label="runtime_comparison",
            ),
        ],
    )
    model_verdict = assess_model_comparison_validity(
        [
            _comparison_record(
                run_id="model-baseline",
                runtime_id=None,
                model_id="model-a",
                interpretation_label="model_comparison",
            ),
        ],
        [
            _comparison_record(
                run_id="model-current",
                runtime_id=None,
                model_id="model-b",
                interpretation_label="model_comparison",
            ),
        ],
    )

    assert runtime_verdict.valid is False
    assert model_verdict.valid is False
    assert "provisional" in " ".join(runtime_verdict.reasons).lower()
    assert "provisional" in " ".join(model_verdict.reasons).lower()


@pytest.mark.parametrize("fallback_version", ["swebench-native-smoke", "bfcl-native-smoke"])
def test_proof_gates_reject_fallback_harness_labels(
    tmp_path: Path,
    fallback_version: str,
) -> None:
    verifier = tmp_path / f"{fallback_version}.json"
    verifier.write_text('{"resolved": true}\n', encoding="utf-8")
    live_record = _comparison_record(
        run_id="fallback-live-proof",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
        interpretation_label="adapter_smoke",
    ).model_copy(
        update={
            "benchmark_version": "terminal-bench@2.1",
            "harness_version": fallback_version,
            "artifact_paths": [str(verifier)],
            "verifier_log_path": str(verifier),
            "verifier_integrity_label": "native",
            "attempt_validity": "valid",
        },
    )
    evidence_path = tmp_path / f"{fallback_version}.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence_path, live_record)

    qualification = qualify_lane(
        evidence_path,
        expected_instances=1,
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        require_runtime=True,
        repo_root=tmp_path,
    )
    runtime_verdict = assess_runtime_comparison_validity(
        [live_record],
        [
            live_record.model_copy(
                update={
                    "run_id": "fallback-current",
                    "runtime_id": "codex-cli",
                    "runtime_version": "codex-cli@1",
                    "runtime_config_hash": "sha256:codex-cli",
                },
            ),
        ],
    )
    model_baseline = live_record.model_copy(
        update={
            "run_id": "fallback-model-baseline",
            "model_id": "model-a",
            "runtime_id": None,
            "runtime_kind": None,
            "runtime_version": None,
            "runtime_config_hash": None,
            "interpretation_label": "model_comparison",
        },
    )
    model_verdict = assess_model_comparison_validity(
        [model_baseline],
        [
            model_baseline.model_copy(
                update={"run_id": "fallback-model-current", "model_id": "model-b"},
            ),
        ],
    )

    assert qualification.ok is False
    assert runtime_verdict.valid is False
    assert model_verdict.valid is False
    qualification_reason = " ".join(qualification.reasons).lower()
    runtime_reason = " ".join(runtime_verdict.reasons).lower()
    model_reason = " ".join(model_verdict.reasons).lower()
    assert "fallback" in qualification_reason or "uncaptured" in qualification_reason
    assert "fallback" in runtime_reason or "uncaptured" in runtime_reason
    assert "fallback" in model_reason or "uncaptured" in model_reason


def test_terminal_bench_evidence_replaces_planning_label_with_release_identity(
    tmp_path: Path,
) -> None:
    """The official dataset selector supplies a concrete 2.1 release identity."""
    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    assert plan.benchmark_version == _PROVISIONAL_VERSION

    def resolved_runner(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        jobs_dir = Path(command[command.index("--jobs-dir") + 1])
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / "result.json").write_text(
            json.dumps({"resolved": True}) + "\n",
            encoding="utf-8",
        )
        return HarborCliResult(0, "", "", 0.1, tuple(command))

    evidence_path = tmp_path / "evidence.jsonl"
    execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        harbor_process_runner=resolved_runner,
        run_id="terminal-bench-release-identity",
    )

    record = read_evidence_jsonl(evidence_path)[0]
    assert record.benchmark_version == "terminal-bench@2.1"
