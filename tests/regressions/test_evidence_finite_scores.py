"""Evidence JSON must reject non-finite cost/latency/partial_score."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from bencheval.evidence import EvidenceRecord
from bencheval.exceptions import EvidenceValidationError


def _line(**overrides: object) -> str:
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
        "adapter_metadata": {},
        "created_at": datetime(2026, 5, 29, tzinfo=UTC).isoformat(),
    }
    base.update(overrides)
    return json.dumps(base)


def test_evidence_rejects_infinite_cost_usd() -> None:
    with pytest.raises((EvidenceValidationError, ValueError)):
        EvidenceRecord.model_validate_json(_line(cost_usd=float("inf")))
