from __future__ import annotations

from pathlib import Path

import pytest

from bencheval.admission import admission_path_for_suite, load_admission_document
from bencheval.workspace_staging import (
    assert_agent_workspace_clean,
    is_verifier_only_relative_path,
    requires_agent_staging,
    stage_agent_workspace,
    verifier_only_paths,
)

_ROOT = Path(__file__).resolve().parents[1]
_CORE16_ADMISSION = load_admission_document(admission_path_for_suite("core-16"))


@pytest.mark.parametrize(
    ("relative_path", "expected"),
    [
        ("prompt.json", False),
        ("prompt_variants.json", False),
        ("reference.json", True),
        ("verify.py", True),
        ("hidden_variants.json", True),
        ("verifier_only/gold_labels.json", True),
        ("hidden_fixtures/old_minimal.yml", True),
        ("hidden/alternate_gold.json", True),
        ("matrix/hidden_gold.json", True),
        ("compatibility/check_imports.py", True),
        ("invariants.json", True),
        ("repo/src/app.py", False),
    ],
)
def test_is_verifier_only_relative_path(relative_path: str, expected: bool) -> None:
    assert is_verifier_only_relative_path(relative_path) is expected


@pytest.mark.parametrize("task_id", sorted(_CORE16_ADMISSION.tasks))
def test_core16_workspaces_require_agent_staging(task_id: str) -> None:
    entry = _CORE16_ADMISSION.tasks[task_id]
    source = (_ROOT / entry.workspace).resolve()
    assert requires_agent_staging(source)


@pytest.mark.parametrize("task_id", sorted(_CORE16_ADMISSION.tasks))
def test_core16_staged_workspace_excludes_verifier_only_fixtures(
    task_id: str,
    tmp_path: Path,
) -> None:
    entry = _CORE16_ADMISSION.tasks[task_id]
    source = (_ROOT / entry.workspace).resolve()
    hidden = verifier_only_paths(source)
    staged = stage_agent_workspace(source, tmp_path / task_id)
    assert_agent_workspace_clean(staged)
    for path in hidden:
        rel = path.relative_to(source)
        assert not (staged / rel).exists()
    assert not (staged / entry.reference_solution).exists()
    assert not (staged / entry.negative_control).exists()
    assert not (staged / "verify.py").exists()
    if task_id == "be-core-t3-tool-necessity-gate":
        assert (staged / "prompt_variants.json").is_file()
        assert not (staged / "hidden_variants.json").exists()
