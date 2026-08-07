"""F011: planner labels stay provisional; live evidence/compare reject them."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bencheval.benchmark_plan import plan_control_plane
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.live_proof import qualify_lane
from bencheval.runtime_compare import assess_runtime_comparison_validity
from bencheval.terminal_bench_harbor import TERMINAL_BENCH_RELEASE_VERSION


def test_executable_plans_use_provisional_benchmark_version_labels() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    assert plan.benchmark_version.startswith("provisional:")
    assert TERMINAL_BENCH_RELEASE_VERSION.startswith("terminal-bench@")


def test_live_proof_rejects_provisional_benchmark_version(tmp_path: Path) -> None:
    verifier = tmp_path / "verifier.json"
    verifier.write_text('{"resolved": true}\n', encoding="utf-8")
    record = EvidenceRecord(
        run_id="f011",
        task_id="fix-git",
        model_id="kimi-k2.7-code",
        execution_profile="E2",
        backend="harbor",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.1,
        latency_sec=1.0,
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
        benchmark_id="terminal-bench",
        benchmark_version="provisional:terminal-bench/2.1",
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@1",
        runtime_id="claude-code",
        runtime_kind="cli_agent",
        runtime_version="claude@1",
        runtime_config_hash="sha256:abc",
        provider_id="bytellm",
        instance_id="hello-world",
        interpretation_label="adapter_smoke",
        artifact_paths=[str(verifier)],
        verifier_log_path=str(verifier),
        verifier_integrity_label="native",
        counts_toward_pass_at_k=True,
    )
    path = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(path, record)
    q = qualify_lane(
        path,
        expected_instances=1,
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        require_runtime=True,
        repo_root=tmp_path,
    )
    assert q.ok is False
    assert "provisional" in " ".join(q.reasons).lower()


def test_runtime_compare_rejects_provisional_benchmark_version() -> None:
    def row(run_id: str, runtime_id: str) -> EvidenceRecord:
        return EvidenceRecord(
            run_id=run_id,
            task_id="hello-world",
            model_id="kimi-k2.7-code",
            execution_profile="E2",
            backend="harbor",
            primary_pass=True,
            partial_score=1.0,
            cost_usd=0.1,
            latency_sec=1.0,
            created_at=datetime(2026, 8, 6, tzinfo=UTC),
            benchmark_id="terminal-bench",
            benchmark_version="provisional:terminal-bench/2.1",
            slice_id="smoke-5",
            adapter_id="terminal-bench-harbor",
            harness_kind="harbor",
            harness_version="harbor@1",
            runtime_id=runtime_id,
            runtime_kind="cli_agent",
            runtime_version=f"{runtime_id}@1",
            runtime_config_hash=f"sha256:{runtime_id}",
            provider_id="bytellm",
            instance_id="hello-world",
            interpretation_label="runtime_comparison",
            counts_toward_pass_at_k=True,
        )

    verdict = assess_runtime_comparison_validity(
        [row("a", "claude-code")],
        [row("b", "codex-cli")],
    )
    assert verdict.valid is False
    assert "provisional" in " ".join(verdict.reasons).lower()
