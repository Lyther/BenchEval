"""RED contracts for the selected SWE-bench Verified diagnostic lifecycle.

The catalog must remain non-executable. These tests define the immutable source,
small diagnostic slice, explicit generation inputs, strict prediction boundary,
aggregate-report coherence, cumulative deadline, and diagnostic dispatch.

SUBSTITUTE_JUSTIFICATION
- substitute: injected ``SwebenchProcessRunner`` callables and planted official
  prediction/report files in four orchestration tests
- replaces: charged Inspect/provider generation and Docker-backed SWE evaluation
- necessity: malformed predictions, conflicting reports, and elapsed-budget
  exhaustion must be forced deterministically before any charged or container
  effect; a real model/evaluator run cannot guarantee these negative states
- real-option: an uncharged real dataset/materialization and evaluator-schema
  probe precedes one real charged diagnostic on dev-box-cpu
- proof-limit: diagnostic adapter orchestration only; it does not prove provider,
  Inspect solver, Docker, image, or official scoring behavior
- real-proof: retained diagnostic
  ``sha256:5f7f79ce44eb8c00d7ee826914e8d4591206de2d3b876a2524ccad508e373e52``
  scored the run-owned official-dataset row, stamped
  ``swe-bench-verified@78f471bf655a3137+data-030cfd7f2a704c4c``, retained
  official/Inspect rows, the transformation manifest, and the bound
  Inspect ``.eval``, and stamped ``runtime_version=0.148.0``. Schema-v2
  ``error_ids`` means no executed per-instance ``report.json``. Historical
  ``sha256:fcc766f5…235b5`` used Hub alias ``swebench eval verified``.
- covered tests: tests using the injected runner in this module,
  including test_official_eval_error_still_retains_prediction_and_summary
"""

from __future__ import annotations

import json
import time
import tomllib
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import HfDatasetSnapshotIdentity, load_benchmark_catalog
from bencheval.control_plane_executor import (
    diagnostic_capable_benchmark,
    execute_control_plane_run,
)
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.swebench_adapter import (
    SwebenchCliResult,
    build_swebench_eval_command,
    build_swebench_run_command,
    resolve_swebench_subprocess,
    run_swebench_instance,
)

_INSTANCE_ID = "django__django-11099"
_REVISION = "78f471bf655a3137b2e8a75af1501690ec009ec3"
_PARQUET_SHA = "sha256:030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25"


def _plan(*, slice_id: str = "swe-bench-verified-smoke-10"):
    return plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id=slice_id,
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
        diagnostic=True,
    )


def _prediction() -> str:
    return (
        json.dumps(
            {
                "instance_id": _INSTANCE_ID,
                "model_name_or_path": "kimi-k2.7-code",
                "model_patch": "diff --git a/a b/a\n",
            },
        )
        + "\n"
    )


def test_swe_catalog_binds_the_official_verified_snapshot_but_stays_demoted() -> None:
    benchmark = load_benchmark_catalog().by_id_or_alias("swe-bench-verified")

    assert benchmark.executable is False
    assert isinstance(benchmark.identity, HfDatasetSnapshotIdentity)
    assert benchmark.identity.repo == "SWE-bench/SWE-bench_Verified"
    assert benchmark.identity.revision == _REVISION
    assert benchmark.identity.files == {"data/test-00000-of-00001.parquet": _PARQUET_SHA}
    from bencheval.identity_strings import swebench_benchmark_identity

    assert swebench_benchmark_identity(benchmark.identity) == (
        "swe-bench-verified@78f471bf655a3137+data-030cfd7f2a704c4c"
    )


def test_swe_official_evaluator_is_an_exact_separate_dependency_group() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    groups = project["dependency-groups"]

    assert "swe" in groups
    assert groups["swe"] == ["swebench==5.0.1"]
    assert "swebench==5.0.1" not in project["project"]["dependencies"]
    assert "swebench==5.0.1" not in project["project"]["optional-dependencies"]["eval"]


def test_one_instance_diagnostic_slice_is_plannable_without_catalog_promotion() -> None:
    plan = _plan(slice_id="swe-bench-verified-diagnostic-1")

    assert plan.diagnostic is True
    assert [item.instance_id for item in plan.instances] == [_INSTANCE_ID]
    assert plan.benchmark_id == "swe-bench-verified"


def test_generation_command_explicitly_binds_the_planned_model_and_local_dataset() -> None:
    artifacts = Path("run-owned").resolve()
    command = build_swebench_run_command(
        plan=_plan(),
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
    )

    assert command[command.index("--model") + 1] == "openai/kimi-k2.7-code"
    task_args = [command[index + 1] for index, value in enumerate(command) if value == "-T"]
    assert f"dataset={artifacts / 'inspect-dataset'}" in task_args
    assert f"revision={_REVISION}" in task_args
    assert any(
        value.startswith("image_name_template=") and "@sha256:" in value for value in task_args
    )
    template = next(
        value.split("=", 1)[1] for value in task_args if value.startswith("image_name_template=")
    )
    formatted = template.format(
        id=_INSTANCE_ID,
        arch="x86_64",
        org="django",
        repo="django",
        issue="11099",
    )
    assert "{" not in formatted
    assert "@sha256:" in formatted
    assert _INSTANCE_ID in formatted


def test_malformed_existing_predictions_never_reach_the_official_evaluator(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    commands: list[tuple[str, ...]] = []

    def runner(command, *, cwd, timeout_sec) -> SwebenchCliResult:
        argv = tuple(str(part) for part in command)
        commands.append(argv)
        root = artifacts / _INSTANCE_ID
        root.mkdir(parents=True, exist_ok=True)
        (root / "predictions.jsonl").write_text("{}\n", encoding="utf-8")
        if len(commands) > 1:
            (root / "report.json").write_text(
                json.dumps({_INSTANCE_ID: {"resolved": True}}),
                encoding="utf-8",
            )
        return SwebenchCliResult(0, "", "", 0.0, argv)

    outcome = run_swebench_instance(
        plan=_plan(),
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=runner,
        timeout_sec=30,
        run_id="swe-malformed-prediction",
    )

    assert len(commands) == 1
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"


def test_conflicting_schema_v2_summary_invalidates_a_true_instance_report(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    commands: list[tuple[str, ...]] = []

    def runner(command, *, cwd, timeout_sec) -> SwebenchCliResult:
        argv = tuple(str(part) for part in command)
        commands.append(argv)
        root = artifacts / _INSTANCE_ID
        if len(commands) == 1:
            (root / "predictions.jsonl").write_text(_prediction(), encoding="utf-8")
            official = root / "official-dataset"
            official.mkdir()
            (official / "test.jsonl").write_text("{}\n", encoding="utf-8")
        else:
            (root / "report.json").write_text(
                json.dumps({_INSTANCE_ID: {"resolved": True}}),
                encoding="utf-8",
            )
            summary = {
                "schema_version": 2,
                "total_instances": 1,
                "submitted_instances": 1,
                "completed_instances": 1,
                "resolved_instances": 0,
                "unresolved_instances": 1,
                "resolved_ids": [],
                "unresolved_ids": [_INSTANCE_ID],
                "empty_patch_ids": [],
                "error_ids": [],
                "incomplete_ids": [],
                "infra_failure_ids": [],
                "ambiguous_failure_ids": [],
            }
            (root / "kimi-k2.7-code.swe-conflict.json").write_text(
                json.dumps(summary),
                encoding="utf-8",
            )
        return SwebenchCliResult(0, "", "", 0.0, argv)

    outcome = run_swebench_instance(
        plan=_plan(),
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=runner,
        timeout_sec=30,
        run_id="swe-conflict",
    )

    assert len(commands) == 2
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"


def test_elapsed_wall_time_not_runner_reported_latency_controls_second_phase(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    calls = 0

    def runner(command, *, cwd, timeout_sec) -> SwebenchCliResult:
        nonlocal calls
        calls += 1
        argv = tuple(str(part) for part in command)
        root = artifacts / _INSTANCE_ID
        if calls == 1:
            time.sleep(1.05)
            (root / "predictions.jsonl").write_text(_prediction(), encoding="utf-8")
            return SwebenchCliResult(0, "", "", 0.0, argv)
        raise AssertionError("official evaluator launched after the cumulative deadline")

    with pytest.raises(AdapterFailureError) as excinfo:
        run_swebench_instance(
            plan=_plan(),
            instance_id=_INSTANCE_ID,
            artifacts_dir=artifacts,
            repo_root=tmp_path,
            process_runner=runner,
            timeout_sec=1,
            run_id="swe-cumulative-deadline",
        )

    assert excinfo.value.failure_label == "runtime_budget_exceeded"
    assert calls == 1


def test_subsecond_remaining_wall_does_not_launch_eval(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    calls = 0

    def runner(command, *, cwd, timeout_sec) -> SwebenchCliResult:
        nonlocal calls
        calls += 1
        argv = tuple(str(part) for part in command)
        root = artifacts / _INSTANCE_ID
        if calls == 1:
            (root / "predictions.jsonl").write_text(_prediction(), encoding="utf-8")
            return SwebenchCliResult(0, "", "", 0.6, argv)
        raise AssertionError("official evaluator launched with a sub-second leftover")

    with pytest.raises(AdapterFailureError) as excinfo:
        run_swebench_instance(
            plan=_plan(),
            instance_id=_INSTANCE_ID,
            artifacts_dir=artifacts,
            repo_root=tmp_path,
            process_runner=runner,
            timeout_sec=1,
            run_id="swe-subsecond-deadline",
        )

    assert excinfo.value.failure_label == "runtime_budget_exceeded"
    assert calls == 1


def test_swe_diagnostic_failure_evidence_stamps_inspect_backend(tmp_path: Path) -> None:
    plan = _plan(slice_id="swe-bench-verified-diagnostic-1")

    def failing_runner(command, *, cwd, timeout_sec) -> SwebenchCliResult:
        raise AdapterFailureError(
            "swebench harness timed out after 1s",
            failure_label="runtime_budget_exceeded",
        )

    execute_control_plane_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=tmp_path / "artifacts",
        run_id="swe-backend-stamp",
        swebench_process_runner=failing_runner,
    )
    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")
    assert len(rows) == 1
    assert rows[0].failure_class == "runtime_budget_exceeded"
    assert rows[0].backend == "inspect"


def test_swe_is_diagnostic_capable_without_becoming_executable() -> None:
    benchmark = load_benchmark_catalog().by_id_or_alias("swe-bench-verified")

    assert benchmark.executable is False
    assert diagnostic_capable_benchmark(benchmark) is True


def test_executed_report_without_schema_v2_summary_is_unparseable(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    commands: list[tuple[str, ...]] = []

    def runner(command, *, cwd, timeout_sec) -> SwebenchCliResult:
        argv = tuple(str(part) for part in command)
        commands.append(argv)
        root = artifacts / _INSTANCE_ID
        root.mkdir(parents=True, exist_ok=True)
        if len(commands) == 1:
            (root / "predictions.jsonl").write_text(_prediction(), encoding="utf-8")
            official = root / "official-dataset"
            official.mkdir()
            (official / "test.jsonl").write_text("{}\n", encoding="utf-8")
        else:
            (root / "report.json").write_text(
                json.dumps({_INSTANCE_ID: {"resolved": True}}),
                encoding="utf-8",
            )
        return SwebenchCliResult(0, "", "", 0.1, argv)

    outcome = run_swebench_instance(
        plan=_plan(slice_id="swe-bench-verified-diagnostic-1"),
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=runner,
        timeout_sec=30,
        run_id="swe-missing-summary",
    )

    assert len(commands) == 2
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"


def test_official_eval_error_still_retains_prediction_and_summary(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    run_id = "swe-retain-pred"
    commands: list[tuple[str, ...]] = []

    def runner(command, *, cwd, timeout_sec) -> SwebenchCliResult:
        argv = tuple(str(part) for part in command)
        commands.append(argv)
        root = artifacts / _INSTANCE_ID
        root.mkdir(parents=True, exist_ok=True)
        if len(commands) == 1:
            (root / "predictions.jsonl").write_text(_prediction(), encoding="utf-8")
            official = root / "official-dataset"
            inspect = root / "inspect-dataset"
            official.mkdir()
            inspect.mkdir()
            (official / "test.jsonl").write_text("{}\n", encoding="utf-8")
            (inspect / "test.jsonl").write_text("{}\n", encoding="utf-8")
            (root / "transformation-manifest.json").write_text("{}\n", encoding="utf-8")
        else:
            (root / f"kimi-k2.7-code.{run_id}.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "resolved_ids": [],
                        "unresolved_ids": [],
                        "empty_patch_ids": [],
                        "error_ids": [_INSTANCE_ID],
                    },
                ),
                encoding="utf-8",
            )
        return SwebenchCliResult(0, "", "", 0.1, argv)

    execute_control_plane_run(
        plan=_plan(slice_id="swe-bench-verified-diagnostic-1"),
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=artifacts,
        run_id=run_id,
        swebench_process_runner=runner,
    )
    rows = read_evidence_jsonl(tmp_path / "evidence.jsonl")

    assert len(commands) == 2
    assert len(rows) == 1
    assert rows[0].failure_class == "runtime_output_unparseable"
    assert any(path.endswith("predictions.jsonl") for path in rows[0].artifact_paths)
    assert any(path.endswith(f"kimi-k2.7-code.{run_id}.json") for path in rows[0].artifact_paths)
    assert any(path.endswith("official-dataset/test.jsonl") for path in rows[0].artifact_paths)
    assert any(path.endswith("inspect-dataset/test.jsonl") for path in rows[0].artifact_paths)
    assert any(path.endswith("transformation-manifest.json") for path in rows[0].artifact_paths)


def test_inspect_generation_is_isolated_from_official_swebench_5() -> None:
    inspect_cmd = build_swebench_run_command(
        plan=_plan(),
        instance_id=_INSTANCE_ID,
        artifacts_dir=Path("run-owned").resolve(),
    )
    argv = resolve_swebench_subprocess(inspect_cmd)
    separator = argv.index("--")
    prefix = argv[:separator]
    launched = argv[separator + 1 :]

    assert prefix[:3] == ("uv", "run", "--isolated")
    assert prefix[prefix.index("--extra") + 1] == "eval"
    assert prefix[prefix.index("--with") + 1] == "swebench==4.1.0"
    assert launched == inspect_cmd
    assert "5.0.1" not in argv
    assert launched[0] == "inspect"


def test_official_eval_stays_isolated_swebench_5(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports"
    dataset_path = report_dir / "eval-input"
    dataset_path.mkdir(parents=True)
    (dataset_path / "test.jsonl").write_text("{}\n", encoding="utf-8")
    eval_cmd = build_swebench_eval_command(
        instance_id=_INSTANCE_ID,
        predictions_path=Path("predictions.jsonl"),
        run_id="swe-isolated-eval",
        report_dir=report_dir,
        dataset_path=dataset_path,
    )
    argv = resolve_swebench_subprocess(eval_cmd)
    separator = argv.index("--")

    assert argv[:3] == ("uv", "run", "--isolated")
    assert "--locked" in argv
    assert argv[argv.index("--project") + 1] == str(Path.cwd())
    assert argv[argv.index("--only-group") + 1] == "swe"
    assert "--group" not in argv
    assert argv[separator + 1 :] == eval_cmd
    assert eval_cmd[:2] == ("swebench", "eval")
    assert eval_cmd[2] == str(dataset_path.resolve())
    assert "verified" not in eval_cmd
    assert "SWE-bench/SWE-bench_Verified" not in eval_cmd


@pytest.mark.parametrize(
    "alias",
    ["verified", "lite", "SWE-bench/SWE-bench_Verified", "princeton-nlp/SWE-bench_Verified"],
)
def test_official_eval_rejects_hub_dataset_aliases(alias: str) -> None:
    with pytest.raises(BenchEvalError, match=r"eval-input|Hub alias|official"):
        build_swebench_eval_command(
            instance_id=_INSTANCE_ID,
            predictions_path=Path("predictions.jsonl"),
            run_id="swe-alias-reject",
            report_dir=Path("reports"),
            dataset_path=Path(alias),
        )


def test_official_eval_rejects_an_external_dataset_path(tmp_path: Path) -> None:
    report_dir = tmp_path / "run-owned"
    report_dir.mkdir()
    with pytest.raises(BenchEvalError, match="eval-input"):
        build_swebench_eval_command(
            instance_id=_INSTANCE_ID,
            predictions_path=report_dir / "predictions.jsonl",
            run_id="swe-external-dataset",
            report_dir=report_dir,
            dataset_path=tmp_path / "outside-dataset",
        )
