from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import BenchEvalError
from bencheval.export import export_evidence

# SUBSTITUTE_JUSTIFICATION
# - substitute: constructed EvidenceRecord inputs in test_export_requires_analytics_extra,
#   test_export_duckdb_missing_raises_bencheval_error,
#   test_export_control_plane_record_without_task_contract,
#   test_export_provenance_round_trips_through_parquet, and
#   test_export_all_pass_duckdb_succeeds; monkeypatched missing duckdb import in
#   test_export_duckdb_missing_raises_bencheval_error
# - replaces: uninstalling a dependency and charged benchmark-generated evidence
# - necessity: import failure cannot be forced safely by mutating the active environment;
#   exact export rows require controlled input
# - real-option: uninstalling DuckDB corrupts the test env; live scores vary
# - proof-limit: proves local schema and export behavior against the real analytics
#   libraries; constructed rows do not prove a benchmark or provider run
# - real-proof: make check-production-v1 requires the analytics extra and runs these
#   real PyArrow/DuckDB file round trips; live benchmark evidence remains BLOCKED on
#   the provisioned dev-box and provider credentials


def _record(**overrides: object) -> EvidenceRecord:
    base: dict[str, object] = {
        "run_id": "run-export-001",
        "task_id": "be-core-t1-single-structured-call",
        "model_id": "mockllm/model",
        "execution_profile": "E0",
        "backend": "local",
        "primary_pass": True,
        "partial_score": 1.0,
        "cost_usd": 0.0,
        "latency_sec": 0.1,
        "failure_labels": [],
        "artifact_paths": [],
        "verifier_log_path": None,
        "adapter_metadata": {},
        "created_at": datetime(2026, 5, 29, tzinfo=UTC),
    }
    base.update(overrides)
    return EvidenceRecord(**base)


def test_export_requires_analytics_extra(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, _record())
    try:
        # parquet export requires pyarrow only (duckdb is needed for fmt="duckdb").
        # Probing duckdb here wrongly expected a raise on a pyarrow-present /
        # duckdb-absent env, where parquet export correctly succeeds.
        import pyarrow  # noqa: F401
    except ImportError:
        with pytest.raises(BenchEvalError, match="analytics export requires"):
            export_evidence(evidence, fmt="parquet", output_dir=tmp_path / "warehouse")
        return
    out = export_evidence(evidence, fmt="parquet", output_dir=tmp_path / "warehouse")
    assert (out / "attempts.parquet").is_file()
    assert (out / "failures.parquet").is_file()


def test_export_duckdb_missing_raises_bencheval_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    try:
        import pyarrow  # noqa: F401
    except ImportError:
        pytest.skip("pyarrow not installed")

    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, _record())
    monkeypatch.delitem(sys.modules, "duckdb", raising=False)
    monkeypatch.setitem(sys.modules, "duckdb", None)

    with pytest.raises(BenchEvalError, match="analytics export requires"):
        export_evidence(evidence, fmt="duckdb", output_dir=tmp_path / "warehouse")


def test_export_control_plane_record_without_task_contract(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    row = _record(
        task_id="django__django-11099",
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        adapter_id="swebench",
        runtime_id="claude-code",
        instance_id="django__django-11099",
    )
    JsonlEvidenceSink().append_jsonl(evidence, row)
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        pytest.skip("analytics extra not installed")
    out = export_evidence(evidence, fmt="parquet", output_dir=tmp_path / "wh")
    assert (out / "attempts.parquet").is_file()
    assert (out / "runtime.parquet").is_file()
    assert (out / "model.parquet").is_file()


def test_export_provenance_round_trips_through_parquet(tmp_path: Path) -> None:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        pytest.skip("analytics extra not installed")

    evidence = tmp_path / "evidence.jsonl"
    row = _record(
        benchmark_id="hle",
        benchmark_version="hle@official",
        slice_id="smoke",
        adapter_id="hle",
        harness_kind="hle-native",
        harness_version="hle@captured",
        provider_id="bytellm",
        provider_config_hash="sha256:provider-export-sentinel",
        judge_model_id="gpt-5.4-2026-03-05",
        instance_id="hle-smoke-aggregate",
    )
    JsonlEvidenceSink().append_jsonl(evidence, row)

    out = export_evidence(evidence, fmt="parquet", output_dir=tmp_path / "warehouse")
    exported = pq.read_table(out / "attempts.parquet").to_pylist()

    assert exported[0]["provider_id"] == "bytellm"
    assert exported[0]["provider_config_hash"] == "sha256:provider-export-sentinel"
    assert exported[0]["judge_model_id"] == "gpt-5.4-2026-03-05"


def test_export_all_pass_duckdb_succeeds(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(
        evidence,
        _record(
            provider_id="bytellm",
            provider_config_hash="sha256:provider-export-sentinel",
            judge_model_id="gpt-5.4-2026-03-05",
        ),
    )
    try:
        import duckdb
        import pyarrow  # noqa: F401
    except ImportError:
        pytest.skip("analytics extra not installed")
    db_path = export_evidence(evidence, fmt="duckdb", output_dir=tmp_path / "warehouse")
    assert db_path.is_file()
    con = duckdb.connect(str(db_path))
    try:
        failures_count = con.execute("SELECT COUNT(*) FROM failures").fetchone()[0]
        metadata_count = con.execute("SELECT COUNT(*) FROM adapter_metadata").fetchone()[0]
        attempts_count = con.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
        provenance = con.execute(
            "SELECT provider_id, provider_config_hash, judge_model_id FROM attempts",
        ).fetchone()
        assert failures_count == 0
        assert metadata_count == 0
        assert attempts_count == 1
        assert provenance == (
            "bytellm",
            "sha256:provider-export-sentinel",
            "gpt-5.4-2026-03-05",
        )
    finally:
        con.close()
