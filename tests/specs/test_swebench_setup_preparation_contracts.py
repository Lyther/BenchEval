"""R5.2 contracts: the SWE diagnostic prepares its checkout through Inspect's native setup.

Architecture §22.11 / roadmap R5.2. The official image's ``/testbed`` sits at a
commit that differs from the dataset base commit by the executable bit alone, so
the pinned scorer's ``git add -A; git diff --cached <base_commit>`` export
carries the whole tree and the official evaluator cannot apply it. The remedy
stays inside the locked stack: the run-owned generation row carries a per-sample
``setup`` script derived from the verified source row, Inspect runs it in the
sandbox before the agent, and the transformation manifest retains the exact
bytes, the recipe, and its digest so the generation log can be checked against
what the proof keeps.

The guard is deliberately narrow: only an executable-bit difference is
normalized. Changed contents, added or deleted paths, and file-type changes
refuse the image before any inference, and ``core.fileMode=false`` is recorded
as a bounded preparation policy for this lane rather than a general claim that
modes do not matter.

SUBSTITUTE_JUSTIFICATION
- substitute: a planted one-row parquet with the official schema's fields, local
  git repositories built per case, an injected ``SwebenchProcessRunner`` that
  writes real Inspect ``.eval`` logs and the manifest a materialized run writes,
  and planted official report/summary files
- replaces: the 1.2 GB pinned Hub snapshot, the official Docker image, charged
  Codex generation, and Docker-backed official evaluation
- necessity: image incompatibilities (content drift, added/deleted paths, file
  type changes, a base that tracks the agent's state directory) and log-level
  preparation drift must be forced deterministically, and they must be refused
  before any charge or container effect
- real-option: the preparation script under test is the exact text the adapter
  emits, executed by real ``git`` against real repositories; the image-level
  rehearsal ran the same bytes in disposable containers of the official image
- proof-limit: proves row materialization, manifest retention, the guard's
  decisions, the export shape after preparation, and the adapter's refusal of a
  generation log that contradicts the prepared setup; it does not prove that
  Inspect ran the script ahead of the Codex solver on the official image
- real-proof: the uncharged Inspect-run rehearsal and the R5.2 acceptance run
  recorded in docs/roadmap.md
- covered tests: every test in this module
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

import bencheval.swebench_adapter as adapter
from bencheval.benchmark_plan import plan_control_plane
from bencheval.domain import RunPlan
from bencheval.exceptions import BenchEvalError
from bencheval.swebench_adapter import (
    SwebenchCliResult,
    materialize_swebench_diagnostic_inputs,
    run_swebench_instance,
    swebench_diagnostic_setup_script,
)
from tests.factories import write_swe_generation_log_for_plan

_BENCHMARK = "swe-bench-verified"
_SLICE = "swe-bench-verified-diagnostic-1"
_INSTANCE_ID = "django__django-11099"
_FC_MODEL = "gpt-5.2-2025-12-11-FC"
_BASE_COMMIT = "d26b2424437dabeeca94d7900b37d2df4410da0c"
_PASS_TO_PASS = '["test_a", "test_b"]'
_FAIL_TO_PASS = '["test_c"]'


def _plan() -> RunPlan:
    return plan_control_plane(
        benchmark_id=_BENCHMARK,
        slice_id=_SLICE,
        runtime_id="codex-cli",
        model_id=_FC_MODEL,
        diagnostic=True,
    )


def _plant_parquet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    base_commit: str = _BASE_COMMIT,
    extra: dict[str, object] | None = None,
) -> Path:
    """A real one-row parquet carrying the official row's fields."""
    pq = pytest.importorskip("pyarrow.parquet")
    pa = pytest.importorskip("pyarrow")

    row: dict[str, object] = {
        "instance_id": _INSTANCE_ID,
        "repo": "django/django",
        "base_commit": base_commit,
        "environment_setup_commit": "419a78300f7cd27611196e1e464d50fd0385ff27",
        "patch": "diff --git a/x b/x\n",
        "test_patch": "diff --git a/t b/t\n",
        "problem_statement": "usernames ending in a newline are accepted",
        "hints_text": "",
        "created_at": "2019-03-20T00:00:00Z",
        "version": "3.0",
        "PASS_TO_PASS": _PASS_TO_PASS,
        "FAIL_TO_PASS": _FAIL_TO_PASS,
    }
    row.update(extra or {})
    planted = tmp_path / "data" / "test-00000-of-00001.parquet"
    planted.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([row]), planted)
    monkeypatch.setattr(
        adapter,
        "_SWE_SOURCE_PARQUET_SHA256",
        f"sha256:{hashlib.sha256(planted.read_bytes()).hexdigest()}",
    )
    return planted


def _materialize(tmp_path: Path, planted: Path) -> tuple[Path, adapter.SwebenchMaterialization]:
    instance_dir = tmp_path / "artifacts" / _INSTANCE_ID
    result = materialize_swebench_diagnostic_inputs(
        instance_dir=instance_dir,
        instance_id=_INSTANCE_ID,
        source_parquet=planted,
        bind_image=False,
    )
    return instance_dir, result


def _row(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8").splitlines()[0])


# --- the materialized generation row ---------------------------------------------------


def test_generation_row_carries_the_prepared_setup_and_the_official_row_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = _plant_parquet(tmp_path, monkeypatch)

    instance_dir, result = _materialize(tmp_path, planted)

    generation = _row(instance_dir / "inspect-dataset" / "test.jsonl")
    official = _row(instance_dir / "official-dataset" / "test.jsonl")
    expected = swebench_diagnostic_setup_script(_BASE_COMMIT)
    # The preparation is derived from the verified source row, not from a
    # constant: the base commit it pins is the row's own.
    assert generation["setup"] == expected
    assert _BASE_COMMIT in expected
    assert generation["base_commit"] == _BASE_COMMIT
    # The official row stays the dataset's own record.
    assert "setup" not in official
    assert official["PASS_TO_PASS"] == json.loads(_PASS_TO_PASS)
    assert official["base_commit"] == _BASE_COMMIT
    digest = f"sha256:{hashlib.sha256(expected.encode('utf-8')).hexdigest()}"
    assert result.setup_sha256 == digest


def test_transformation_manifest_retains_the_setup_bytes_recipe_and_bounded_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = _plant_parquet(tmp_path, monkeypatch)

    instance_dir, result = _materialize(tmp_path, planted)

    manifest = json.loads((instance_dir / "transformation-manifest.json").read_text())
    script = swebench_diagnostic_setup_script(_BASE_COMMIT)
    assert manifest["setup_script"] == script
    assert manifest["setup_sha256"] == result.setup_sha256
    assert manifest["setup_recipe"] == adapter._SETUP_RECIPE
    assert manifest["setup_base_commit"] == _BASE_COMMIT
    assert manifest["setup_exclude"] == "/.codex/"
    # The mode normalization is recorded as a bounded preparation policy, never
    # as a general equivalence claim.
    policy = manifest["setup_mode_policy"]
    assert "core.fileMode=false" in policy
    assert "not a claim" in policy


def test_source_row_that_already_defines_setup_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = _plant_parquet(tmp_path, monkeypatch, extra={"setup": "echo dataset-owned"})

    with pytest.raises(BenchEvalError, match="already carries a 'setup' field"):
        _materialize(tmp_path, planted)


@pytest.mark.parametrize(
    "base_commit",
    ["d26b2424", "", "D26B2424437DABEECA94D7900B37D2DF4410DA0C", "../../etc/passwd"],
    ids=["abbreviated", "empty", "uppercase", "path-like"],
)
def test_base_commit_that_is_not_a_full_object_name_is_refused(base_commit: str) -> None:
    with pytest.raises(BenchEvalError, match="not a full object name"):
        swebench_diagnostic_setup_script(base_commit)


def test_materialization_refuses_a_row_whose_base_commit_is_not_a_full_object_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = _plant_parquet(tmp_path, monkeypatch, base_commit="d26b2424")

    with pytest.raises(BenchEvalError, match="not a full object name"):
        _materialize(tmp_path, planted)


# --- the preparation script against real repositories ----------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _repo(tmp_path: Path, *, track_agent_state: bool = False) -> tuple[Path, str]:
    """A repository whose base commit stands in for the dataset base."""
    repo = tmp_path / "testbed"
    repo.mkdir()
    hooks = tmp_path / "no-hooks"
    hooks.mkdir()
    _git(repo, "init", "-q", ".")
    _git(repo, "config", "user.email", "contracts@example.invalid")
    _git(repo, "config", "user.name", "contracts")
    # The fixture must not depend on the developer's global hook configuration.
    _git(repo, "config", "core.hooksPath", str(hooks))
    (repo / "a.txt").write_text("alpha\n", encoding="utf-8")
    (repo / "run.sh").write_text("echo hi\n", encoding="utf-8")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "m.py").write_text("x = 1\n", encoding="utf-8")
    if track_agent_state:
        (repo / ".codex").mkdir()
        (repo / ".codex" / "config.toml").write_text("tracked = true\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "dataset base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _run_setup(repo: Path, base_commit: str) -> subprocess.CompletedProcess[str]:
    script = repo.parent / "setup.sh"
    script.write_text(swebench_diagnostic_setup_script(base_commit), encoding="utf-8")
    return subprocess.run(
        ["bash", str(script), str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )


def _tree_snapshot(repo: Path) -> list[tuple[str, int, bytes]]:
    """Every working-tree file with its permissions and contents."""
    return sorted(
        (str(path.relative_to(repo)), path.stat().st_mode, path.read_bytes())
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    )


def _mode_only_image(repo: Path) -> None:
    """What the official image looks like: the same blobs, the executable bit set."""
    (repo / "run.sh").chmod(0o755)
    _git(repo, "update-index", "--chmod=+x", "run.sh")
    _git(repo, "commit", "-q", "-m", "image checkout")


def test_executable_bit_only_image_is_prepared_at_the_dataset_base(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _mode_only_image(repo)
    before = _tree_snapshot(repo)

    result = _run_setup(repo, base)

    assert result.returncode == 0, result.stderr
    assert "bencheval-swe-prepared" in result.stdout
    # HEAD and the index move to the base; the working tree is untouched.
    assert _git(repo, "rev-parse", "HEAD") == base
    assert _git(repo, "status", "--porcelain") == ""
    assert _git(repo, "config", "core.fileMode") == "false"
    # Contents and permissions of every tracked file survive preparation.
    assert _tree_snapshot(repo) == before
    assert "/.codex/" in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def _content_drift(repo: Path) -> None:
    (repo / "a.txt").write_text("beta\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "content")


def _added_path(repo: Path) -> None:
    (repo / "extra.txt").write_text("new\n", encoding="utf-8")
    _git(repo, "add", "extra.txt")
    _git(repo, "commit", "-q", "-m", "added")


def _deleted_path(repo: Path) -> None:
    _git(repo, "rm", "-q", "a.txt")
    _git(repo, "commit", "-q", "-m", "deleted")


def _file_type_change(repo: Path) -> None:
    _git(repo, "rm", "-q", "--cached", "a.txt")
    (repo / "a.txt").unlink()
    (repo / "a.txt").symlink_to("run.sh")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "symlink")


@pytest.mark.parametrize(
    "mutate",
    [_content_drift, _added_path, _deleted_path, _file_type_change],
    ids=["changed-contents", "added-path", "deleted-path", "file-type-change"],
)
def test_image_that_differs_beyond_the_executable_bit_refuses_before_inference(
    mutate, tmp_path: Path
) -> None:
    repo, base = _repo(tmp_path)
    _mode_only_image(repo)
    mutate(repo)
    head = _git(repo, "rev-parse", "HEAD")

    result = _run_setup(repo, base)

    assert result.returncode == 3
    assert "beyond the executable bit" in result.stderr
    # Refusing leaves the checkout exactly as it was found.
    assert _git(repo, "rev-parse", "HEAD") == head
    assert _git(repo, "config", "--get", "core.fileMode") != "false"


def test_workspace_content_the_history_check_cannot_see_refuses_before_inference(
    tmp_path: Path,
) -> None:
    """History can match the base while the checkout still carries extra content.

    The commit-to-commit guard cannot see uncommitted or untracked files, so the
    prepared workspace is re-checked: anything it would still export refuses.
    """
    repo, base = _repo(tmp_path)
    _mode_only_image(repo)
    # Committed history is mode-only drift, which the first guard accepts.
    (repo / "leftover.txt").write_text("not part of the benchmark base\n", encoding="utf-8")
    (repo / "pkg" / "m.py").write_text("x = 99\n", encoding="utf-8")

    result = _run_setup(repo, base)

    assert result.returncode == 3
    assert "still exports a diff" in result.stderr


def test_base_commit_absent_from_the_image_history_refuses_before_inference(
    tmp_path: Path,
) -> None:
    repo, _ = _repo(tmp_path)
    _mode_only_image(repo)

    result = _run_setup(repo, "0" * 40)

    assert result.returncode != 0
    assert _git(repo, "status", "--porcelain") == ""


def test_base_that_tracks_the_agent_state_directory_refuses_to_exclude_it(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path, track_agent_state=True)
    _mode_only_image(repo)

    result = _run_setup(repo, base)

    assert result.returncode == 3
    assert "refusing to exclude tracked content" in result.stderr
    assert "/.codex/" not in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def test_prepared_workspace_exports_the_agents_edit_without_its_runtime_state(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path)
    _mode_only_image(repo)
    assert _run_setup(repo, base).returncode == 0

    # What the agent leaves behind: its own state directory plus a real fix.
    (repo / ".codex" / "sessions").mkdir(parents=True)
    (repo / ".codex" / "config.toml").write_text('model = "inspect-generic"\n', encoding="utf-8")
    (repo / ".codex" / "sessions" / "rollout.jsonl").write_text("{}\n", encoding="utf-8")
    (repo / "pkg" / "m.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "pkg" / "test_m.py").write_text("assert True\n", encoding="utf-8")
    # Exactly what the pinned scorer runs to export model_patch.
    _git(repo, "add", "-A")
    exported = _git(repo, "diff", "--cached", base)

    changed = [line.split(" b/")[-1] for line in exported.splitlines() if line.startswith("diff ")]
    assert changed == ["pkg/m.py", "pkg/test_m.py"]
    assert ".codex" not in exported
    assert len(exported) < 1000


# --- the adapter checks the generation log against what the proof retains --------------


def _write_manifest(instance_dir: Path, *, setup: str | None) -> None:
    manifest: dict[str, object] = {
        "source_repo": adapter._SWE_VERIFIED_REPO,
        "instance_id": _INSTANCE_ID,
        "image_digest": None,
    }
    if setup is not None:
        manifest["setup_recipe"] = adapter._SETUP_RECIPE
        manifest["setup_sha256"] = f"sha256:{hashlib.sha256(setup.encode('utf-8')).hexdigest()}"
        manifest["setup_script"] = setup
    instance_dir.mkdir(parents=True, exist_ok=True)
    (instance_dir / "transformation-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _plant_official_inputs(instance_dir: Path) -> None:
    official = instance_dir / "official-dataset"
    official.mkdir(parents=True, exist_ok=True)
    (official / "test.jsonl").write_text("{}\n", encoding="utf-8")


def _plant_resolved_report(instance_dir: Path, *, run_id: str) -> None:
    (instance_dir / "report.json").write_text(
        json.dumps({_INSTANCE_ID: {"resolved": True}}), encoding="utf-8"
    )
    (instance_dir / f"{_FC_MODEL}.{run_id}.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "resolved_ids": [_INSTANCE_ID],
                "unresolved_ids": [],
                "empty_patch_ids": [],
                "error_ids": [],
                "infra_failure_ids": [],
                "ambiguous_failure_ids": [],
            }
        ),
        encoding="utf-8",
    )


class _PreparedRunner:
    """An injected runner that retains what a materialized generation retains."""

    def __init__(
        self,
        artifacts: Path,
        plan: RunPlan,
        *,
        manifest_setup: str | None,
        log_setup: str | None,
        setup_result: int = 0,
        setup_after_model: bool = False,
        run_id: str,
    ) -> None:
        self.artifacts = artifacts
        self.plan = plan
        self.commands: list[tuple[str, ...]] = []
        self._manifest_setup = manifest_setup
        self._log_setup = log_setup
        self._setup_result = setup_result
        self._setup_after_model = setup_after_model
        self._run_id = run_id

    def __call__(
        self, command: Sequence[str], *, cwd: Path | None, timeout_sec: int
    ) -> SwebenchCliResult:
        argv = tuple(str(part) for part in command)
        self.commands.append(argv)
        instance_dir = self.artifacts / _INSTANCE_ID
        if len(self.commands) == 1:
            _write_manifest(instance_dir, setup=self._manifest_setup)
            write_swe_generation_log_for_plan(
                instance_dir,
                self.plan,
                setup=self._log_setup,
                setup_result=self._setup_result,
                setup_after_model=self._setup_after_model,
            )
            _plant_official_inputs(instance_dir)
        else:
            _plant_resolved_report(instance_dir, run_id=self._run_id)
        return SwebenchCliResult(0, "", "", 0.1, argv)


def _run(
    runner: _PreparedRunner, tmp_path: Path, *, run_id: str
) -> adapter.SwebenchInstanceOutcome:
    return run_swebench_instance(
        plan=runner.plan,
        instance_id=_INSTANCE_ID,
        artifacts_dir=runner.artifacts,
        repo_root=tmp_path,
        process_runner=runner,
        timeout_sec=30,
        run_id=run_id,
    )


def test_prepared_run_whose_log_retains_the_setup_reaches_the_official_evaluator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BENCHEVAL_INSPECT_MODEL", raising=False)
    monkeypatch.delenv("BYTELLM_BASE_URL", raising=False)
    plan = _plan()
    script = swebench_diagnostic_setup_script(_BASE_COMMIT)
    runner = _PreparedRunner(
        tmp_path / "artifacts",
        plan,
        manifest_setup=script,
        log_setup=script,
        run_id="r52-prepared",
    )

    outcome = _run(runner, tmp_path, run_id="r52-prepared")

    assert len(runner.commands) == 2
    assert outcome.primary_pass is True
    assert outcome.failure_class is None
    # The setup identity travels with the row the way the binding does.
    digest = f"sha256:{hashlib.sha256(script.encode('utf-8')).hexdigest()}"
    assert outcome.adapter_metadata["setup_sha256"] == digest
    assert outcome.adapter_metadata["setup_recipe"] == adapter._SETUP_RECIPE


@pytest.mark.parametrize(
    ("log_setup", "setup_result", "setup_after_model", "reason"),
    [
        (None, 0, False, "without the prepared setup script"),
        ("#!/usr/bin/env bash\necho other\n", 0, False, "not the materialized"),
        (True, 1, False, "no successful setup execution"),
        (True, 0, True, "after the first model call"),
    ],
    ids=["no-setup-on-sample", "different-setup", "setup-failed", "setup-after-the-model"],
)
def test_generation_that_contradicts_the_prepared_setup_never_reaches_the_evaluator(
    log_setup: str | bool | None,
    setup_result: int,
    setup_after_model: bool,
    reason: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BENCHEVAL_INSPECT_MODEL", raising=False)
    monkeypatch.delenv("BYTELLM_BASE_URL", raising=False)
    plan = _plan()
    script = swebench_diagnostic_setup_script(_BASE_COMMIT)
    runner = _PreparedRunner(
        tmp_path / "artifacts",
        plan,
        manifest_setup=script,
        log_setup=script if log_setup is True else log_setup,
        setup_result=setup_result,
        setup_after_model=setup_after_model,
        run_id="r52-setup-drift",
    )

    outcome = _run(runner, tmp_path, run_id="r52-setup-drift")

    # One command: the official evaluator is never invoked on generation that
    # did not run the prepared workspace.
    assert len(runner.commands) == 1
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_config_drift"
    assert reason in outcome.adapter_metadata["generation_identity_mismatch"]
    assert not (tmp_path / "artifacts" / _INSTANCE_ID / "predictions.jsonl").exists()
    assert outcome.predictions_path is None


def test_a_run_without_a_materialized_setup_is_still_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Historical instance directories carry no setup and must keep scoring."""
    monkeypatch.delenv("BENCHEVAL_INSPECT_MODEL", raising=False)
    monkeypatch.delenv("BYTELLM_BASE_URL", raising=False)
    plan = _plan()
    runner = _PreparedRunner(
        tmp_path / "artifacts",
        plan,
        manifest_setup=None,
        log_setup=None,
        run_id="r52-legacy",
    )

    outcome = _run(runner, tmp_path, run_id="r52-legacy")

    assert len(runner.commands) == 2
    assert outcome.primary_pass is True
    assert "setup_sha256" not in outcome.adapter_metadata
