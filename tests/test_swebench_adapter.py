"""SWE-bench adapter unit tests (parse/build; diagnostic evaluate, catalog demoted).

SUBSTITUTE_JUSTIFICATION
- substitute: injected Inspect/swebench runner and disposable leftover
  report.json or workspace.diff in test_run_instance_single,
  test_run_instance_clears_stale_official_report, and
  test_run_instance_clears_stale_workspace_diff
- replaces: charged Inspect generation and official SWE-Bench evaluation
- necessity: leftover-artifact and local parse cases must be forced without a
  Docker evaluator; the official path cannot safely produce stale artifacts
- real-option: official generation plus evaluation must be implemented first
- proof-limit: diagnostic parser/wrapper coverage only; cannot qualify SWE-Bench
- real-proof: charged diagnostic sha256:5f7f79ce…373e52; this module stays parser-only
- covered tests: test_run_instance_single,
  test_official_empty_patch_is_a_valid_model_failure,
  test_official_empty_patch_uses_slash_sanitized_summary_name,
  test_run_instance_clears_stale_official_report,
  test_run_instance_clears_stale_workspace_diff
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.exceptions import BenchEvalError
from bencheval.swebench_adapter import (
    SWEBENCH_ADAPTER_ID,
    SwebenchCliResult,
    _inspect_compat_row,
    build_swebench_run_command,
    materialize_swebench_diagnostic_inputs,
    parse_swebench_instance_outcome,
    run_swebench_instance,
)


def _plant_official_dataset(instance_dir: Path) -> None:
    official = instance_dir / "official-dataset"
    official.mkdir(exist_ok=True)
    (official / "test.jsonl").write_text("{}\n", encoding="utf-8")


def _schema_v2(instance_id: str, *, resolved: bool) -> str:
    return json.dumps(
        {
            "schema_version": 2,
            "resolved_ids": [instance_id] if resolved else [],
            "unresolved_ids": [] if resolved else [instance_id],
            "empty_patch_ids": [],
            "error_ids": [],
            "infra_failure_ids": [],
            "ambiguous_failure_ids": [],
        },
    )


def test_build_swebench_run_command() -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )
    cmd = build_swebench_run_command(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=Path("/tmp/out"),
    )
    assert cmd[:3] == ("inspect", "eval", "inspect_evals/swe_bench")
    assert cmd[cmd.index("--sample-id") + 1] == "django__django-11099"
    assert cmd[cmd.index("--solver") + 1] == "inspect_swe/codex_cli"
    assert cmd[cmd.index("-S") + 1] == "version=0.148.0"
    assert plan.model_binding == "runtime_configured"


def test_parse_official_report_and_diff(tmp_path: Path) -> None:
    art = tmp_path / "inst"
    art.mkdir()
    report = art / "report.json"
    report.write_text(
        json.dumps(
            {
                "django__django-11099": {
                    "resolved": True,
                    "tests_passed": True,
                    "cost_usd": 0.25,
                },
            },
        ),
        encoding="utf-8",
    )
    (art / "workspace.diff").write_text("diff --git a/foo b/foo\n", encoding="utf-8")
    cli = SwebenchCliResult(0, "ok", "", 1.0, ("claude-code", "run"))
    out = parse_swebench_instance_outcome(
        instance_id="django__django-11099",
        cli=cli,
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="swebench-test",
    )
    assert out.primary_pass is True
    assert out.workspace_diff_path is not None
    assert out.verifier_log_path == str(report.relative_to(tmp_path))
    assert out.native_score.get("resolved") is True


def test_execute_swebench_refuses_until_evaluate_wired(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )
    assert plan.adapter_id == SWEBENCH_ADAPTER_ID
    with pytest.raises(BenchEvalError, match="executable_adapter"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "evidence.jsonl",
            artifacts_dir=tmp_path / "artifacts",
            run_id="test-run-swe",
        )


def test_run_instance_single(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )

    def fake_runner(command, *, cwd, timeout_sec):
        argv = tuple(str(part) for part in command)
        instance_dir = tmp_path / "a" / "django__django-11099"
        instance_dir.mkdir(parents=True, exist_ok=True)
        if argv[:2] == ("inspect", "eval"):
            (instance_dir / "predictions.jsonl").write_text(
                json.dumps(
                    {
                        "instance_id": "django__django-11099",
                        "model_name_or_path": "kimi-k2.7-code",
                        "model_patch": "diff --git a/a b/a\n",
                    },
                )
                + "\n",
                encoding="utf-8",
            )
            _plant_official_dataset(instance_dir)
        if argv[:2] == ("swebench", "eval"):
            run_id = argv[argv.index("--run-id") + 1]
            (instance_dir / "report.json").write_text(
                json.dumps({"django__django-11099": {"resolved": False}}),
                encoding="utf-8",
            )
            (instance_dir / f"kimi-k2.7-code.{run_id}.json").write_text(
                _schema_v2("django__django-11099", resolved=False),
                encoding="utf-8",
            )
        return SwebenchCliResult(0, "", "", 0.1, argv)

    out = run_swebench_instance(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=fake_runner,
    )
    assert out.primary_pass is False
    assert out.failure_class == "model_wrong_solution"


def test_official_empty_patch_is_a_valid_model_failure(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )

    def fake_runner(command, *, cwd, timeout_sec):
        argv = tuple(str(part) for part in command)
        instance_dir = tmp_path / "a" / "django__django-11099"
        instance_dir.mkdir(parents=True, exist_ok=True)
        if argv[:2] == ("inspect", "eval"):
            (instance_dir / "predictions.jsonl").write_text(
                json.dumps(
                    {
                        "instance_id": "django__django-11099",
                        "model_name_or_path": "eval-model-name",
                        "model_patch": "",
                    },
                )
                + "\n",
                encoding="utf-8",
            )
            _plant_official_dataset(instance_dir)
        if argv[:2] == ("swebench", "eval"):
            (instance_dir / "eval-model-name.swe-empty.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "resolved_ids": [],
                        "unresolved_ids": [],
                        "empty_patch_ids": ["django__django-11099"],
                        "error_ids": [],
                        "infra_failure_ids": [],
                        "ambiguous_failure_ids": [],
                    },
                ),
                encoding="utf-8",
            )
        return SwebenchCliResult(0, "", "", 0.1, argv)

    out = run_swebench_instance(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=fake_runner,
        run_id="swe-empty",
    )
    assert out.primary_pass is False
    assert out.failure_class == "model_wrong_solution"
    assert out.native_score.get("empty_patch") is True


def test_official_empty_patch_uses_slash_sanitized_summary_name(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )

    def fake_runner(command, *, cwd, timeout_sec):
        argv = tuple(str(part) for part in command)
        instance_dir = tmp_path / "a" / "django__django-11099"
        instance_dir.mkdir(parents=True, exist_ok=True)
        if argv[:2] == ("inspect", "eval"):
            (instance_dir / "predictions.jsonl").write_text(
                json.dumps(
                    {
                        "instance_id": "django__django-11099",
                        "model_name_or_path": "org/eval-model",
                        "model_patch": "",
                    },
                )
                + "\n",
                encoding="utf-8",
            )
            _plant_official_dataset(instance_dir)
        if argv[:2] == ("swebench", "eval"):
            (instance_dir / "org__eval-model.swe-slash.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "resolved_ids": [],
                        "unresolved_ids": [],
                        "empty_patch_ids": ["django__django-11099"],
                        "error_ids": [],
                        "infra_failure_ids": [],
                        "ambiguous_failure_ids": [],
                    },
                ),
                encoding="utf-8",
            )
        return SwebenchCliResult(0, "", "", 0.1, argv)

    out = run_swebench_instance(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=fake_runner,
        run_id="swe-slash",
    )
    assert out.failure_class == "model_wrong_solution"
    assert out.native_score.get("empty_patch") is True


def test_run_instance_clears_stale_official_report(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )
    instance_dir = tmp_path / "a" / "django__django-11099"
    instance_dir.mkdir(parents=True)
    (instance_dir / "report.json").write_text(
        json.dumps({"django__django-11099": {"resolved": True}}),
        encoding="utf-8",
    )

    calls: list[tuple[str, ...]] = []

    def fake_runner(command, *, cwd, timeout_sec):
        calls.append(tuple(str(part) for part in command))
        return SwebenchCliResult(0, "", "", 0.1, tuple(command))

    out = run_swebench_instance(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=fake_runner,
    )
    assert out.primary_pass is False
    assert out.failure_class == "runtime_output_unparseable"
    assert calls and calls[0][:2] == ("inspect", "eval")
    assert all(call[:2] != ("swebench", "eval") for call in calls)


def test_run_instance_clears_stale_workspace_diff(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )
    instance_dir = tmp_path / "a" / "django__django-11099"
    call_count = 0

    def fake_runner(command, *, cwd, timeout_sec):
        nonlocal call_count
        call_count += 1
        argv = tuple(str(part) for part in command)
        instance_dir = tmp_path / "a" / "django__django-11099"
        instance_dir.mkdir(parents=True, exist_ok=True)
        if argv[:2] == ("inspect", "eval"):
            (instance_dir / "predictions.jsonl").write_text(
                json.dumps(
                    {
                        "instance_id": "django__django-11099",
                        "model_name_or_path": "kimi-k2.7-code",
                        "model_patch": "diff --git a/a b/a\n",
                    },
                )
                + "\n",
                encoding="utf-8",
            )
            _plant_official_dataset(instance_dir)
        if argv[:2] == ("swebench", "eval"):
            run_id = argv[argv.index("--run-id") + 1]
            (instance_dir / "report.json").write_text(
                json.dumps({"django__django-11099": {"resolved": False}}),
                encoding="utf-8",
            )
            (instance_dir / f"kimi-k2.7-code.{run_id}.json").write_text(
                _schema_v2("django__django-11099", resolved=False),
                encoding="utf-8",
            )
        if call_count == 2:
            (instance_dir / "workspace.diff").write_text(
                "STALE-FIRST-RUN",
                encoding="utf-8",
            )
        return SwebenchCliResult(0, "", "", 0.1, argv)

    first = run_swebench_instance(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=fake_runner,
    )
    second = run_swebench_instance(
        plan=plan,
        instance_id="django__django-11099",
        artifacts_dir=tmp_path / "a",
        repo_root=tmp_path,
        process_runner=fake_runner,
    )

    assert first.workspace_diff_path is not None
    assert second.workspace_diff_path is None
    assert not (instance_dir / "workspace.diff").exists()


def test_parse_missing_official_report_on_success_rc_fails(tmp_path: Path) -> None:
    art = tmp_path / "empty"
    art.mkdir()
    cli = SwebenchCliResult(0, "", "", 0.1, ("claude-code",))
    out = parse_swebench_instance_outcome(
        instance_id="x",
        cli=cli,
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="v",
    )
    assert out.primary_pass is False
    assert out.failure_class == "runtime_output_unparseable"


def test_inspect_compat_row_encodes_list_fields_as_canonical_json() -> None:
    row = {
        "instance_id": "django__django-11099",
        "PASS_TO_PASS": ["z", "a"],
        "FAIL_TO_PASS": '["b"]',
    }

    converted = _inspect_compat_row(row)

    assert converted["PASS_TO_PASS"] == '["z","a"]'
    assert converted["FAIL_TO_PASS"] == '["b"]'


def test_hub_symlink_through_home_alias_stays_inside_cache(tmp_path: Path) -> None:
    from bencheval.swebench_adapter import _path_is_under

    real = tmp_path / "data00" / "hub"
    alias = tmp_path / "home" / "hub"
    alias.parent.mkdir(parents=True)
    real.mkdir(parents=True)
    alias.symlink_to(real)
    blob = real / "blobs" / "x"
    blob.parent.mkdir()
    blob.write_bytes(b"x")
    link = alias / "snapshots" / "rev" / "data" / "file.parquet"
    link.parent.mkdir(parents=True)
    link.symlink_to(blob)

    assert _path_is_under(link.resolve(), alias)


def test_materialize_rejects_parquet_bytes_that_do_not_match_the_pin(tmp_path: Path) -> None:
    planted = tmp_path / "data" / "test-00000-of-00001.parquet"
    planted.parent.mkdir(parents=True)
    planted.write_bytes(b"not-the-official-parquet")

    with pytest.raises(BenchEvalError, match="sha256 drift"):
        materialize_swebench_diagnostic_inputs(
            instance_dir=tmp_path / "inst",
            instance_id="django__django-11099",
            source_parquet=planted,
            bind_image=False,
        )
