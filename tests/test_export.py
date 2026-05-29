from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import BenchEvalError
from bencheval.export import export_evidence


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
        import duckdb  # noqa: F401
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


def test_export_all_pass_duckdb_succeeds(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, _record())
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
        assert failures_count == 0
        assert metadata_count == 0
        assert attempts_count == 1
    finally:
        con.close()
