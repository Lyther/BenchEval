from __future__ import annotations

from pathlib import Path

import yaml

from bencheval.task_registry import (
    index_tasks,
    lint_task_contract,
    lint_task_path,
    load_suites,
    load_task_contract,
    load_task_dir,
)
from tests.selftest_paths import core8_dir, core16_dir


def test_load_task_contract_core8_example() -> None:
    Path(__file__).resolve().parents[1]
    path = core8_dir() / "c1-small-logic-patch.yaml"
    contract = load_task_contract(path)
    assert contract.task.id == "be-core-c1-small-logic-patch"


def test_load_task_dir_deterministic_order() -> None:
    Path(__file__).resolve().parents[1]
    contracts = load_task_dir(core8_dir())
    ids = [c.task.id for c in contracts]
    assert ids == sorted(ids)
    assert len(ids) == 8


def test_load_task_dir_core16() -> None:
    Path(__file__).resolve().parents[1]
    contracts = load_task_dir(core16_dir())
    ids = [c.task.id for c in contracts]
    assert ids == sorted(ids)
    assert len(ids) == 8


def test_index_tasks_includes_core8_and_core16() -> None:
    index = index_tasks()
    assert len(index) == 16
    assert "be-core-c1-small-logic-patch" in index
    assert "be-core-t3-tool-necessity-gate" in index


def test_lint_reports_stable_issue_codes(tmp_path: Path) -> None:
    contract_yaml = {
        "schema_version": "0.2",
        "task": {
            "id": "be-lint-core-bad",
            "version": "0.2.0",
            "family_id": "lint-bad",
            "category": "agentic_coding",
            "title": "Lint Bad",
            "intent": "Violates core internet rule.",
        },
        "provenance": {
            "source_type": "synthetic",
            "license": "internal",
            "spdx": "LicenseRef-Internal",
            "source_hash": "sha256:00",
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
        "output_contract": {"type": "json", "schema": "schemas/x.json"},
        "execution": {
            "profile": "E1",
            "allowed_tools": ["read_file"],
            "forbidden_tools": ["network"],
            "internet": True,
        },
        "constraints": {
            "budget_class": "B2",
            "max_steps": 20,
            "max_wall_clock_sec": 300,
            "max_cost_usd": 2.0,
            "must_not_modify_tests": True,
        },
        "verification": {
            "mode": "deterministic",
            "verifier": "verify.py",
            "replay_required": True,
            "primary_pass_metric": "pass",
            "partial_metrics": ["hidden_tests_pass"],
        },
        "risk_tags": ["agentic_coding"],
    }
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(contract_yaml), encoding="utf-8")
    contract = load_task_contract(p)
    first = lint_task_contract(contract, path=str(p), is_core=True)
    second = lint_task_contract(contract, path=str(p), is_core=True)
    codes = [issue.code for issue in first]
    assert codes == [issue.code for issue in second]
    assert codes == ["core_invariant"]
    assert first[0].message == "Core tasks must not enable internet"


def test_core8_tasks_lint_clean() -> None:
    root = Path(__file__).resolve().parents[1]
    suites = load_suites(root / "config/suites.yaml")
    for fp in sorted(core8_dir().glob("*.yaml")):
        report = lint_task_path(fp, suites=suites)
        assert report.ok, [(i.code, i.message) for i in report.issues]
