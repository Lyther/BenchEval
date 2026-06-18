from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bencheval.admission import (
    Core8AdmissionDocument,
    HumanSignOff,
    TaskAdmissionEntry,
    VerifierOutput,
    audit_suite_admission,
    audit_task_admission,
    load_admission_document,
    run_workspace_verifier,
)
from bencheval.exceptions import BenchEvalError
from tests.selftest_paths import core8_workspace

_CORE8_TASKS = (
    "be-core-t1-single-structured-call",
    "be-core-t2-multi-tool-join",
    "be-core-c1-small-logic-patch",
    "be-core-c2-regression-test-authoring",
    "be-core-a1-multi-file-repo-fix",
    "be-core-a2-build-log-triage",
    "be-core-s1-secure-input-boundary-patch",
    "be-core-s4-local-prompt-injection-resistance",
)


def test_load_admission_document_has_all_core8_tasks() -> None:
    doc = load_admission_document()
    assert doc.suite == "core-8"
    assert len(doc.tasks) == 8
    assert "be-core-t1-single-structured-call" in doc.tasks


@pytest.mark.parametrize("task_id", _CORE8_TASKS)
def test_core8_task_fully_admitted(task_id: str) -> None:
    report = audit_task_admission(task_id)
    assert report.automated_pass is True
    assert report.admitted is True


def test_t1_human_sign_off_gate_passes() -> None:
    report = audit_task_admission("be-core-t1-single-structured-call")
    by_name = {g.name: g for g in report.gates}
    assert by_name["human_sign_off"].status == "pass"
    assert by_name["reference_passes_verifier"].status == "pass"
    assert by_name["negative_control_fails_verifier"].status == "pass"
    assert by_name["replay_determinism_checked"].status == "pass"


def test_suite_audit_core8_all_admitted() -> None:
    report = audit_suite_admission("core-8")
    payload = report.to_dict()
    assert report.suite == "core-8"
    assert len(report.tasks) == 8
    assert report.admitted is True
    assert payload["task_count"] == 8
    assert payload["admitted_count"] == 8
    assert payload["automated_pass_count"] == 8
    assert payload["failed_count"] == 0
    assert payload["pending_count"] == 0


def test_suite_audit_smoke_alias_covers_eight_tasks() -> None:
    report = audit_suite_admission("smoke")
    payload = report.to_dict()
    assert report.suite == "smoke"
    assert len(report.tasks) == 8
    assert report.admitted is True
    assert payload["task_count"] == 8
    assert payload["admitted_count"] == 8
    assert payload["automated_pass_count"] == 8
    assert payload["failed_count"] == 0
    assert payload["pending_count"] == 0


def test_human_sign_off_complete_enables_admitted(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    t1_ws = core8_workspace("be-core-t1-single-structured-call")
    doc = Core8AdmissionDocument(
        schema_version="0.1",
        suite="core-8",
        updated_at="2026-05-29",
        tasks={
            "be-core-t1-single-structured-call": TaskAdmissionEntry(
                workspace=str(t1_ws.relative_to(root)),
                reference_solution="reference.json",
                negative_control="negative.json",
                required_artifacts=[
                    "prompt.json",
                    "tool_catalog.json",
                    "reference.json",
                    "negative.json",
                    "verify.py",
                ],
                human_sign_off=HumanSignOff(reviewer="test.reviewer", date="2026-05-29"),
            ),
        },
    )
    path = tmp_path / "admission.yaml"
    path.write_text(yaml.safe_dump(doc.model_dump(mode="json")), encoding="utf-8")
    report = audit_task_admission("be-core-t1-single-structured-call", admission_path=path)
    assert report.automated_pass is True
    assert report.admitted is True


def test_workspace_verifier_replay_is_deterministic() -> None:
    Path(__file__).resolve().parents[1]
    ws = core8_workspace("be-core-t1-single-structured-call")
    ref = ws / "reference.json"
    first = run_workspace_verifier(ws, ref)
    second = run_workspace_verifier(ws, ref)
    assert first == second


def test_verifier_output_rejects_string_primary_pass() -> None:
    with pytest.raises(ValidationError):
        VerifierOutput.model_validate(
            {"primary_pass": "false", "partial_score": 0.0, "partial_metrics": {}},
        )


def test_workspace_verifier_schema_error(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    candidate = ws / "candidate.json"
    candidate.write_text("{}", encoding="utf-8")
    (ws / "verify.py").write_text(
        "import json, sys\n"
        'payload = {"primary_pass": "false", "partial_score": 0.0, "partial_metrics": {}}\n'
        "print(json.dumps(payload))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    with pytest.raises(BenchEvalError, match="schema validation"):
        run_workspace_verifier(ws, candidate)
