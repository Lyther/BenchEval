"""BFCL v4 adapter unit tests (parse/build/run-phase; admitted after the live lifecycle qualified).

SUBSTITUTE_JUSTIFICATION
- substitute: stub `process_runner` callables in this module's run-phase,
  launch-env, and executor-dispatch tests
- replaces: the external `bfcl` CLI process and its charged provider calls
- necessity: the assertions target BenchEval-side phase sequencing, failure
  short-circuiting, and budget-envelope arithmetic at the subprocess boundary;
  a real bfcl install cannot deterministically manufacture a generate-phase
  failure or an exactly-exhausted inter-phase budget
- real-option: an official bfcl-eval install plus registered model/provider
  credentials; unavailable in the local Tier-0 environment
- proof-limit: proves orchestration and failure mapping only, not BFCL
  execution, scorer correctness, or live readiness
- real-proof: run-20260824-045622-854659-a46ae44d (dev-box-cpu, 2026-08-24,
  registered `passed`): 5/5 smoke categories officially scored via the real
  generate → evaluate lifecycle; the diagnostic-labeled demonstration
  run-20260824-040631-228703-4756f857 covered the same lifecycle earlier
  (evidence under the machine-local, gitignored results/ tree)
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from bencheval.adapter_admission import assess_bfcl_v4_admission
from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import (
    BFCL_ADAPTER_ID,
    BfclCliResult,
    build_bfcl_run_command,
    parse_bfcl_instance_outcome,
    run_bfcl_instance,
)
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.exceptions import AdapterFailureError, BenchEvalError


def test_bfcl_admission_passes_after_live_qualification() -> None:
    # Round-1 F008 contract, inverted: the wired generate+evaluate lifecycle
    # ran live on the dev-box (diagnostic-labeled demonstration
    # run-20260824-040631-228703-4756f857, then registered `passed` run
    # run-20260824-045622-854659-a46ae44d), so
    # the Tier-0 wiring gate must report passed. Demoted fail-closed coverage
    # stays with swe-bench-verified in tests/test_adapter_admission.py.
    report = assess_bfcl_v4_admission()
    assert report.passed is True
    assert {name: ok for name, ok, _ in report.checks}.get("catalog_executable") is True


def test_build_bfcl_run_command() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    cmd = build_bfcl_run_command(
        plan=plan,
        instance_id="simple",
        artifacts_dir=Path("/tmp/out"),
    )
    assert cmd[:2] == ("bfcl", "generate")
    assert "--test-category" in cmd
    assert "simple" in cmd
    assert "--result-dir" in cmd


def _bfcl_generate_cmd(monkeypatch: pytest.MonkeyPatch, env_value: str | None) -> tuple[str, ...]:
    if env_value is None:
        monkeypatch.delenv("BENCHEVAL_BFCL_NUM_THREADS", raising=False)
    else:
        monkeypatch.setenv("BENCHEVAL_BFCL_NUM_THREADS", env_value)
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    return build_bfcl_run_command(
        plan=plan,
        instance_id="simple_python",
        artifacts_dir=Path("/tmp/out"),
    )


def test_build_bfcl_run_command_pins_num_threads_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Hosted-model generation defaults to 1 thread upstream; the smoke slice's
    # 300s per-instance cap can only be met with bounded concurrency, and the
    # value must land in argv (and thereby in evidence adapter_metadata).
    cmd = _bfcl_generate_cmd(monkeypatch, None)
    assert "--num-threads" in cmd
    assert cmd[cmd.index("--num-threads") + 1] == "16"


def test_build_bfcl_run_command_num_threads_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cmd = _bfcl_generate_cmd(monkeypatch, "48")
    assert cmd[cmd.index("--num-threads") + 1] == "48"


@pytest.mark.parametrize("bad", ["abc", "0", "-3", "1.5", ""])
def test_build_bfcl_run_command_num_threads_env_invalid(
    monkeypatch: pytest.MonkeyPatch,
    bad: str,
) -> None:
    with pytest.raises(BenchEvalError, match="BENCHEVAL_BFCL_NUM_THREADS"):
        _bfcl_generate_cmd(monkeypatch, bad)


def test_parse_scores_only_the_official_evaluate_artifact(tmp_path: Path) -> None:
    # Lifecycle contract: the official evaluate score artifact is the only
    # scoring authority; a contradictory generation-side verdict.json is
    # harness scratch output and must be ignored.
    art = tmp_path / "inst"
    art.mkdir()
    (art / "verdict.json").write_text(
        json.dumps({"primary_pass": False, "correct": False, "cost_usd": 0.01}),
        encoding="utf-8",
    )
    score_dir = art / "scores"
    score_file = score_dir / "gpt-5.2-2025-12-11" / "non_live" / "BFCL_v4_simple_python_score.json"
    score_file.parent.mkdir(parents=True)
    score_file.write_text(
        json.dumps({"accuracy": 1.0, "correct_count": 1, "total_count": 1}) + "\n",
        encoding="utf-8",
    )
    cli = BfclCliResult(0, "", "", 0.2, ("bfcl", "evaluate"))
    out = parse_bfcl_instance_outcome(
        instance_id="simple_python",
        cli=cli,
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="bfcl-eval@2026.3.23",
        score_dir=score_dir,
        model_id="gpt-5.2-2025-12-11",
    )
    assert out.primary_pass is True
    assert out.partial_score == 1.0
    assert out.verifier_log_path is not None
    assert out.verifier_log_path.endswith("BFCL_v4_simple_python_score.json")
    assert out.adapter_metadata["adapter_id"] == BFCL_ADAPTER_ID


def test_run_generate_failure_skips_evaluate(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
    )
    calls: list[tuple[str, ...]] = []

    def failing_generate(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        calls.append(tuple(command))
        return BfclCliResult(1, "", "generate boom", 0.1, tuple(command))

    outcome = run_bfcl_instance(
        plan=plan,
        instance_id="simple_python",
        artifacts_dir=tmp_path / "artifacts",
        repo_root=tmp_path,
        process_runner=failing_generate,
        harness_version="bfcl-eval@2026.3.23",
    )

    assert [command[1] for command in calls] == ["generate"]
    assert outcome.primary_pass is False
    assert outcome.failure_class == "harness_failure"
    assert outcome.verifier_log_path is None


def test_run_budget_exhausted_between_phases_raises(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
    )
    calls: list[tuple[str, ...]] = []

    def instant_runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        calls.append(tuple(command))
        return BfclCliResult(0, "", "", 0.0, tuple(command))

    # timeout_sec=0 exhausts the cumulative envelope the moment generate ends.
    with pytest.raises(AdapterFailureError, match="timed out") as excinfo:
        run_bfcl_instance(
            plan=plan,
            instance_id="simple_python",
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=instant_runner,
            timeout_sec=0,
            harness_version="bfcl-eval@2026.3.23",
        )

    assert excinfo.value.failure_label == "runtime_budget_exceeded"
    assert [command[1] for command in calls] == ["generate"]


def test_execute_bfcl_dispatches_when_admitted(tmp_path: Path) -> None:
    # Admitted contract: a non-diagnostic bfcl plan dispatches through the
    # executor and produces scored rows. Refusal-while-demoted coverage stays
    # with swe-bench-verified (test_review_r1_native_honesty.py).
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
    )
    plan = plan.model_copy(update={"instances": plan.instances[:1]})

    def runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        call = tuple(command)
        if call[1] == "evaluate":
            score_root = Path(call[list(call).index("--score-dir") + 1])
            score_file = (
                score_root / "gpt-5.2-2025-12-11" / "non_live" / "BFCL_v4_simple_python_score.json"
            )
            score_file.parent.mkdir(parents=True, exist_ok=True)
            score_file.write_text(
                json.dumps({"accuracy": 1.0, "correct_count": 1, "total_count": 1}) + "\n",
                encoding="utf-8",
            )
        return BfclCliResult(0, "", "", 0.1, call)

    summary = execute_control_plane_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=tmp_path / "art",
        run_id="bfcl-run",
        bfcl_process_runner=runner,
        bfcl_benchmark_identity=_BFCL_IDENTITY,
    )

    assert summary.instance_count == 1
    assert summary.passed_count == 1


# ---------------------------------------------------------------------------
# Immutable package-data identity (catalog ``identity:`` block for bfcl-v4)
# ---------------------------------------------------------------------------

_BFCL_SIMPLE_RELPATH = "data/BFCL_v4_simple_python.json"
_BFCL_ANSWER_RELPATH = "data/possible_answer/BFCL_v4_simple_python.json"
_BFCL_IDENTITY = "bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b"


def _write_bfcl_package(root: Path, *, simple: bytes, answer: bytes) -> dict[str, str]:
    (root / "data" / "possible_answer").mkdir(parents=True, exist_ok=True)
    (root / _BFCL_SIMPLE_RELPATH).write_bytes(simple)
    (root / _BFCL_ANSWER_RELPATH).write_bytes(answer)
    import hashlib

    return {
        _BFCL_SIMPLE_RELPATH: f"sha256:{hashlib.sha256(simple).hexdigest()}",
        _BFCL_ANSWER_RELPATH: f"sha256:{hashlib.sha256(answer).hexdigest()}",
    }


def _bfcl_identity_dto(files: dict[str, str]):
    from bencheval.benchmark_registry import BfclPackageDataIdentity

    return BfclPackageDataIdentity(
        kind="bfcl-package-data",
        bfcl_eval_version="2026.3.23",
        upstream_commit="6ea57973c7a6097fd7c5915698c54c17c5b1b6c8",
        files=files,
    )


def test_verify_bfcl_package_data_accepts_real_pinned_bytes(tmp_path: Path) -> None:
    from bencheval.bfcl_native_adapter import verify_bfcl_package_data

    root = tmp_path / "bfcl_eval"
    files = _write_bfcl_package(root, simple=b'[{"a": 1}]\n', answer=b'[{"b": 2}]\n')

    verify_bfcl_package_data(package_root=root, files=files)


def test_verify_bfcl_package_data_fails_closed_on_drift_and_absence(tmp_path: Path) -> None:
    from bencheval.bfcl_native_adapter import verify_bfcl_package_data

    root = tmp_path / "bfcl_eval"
    files = _write_bfcl_package(root, simple=b'[{"a": 1}]\n', answer=b'[{"b": 2}]\n')
    (root / _BFCL_ANSWER_RELPATH).write_bytes(b"drifted\n")
    with pytest.raises(BenchEvalError, match="sha256"):
        verify_bfcl_package_data(package_root=root, files=files)

    (root / _BFCL_ANSWER_RELPATH).unlink()
    with pytest.raises(BenchEvalError, match=r"(?i)(missing|absent|not found)"):
        verify_bfcl_package_data(package_root=root, files=files)


def test_capture_bfcl_benchmark_identity_binds_package_data_bytes(tmp_path: Path) -> None:
    from bencheval.bfcl_native_adapter import capture_bfcl_benchmark_identity
    from bencheval.identity_strings import combined_data_sha256

    root = tmp_path / "bfcl_eval"
    files = _write_bfcl_package(root, simple=b'[{"a": 1}]\n', answer=b'[{"b": 2}]\n')

    captured = capture_bfcl_benchmark_identity(_bfcl_identity_dto(files), package_root=root)

    expected = "bfcl-v4@bfcl-eval-2026.3.23+data-" + combined_data_sha256(files)[:16]
    assert captured == expected

    (root / _BFCL_SIMPLE_RELPATH).write_bytes(b"drifted\n")
    with pytest.raises(BenchEvalError, match="sha256"):
        capture_bfcl_benchmark_identity(_bfcl_identity_dto(files), package_root=root)


def test_run_bfcl_instance_refuses_mismatched_supplied_identity(tmp_path: Path) -> None:
    """A supplied identity at the injected-runner boundary is validated pre-launch.

    Extends the module-level SUBSTITUTE_JUSTIFICATION: the stub runner proves
    the run aborts before any (substituted) launch when identity drifts.
    """
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
    )
    calls: list[tuple[str, ...]] = []

    def runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del env
        calls.append(tuple(command))
        return BfclCliResult(0, "", "", 0.0, tuple(command))

    with pytest.raises(BenchEvalError, match=r"(?i)(identity|drift)"):
        run_bfcl_instance(
            plan=plan,
            instance_id="simple_python",
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=runner,
            harness_version="bfcl-eval@2026.3.23",
            benchmark_identity="bfcl-v4@bfcl-eval-2026.3.23+data-0000000000000000",
        )

    assert calls == []


def test_run_bfcl_instance_stamps_validated_identity(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
    )

    def failing_generate(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        return BfclCliResult(1, "", "generate boom", 0.1, tuple(command))

    outcome = run_bfcl_instance(
        plan=plan,
        instance_id="simple_python",
        artifacts_dir=tmp_path / "artifacts",
        repo_root=tmp_path,
        process_runner=failing_generate,
        harness_version="bfcl-eval@2026.3.23",
        benchmark_identity=_BFCL_IDENTITY,
    )

    assert outcome.adapter_metadata["benchmark_version"] == _BFCL_IDENTITY


# The smoke-5 slice runs five categories; the identity pin covers every data
# file behind them (irrelevance has no possible_answer file in v4 by design).
_BFCL_SMOKE_RELPATHS = (
    "data/BFCL_v4_simple_python.json",
    "data/possible_answer/BFCL_v4_simple_python.json",
    "data/BFCL_v4_irrelevance.json",
    "data/BFCL_v4_parallel.json",
    "data/possible_answer/BFCL_v4_parallel.json",
    "data/BFCL_v4_multiple.json",
    "data/possible_answer/BFCL_v4_multiple.json",
    "data/BFCL_v4_parallel_multiple.json",
    "data/possible_answer/BFCL_v4_parallel_multiple.json",
)


def _write_bfcl_smoke_package(root: Path) -> dict[str, str]:
    import hashlib

    pins: dict[str, str] = {}
    for index, relpath in enumerate(_BFCL_SMOKE_RELPATHS):
        payload = f"payload-{index}\n".encode()
        target = root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        pins[relpath] = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    return pins


def test_verify_bfcl_package_data_fails_closed_on_new_category_drift(tmp_path: Path) -> None:
    """Drift in a newly pinned category file fails closed like the originals.

    Extends the module-level SUBSTITUTE_JUSTIFICATION: a fabricated tmp-dir
    package root stands in for the installed bfcl_eval package data so the
    digest-compare boundary is exercised deterministically.
    """
    from bencheval.bfcl_native_adapter import verify_bfcl_package_data

    root = tmp_path / "bfcl_eval"
    files = _write_bfcl_smoke_package(root)

    drifted = root / "data/BFCL_v4_parallel.json"
    original = drifted.read_bytes()
    drifted.write_bytes(b"drifted\n")
    with pytest.raises(BenchEvalError, match="sha256"):
        verify_bfcl_package_data(package_root=root, files=files)

    drifted.write_bytes(original)
    (root / "data/possible_answer/BFCL_v4_parallel_multiple.json").unlink()
    with pytest.raises(BenchEvalError, match=r"(?i)(missing|absent|not found)"):
        verify_bfcl_package_data(package_root=root, files=files)


# ---------------------------------------------------------------------------
# Provider launch environment (mirrors the HLE adapter boundary)
# ---------------------------------------------------------------------------


class _EnvRecordingRunner:
    def __init__(self) -> None:
        self.envs: list[dict[str, str]] = []

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec
        self.envs.append(dict(env))
        return BfclCliResult(1, "", "generate boom", 0.1, tuple(command))


def test_real_runner_requires_credential_env_before_any_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BYTELLM_API_KEY", raising=False)
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
    )
    with pytest.raises(BenchEvalError, match="BYTELLM_API_KEY"):
        run_bfcl_instance(
            plan=plan,
            instance_id="simple_python",
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
        )
    assert not (tmp_path / "artifacts").exists()


def test_injected_runner_receives_provider_launch_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The injected boundary still receives the resolved provider environment.

    Extends the module-level SUBSTITUTE_JUSTIFICATION: the stub runner records
    the env kwarg instead of launching the external bfcl CLI.
    """
    monkeypatch.delenv("BYTELLM_API_KEY", raising=False)
    monkeypatch.delenv("BYTELLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
    )
    runner = _EnvRecordingRunner()

    run_bfcl_instance(
        plan=plan,
        instance_id="simple_python",
        artifacts_dir=tmp_path / "artifacts",
        repo_root=tmp_path,
        process_runner=runner,
        harness_version="bfcl-eval@2026.3.23",
        benchmark_identity=_BFCL_IDENTITY,
    )

    assert runner.envs
    assert runner.envs[0]["OPENAI_BASE_URL"] == "http://127.0.0.1:4000/v1"
    assert "OPENAI_API_KEY" not in runner.envs[0]


def test_injected_runner_env_maps_bytellm_key_to_openai_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The provider credential crosses the boundary as OPENAI_API_KEY only.

    Extends the module-level SUBSTITUTE_JUSTIFICATION (stub runner records the
    env kwarg). The credential value is never logged or written to artifacts.
    """
    monkeypatch.setenv("BYTELLM_API_KEY", "test-credential-placeholder")
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
    )
    runner = _EnvRecordingRunner()

    run_bfcl_instance(
        plan=plan,
        instance_id="simple_python",
        artifacts_dir=tmp_path / "artifacts",
        repo_root=tmp_path,
        process_runner=runner,
        harness_version="bfcl-eval@2026.3.23",
        benchmark_identity=_BFCL_IDENTITY,
    )

    assert runner.envs
    assert runner.envs[0]["OPENAI_API_KEY"] == "test-credential-placeholder"
