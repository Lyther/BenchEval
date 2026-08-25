"""RED contracts for SWE-bench's official per-instance report authority.

The benchmark remains non-executable. These parser contracts define the
already-researched scoring boundary before the generation→evaluation lifecycle
is implemented: only the official evaluator report for the requested instance
may determine ``primary_pass``.

SUBSTITUTE_JUSTIFICATION
- substitute: sanitized SWE-bench ``report.json`` payloads,
  ``SwebenchCliResult`` values, and the injected ``process_runner`` in
  ``test_run_instance_rejects_post_launch_directory_swap``
- replaces: official SWE-bench Docker evaluator output and its completed
  subprocess result
- necessity: wrong-instance, non-boolean, missing-report, conflicting local
  verdict, and post-launch directory-swap states must be forced
  deterministically; the official evaluator cannot safely guarantee those
  negative combinations for a real task
- real-option: a live mini-SWE generation plus official Docker evaluation is
  the required integration proof, but it cannot deterministically produce the
  hostile/malformed report cases or the exact rename-and-symlink race
- proof-limit: diagnostic parser-contract and BenchEval-owned filesystem
  evidence only; it does not prove mini-SWE generation, Docker evaluation,
  package/dataset/image identity, deadlines, cleanup, admission, or live
  benchmark correctness
- real-proof: BLOCKED until the two-phase adapter is implemented and a real
  diagnostic smoke is retained from the official evaluator on the dev-box
- covered tests: every test in this module
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import AdapterFailureError
from bencheval.swebench_adapter import (
    SwebenchCliResult,
    parse_swebench_instance_outcome,
    run_swebench_instance,
)

_INSTANCE_ID = "django__django-11099"


def _cli() -> SwebenchCliResult:
    return SwebenchCliResult(
        returncode=0,
        stdout="official evaluator completed",
        stderr="",
        latency_sec=1.0,
        command=("python", "-m", "swebench.harness.run_evaluation"),
    )


def _write_official_report(
    artifacts: Path,
    *,
    instance_id: str = _INSTANCE_ID,
    resolved: object,
) -> Path:
    report = artifacts / "report.json"
    report.write_text(
        json.dumps(
            {
                instance_id: {
                    "patch_is_None": False,
                    "patch_exists": True,
                    "patch_successfully_applied": True,
                    "resolved": resolved,
                    "tests_status": {
                        "FAIL_TO_PASS": {"success": [], "failure": []},
                        "PASS_TO_PASS": {"success": [], "failure": []},
                    },
                },
            },
        ),
        encoding="utf-8",
    )
    return report


def _parse(artifacts: Path, tmp_path: Path):
    return parse_swebench_instance_outcome(
        instance_id=_INSTANCE_ID,
        cli=_cli(),
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        harness_version="swebench@pinned-test-revision",
    )


def test_official_requested_instance_report_can_grant_pass(tmp_path: Path) -> None:
    artifacts = tmp_path / "instance"
    artifacts.mkdir()
    report = _write_official_report(artifacts, resolved=True)

    outcome = _parse(artifacts, tmp_path)

    assert outcome.primary_pass is True
    assert outcome.failure_class is None
    assert outcome.verifier_log_path == str(report.relative_to(tmp_path))
    assert outcome.native_score["resolved"] is True


def test_official_resolved_false_is_a_valid_wrong_solution(tmp_path: Path) -> None:
    artifacts = tmp_path / "instance"
    artifacts.mkdir()
    _write_official_report(artifacts, resolved=False)

    outcome = _parse(artifacts, tmp_path)

    assert outcome.primary_pass is False
    assert outcome.partial_score == 0.0
    assert outcome.failure_class == "model_wrong_solution"


def test_local_result_file_cannot_grant_pass_without_official_report(tmp_path: Path) -> None:
    artifacts = tmp_path / "instance"
    artifacts.mkdir()
    (artifacts / "result.json").write_text('{"resolved": true}', encoding="utf-8")

    outcome = _parse(artifacts, tmp_path)

    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"
    assert outcome.verifier_log_path is None


def test_official_report_overrides_conflicting_local_verdict(tmp_path: Path) -> None:
    artifacts = tmp_path / "instance"
    artifacts.mkdir()
    _write_official_report(artifacts, resolved=False)
    (artifacts / "verifier.json").write_text('{"resolved": true}', encoding="utf-8")

    outcome = _parse(artifacts, tmp_path)

    assert outcome.primary_pass is False
    assert outcome.failure_class == "model_wrong_solution"


@pytest.mark.parametrize(
    ("instance_id", "resolved"),
    [
        ("django__django-99999", True),
        (_INSTANCE_ID, "true"),
        (_INSTANCE_ID, 1),
    ],
)
def test_wrong_instance_or_non_boolean_official_report_fails_closed(
    instance_id: str,
    resolved: object,
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "instance"
    artifacts.mkdir()
    _write_official_report(artifacts, instance_id=instance_id, resolved=resolved)

    outcome = _parse(artifacts, tmp_path)

    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"


def test_official_report_symlink_cannot_grant_pass(tmp_path: Path) -> None:
    artifacts = tmp_path / "instance"
    artifacts.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    forged = outside / "report.json"
    forged.write_text(
        json.dumps({_INSTANCE_ID: {"resolved": True}}),
        encoding="utf-8",
    )
    (artifacts / "report.json").symlink_to(forged)

    outcome = _parse(artifacts, tmp_path)

    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"
    assert outcome.verifier_log_path is None


def test_run_instance_rejects_post_launch_directory_swap(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    artifacts = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    outside.mkdir()

    def _runner(command: object, *, cwd: object, timeout_sec: object) -> SwebenchCliResult:
        instance_dir = artifacts / _INSTANCE_ID
        instance_dir.rename(artifacts / f"{_INSTANCE_ID}-moved")
        instance_dir.symlink_to(outside, target_is_directory=True)
        return SwebenchCliResult(0, "must-not-escape", "must-not-escape", 0.1, tuple(command))

    with pytest.raises(AdapterFailureError) as excinfo:
        run_swebench_instance(
            plan=plan,
            instance_id=_INSTANCE_ID,
            artifacts_dir=artifacts,
            repo_root=tmp_path,
            process_runner=_runner,
        )

    assert excinfo.value.failure_label == "evidence_corrupt"
    assert list(outside.iterdir()) == []


def test_workspace_diff_symlink_is_not_recorded(tmp_path: Path) -> None:
    artifacts = tmp_path / "instance"
    artifacts.mkdir()
    _write_official_report(artifacts, resolved=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    forged = outside / "workspace.diff"
    forged.write_text("forged-diff\n", encoding="utf-8")
    (artifacts / "workspace.diff").symlink_to(forged)

    outcome = _parse(artifacts, tmp_path)

    assert outcome.primary_pass is True
    assert outcome.workspace_diff_path is None
