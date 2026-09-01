"""Regression for SWE config-root and evaluator-project separation.

SUBSTITUTE_JUSTIFICATION
- substitute: disposable no-lock, extra-entry, and byte-copied lookalike project directories
- replaces: hostile or stale current-working-directory projects presented to an installed wheel
- necessity: project discovery must reject all three shapes without removing or corrupting the
  real checkout's ``pyproject.toml`` and ``uv.lock``
- real-option: mutating the operator checkout would make the repository and concurrent runs unsafe;
  the test instead executes a real built wheel and its real resolver against the smallest controlled
  hostile inputs
- proof-limit: proves cwd project rejection only; it does not prove official SWE evaluation,
  Docker, provider behavior, or charged-run readiness
- real-proof: BLOCKED on a future deliberately charged SWE diagnostic from a provisioned host;
  these negative cases remain diagnostic input-validation evidence
- covered tests: ``test_installed_wheel_rejects_unowned_swe_projects``
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(shutil.which("rsync") is None, reason="real config exporter requires rsync")
def test_swe_preflight_and_launch_ignore_external_config_root(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    bundle = tmp_path / "config-bundle"
    exported = subprocess.run(
        [str(repo / "scripts" / "export-config-bundle.sh"), str(bundle)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert exported.returncode == 0, exported.stderr

    probe = """
import json
from bencheval.doctor import run_native_doctor
from bencheval.paths import repo_root
from bencheval.swebench_adapter import resolve_swebench_subprocess

command = resolve_swebench_subprocess(("swebench", "eval"))
project_index = command.index("--project") + 1
report = run_native_doctor("swebench-native")
group = next(check for check in report.checks if check.name == "swe_evaluator_group")
print(json.dumps({
    "config_root": str(repo_root()),
    "project_root": command[project_index],
    "group_status": group.status,
    "command": command,
}))
"""
    env = dict(os.environ)
    env["BENCHEVAL_HOME"] = str(bundle)
    run = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    payload = json.loads(run.stdout)
    assert Path(payload["config_root"]) == bundle.resolve()
    assert Path(payload["project_root"]) == repo.resolve()
    assert payload["group_status"] == "pass"
    command = payload["command"]
    assert "--locked" in command
    assert command[command.index("--only-group") + 1] == "swe"
    assert "--group" not in command


def test_installed_wheel_rejects_unowned_swe_projects(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[2]
    wheel_dir = tmp_path / "wheels"
    built = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    wheel = next(wheel_dir.glob("bencheval-*.whl"))

    project_text = (repo / "pyproject.toml").read_text(encoding="utf-8")
    extra_group_text = project_text.replace(
        '    "swebench==5.0.1",\n]',
        '    "swebench==5.0.1",\n    "pip==26.0.1",\n]',
        1,
    )
    assert extra_group_text != project_text
    projects = {
        "no-lock": project_text,
        "extra-entry": extra_group_text,
        "lookalike": project_text,
    }
    probe = """
from bencheval.doctor import run_native_doctor
from bencheval.exceptions import BenchEvalError
from bencheval.swebench_adapter import resolve_swebench_subprocess, swebench_project_root

assert swebench_project_root() is None
report = run_native_doctor("swebench-native")
group = next(check for check in report.checks if check.name == "swe_evaluator_group")
assert group.status == "fail", group
try:
    resolve_swebench_subprocess(("swebench", "eval"))
except BenchEvalError:
    pass
else:
    raise AssertionError("unowned project reached the SWE evaluator launch")
"""
    for name, pyproject in projects.items():
        project = tmp_path / name
        project.mkdir()
        (project / "pyproject.toml").write_text(pyproject, encoding="utf-8")
        if name == "lookalike":
            shutil.copy2(repo / "uv.lock", project / "uv.lock")
        run = subprocess.run(
            ["uv", "run", "--no-project", "--with", str(wheel), "python", "-c", probe],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )
        assert run.returncode == 0, f"{name}: {run.stderr}"
