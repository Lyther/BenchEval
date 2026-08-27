"""Peer ship-hygiene regressions for product-spine closeout."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.external_agent_adapter import __all__ as external_agent_all

REPO = Path(__file__).resolve().parents[2]


def _require_git_checkout() -> None:
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        pytest.skip("gitignore contracts require a git checkout")


def test_pilot_matrix_defaults_to_registry_model() -> None:
    text = (REPO / "scripts" / "run-live-pilot-matrix.sh").read_text(encoding="utf-8")
    assert "BENCHEVAL_PILOT_MODEL:-kimi-k2.7-code" in text
    assert "default: kimi-k2.7-code" in text
    assert "config/models.yaml" in text


def test_swe_rebench_orphan_slice_removed() -> None:
    assert not (REPO / "config" / "slices" / "swe-rebench-smoke-10.yaml").exists()
    assert not (REPO / "config" / "manifests" / "swe-rebench-smoke-10.txt").exists()


def test_harbor_agent_runtime_mapping_removed() -> None:
    text = (REPO / "src" / "bencheval" / "terminal_bench_harbor.py").read_text(encoding="utf-8")
    assert '"harbor-agent"' not in text


def test_bfcl_smoke_is_adapter_smoke_not_native_claim() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    assert plan.comparison_validity == "adapter_smoke"
    assert "benchmark_native_claim" not in plan.comparison_validity


def test_product_yaml_has_no_utf8_bom() -> None:
    roots = [
        REPO / "config" / "benchmarks.yaml",
        REPO / "config" / "models.yaml",
        REPO / "config" / "agents",
        REPO / "config" / "providers",
        REPO / "config" / "runtimes",
        REPO / "config" / "slices",
    ]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.glob("*.yaml")))
            files.extend(sorted(root.glob("*.yml")))
    assert files
    for path in files:
        assert not path.read_bytes().startswith(b"\xef\xbb\xbf"), path


def test_roadmap_separates_current_from_historical_ledger() -> None:
    text = (REPO / "docs" / "roadmap.md").read_text(encoding="utf-8")
    assert "## Current roadmap" in text
    assert "## Historical ledger (do not execute)" in text
    current, _, _historical = text.partition("## Historical ledger (do not execute)")
    assert "inspect-api" not in current
    assert "harbor-agent" not in current
    assert "planner.py" not in current
    assert "run --config" not in current


def test_pending_adapter_justification_records_closed_catalog_only_decision() -> None:
    text = (
        REPO / "tests" / "specs" / "test_pending_adapter_pre_admission_integrity_contracts.py"
    ).read_text(encoding="utf-8")
    assert "intended admission surfaces" not in text
    assert "until the dual-use product boundary is decided" not in text
    assert "catalog-only" in text
    assert "v1 product decision" in text
    assert "post-v1 product decision" in text


def test_docs_mark_append_validation_and_pending_anchored_writes_complete() -> None:
    readme = (REPO / "results" / "manifests" / "README.md").read_text(encoding="utf-8")
    assert "Roadmap R2 will enforce" not in readme
    assert "append_live_run" in readme
    assert "last-event operational view" in readme or "last-valid-event" in readme

    architecture = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "does not yet enforce lifecycle consistency" not in architecture
    assert "may still be completed so dormant code" not in architecture
    assert "append-time" in architecture
    assert "last-valid-event operational-view" in architecture

    roadmap = (REPO / "docs" / "roadmap.md").read_text(encoding="utf-8")
    current, _, _historical = roadmap.partition("## Historical ledger (do not execute)")
    r2 = current.split("### R2", maxsplit=1)[1].split("### R3", maxsplit=1)[0]
    r4 = current.split("### R4", maxsplit=1)[1].split("### R5", maxsplit=1)[0]
    assert "- [x]" in r2 and "append-time" in r2
    assert "- [x]" in r2 and "last-valid-event" in r2
    assert "- [x]" in r4 and "anchored" in r4


def test_architecture_swe_lifecycle_does_not_claim_local_verdict_authority() -> None:
    architecture = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
    section = architecture.split("### 18.1", maxsplit=1)[1].split("### 18.2", maxsplit=1)[0]
    assert "trusts local `verifier.json`" not in section
    assert "`report.json" in section


def test_architecture_has_no_deleted_workspace_staging() -> None:
    text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
    assert "workspace_staging.py" not in text


def test_external_catalog_is_research_only_without_dead_cli() -> None:
    text = (REPO / "docs" / "context" / "external-benchmark-catalog.md").read_text(encoding="utf-8")
    assert "Research only" in text or "research only" in text
    assert "8** executables" not in text
    assert "cybergym`, `exploitgym`). Rows below" not in text
    assert "4** Tier-0 executable" in text
    assert "`swe-bench-pro`, `cybergym`, and `exploitgym` remain" in text
    assert "doctor --backend inspect" not in text
    assert "harbor_adapter.py" not in text
    assert "run --manifest" not in text


def test_concept_hld_marks_obsolete_cli_historical() -> None:
    text = (REPO / "docs" / "context" / "concept-hld.md").read_text(encoding="utf-8")
    assert "Historical command blocks (do not execute)" in text
    assert "bencheval run bfcl-v4/smoke-5" in text
    header = text.split("---", 1)[0]
    assert "Tier-0 executables:" in header
    assert "terminal-bench" in header
    assert "exploitgym" in header
    assert "remain pending" in header
    assert "gpqa-diamond" in header
    assert "hle" in header
    live, _, _hist = text.partition("### 8.H Historical command blocks")
    assert "doctor --runtime" not in live
    assert "bencheval doctor --model" in live


def test_architecture_points_operators_to_readme_not_hld() -> None:
    text = (REPO / "docs" / "architecture.md").read_text(encoding="utf-8")
    header = text.split("## 0.", 1)[0]
    assert "Operator contract / product SoT" in header
    assert "historical design ledger" in header.lower()
    assert "Source of truth for product:** [`docs/context/concept-hld.md`]" not in header


def test_deployment_diagram_has_no_removed_plan_command() -> None:
    text = (REPO / "docs" / "diagrams" / "deployment.md").read_text(encoding="utf-8")
    assert "bencheval plan" not in text
    assert "run --dry-run" in text


def test_solver_stall_issue_brief_is_superseded() -> None:
    text = (REPO / "docs" / "issues" / "solver-stall-and-attribution.md").read_text(
        encoding="utf-8"
    )
    header = text.split("## Summary", 1)[0]
    assert "**Status:** SUPERSEDED" in header
    assert "removed" in header.lower()
    assert "product-spine prune" in header.lower()


def test_runtime_profile_docstring_has_no_inspect_api() -> None:
    text = (REPO / "src" / "bencheval" / "domain.py").read_text(encoding="utf-8")
    assert "inspect-api" not in text


def test_external_agent_public_api_has_no_momo_aliases() -> None:
    momo_names = {
        "MOMO_ADAPTER_ID",
        "MomoCliResult",
        "MomoInstanceOutcome",
        "MomoProcessRunner",
        "MomoRunSummary",
        "build_momo_run_command",
        "execute_momo_agent_run",
        "run_momo_instance",
    }
    assert momo_names.isdisjoint(set(external_agent_all))


def test_review_and_readiness_residue_is_gitignored() -> None:
    _require_git_checkout()
    probe = subprocess.run(
        [
            "git",
            "check-ignore",
            "-v",
            ".agent-surface/readiness/example/readiness.json",
            ".review_state_r2.md",
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0
    assert ".agent-surface/" in probe.stdout
    assert ".review_state*.md" in probe.stdout


def test_private_proof_staging_is_gitignored() -> None:
    _require_git_checkout()
    probe = subprocess.run(
        ["git", "check-ignore", "-v", "results/proofs-staging/example/proof.json"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0
    assert "results/proofs-staging/" in probe.stdout
    status = subprocess.run(
        ["git", "status", "--untracked-files=all", "--porcelain"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    assert not any("proofs-staging" in line for line in status.stdout.splitlines())


def test_private_proof_store_is_gitignored() -> None:
    _require_git_checkout()
    probe = subprocess.run(
        ["git", "check-ignore", "-v", "results/proofs/example/private.json"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0
    assert "results/proofs/*" in probe.stdout
