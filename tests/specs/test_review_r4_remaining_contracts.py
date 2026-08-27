"""RED contracts for the locally provable remaining launch-control gaps.

SUBSTITUTE_JUSTIFICATION
- substitute: launch-boundary observers in the SWE-bench, BFCL, GPQA, and HLE timeout tests
- replaces: the external harness process after BenchEval computes its timeout
- necessity: the contract is the exact timeout supplied to the real subprocess boundary, and the
  observer must stop before executing a benchmark or incurring provider cost
- real-option: the real harnesses cannot safely guarantee a one- or seven-second budget and would
  add unrelated Docker, dataset, and credential failures after the boundary under test
- proof-limit: proves the launch boundary receives the intended envelope (per-instance for the
  per-instance SWE/BFCL harnesses, run-total for the aggregate GPQA/HLE harnesses); it does not
  prove OS-level termination or cleanup of a hostile real process
- real-proof: BLOCKED on disposable dev-box timeout pilots for each official harness
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import BfclCliResult, run_bfcl_instance
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.gpqa_adapter import GpqaCliResult, run_gpqa_slice
from bencheval.hle_adapter import HleCliResult, run_hle_slice
from bencheval.runtime_registry import load_runtime_catalog
from bencheval.swebench_adapter import SwebenchCliResult, run_swebench_instance
from bencheval.terminal_bench_harbor import HarborCliResult, harbor_agent_for_runtime


def _legacy_pass_result(runtime_id: str) -> str:
    """Legacy-verdict result.json carrying the agent_info identity the run path requires."""
    pin = load_runtime_catalog().by_id(runtime_id).versioning.agent_version_pin
    return json.dumps(
        {
            "resolved": True,
            "agent_info": {
                "name": harbor_agent_for_runtime(runtime_id),
                "version": pin,
                "model_info": None,
            },
        },
    )


_MODEL = "kimi-k2.7-code"
_PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)


@pytest.mark.parametrize("proxy_name", _PROXY_ENV_NAMES)
def test_runtime_identity_tracks_proxy_presence_without_hashing_credential_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    proxy_name: str,
) -> None:
    """Launch identity changes on proxy use, but not when only its secret value changes."""
    for name in _PROXY_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BENCHEVAL_HARBOR_FORWARD_PROXY", "1")

    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id=_MODEL,
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    command_used_env_file: list[bool] = []

    def run_once(label: str) -> str:
        def resolved_harbor(
            command: tuple[str, ...],
            *,
            cwd: Path | None,
            timeout_sec: int,
        ) -> HarborCliResult:
            uses_env_file = "--env-file" in command
            command_used_env_file.append(uses_env_file)
            if uses_env_file:
                env_file = Path(command[command.index("--env-file") + 1])
                assert env_file.is_file()
                assert proxy_name in env_file.read_text(encoding="utf-8")
            jobs_dir = Path(command[command.index("--jobs-dir") + 1])
            jobs_dir.mkdir(parents=True, exist_ok=True)
            (jobs_dir / "result.json").write_text(
                _legacy_pass_result("claude-code") + "\n", encoding="utf-8"
            )
            return HarborCliResult(0, "", "", 0.01, tuple(command))

        evidence_path = tmp_path / f"{label}.jsonl"
        execute_control_plane_run(
            plan=plan,
            output_path=evidence_path,
            artifacts_dir=tmp_path / f"artifacts-{label}",
            harbor_process_runner=resolved_harbor,
            run_id=f"proxy-identity-{label}",
        )
        row = read_evidence_jsonl(evidence_path)[0]
        assert row.primary_pass is True
        assert row.runtime_config_hash is not None
        return row.runtime_config_hash

    without_proxy = run_once("absent")
    assert command_used_env_file[-1] is False

    monkeypatch.setenv(proxy_name, "http://contract-user:first-secret@proxy.invalid:8118")
    with_first_secret = run_once("present-a")
    assert command_used_env_file[-1] is True

    monkeypatch.setenv(proxy_name, "http://contract-user:second-secret@proxy.invalid:8118")
    with_second_secret = run_once("present-b")
    assert command_used_env_file[-1] is True

    assert with_second_secret == with_first_secret
    assert with_first_secret != without_proxy


class _LaunchObserved(RuntimeError):
    """Stop a contract test immediately after observing the subprocess boundary."""


@pytest.mark.parametrize("budget_sec", [1, 7])
def test_swebench_launch_timeout_does_not_exceed_one_instance_budget(
    tmp_path: Path,
    budget_sec: int,
) -> None:
    base_plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id=_MODEL,
    )
    plan = base_plan.model_copy(
        update={
            "instances": base_plan.instances[:1],
            # F005 contract: per-instance budget drives the launch timeout.
            "max_wall_clock_sec_per_instance": budget_sec,
        },
    )
    observed: list[int] = []

    def observe_launch(
        command: tuple[str, ...],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> SwebenchCliResult:
        observed.append(timeout_sec)
        raise _LaunchObserved

    with pytest.raises(_LaunchObserved):
        run_swebench_instance(
            plan=plan,
            instance_id=plan.instances[0].instance_id,
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=observe_launch,
        )

    assert observed == [budget_sec]


@pytest.mark.parametrize("budget_sec", [1, 7])
def test_bfcl_launch_timeout_does_not_exceed_one_instance_budget(
    tmp_path: Path,
    budget_sec: int,
) -> None:
    base_plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        # The only config/models.yaml entry the pinned upstream
        # MODEL_CONFIG_MAPPING supports; the launch gate rejects others first.
        model_id="gpt-5.2-2025-12-11",
    )
    plan = base_plan.model_copy(
        update={
            "instances": base_plan.instances[:1],
            # F005 contract: per-instance budget drives the launch timeout.
            "max_wall_clock_sec_per_instance": budget_sec,
        },
    )
    observed: list[int] = []

    def observe_launch(
        command: tuple[str, ...],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del env
        observed.append(timeout_sec)
        raise _LaunchObserved

    with pytest.raises(_LaunchObserved):
        run_bfcl_instance(
            plan=plan,
            instance_id=plan.instances[0].instance_id,
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=observe_launch,
            harness_version="bfcl-eval@2026.3.23",
        )

    assert observed == [budget_sec]


@pytest.mark.parametrize("budget_sec", [1, 7])
def test_hle_launch_timeout_uses_the_run_total_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    budget_sec: int,
) -> None:
    home = tmp_path / "hle-home"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# entry point\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# entry point\n", encoding="utf-8")
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))

    base_plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id=_MODEL,
    )
    plan = base_plan.model_copy(
        update={
            "instances": base_plan.instances[:1],
            # Round-3 F005 contract: the aggregate HLE harness runs prediction
            # and judging for every sample in one subprocess chain, bounded by
            # the run-total envelope; no per-instance limit is enforceable
            # inside the aggregate process.
            "max_wall_clock_sec": budget_sec,
        },
    )
    observed: list[int] = []

    def observe_launch(
        command: tuple[str, ...],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env=None,
    ) -> HleCliResult:
        observed.append(timeout_sec)
        raise _LaunchObserved

    with pytest.raises(_LaunchObserved):
        run_hle_slice(
            plan=plan,
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=observe_launch,
            run_id=f"hle-budget-{budget_sec}",
        )

    assert observed == [budget_sec]


@pytest.mark.parametrize("budget_sec", [1, 7])
def test_gpqa_launch_timeout_uses_the_run_total_envelope(
    tmp_path: Path,
    budget_sec: int,
) -> None:
    base_plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id=_MODEL,
    )
    plan = base_plan.model_copy(
        update={
            "instances": base_plan.instances[:1],
            # Round-3 F005 contract: one Inspect eval covers every sample in a
            # single aggregate subprocess, bounded by the run-total envelope.
            "max_wall_clock_sec": budget_sec,
        },
    )
    observed: list[int] = []

    def observe_launch(
        command: tuple[str, ...],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env=None,
    ) -> GpqaCliResult:
        observed.append(timeout_sec)
        raise _LaunchObserved

    with pytest.raises(_LaunchObserved):
        run_gpqa_slice(
            plan=plan,
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=observe_launch,
        )

    assert observed == [budget_sec]
