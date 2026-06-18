"""Export BenchEval evidence JSONL into warehouse tables."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from bencheval.evidence import EvidenceRecord, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError, TaskContractError
from bencheval.task_registry import load_task_contract, resolve_task_path


def _is_control_plane_record(record: EvidenceRecord) -> bool:
    return bool(record.benchmark_id and record.slice_id and record.adapter_id)


def _task_version_for_record(record: EvidenceRecord) -> str:
    if _is_control_plane_record(record):
        return record.benchmark_version or record.harness_version or "control-plane"
    try:
        contract = load_task_contract(resolve_task_path(record.task_id))
    except TaskContractError:
        return "unknown"
    return contract.task.version


def _require_analytics_deps(*, require_duckdb: bool = False):
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as e:
        raise BenchEvalError(
            "analytics export requires optional dependencies; run `uv sync --extra analytics`",
        ) from e
    duck = None
    if require_duckdb:
        try:
            import duckdb as duck
        except ImportError as e:
            raise BenchEvalError(
                "analytics export requires optional dependencies; run `uv sync --extra analytics`",
            ) from e
    return pa, pq, duck


def _table_schemas(pa):
    return {
        "attempts": pa.schema(
            [
                ("run_id", pa.string()),
                ("task_id", pa.string()),
                ("task_version", pa.string()),
                ("model_id", pa.string()),
                ("backend", pa.string()),
                ("execution_profile", pa.string()),
                ("primary_pass", pa.bool_()),
                ("partial_score", pa.float64()),
                ("cost_usd", pa.float64()),
                ("latency_sec", pa.float64()),
                ("verifier_log_path", pa.string()),
                ("created_at", pa.string()),
                ("benchmark_id", pa.string()),
                ("slice_id", pa.string()),
                ("adapter_id", pa.string()),
                ("runtime_id", pa.string()),
                ("instance_id", pa.string()),
                ("interpretation_label", pa.string()),
                ("harness_version", pa.string()),
            ],
        ),
        "failures": pa.schema(
            [
                ("run_id", pa.string()),
                ("task_id", pa.string()),
                ("failure_label", pa.string()),
            ],
        ),
        "adapter_metadata": pa.schema(
            [
                ("run_id", pa.string()),
                ("task_id", pa.string()),
                ("metadata_key", pa.string()),
                ("metadata_value", pa.string()),
            ],
        ),
        "task_versions": pa.schema(
            [
                ("task_id", pa.string()),
                ("task_version", pa.string()),
                ("exported_at", pa.string()),
            ],
        ),
        "runtime": pa.schema(
            [
                ("run_id", pa.string()),
                ("runtime_id", pa.string()),
                ("runtime_version", pa.string()),
                ("runtime_kind", pa.string()),
            ],
        ),
        "model": pa.schema(
            [
                ("run_id", pa.string()),
                ("model_id", pa.string()),
            ],
        ),
    }


def _table_from_rows(pa, name: str, rows: list[dict[str, object]], schemas: dict):
    schema = schemas[name]
    if rows:
        return pa.Table.from_pylist(rows, schema=schema)
    return pa.Table.from_pylist([], schema=schema)


def _attempt_rows(records: list[EvidenceRecord]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        rows.append(
            {
                "run_id": record.run_id,
                "task_id": record.task_id,
                "task_version": _task_version_for_record(record),
                "model_id": record.model_id,
                "backend": record.backend,
                "execution_profile": record.execution_profile,
                "primary_pass": record.primary_pass,
                "partial_score": record.partial_score,
                "cost_usd": record.cost_usd,
                "latency_sec": record.latency_sec,
                "verifier_log_path": record.verifier_log_path,
                "created_at": record.created_at.isoformat(),
                "benchmark_id": record.benchmark_id,
                "slice_id": record.slice_id,
                "adapter_id": record.adapter_id,
                "runtime_id": record.runtime_id,
                "instance_id": record.instance_id,
                "interpretation_label": record.interpretation_label,
                "harness_version": record.harness_version,
            },
        )
    return rows


def _runtime_rows(records: list[EvidenceRecord]) -> list[dict[str, object]]:
    seen: set[tuple[str, str | None]] = set()
    rows: list[dict[str, object]] = []
    for record in records:
        key = (record.run_id, record.runtime_id)
        if key in seen or record.runtime_id is None:
            continue
        seen.add(key)
        rows.append(
            {
                "run_id": record.run_id,
                "runtime_id": record.runtime_id,
                "runtime_version": record.runtime_version,
                "runtime_kind": record.runtime_kind,
            },
        )
    return rows


def _model_rows(records: list[EvidenceRecord]) -> list[dict[str, object]]:
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, object]] = []
    for record in records:
        key = (record.run_id, record.model_id)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"run_id": record.run_id, "model_id": record.model_id})
    return rows


def _failure_rows(records: list[EvidenceRecord]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        for label in record.failure_labels:
            rows.append(
                {
                    "run_id": record.run_id,
                    "task_id": record.task_id,
                    "failure_label": label,
                },
            )
    return rows


def _metadata_rows(records: list[EvidenceRecord]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record in records:
        for key, value in record.adapter_metadata.items():
            rows.append(
                {
                    "run_id": record.run_id,
                    "task_id": record.task_id,
                    "metadata_key": key,
                    "metadata_value": value,
                },
            )
    return rows


def export_evidence(
    evidence_path: Path,
    *,
    fmt: str,
    output_dir: Path,
) -> Path:
    records = read_evidence_jsonl(evidence_path)
    pa, pq, duck = _require_analytics_deps(require_duckdb=fmt == "duckdb")
    schemas = _table_schemas(pa)
    output_dir.mkdir(parents=True, exist_ok=True)
    exported_at = datetime.now(tz=UTC).isoformat()
    tables = {
        "attempts": _attempt_rows(records),
        "failures": _failure_rows(records),
        "adapter_metadata": _metadata_rows(records),
        "task_versions": [
            {
                "task_id": record.task_id,
                "task_version": _task_version_for_record(record),
                "exported_at": exported_at,
            }
            for record in records
        ],
        "runtime": _runtime_rows(records),
        "model": _model_rows(records),
    }
    if fmt == "parquet":
        for name, rows in tables.items():
            table = _table_from_rows(pa, name, rows, schemas)
            pq.write_table(table, output_dir / f"{name}.parquet")
        return output_dir
    if fmt == "duckdb":
        db_path = output_dir / "warehouse.duckdb"
        if db_path.exists():
            db_path.unlink()
        parquet_dir = output_dir / "_parquet"
        parquet_dir.mkdir(parents=True, exist_ok=True)
        for name, rows in tables.items():
            table = _table_from_rows(pa, name, rows, schemas)
            pq.write_table(table, parquet_dir / f"{name}.parquet")

        con = duck.connect(str(db_path))
        try:
            for name in tables:
                con.execute(
                    f"CREATE TABLE {name} AS SELECT * FROM read_parquet(?)",
                    [str(parquet_dir / f"{name}.parquet")],
                )
            from bencheval.paths import repo_root

            views_dir = repo_root() / "warehouse" / "views"
            if views_dir.is_dir():
                for sql_path in sorted(views_dir.glob("*.sql")):
                    con.execute(sql_path.read_text(encoding="utf-8"))
        finally:
            con.close()
        return db_path
    raise BenchEvalError(f"unsupported export format {fmt!r}")
