"""F005: live_proof must not qualify artifact-free rows with failure_class=None.

Before the fix, ``is_native_harness_attempt`` treated a null failure_class as
proof a native scorer ran, and empty ``artifact_paths`` passed the missing-ref
check (which only inspected existing refs). Those rows must not qualify.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.live_proof import is_native_harness_attempt, qualify_lane

_TS = datetime(2026, 8, 6, tzinfo=UTC)


def _write_jsonl(path: Path, records: list[EvidenceRecord]) -> Path:
    sink = JsonlEvidenceSink()
    for record in records:
        sink.append_jsonl(path, record)
    return path


def test_artifact_free_null_failure_class_does_not_qualify(tmp_path: Path) -> None:
    """Artifact-free row with failure_class=None must NOT qualify (F005)."""
    rows = [
        EvidenceRecord(
            run_id="lane-run",
            task_id=f"inst-{i:02d}",
            model_id="kimi-k2.7-code",
            execution_profile="E2",
            backend="harbor",
            primary_pass=True,
            partial_score=1.0,
            cost_usd=0.0,
            latency_sec=1.0,
            failure_labels=[],
            artifact_paths=[],
            verifier_log_path=None,
            created_at=_TS,
            benchmark_id="terminal-bench",
            benchmark_version="tb-2.0",
            slice_id="smoke-5",
            adapter_id="terminal-bench-harbor",
            harness_kind="harbor",
            harness_version="harbor@0.1",
            runtime_id="claude-code",
            runtime_version="claude 1.0",
            runtime_config_hash="sha256:abc",
            provider_id="bytellm",
            provider_config_hash="sha256:bytellm-test",
            instance_id=f"inst-{i:02d}",
            interpretation_label="adapter_smoke",
            failure_class=None,
            attempt_validity="valid",
            counts_toward_pass_at_k=True,
            # Deliberately omit verifier_integrity_label / artifacts.
        )
        for i in range(5)
    ]
    evidence = _write_jsonl(tmp_path / "evidence.jsonl", rows)

    assert not is_native_harness_attempt(rows[0], repo_root=tmp_path)

    q = qualify_lane(
        evidence,
        expected_instances=5,
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        require_runtime=True,
        repo_root=tmp_path,
    )
    assert not q.ok
    assert q.eligible_rows == ()
