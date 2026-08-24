from __future__ import annotations

from pathlib import Path

from bencheval.adapter_admission import (
    assert_bfcl_v4_admitted,
    assert_swebench_verified_admitted,
    assert_terminal_bench_harbor_admitted,
    assess_bfcl_v4_admission,
    assess_cybergym_admission,
    assess_exploitgym_admission,
    assess_gpqa_admission,
    assess_hle_admission,
    assess_swebench_pro_admission,
    assess_swebench_verified_admission,
    assess_terminal_bench_harbor_admission,
)
from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import load_benchmark_catalog


def test_terminal_bench_harbor_admission_passes() -> None:
    report = assess_terminal_bench_harbor_admission()
    assert report.passed is True
    assert_terminal_bench_harbor_admitted()
    status_row = next(c for c in report.checks if c[0] == "catalog_adapter_status")
    assert status_row[1] is True


def test_terminal_bench_catalog_manifest_available() -> None:
    catalog = load_benchmark_catalog()
    entry = next(b for b in catalog.benchmarks if b.id == "terminal-bench")
    assert entry.adapter_status == "manifest_available"


def test_plan_omits_adapter_status_caveat_when_admitted() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    assert not any(c.startswith("adapter_status:") for c in plan.caveats)


def test_admission_fails_without_adapter_files(tmp_path: Path) -> None:
    report = assess_terminal_bench_harbor_admission(repo_root=tmp_path)
    assert report.passed is False
    by_name = {name: ok for name, ok, _ in report.checks}
    assert by_name.get("typed_slice_smoke_5") is True
    assert by_name.get("harbor_adapter_module") is False
    assert by_name.get("control_plane_executor") is False


def test_bfcl_v4_admission_passes_after_live_qualification() -> None:
    # Round-1 F008 contract, inverted: the wired generate+evaluate lifecycle
    # ran live on the dev-box (diagnostic-labeled demonstration
    # run-20260824-040631-228703-4756f857, then registered `passed` run
    # run-20260824-045622-854659-a46ae44d), so
    # the Tier-0 wiring gate must report passed. Demoted fail-closed coverage
    # stays with swe-bench-verified below.
    report = assess_bfcl_v4_admission()
    assert report.passed is True
    assert_bfcl_v4_admitted()
    by_name = {name: ok for name, ok, _ in report.checks}
    assert by_name.get("catalog_adapter_status") is True
    assert by_name.get("catalog_executable") is True
    assert by_name.get("typed_slice_smoke_5") is True
    assert by_name.get("bfcl_adapter_module") is True


def test_swebench_verified_admission_fails_closed_while_demoted() -> None:
    import pytest

    from bencheval.exceptions import BenchEvalError

    report = assess_swebench_verified_admission()
    assert report.passed is False
    with pytest.raises(BenchEvalError, match="swe-bench-verified admission failed"):
        assert_swebench_verified_admitted()
    by_name = {name: ok for name, ok, _ in report.checks}
    assert by_name.get("catalog_adapter_status") is True
    assert by_name.get("catalog_executable") is False
    assert by_name.get("typed_slice_smoke_10") is True
    assert by_name.get("swebench_adapter_module") is True


def test_new_adapter_admissions_pass() -> None:
    swe_pro = assess_swebench_pro_admission()
    assert swe_pro.passed is False
    assert {name: ok for name, ok, _ in swe_pro.checks}.get("catalog_executable") is False
    assert assess_gpqa_admission().passed is True
    assert assess_hle_admission().passed is True
    cybergym = assess_cybergym_admission()
    assert cybergym.passed is False
    by_name = {name: ok for name, ok, _ in cybergym.checks}
    assert by_name.get("catalog_executable") is False
    assert by_name.get("catalog_adapter_status") is False
    exploit = assess_exploitgym_admission()
    assert exploit.passed is False
    assert {name: ok for name, ok, _ in exploit.checks}.get("catalog_executable") is False
