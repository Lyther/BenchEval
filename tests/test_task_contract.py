from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bencheval.exceptions import TaskContractError
from bencheval.task_contract import TaskContract
from bencheval.task_registry import compute_source_hash, load_task_contract


def _minimal_contract(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": "0.2",
        "task": {
            "id": "be-test-task",
            "version": "0.2.0",
            "family_id": "test",
            "category": "coding",
            "title": "Test Task",
            "intent": "Test intent",
        },
        "provenance": {
            "source_type": "synthetic",
            "license": "internal",
            "spdx": "LicenseRef-Internal",
            "source_hash": "sha256:deadbeef",
            "leak_risk": "low",
            "public_indexed": False,
            "created_at": "2026-05-29",
            "reviewed_by": [],
        },
        "variant": {
            "variant_id": "canonical",
            "generator": "manual",
            "seed": None,
            "stable_for_regression": True,
            "rotation_group": "core-2026q2",
        },
        "input_contract": {"provided": ["x"], "hidden": ["y"]},
        "output_contract": {"type": "json", "schema": "schemas/test.schema.json"},
        "execution": {
            "profile": "E1",
            "allowed_tools": ["read_file"],
            "forbidden_tools": ["network"],
            "internet": False,
        },
        "constraints": {
            "budget_class": "B1",
            "max_steps": 10,
            "max_wall_clock_sec": 180,
            "max_cost_usd": 0.25,
            "must_not_modify_tests": True,
        },
        "verification": {
            "mode": "deterministic",
            "verifier": "verify.py",
            "replay_required": True,
            "primary_pass_metric": "pass",
            "partial_metrics": ["visible_tests_pass"],
        },
        "risk_tags": ["coding"],
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged = dict(base[key])  # type: ignore[index]
            merged.update(value)
            base[key] = merged
        else:
            base[key] = value
    return base


def test_valid_contract_loads(tmp_path: Path) -> None:
    data = _minimal_contract()
    p = tmp_path / "task.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    contract = load_task_contract(p)
    assert contract.task.id == "be-test-task"
    assert contract.provenance.spdx == "LicenseRef-Internal"


def test_invalid_missing_provenance_fails() -> None:
    data = _minimal_contract()
    del data["provenance"]
    with pytest.raises(ValidationError):
        TaskContract.model_validate(data)


def test_public_indexed_core_task_fails() -> None:
    data = _minimal_contract(provenance={"public_indexed": True, "source_type": "synthetic"})
    with pytest.raises(ValueError, match="public_indexed"):
        TaskContract.model_validate(data)


def test_internet_true_in_core_task_fails() -> None:
    data = _minimal_contract(execution={"internet": True})
    contract = TaskContract.model_validate(data)
    with pytest.raises(ValueError, match="internet"):
        contract.validate_core_membership(is_core=True)


def test_defensive_task_without_partial_metrics_fails() -> None:
    data = _minimal_contract(
        task={"category": "defensive_security"},
        verification={"partial_metrics": []},
    )
    with pytest.raises(ValueError, match="partial_metrics"):
        TaskContract.model_validate(data)


def test_public_calibration_defensive_without_partial_metrics_fails() -> None:
    data = _minimal_contract(
        task={"category": "defensive_security"},
        provenance={"source_type": "public_calibration", "public_indexed": True},
        verification={"partial_metrics": []},
    )
    with pytest.raises(ValueError, match="partial_metrics"):
        TaskContract.model_validate(data)


def test_public_calibration_defensive_with_partial_metrics_ok() -> None:
    data = _minimal_contract(
        task={"category": "defensive_security"},
        provenance={"source_type": "public_calibration", "public_indexed": True},
        verification={"partial_metrics": ["label_accuracy"]},
    )
    contract = TaskContract.model_validate(data)
    assert contract.is_calibration
    assert contract.provenance.public_indexed is True


def test_invalid_execution_profile_fails_at_validate() -> None:
    data = _minimal_contract(execution={"profile": "BAD"})
    with pytest.raises(ValidationError):
        TaskContract.model_validate(data)


def test_invalid_execution_profile_fails_load_task_contract(tmp_path: Path) -> None:
    data = _minimal_contract(execution={"profile": "BAD"})
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(TaskContractError):
        load_task_contract(p)


def test_compute_source_hash_is_stable(tmp_path: Path) -> None:
    data = _minimal_contract()
    p = tmp_path / "task.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    raw = p.read_bytes()
    h1 = compute_source_hash(raw)
    h2 = compute_source_hash(raw)
    assert h1 == h2
