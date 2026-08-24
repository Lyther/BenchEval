"""RED contracts for remaining run-control and provenance obligations.

SUBSTITUTE_JUSTIFICATION
- substitute: injected Harbor, SWE-bench, and BFCL process runners in the effective-config, budget,
  and cleanup tests
- replaces: external harness CLIs, the container runtime, provider calls, and billed model execution
- necessity: the assertions require deterministic charged-cost boundaries and controlled transient
  artifacts; a real provider run cannot safely guarantee an exact cost crossing or filesystem shape
- real-option: a disposable real Harbor stack still performs a charged, nondeterministic provider
  call and cannot force the exact boundary condition without modifying the external service
- proof-limit: these tests prove only BenchEval's local response to authentic-shaped Harbor results;
  they do not prove Harbor execution, provider billing, container isolation, or live cleanup
- real-proof: BLOCKED until a dev-box has Docker, Harbor, provider credentials, and a disposable
  benchmark task; run the equivalent real pilot with a deliberately tiny budget and inspect its
  evidence and post-run artifact tree
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import BfclCliResult
from bencheval.control_plane_executor import _hash_config_inputs, execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.runtime_registry import load_runtime_catalog
from bencheval.terminal_bench_harbor import HarborCliResult, harbor_agent_for_runtime

_BFCL_MODEL = "gpt-5.2-2025-12-11"
_BFCL_IDENTITY = "bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b"


class _BfclLifecycleRunner:
    """Fabricates the pinned official score artifact on each evaluate call.

    Covered by the file-scope SUBSTITUTE_JUSTIFICATION: the injected runner
    replaces the real ``bfcl`` CLI so the budget/cleanup boundaries are
    deterministic (per-phase latency is a constructor knob).
    """

    def __init__(self, *, latency_sec: float = 2.0, transient: bool = False) -> None:
        self._latency_sec = latency_sec
        self._transient = transient

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
        if call[1] == "evaluate":
            category = call[list(call).index("--test-category") + 1]
            score_root = Path(call[list(call).index("--score-dir") + 1])
            score_file = score_root / _BFCL_MODEL / "non_live" / f"BFCL_v4_{category}_score.json"
            score_file.parent.mkdir(parents=True, exist_ok=True)
            score_file.write_text(
                json.dumps({"accuracy": 1.0, "correct_count": 1, "total_count": 1}) + "\n",
                encoding="utf-8",
            )
            if self._transient:
                transient_dir = score_root.parent / "agent-workspace"
                transient_dir.mkdir(exist_ok=True)
                (transient_dir / "scratch.txt").write_text("ephemeral\n", encoding="utf-8")
        return BfclCliResult(0, "", "", self._latency_sec, call)


def _legacy_pass_result(runtime_id: str, **extra: object) -> str:
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
            **extra,
        },
    )


def test_runtime_config_hash_is_order_independent_and_content_sensitive(
    tmp_path: Path,
) -> None:
    """A config identity follows content, not registry tuple ordering."""
    first = tmp_path / "first.toml"
    second = tmp_path / "second.toml"
    first.write_text("model = 'alpha'\n", encoding="utf-8")
    second.write_text("tools = ['shell']\n", encoding="utf-8")

    forward = _hash_config_inputs(("first.toml", "second.toml"), root=tmp_path)
    reversed_order = _hash_config_inputs(("second.toml", "first.toml"), root=tmp_path)

    assert forward is not None
    assert forward == reversed_order

    first.write_text("model = 'beta'\n", encoding="utf-8")
    changed = _hash_config_inputs(("first.toml", "second.toml"), root=tmp_path)
    assert changed != forward


@pytest.mark.parametrize(
    ("runtime_id", "environment_name", "values"),
    [
        ("claude-code", "BENCHEVAL_CLAUDE_CODE_ALLOWED_TOOLS", ("Read", "Read,Write")),
        (
            "codex-cli",
            "OPENAI_BASE_URL",
            ("https://provider-a.example/v1", "https://provider-b.example/v1"),
        ),
        (
            "codex-cli",
            "BENCHEVAL_CODEX_ENV_KEY",
            ("OPENAI_API_KEY", "BYTELLM_API_KEY"),
        ),
    ],
)
def test_evidence_hashes_the_effective_runtime_configuration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runtime_id: str,
    environment_name: str,
    values: tuple[str, str],
) -> None:
    """Evidence identity changes when a runtime-affecting command option changes."""
    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id=runtime_id,
        model_id="kimi-k2.7-code",
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    if environment_name == "BENCHEVAL_CODEX_ENV_KEY":
        monkeypatch.setenv("OPENAI_BASE_URL", "https://provider.example/v1")

    def resolved_runner(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        jobs_dir = Path(command[command.index("--jobs-dir") + 1])
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / "result.json").write_text(
            _legacy_pass_result(runtime_id) + "\n", encoding="utf-8"
        )
        return HarborCliResult(0, "", "", 0.1, tuple(command))

    hashes: list[str | None] = []
    for index, value in enumerate(values):
        monkeypatch.setenv(environment_name, value)
        evidence_path = tmp_path / f"effective-{index}.jsonl"
        execute_control_plane_run(
            plan=plan,
            output_path=evidence_path,
            artifacts_dir=tmp_path / f"artifacts-{index}",
            harbor_process_runner=resolved_runner,
            run_id=f"effective-config-{runtime_id}-{index}",
        )
        hashes.append(read_evidence_jsonl(evidence_path)[0].runtime_config_hash)

    assert all(value is not None for value in hashes)
    assert hashes[0] != hashes[1]


def test_control_plane_stops_before_launching_past_the_cost_budget(tmp_path: Path) -> None:
    """A charged result consumes the run-wide budget before another task launches."""
    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    plan = base_plan.model_copy(
        update={
            "instances": base_plan.instances[:3],
            "max_cost_usd": 0.10,
        },
    )
    calls: list[str] = []

    def charged_runner(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        instance_id = command[command.index("--task-name") + 1]
        calls.append(instance_id)
        jobs_dir = Path(command[command.index("--jobs-dir") + 1])
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / "result.json").write_text(
            _legacy_pass_result("claude-code", cost_usd=0.20) + "\n",
            encoding="utf-8",
        )
        return HarborCliResult(0, "", "", 0.1, tuple(command))

    evidence_path = tmp_path / "evidence.jsonl"
    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        harbor_process_runner=charged_runner,
        run_id="cost-budget-contract",
    )

    rows = read_evidence_jsonl(evidence_path)
    assert calls == [plan.instances[0].instance_id]
    assert summary.instance_count == 3
    assert summary.passed_count == 1
    assert summary.failed_count == 2
    assert len(rows) == 3
    assert rows[0].cost_usd == 0.20
    assert rows[0].primary_pass is True
    assert {row.benchmark_version for row in rows} == {"terminal-bench@2.1"}
    assert [row.instance_id for row in rows[1:]] == [
        inst.instance_id for inst in plan.instances[1:]
    ]
    assert all(row.cost_usd == 0.0 for row in rows[1:])
    assert all(row.primary_pass is False for row in rows[1:])
    assert all(row.failure_class == "runtime_budget_exceeded" for row in rows[1:])


def test_control_plane_stops_before_launching_past_the_wall_budget(tmp_path: Path) -> None:
    """Reported elapsed time consumes the same run-wide envelope used by dry-run."""
    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    plan = base_plan.model_copy(
        update={
            "instances": base_plan.instances[:3],
            "max_wall_clock_sec": 1,
        },
    )
    calls: list[str] = []

    def slow_runner(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        instance_id = command[command.index("--task-name") + 1]
        calls.append(instance_id)
        jobs_dir = Path(command[command.index("--jobs-dir") + 1])
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / "result.json").write_text(
            _legacy_pass_result("claude-code") + "\n", encoding="utf-8"
        )
        return HarborCliResult(0, "", "", 2.0, tuple(command))

    evidence_path = tmp_path / "evidence.jsonl"
    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        harbor_process_runner=slow_runner,
        run_id="wall-budget-contract",
    )

    rows = read_evidence_jsonl(evidence_path)
    assert calls == [plan.instances[0].instance_id]
    assert summary.instance_count == 3
    assert summary.passed_count == 1
    assert summary.failed_count == 2
    assert len(rows) == 3
    assert rows[0].latency_sec == 2.0
    assert rows[0].primary_pass is True
    assert {row.benchmark_version for row in rows} == {"terminal-bench@2.1"}
    assert [row.instance_id for row in rows[1:]] == [
        inst.instance_id for inst in plan.instances[1:]
    ]
    assert all(row.latency_sec == 0.0 for row in rows[1:])
    assert all(row.primary_pass is False for row in rows[1:])
    assert all(row.failure_class == "runtime_budget_exceeded" for row in rows[1:])


def test_swebench_stops_before_launching_past_the_cost_budget(tmp_path: Path) -> None:
    """Demoted SWE-bench adapters refuse execute_control_plane_run."""
    base_plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    plan = base_plan.model_copy(
        update={"instances": base_plan.instances[:3], "max_cost_usd": 0.10},
    )
    with pytest.raises(BenchEvalError, match="executable_adapter"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "evidence.jsonl",
            artifacts_dir=tmp_path / "artifacts",
            run_id="swebench-cost-budget-contract",
        )


def test_swebench_stops_before_launching_past_the_wall_budget(tmp_path: Path) -> None:
    """Demoted SWE-bench adapters refuse execute_control_plane_run."""
    base_plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    plan = base_plan.model_copy(
        update={"instances": base_plan.instances[:3], "max_wall_clock_sec": 1},
    )
    with pytest.raises(BenchEvalError, match="executable_adapter"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "evidence.jsonl",
            artifacts_dir=tmp_path / "artifacts",
            run_id="swebench-wall-budget-contract",
        )


def test_bfcl_applies_run_wide_budget_before_next_category(tmp_path: Path) -> None:
    """The run-wide wall budget skips the next category with a budget row.

    BFCL outcomes always carry cost_usd 0.0 (the ``bfcl`` CLI reports no cost),
    so the cost axis can never exhaust for bfcl; only the wall axis is exercised.
    """
    base_plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_BFCL_MODEL,
    )
    plan = base_plan.model_copy(
        update={"instances": base_plan.instances[:2], "max_wall_clock_sec": 1},
    )
    runner = _BfclLifecycleRunner(latency_sec=2.0)  # 4.0s per category (generate+evaluate)

    summary = execute_control_plane_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=tmp_path / "artifacts",
        run_id="bfcl-budget-contract",
        bfcl_process_runner=runner,
        bfcl_benchmark_identity=_BFCL_IDENTITY,
    )

    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert [row.instance_id for row in rows] == ["simple_python", "irrelevance"]
    assert rows[0].primary_pass is True
    assert rows[1].failure_class == "runtime_budget_exceeded"
    assert summary.passed_count == 1
    assert summary.failed_count == 1


def test_control_plane_applies_cleanup_policy_and_records_the_result(tmp_path: Path) -> None:
    """Successful execution preserves proof but removes per-task transient state."""
    base_plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
        cleanup_policy="always",
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    result_paths: list[Path] = []
    transient_paths: list[Path] = []

    def artifact_runner(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        jobs_dir = Path(command[command.index("--jobs-dir") + 1])
        jobs_dir.mkdir(parents=True, exist_ok=True)
        result_path = jobs_dir / "result.json"
        result_path.write_text(_legacy_pass_result("claude-code") + "\n", encoding="utf-8")
        transient_path = jobs_dir / "agent-workspace"
        transient_path.mkdir()
        (transient_path / "scratch.txt").write_text("ephemeral\n", encoding="utf-8")
        result_paths.append(result_path)
        transient_paths.append(transient_path)
        return HarborCliResult(0, "", "", 0.1, tuple(command))

    evidence_path = tmp_path / "evidence.jsonl"
    execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        harbor_process_runner=artifact_runner,
        run_id="cleanup-contract",
    )

    rows = read_evidence_jsonl(evidence_path)
    assert len(rows) == 1
    assert rows[0].primary_pass is True
    assert rows[0].cleanup_result == "success"
    assert result_paths[0].is_file()
    assert not transient_paths[0].exists()


def test_swebench_applies_cleanup_policy_without_deleting_verifier(tmp_path: Path) -> None:
    """Demoted SWE-bench adapters refuse execute_control_plane_run."""
    base_plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
        cleanup_policy="always",
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    with pytest.raises(BenchEvalError, match="executable_adapter"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "evidence.jsonl",
            artifacts_dir=tmp_path / "artifacts",
            run_id="swebench-cleanup-contract",
        )


def test_bfcl_applies_cleanup_policy_without_deleting_verdict(tmp_path: Path) -> None:
    """Admitted BFCL dispatch removes transient dirs but keeps the official score artifact."""
    base_plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_BFCL_MODEL,
        cleanup_policy="always",
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    execute_control_plane_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=tmp_path / "artifacts",
        run_id="bfcl-cleanup-contract",
        bfcl_process_runner=_BfclLifecycleRunner(transient=True),
        bfcl_benchmark_identity=_BFCL_IDENTITY,
    )

    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert len(rows) == 1
    assert rows[0].primary_pass is True
    assert rows[0].cleanup_result == "success"
    instance_artifacts = tmp_path / "artifacts" / "simple_python"
    assert not (instance_artifacts / "agent-workspace").exists()
    assert list(instance_artifacts.rglob("BFCL_v4_simple_python_score.json"))
