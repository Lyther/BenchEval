"""Production v1 CLI: execution_support filter, unknown-id gate, export-run."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_registry import execution_support_label, load_benchmark_catalog
from bencheval.cli import main
from tests.factories import make_control_plane_evidence_record as _cp_record

# SUBSTITUTE_JUSTIFICATION
# - substitute: monkeypatched execute_control_plane_run and temporary cwd/environment in
#   test_control_plane_run_defaults_output_under_results
# - replaces: charged GPQA execution while retaining real CLI planning/path selection
# - necessity: a non-dry CLI run must reach output rendering without a charged provider call
# - real-option: real GPQA CLI smoke on the provisioned dev-box
# - proof-limit: proves CLI default-path behavior only, not adapter execution
# - real-proof: BLOCKED until a live GPQA pilot retains evidence and Inspect logs


def test_benchmark_list_executable_filter_matches_catalog_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        ["benchmark", "list", "--execution-support", "executable_adapter", "--format", "json"],
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    catalog = load_benchmark_catalog()
    expected = {
        b.id for b in catalog.benchmarks if execution_support_label(b) == "executable_adapter"
    }
    assert {b["id"] for b in payload["benchmarks"]} == expected
    for b in payload["benchmarks"]:
        assert b["execution_support"] == "executable_adapter"


def test_executable_benchmark_count_snapshot() -> None:
    catalog = load_benchmark_catalog()
    executable = [
        b for b in catalog.benchmarks if execution_support_label(b) == "executable_adapter"
    ]
    assert len(executable) == 4
    for b in executable:
        assert b.adapter_id
        assert b.default_slice


def test_benchmark_list_defaults_to_executable(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["benchmark", "list", "--format", "json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 4


def test_run_bfcl_admitted_executable_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    # BFCL is admitted (executable: true) after the qualified live lifecycle, so
    # a plain dry-run builds the plan instead of refusing.
    code = main(["run", "bfcl-v4/smoke-5", "--model", "kimi-k2.7-code", "--dry-run"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["benchmark_id"] == "bfcl-v4"
    assert payload["diagnostic"] is False


def test_run_terminal_bench_without_runtime_errors(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run", "terminal-bench/smoke-5", "--model", "kimi-k2.7-code", "--dry-run"])
    assert code == 1
    err = capsys.readouterr().err
    assert "--runtime is required" in err


def test_run_rejects_runtime_and_agent_together(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "run",
            "bfcl-v4/smoke-5",
            "--model",
            "m",
            "--runtime",
            "claude-code",
            "--agent",
            "momo",
            "--dry-run",
        ],
    )
    assert code == 1
    assert "mutually exclusive" in capsys.readouterr().err


def test_control_plane_run_defaults_output_under_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_execute(*, plan, output_path, artifacts_dir, run_id=None):
        from bencheval.control_plane_executor import ControlPlaneRunSummary

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("", encoding="utf-8")
        return ControlPlaneRunSummary(
            run_id=run_id or "run-test",
            instance_count=1,
            passed_count=1,
            failed_count=0,
            output_path=output_path,
        )

    monkeypatch.setattr(
        "bencheval.cli.execute_control_plane_run",
        fake_execute,
    )
    monkeypatch.setenv("BENCHEVAL_HOME", str(Path(__file__).resolve().parents[1]))
    monkeypatch.chdir(tmp_path)
    code = main(["run", "gpqa-diamond/smoke", "--model", "kimi-k2.7-code", "-y"])
    assert code == 0
    out_text = capsys.readouterr().out
    assert "results/evidence" in out_text.replace("\\", "/")


def test_unknown_benchmark_run_fails_before_execute(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "run",
            "no-such-benchmark/smoke-5",
            "--runtime",
            "claude-code",
            "--model",
            "kimi-k2.7-code",
            "--dry-run",
        ],
    )
    assert code == 1
    assert "benchmark not found" in capsys.readouterr().err.lower()


def test_cybench_absent_from_product_catalog() -> None:
    catalog = load_benchmark_catalog()
    ids = {b.id for b in catalog.benchmarks}
    assert "cybench" not in ids


def test_export_run_smoke(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    evidence = tmp_path / "e.jsonl"
    rows = [
        _cp_record(instance_id="tb-001", runtime_id="claude-code", primary_pass=True),
        _cp_record(instance_id="tb-002", runtime_id="claude-code", primary_pass=False),
    ]
    evidence.write_text(
        "\n".join(r.model_dump_json() for r in rows) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "bundle"
    code = main(
        [
            "export-run",
            "--evidence",
            str(evidence),
            "--output",
            str(out),
            "--redaction",
            "private",
        ],
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["archive"]).is_file()
