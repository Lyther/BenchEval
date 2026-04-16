from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import JsonValue

from bencheval import StrictSummaryBuilder, SummaryValidationError
from bencheval.models import ManifestDigest, ModelFamily, RunStamp, SummaryRow
from tests.factories import make_summary_row

REPO_ROOT = Path(__file__).resolve().parents[1]


def _header_from_row(row: SummaryRow) -> dict[str, JsonValue]:
    d = row.model_dump(mode="python")
    for k in (
        "benchmark",
        "benchmark_revision",
        "task_manifest_hash",
        "model_family",
        "auth_lane",
        "log_file",
    ):
        del d[k]
    return d


def _digest_and_stamp(row: SummaryRow) -> tuple[ManifestDigest, RunStamp]:
    manifest = ManifestDigest(
        benchmark=row.benchmark,
        manifest_path="config/manifests/x.txt",
        content_sha256=row.task_manifest_hash,
        task_ids=("t1",),
    )
    stamp = RunStamp(
        auth_lane=row.auth_lane,
        task_manifest_hash=row.task_manifest_hash,
        benchmark_revision=row.benchmark_revision,
        model_family=row.model_family,
    )
    return manifest, stamp


def test_happy_baseline_matches_hand_built_row() -> None:
    row = make_summary_row()
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    eval_path = REPO_ROOT / "results" / "raw" / "example.eval"
    built = StrictSummaryBuilder().build(eval_path, stamp, manifest, header)
    expected = row.model_copy(update={"log_file": "results/raw/example.eval"})
    assert built == expected


def test_happy_experimental_lane_with_estimate() -> None:
    row = make_summary_row(
        auth_lane="experimental_cursor",
        actual_cost_usd=None,
        estimated_api_equivalent_usd=Decimal("12.34"),
        solver="cursor_cli",
        solver_version="cursor-agent@1.0.0",
        inspect_swe_version=None,
    )
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    built = StrictSummaryBuilder().build(Path("/tmp/out.eval"), stamp, manifest, header)
    assert built.auth_lane == "experimental_cursor"
    assert built.actual_cost_usd is None
    assert built.estimated_api_equivalent_usd == Decimal("12.34")


def test_missing_required_header_key_raises() -> None:
    row = make_summary_row()
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    del header["model"]
    with pytest.raises(SummaryValidationError, match="missing required header key: model"):
        StrictSummaryBuilder().build(Path("/tmp/x.eval"), stamp, manifest, header)


def test_stamp_manifest_hash_mismatch_raises() -> None:
    row = make_summary_row()
    manifest = ManifestDigest(
        benchmark=row.benchmark,
        manifest_path="x",
        content_sha256="a" * 64,
        task_ids=("t",),
    )
    stamp = RunStamp(
        auth_lane=row.auth_lane,
        task_manifest_hash="b" * 64,
        benchmark_revision=row.benchmark_revision,
        model_family=row.model_family,
    )
    header = _header_from_row(row)
    with pytest.raises(SummaryValidationError, match="task_manifest_hash"):
        StrictSummaryBuilder().build(Path("/tmp/x.eval"), stamp, manifest, header)


def test_model_prefix_family_mismatch_raises() -> None:
    row = make_summary_row(model="openai/gpt-4o", model_family=ModelFamily.OPENAI)
    manifest = ManifestDigest(
        benchmark=row.benchmark,
        manifest_path="x",
        content_sha256=row.task_manifest_hash,
        task_ids=("t",),
    )
    stamp = RunStamp(
        auth_lane=row.auth_lane,
        task_manifest_hash=row.task_manifest_hash,
        benchmark_revision=row.benchmark_revision,
        model_family=ModelFamily.ANTHROPIC,
    )
    header = _header_from_row(row)
    with pytest.raises(SummaryValidationError, match="model_family mismatch"):
        StrictSummaryBuilder().build(Path("/tmp/x.eval"), stamp, manifest, header)


def test_model_without_slash_derives_local() -> None:
    row = make_summary_row(
        model="phi3-mini",
        model_family=ModelFamily.LOCAL,
        solver="ollama.local",
        solver_version="1.0.0",
        inspect_swe_version=None,
    )
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    built = StrictSummaryBuilder().build(Path("/tmp/x.eval"), stamp, manifest, header)
    assert built.model_family == ModelFamily.LOCAL
    assert built.model == "phi3-mini"


def test_timestamp_iso_z_suffix_parses() -> None:
    row = make_summary_row()
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    header["timestamp"] = "2024-06-01T12:30:45Z"
    built = StrictSummaryBuilder().build(Path("/tmp/x.eval"), stamp, manifest, header)
    assert built.timestamp.year == 2024
    assert built.timestamp.month == 6
    assert built.timestamp.tzinfo is not None


def test_float_actual_cost_serializes_as_decimal_string_in_json() -> None:
    row = make_summary_row()
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    header["actual_cost_usd"] = 1.25
    built = StrictSummaryBuilder().build(Path("/tmp/x.eval"), stamp, manifest, header)
    payload = built.model_dump(mode="json")
    assert isinstance(payload["actual_cost_usd"], str)
    assert Decimal(payload["actual_cost_usd"]) == Decimal("1.25")


def test_invalid_decimal_cost_string_raises() -> None:
    row = make_summary_row()
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    header["actual_cost_usd"] = "not-a-decimal"
    with pytest.raises(SummaryValidationError, match="invalid decimal"):
        StrictSummaryBuilder().build(Path("/tmp/x.eval"), stamp, manifest, header)


def test_inspect_swe_without_version_wraps_validation_error() -> None:
    row = make_summary_row()
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    header["inspect_swe_version"] = None
    with pytest.raises(SummaryValidationError, match="inspect_swe_version"):
        StrictSummaryBuilder().build(Path("/tmp/x.eval"), stamp, manifest, header)


def test_log_file_under_results_raw_is_repo_relative_posix() -> None:
    row = make_summary_row()
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    p = REPO_ROOT / "results" / "raw" / "nested" / "run.eval"
    built = StrictSummaryBuilder().build(p, stamp, manifest, header)
    assert built.log_file == "results/raw/nested/run.eval"


def test_log_file_outside_results_raw_is_absolute_posix() -> None:
    row = make_summary_row()
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    p = Path("/tmp/outside.eval")
    built = StrictSummaryBuilder().build(p, stamp, manifest, header)
    assert built.log_file == p.resolve().as_posix()


def test_provider_model_args_must_be_object() -> None:
    row = make_summary_row()
    manifest, stamp = _digest_and_stamp(row)
    header = _header_from_row(row)
    header["provider_model_args"] = []
    with pytest.raises(SummaryValidationError, match="provider_model_args"):
        StrictSummaryBuilder().build(Path("/tmp/x.eval"), stamp, manifest, header)


def test_empty_header_raises_summary_validation_error() -> None:
    manifest = ManifestDigest(
        benchmark="b",
        manifest_path="x",
        content_sha256="a" * 64,
        task_ids=("t",),
    )
    stamp = RunStamp(
        auth_lane="baseline_api",
        task_manifest_hash="a" * 64,
        benchmark_revision="r",
        model_family=ModelFamily.ANTHROPIC,
    )
    with pytest.raises(SummaryValidationError):
        StrictSummaryBuilder().build(Path("x"), stamp, manifest, {})
