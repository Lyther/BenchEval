"""Property and entropy tests for parser / guard I/O surfaces (verify-edge)."""

from __future__ import annotations

import json
import math
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from bencheval.evidence import EvidenceRecord, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError, EvidenceValidationError, ManifestError
from bencheval.manifest import read_manifest_task_ids
from bencheval.path_safety import ensure_resolved_under_root, validate_control_plane_instance_id

_EDGE_SETTINGS = settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

# Repro: uv run pytest tests/test_edge_fuzz.py -q


@_EDGE_SETTINGS
@given(st.text())
def test_validate_instance_id_never_raises_uncaught(instance_id: str) -> None:
    try:
        validate_control_plane_instance_id(instance_id)
    except BenchEvalError:
        return
    assert instance_id
    assert instance_id[0].isalnum()


@_EDGE_SETTINGS
@given(st.text(min_size=0, max_size=200))
def test_manifest_task_ids_rejects_or_returns(body: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        manifest = Path(tmp) / "instances.txt"
        manifest.write_text(body, encoding="utf-8")
        try:
            ids = read_manifest_task_ids(manifest)
        except ManifestError:
            return
        assert ids
        assert all(line.strip() == line for line in ids)


def test_manifest_rejects_only_comments_and_blanks(tmp_path: Path) -> None:
    manifest = tmp_path / "empty.txt"
    manifest.write_text("# comment\n\n  \n", encoding="utf-8")
    with pytest.raises(ManifestError, match="no task ids"):
        read_manifest_task_ids(manifest)


@_EDGE_SETTINGS
@given(st.text(max_size=80))
def test_ensure_resolved_under_root_escape_or_accept(rel: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        (root / "inside").mkdir()
        candidate = root / rel
        try:
            resolved = ensure_resolved_under_root(candidate, root, what="fuzz")
        except BenchEvalError:
            return
        assert str(resolved).startswith(str(root.resolve()))


def _minimal_evidence_json(**overrides: object) -> str:
    base = {
        "run_id": "r1",
        "task_id": "t1",
        "model_id": "m1",
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
        "created_at": datetime(2026, 5, 29, tzinfo=UTC).isoformat(),
    }
    base.update(overrides)
    return json.dumps(base)


@_EDGE_SETTINGS
@given(
    partial_score=st.floats(allow_nan=True, allow_infinity=True),
    cost=st.floats(allow_nan=True, allow_infinity=True),
)
def test_evidence_record_rejects_non_finite_scores(partial_score: float, cost: float) -> None:
    if (
        math.isfinite(partial_score)
        and 0.0 <= partial_score <= 1.0
        and math.isfinite(cost)
        and cost >= 0.0
    ):
        EvidenceRecord.model_validate_json(
            _minimal_evidence_json(partial_score=partial_score, cost_usd=cost),
        )
        return
    line = _minimal_evidence_json(partial_score=partial_score, cost_usd=cost)
    with pytest.raises((EvidenceValidationError, ValueError)):
        EvidenceRecord.model_validate_json(line)


@_EDGE_SETTINGS
@given(st.binary(min_size=0, max_size=256))
def test_evidence_jsonl_line_never_raises_system_error(raw: bytes) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "evidence.jsonl"
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            path.write_bytes(raw + b"\n")
            with pytest.raises(BenchEvalError, match="decode"):
                read_evidence_jsonl(path)
            return
        path.write_text(text + "\n", encoding="utf-8")
        try:
            read_evidence_jsonl(path)
        except (EvidenceValidationError, BenchEvalError):
            return


def test_evidence_jsonl_minimal_shrink_reproducer(tmp_path: Path) -> None:
    bad = _minimal_evidence_json(partial_score=1.0000001)
    path = tmp_path / "one.jsonl"
    path.write_text(bad + "\n", encoding="utf-8")
    with pytest.raises(EvidenceValidationError):
        read_evidence_jsonl(path)


def test_instance_id_path_traversal_strings_rejected() -> None:
    for bad in ("../x", "..", "a/b", "\x00id", "a\u202ex"):
        with pytest.raises(BenchEvalError):
            validate_control_plane_instance_id(bad)
