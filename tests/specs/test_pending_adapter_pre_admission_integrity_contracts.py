"""RED contracts for pending-adapter post-launch artifact ownership.

CyberGym and ExploitGym are catalog-only and non-executable for v1. This
suite proves only dormant BenchEval-owned filesystem behavior in the retained
research modules. Official live proof is excluded by that closed v1 product
decision.

SUBSTITUTE_JUSTIFICATION
- substitute: the ``_runner`` callables, the temporary ExploitGym entrypoint,
  and ``BENCHEVAL_EXPLOITGYM_HOME`` in the four tests below
- replaces: the external CyberGym/ExploitGym process launch and an installed
  ExploitGym checkout at the adapter's process boundary
- necessity: the negative assertion requires a deterministic directory
  rename-and-symlink swap in the exact interval after launch and before
  BenchEval writes captured stdout/stderr; an official harness cannot safely
  or deterministically expose that race, while the positive assertion must
  use the same boundary to prove the fix does not reject every outcome
- real-option: a helper subprocess could coordinate the same local race but
  would still replace the official harness and add scheduling nondeterminism;
  a real official run cannot force the hostile state without modifying the
  upstream harness
- proof-limit: diagnostic proof of BenchEval-owned local filesystem writes
  only; it does not prove either official lifecycle, scoring, authorization,
  sandboxing, dependency compatibility, or adapter admission
- real-proof: BLOCKED by the closed v1 catalog-only decision; any unblock
  requires a new post-v1 product decision plus official lifecycle proof on an
  authorized operator host
- covered tests: test_pending_adapter_keeps_logs_on_the_normal_owned_path,
  test_pending_adapter_rejects_post_launch_directory_swap
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from bencheval.cybergym_adapter import (
    CybergymCliResult,
    run_cybergym_instance,
)
from bencheval.domain import RunPlan
from bencheval.exceptions import AdapterFailureError
from bencheval.exploitgym_adapter import (
    ExploitgymCliResult,
    run_exploitgym_instance,
)

_INSTANCE_ID = "official-task-1"


def _pending_plan(adapter_id: str) -> RunPlan:
    return RunPlan(
        schema_version="0.3",
        benchmark_id=adapter_id,
        slice_id=f"{adapter_id}-diagnostic-one",
        adapter_id=adapter_id,
        harness_kind=f"{adapter_id}-native",
        agent_id="momo",
        provider_id="bytellm",
        model_id="kimi-k2.7-code",
        model_binding="runtime_configured",
        instances=({"instance_id": _INSTANCE_ID},),
        budget_class="B3",
        max_cost_usd=25.0,
        max_wall_clock_sec=300,
        max_wall_clock_sec_per_instance=300,
        requires_harbor=False,
        requires_sandbox=True,
        network_policy="benchmark_required",
        cleanup_policy="always",
        comparison_validity="adapter_smoke",
    )


def _prepare_adapter(
    *,
    adapter_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Callable[..., object], type[CybergymCliResult] | type[ExploitgymCliResult]]:
    if adapter_id == "cybergym":
        return run_cybergym_instance, CybergymCliResult

    home = tmp_path / "exploitgym"
    runner = home / "examples" / "run_agent.py"
    runner.parent.mkdir(parents=True)
    runner.write_text("# process-boundary entrypoint\n", encoding="utf-8")
    monkeypatch.setenv("BENCHEVAL_EXPLOITGYM_HOME", str(home))
    return run_exploitgym_instance, ExploitgymCliResult


@pytest.mark.parametrize("adapter_id", ["cybergym", "exploitgym"])
def test_pending_adapter_keeps_logs_on_the_normal_owned_path(
    adapter_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_instance, result_type = _prepare_adapter(
        adapter_id=adapter_id,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    artifacts = tmp_path / "artifacts"

    def _runner(command: object, *, cwd: object, timeout_sec: object) -> object:
        return result_type(0, "captured-out", "captured-err", 0.1, tuple(command))

    outcome = run_instance(
        plan=_pending_plan(adapter_id),
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=_runner,
    )

    instance_dir = artifacts / _INSTANCE_ID
    assert (instance_dir / "stdout.log").read_text(encoding="utf-8") == "captured-out"
    assert (instance_dir / "stderr.log").read_text(encoding="utf-8") == "captured-err"
    assert outcome.primary_pass is False


@pytest.mark.parametrize("adapter_id", ["cybergym", "exploitgym"])
def test_pending_adapter_rejects_post_launch_directory_swap(
    adapter_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_instance, result_type = _prepare_adapter(
        adapter_id=adapter_id,
        tmp_path=tmp_path,
        monkeypatch=monkeypatch,
    )
    artifacts = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    outside.mkdir()

    def _runner(command: object, *, cwd: object, timeout_sec: object) -> object:
        instance_dir = artifacts / _INSTANCE_ID
        instance_dir.rename(artifacts / f"{_INSTANCE_ID}-moved")
        instance_dir.symlink_to(outside, target_is_directory=True)
        return result_type(0, "must-not-escape", "must-not-escape", 0.1, tuple(command))

    with pytest.raises(AdapterFailureError) as excinfo:
        run_instance(
            plan=_pending_plan(adapter_id),
            instance_id=_INSTANCE_ID,
            artifacts_dir=artifacts,
            repo_root=tmp_path,
            process_runner=_runner,
        )

    assert excinfo.value.failure_label == "evidence_corrupt"
    assert list(outside.iterdir()) == []
