"""Contracts for the BFCL control-plane executor dispatch.

bfcl-v4 is admitted (``executable: true``) after the qualified live dev-box
lifecycle; this module pins the dispatch route: the executor dispatches
``adapter_id == "bfcl"`` plans through the real generate → evaluate lifecycle
with per-category evidence rows. Diagnostic-flagged plans still label rows
``diagnostic`` at the executor boundary and such rows can never register
``passed``; the CLI refuses ``--diagnostic`` for this now-executable benchmark.

SUBSTITUTE_JUSTIFICATION
- substitute: ``_OfficialLifecycleRunner`` and ``_FailingGenerateRunner``
  injected process runners in this file
- replaces: the real ``bfcl`` CLI subprocess and its charged provider calls
- necessity: deterministic control of generate/evaluate subprocess outcomes
  (official score-artifact fabrication, generate-phase failure) without the
  installed harness or a live provider; neither can deterministically expose
  these orchestration states inside a unit test
- real-option: a dev-box with the official bfcl-eval install and registered
  provider credentials; not available in the local Tier-0 environment
- proof-limit: proves executor dispatch, per-instance evidence mapping, and
  failure routing only — not the real bfcl CLI, the provider path, or the
  official scorer
- real-proof: run-20260824-040631-228703-4756f857 (dev-box-cpu, 2026-08-24):
  5/5 smoke categories officially scored via the real generate → evaluate
  lifecycle (results/evidence/run-20260824-040631-228703-4756f857.jsonl)
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import BfclCliResult
from bencheval.cli import main
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError

_SUPPORTED_MODEL = "gpt-5.2-2025-12-11"
_UNSUPPORTED_MODEL = "kimi-k2.7-code"
_BFCL_IDENTITY = "bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b"
_PINNED_HARNESS_VERSION = "bfcl-eval@2026.3.23"


def _plan(*, diagnostic: bool = True, instances: int = 2, model_id: str = _SUPPORTED_MODEL):
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=model_id,
        diagnostic=diagnostic,
    )
    return plan.model_copy(update={"instances": plan.instances[:instances]})


def _option_value(command: Sequence[str], option: str) -> str:
    return command[list(command).index(option) + 1]


class _OfficialLifecycleRunner:
    """Fabricates the pinned official score artifact on each evaluate call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        call = tuple(command)
        self.calls.append(call)
        if call[1] == "evaluate":
            category = _option_value(call, "--test-category")
            score_root = Path(_option_value(call, "--score-dir"))
            score_file = (
                score_root / _SUPPORTED_MODEL / "non_live" / f"BFCL_v4_{category}_score.json"
            )
            score_file.parent.mkdir(parents=True, exist_ok=True)
            score_file.write_text(
                json.dumps({"accuracy": 1.0, "correct_count": 1, "total_count": 1}) + "\n",
                encoding="utf-8",
            )
        return BfclCliResult(0, "", "", 0.1, call)


class _FailingGenerateRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        call = tuple(command)
        self.calls.append(call)
        return BfclCliResult(1, "", "generate boom", 0.1, call)


def _execute(tmp_path: Path, *, plan, runner) -> object:
    return execute_control_plane_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=tmp_path / "art",
        run_id="bfcl-diag",
        bfcl_process_runner=runner,
        bfcl_benchmark_identity=_BFCL_IDENTITY,
    )


def test_non_diagnostic_bfcl_plan_dispatches_and_executes(tmp_path: Path) -> None:
    # Admitted: a plain bfcl plan dispatches without --diagnostic; rows carry
    # the slice-purpose label, not the diagnostic label.
    plan = _plan(diagnostic=False, instances=1)
    summary = _execute(tmp_path, plan=plan, runner=_OfficialLifecycleRunner())

    assert summary.passed_count == 1
    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert len(rows) == 1
    assert rows[0].primary_pass is True
    assert rows[0].interpretation_label == "adapter_smoke"


def test_diagnostic_dispatch_appends_diagnostic_labeled_rows_per_category(
    tmp_path: Path,
) -> None:
    plan = _plan()
    summary = _execute(tmp_path, plan=plan, runner=_OfficialLifecycleRunner())

    assert summary.instance_count == 2
    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert [row.instance_id for row in rows] == ["simple_python", "irrelevance"]
    assert {row.interpretation_label for row in rows} == {"diagnostic"}


def test_diagnostic_rows_carry_supplied_identity_and_pinned_harness_version(
    tmp_path: Path,
) -> None:
    plan = _plan()
    _execute(tmp_path, plan=plan, runner=_OfficialLifecycleRunner())

    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert {row.benchmark_version for row in rows} == {_BFCL_IDENTITY}
    assert {row.harness_version for row in rows} == {_PINNED_HARNESS_VERSION}


def test_generate_failure_yields_harness_failure_row_without_evaluate(tmp_path: Path) -> None:
    plan = _plan(instances=1)
    runner = _FailingGenerateRunner()
    summary = _execute(tmp_path, plan=plan, runner=runner)

    assert summary.failed_count == 1
    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert len(rows) == 1
    assert rows[0].primary_pass is False
    assert rows[0].failure_class == "harness_failure"
    assert [call[1] for call in runner.calls] == ["generate"]


def test_happy_path_scores_official_artifact_as_primary_pass(tmp_path: Path) -> None:
    plan = _plan(instances=1)
    summary = _execute(tmp_path, plan=plan, runner=_OfficialLifecycleRunner())

    assert summary.passed_count == 1
    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert len(rows) == 1
    row = rows[0]
    assert row.primary_pass is True
    assert row.verifier_log_path is not None
    assert row.verifier_log_path.endswith("BFCL_v4_simple_python_score.json")


def test_unsupported_model_fails_before_any_runner_call(tmp_path: Path) -> None:
    plan = _plan(instances=1, model_id=_UNSUPPORTED_MODEL)
    runner = _OfficialLifecycleRunner()
    with pytest.raises(BenchEvalError, match="not supported"):
        _execute(tmp_path, plan=plan, runner=runner)
    assert runner.calls == []


def test_supplied_identity_mismatch_fails_closed_before_any_runner_call(tmp_path: Path) -> None:
    plan = _plan(instances=1)
    runner = _OfficialLifecycleRunner()
    with pytest.raises(BenchEvalError, match=r"(?i)(identity|drift)"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "evidence.jsonl",
            artifacts_dir=tmp_path / "art",
            run_id="bfcl-diag",
            bfcl_process_runner=runner,
            bfcl_benchmark_identity="bfcl-v4@bfcl-eval-2026.3.23+data-0000000000000000",
        )
    assert runner.calls == []


def test_cli_diagnostic_flag_is_rejected_for_executable_bfcl(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Now that bfcl-v4 is executable, the CLI reserves --diagnostic for demoted
    # benchmarks; executor-level diagnostic labeling is pinned by the tests above.
    code = main(
        [
            "run",
            "bfcl-v4/smoke-5",
            "--model",
            _SUPPORTED_MODEL,
            "--provider",
            "bytellm",
            "--diagnostic",
            "--dry-run",
        ],
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "--diagnostic is only valid for demoted benchmarks" in err
