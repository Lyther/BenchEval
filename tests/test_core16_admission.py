from __future__ import annotations

import pytest

from bencheval.admission import (
    admission_path_for_suite,
    admission_path_for_task,
    audit_suite_admission,
    audit_task_admission,
    load_admission_document,
)
from bencheval.exceptions import BenchEvalError
from bencheval.task_registry import tasks_for_suite

_CORE16_TASKS = (
    "be-core-t3-tool-necessity-gate",
    "be-core-s3-alert-triage-evidence-json",
    "be-core-t4-stateful-policy-workflow",
    "be-core-c3-backward-compatible-config-migration",
    "be-core-c4-minimal-refactor-under-invariants",
    "be-core-s2-authorization-matrix-regression",
    "be-core-a3-dependency-api-bump",
    "be-core-a4-feature-with-invariants",
)


def test_load_core16_admission_document_has_all_tasks() -> None:
    path = admission_path_for_suite("core-16")
    doc = load_admission_document(path)
    assert doc.suite == "core-16"
    assert len(doc.tasks) == 8
    assert "be-core-t3-tool-necessity-gate" in doc.tasks


@pytest.mark.parametrize("task_id", _CORE16_TASKS)
def test_core16_task_automated_gates_pass(task_id: str) -> None:
    path = admission_path_for_suite("core-16")
    report = audit_task_admission(task_id, admission_path=path)
    assert report.automated_pass is True
    by_name = {g.name: g for g in report.gates}
    assert by_name["human_sign_off"].status == "pending"
    assert by_name["reference_passes_verifier"].status == "pass"
    assert by_name["negative_control_fails_verifier"].status == "pass"
    assert by_name["replay_determinism_checked"].status == "pass"


def test_admission_path_for_core16_task_uses_core16_document() -> None:
    path = admission_path_for_task("be-core-t3-tool-necessity-gate")
    assert path.name == "core-16-admission.yaml"


def test_admission_path_for_core16_task_propagates_load_error(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad_path = tmp_path / "core-16-admission.yaml"
    bad_path.write_text("schema_version: '0.1'\nsuite: core-16\n", encoding="utf-8")

    def fake_admission_path_for_suite(suite: str):
        if suite == "core-16":
            return bad_path
        raise AssertionError("unexpected suite")

    monkeypatch.setattr(
        "bencheval.admission.admission_path_for_suite",
        fake_admission_path_for_suite,
    )
    with pytest.raises(BenchEvalError):
        admission_path_for_task("be-core-t3-tool-necessity-gate")


def test_core16_suite_lists_sixteen_tasks() -> None:
    core8_ids = tasks_for_suite("core-8")
    task_ids = tasks_for_suite("core-16")
    assert len(task_ids) == 16
    assert len(task_ids) == len(set(task_ids))
    assert set(core8_ids).issubset(task_ids)
    assert set(_CORE16_TASKS).issubset(task_ids)
    assert len(set(task_ids) - set(core8_ids)) == len(_CORE16_TASKS)


def test_admission_path_for_core8_task_in_core16_suite_uses_core8_document() -> None:
    path = admission_path_for_task("be-core-t1-single-structured-call")
    assert path.name == "core-8-admission.yaml"


def test_core16_suite_audit_automated_pass_pending_human_signoff() -> None:
    report = audit_suite_admission("core-16")
    payload = report.to_dict()
    expansion = {t.task_id for t in report.tasks if not t.admitted}
    core8 = {t.task_id for t in report.tasks if t.admitted}
    assert report.suite == "core-16"
    assert len(report.tasks) == 16
    assert all(t.automated_pass for t in report.tasks)
    assert expansion == set(_CORE16_TASKS)
    assert len(core8) == 8
    assert payload["task_count"] == 16
    assert payload["admitted_count"] == 8
    assert payload["automated_pass_count"] == 16
    assert payload["pending_count"] == 8
    assert payload["failed_count"] == 0
    assert payload["not_admitted_count"] == 8
    assert report.admitted is False
