"""Production v1 CLI: execution_support filter, cybench execute gate, export-run."""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest

from bencheval import cli
from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import execution_support_label, load_benchmark_catalog
from bencheval.cli import main
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import JsonlEvidenceSink
from bencheval.exceptions import BenchEvalError
from bencheval.runtime_compare import compare_runtime_evidence, render_runtime_comparison_markdown
from tests.factories import make_control_plane_evidence_record as _cp_record


def test_benchmark_list_executable_filter_matches_catalog_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The executable set is a config contract: exactly the catalog entries whose
    ``execution_support`` resolves to ``executable_adapter`` (F001/F005) — not a
    literal ID list. Adding an executable benchmark in config alone updates this."""
    code = main(
        ["benchmark", "list", "--execution-support", "executable_adapter", "--format", "json"],
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    ids = {b["id"] for b in payload["benchmarks"]}
    catalog = load_benchmark_catalog()
    expected = {
        b.id for b in catalog.benchmarks if execution_support_label(b) == "executable_adapter"
    }
    assert ids == expected
    for b in payload["benchmarks"]:
        assert b["execution_support"] == "executable_adapter"


def test_executable_benchmark_count_snapshot() -> None:
    """Honesty snapshot of today's executable count. Bump deliberately when a real
    adapter is admitted; guards against silently flipping benchmarks executable."""
    catalog = load_benchmark_catalog()
    executable = [
        b for b in catalog.benchmarks if execution_support_label(b) == "executable_adapter"
    ]
    assert len(executable) == 3
    # Every executable entry must carry a config-declared adapter binding (contract).
    for b in executable:
        assert b.adapter_id is not None
        assert b.harness_kind is not None


def test_run_positional_target_equals_benchmark_slice_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F002: `run <benchmark>/<slice> --dry-run` matches the verbose flag form."""
    code = main(
        ["run", "bfcl-v4/smoke-5", "--runtime", "native-api", "--model", "m", "--dry-run"],
    )
    assert code == 0
    short = json.loads(capsys.readouterr().out)

    code = main(
        [
            "run",
            "--benchmark",
            "bfcl-v4",
            "--slice",
            "smoke-5",
            "--runtime",
            "native-api",
            "--model",
            "m",
            "--dry-run",
        ],
    )
    assert code == 0
    verbose = json.loads(capsys.readouterr().out)
    assert short["benchmark_id"] == verbose["benchmark_id"] == "bfcl-v4"
    assert short["slice_id"] == verbose["slice_id"] == "smoke-5"


def test_plan_alias_is_a_dry_run(capsys: pytest.CaptureFixture[str]) -> None:
    """F002: `plan <target>` is shorthand for `run --dry-run <target>`."""
    code = main(["plan", "bfcl-v4/smoke-5", "--runtime", "native-api", "--model", "m"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["benchmark_id"] == "bfcl-v4"
    assert payload["adapter_id"] == "bfcl"


def test_run_target_requires_benchmark_slice_form(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["plan", "bfcl-v4", "--runtime", "native-api", "--model", "m"])
    assert code == 2
    assert "target must be" in capsys.readouterr().err


def test_run_target_conflicts_with_explicit_flags(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "run",
            "bfcl-v4/smoke-5",
            "--benchmark",
            "bfcl-v4",
            "--runtime",
            "native-api",
            "--model",
            "m",
            "--dry-run",
        ],
    )
    assert code == 2
    assert "not both" in capsys.readouterr().err


def test_control_plane_run_defaults_output_under_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """F002: a control-plane run needs only the four axes; --output/--artifacts-dir
    default under results/ (explicit paths still win)."""
    captured: dict[str, object] = {}

    def fake_execute(*, plan, output_path, artifacts_dir, run_id=None):
        captured["output_path"] = output_path
        captured["artifacts_dir"] = artifacts_dir
        captured["run_id"] = run_id
        return types.SimpleNamespace(
            run_id=run_id,
            output_path=output_path,
            instance_count=1,
            passed_count=1,
            failed_count=0,
        )

    monkeypatch.setattr(cli, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "execute_control_plane_run", fake_execute)
    code = main(["run", "bfcl-v4/smoke-5", "--runtime", "native-api", "--model", "m"])
    assert code == 0
    output_path = Path(str(captured["output_path"]))
    assert output_path.parent == tmp_path / "results" / "evidence"
    assert output_path.suffix == ".jsonl"
    assert output_path.parent.is_dir()  # created ahead of the run
    assert captured["artifacts_dir"] is None  # executor defaults to results/raw/<run_id>


def test_cybench_run_cli_fails_before_execute(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    out = tmp_path / "nope.jsonl"
    code = main(
        [
            "run",
            "--benchmark",
            "cybench",
            "--slice",
            "cybench-smoke-5",
            "--runtime",
            "native-api",
            "--model",
            "openai/gpt-test",
            "--output",
            str(out),
        ],
    )
    assert code == 1
    assert "metadata_only" in capsys.readouterr().err
    assert not out.exists()


def test_cybench_dry_run_reports_execution_support(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "run",
            "--dry-run",
            "--benchmark",
            "cybench",
            "--slice",
            "cybench-smoke-5",
            "--runtime",
            "native-api",
            "--model",
            "openai/gpt-test",
        ],
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["slice_resolution"]["execution_support"] == "metadata_only"


def test_metadata_only_execute_rejected(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="swe-rebench",
        slice_id="swe-rebench-smoke-10",
        runtime_id="native-api",
        model_id="openai/gpt-test",
    )
    with pytest.raises(BenchEvalError, match="metadata_only"):
        execute_control_plane_run(
            plan=plan,
            output_path=tmp_path / "out.jsonl",
            artifacts_dir=tmp_path / "art",
        )


def test_runtime_compare_markdown_shows_invalid_excluded() -> None:
    baseline = [
        _cp_record(instance_id="tb-001", runtime_id="claude-code", primary_pass=True),
        _cp_record(
            instance_id="tb-002",
            runtime_id="claude-code",
            primary_pass=False,
            attempt_validity="invalid",
            counts_toward_pass_at_k=False,
        ),
    ]
    current = [
        _cp_record(instance_id="tb-001", runtime_id="codex-cli", primary_pass=True),
        _cp_record(instance_id="tb-002", runtime_id="codex-cli", primary_pass=True),
    ]
    report = compare_runtime_evidence(baseline, current)
    md = render_runtime_comparison_markdown(report)
    assert "Excluded (invalid)" in md
    assert report.baseline_invalid_excluded == 1


def test_export_run_public_redacts_adapter_metadata(tmp_path: Path) -> None:
    evidence = tmp_path / "ev.jsonl"
    row = _cp_record(instance_id="tb-001")
    row = row.model_copy(
        update={
            "adapter_metadata": {
                "command": "harbor run --api_key=sk-live-secretvalue",
            },
        },
    )
    JsonlEvidenceSink().append_jsonl(evidence, row)
    bundle_dir = tmp_path / "pub-bundle"
    assert (
        main(
            [
                "export-run",
                "--evidence",
                str(evidence),
                "--output",
                str(bundle_dir),
                "--redaction",
                "public",
            ],
        )
        == 0
    )
    text = (bundle_dir / "evidence.jsonl").read_text(encoding="utf-8")
    assert "sk-live-secretvalue" not in text
    assert "[redacted]" in text


def test_export_run_public_omits_raw_tree(tmp_path: Path) -> None:
    evidence = tmp_path / "ev.jsonl"
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "secret.log").write_text("api_key=leak", encoding="utf-8")
    JsonlEvidenceSink().append_jsonl(evidence, _cp_record(instance_id="tb-001"))
    bundle_dir = tmp_path / "pub"
    assert (
        main(
            [
                "export-run",
                "--evidence",
                str(evidence),
                "--raw-dir",
                str(raw),
                "--output",
                str(bundle_dir),
                "--redaction",
                "public",
            ],
        )
        == 0
    )
    assert not (bundle_dir / "raw").exists()
    assert "omitted" in (bundle_dir / "SUMMARY.md").read_text(encoding="utf-8")


def test_export_run_bundle(tmp_path: Path) -> None:
    evidence = tmp_path / "ev.jsonl"
    sink = JsonlEvidenceSink()
    sink.append_jsonl(evidence, _cp_record(instance_id="tb-001"))
    bundle_dir = tmp_path / "bundle"
    code = main(
        [
            "export-run",
            "--evidence",
            str(evidence),
            "--output",
            str(bundle_dir),
            "--redaction",
            "private",
        ],
    )
    assert code == 0
    assert (bundle_dir / "evidence.jsonl").is_file()
    assert (bundle_dir / "report.md").is_file()
    assert (bundle_dir / "manifest.json").is_file()
    assert (bundle_dir / "SHA256SUMS.txt").is_file()
    assert (tmp_path / "bundle.tar.gz").is_file()


def test_export_run_bundle_skips_unreadable_raw_file(tmp_path: Path) -> None:
    evidence = tmp_path / "ev.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, _cp_record(instance_id="tb-001"))
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "readable.txt").write_text("ok\n", encoding="utf-8")
    unreadable = raw / "unreadable.jsonl"
    unreadable.write_text("private session\n", encoding="utf-8")
    unreadable.chmod(0)
    try:
        try:
            unreadable.read_text(encoding="utf-8")
        except PermissionError:
            pass
        else:
            pytest.skip("chmod did not make raw fixture unreadable")

        bundle_dir = tmp_path / "bundle"
        code = main(
            [
                "export-run",
                "--evidence",
                str(evidence),
                "--raw-dir",
                str(raw),
                "--output",
                str(bundle_dir),
                "--redaction",
                "private",
            ],
        )
    finally:
        unreadable.chmod(0o600)

    assert code == 0
    assert (bundle_dir / "raw" / "readable.txt").read_text(encoding="utf-8") == "ok\n"
    skipped = (bundle_dir / "raw_skipped.txt").read_text(encoding="utf-8")
    assert "unreadable.jsonl" in skipped
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["raw_skipped_count"] == 1
