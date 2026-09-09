"""Contracts for the official BFCL Live diagnostic identity and plumbing slice.

SUBSTITUTE_JUSTIFICATION
- substitute: injected BFCL process runner in
  ``test_live_exact_id_runs_through_official_partial_eval_shape`` and
  ``test_live_exact_id_rejects_a_score_without_the_requested_result``
- replaces: charged ``bfcl generate`` and the official ``bfcl evaluate`` process
- necessity: the contract must inspect the run-owned id manifest and exact child
  environment before launch; a live provider call cannot expose that boundary
  deterministically without cost
- real-option: the official CLI on dev-box with provider credentials is the X2.3
  acceptance run after this fail-before-charge contract is implemented
- proof-limit: proves command, environment, manifest, score-discovery, and evidence
  wiring only; it does not prove provider or official evaluator behavior
- real-proof: roadmap X2.3 real six-id BFCL Live diagnostic
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import BfclPackageDataIdentity, load_benchmark_catalog
from bencheval.bfcl_native_adapter import (
    BfclCliResult,
    _parse_official_score,
    bfcl_pinned_harness_version,
    bfcl_supported_models,
    build_bfcl_evaluate_command,
    build_bfcl_run_command,
    run_bfcl_instance,
)
from bencheval.exceptions import AdapterFailureError
from bencheval.identity_strings import bfcl_benchmark_identity, combined_data_sha256
from bencheval.model_registry import load_model_registry
from bencheval.slice_manifest import load_slice_manifest

_LIVE_FILES = {
    "data/BFCL_v4_live_irrelevance.json": (
        "sha256:6559fda2beaceb609a2cd2e504c65b4a56cb448e1ef88fddfd199e163d163349"
    ),
    "data/BFCL_v4_live_multiple.json": (
        "sha256:fd8ccfad4d911420d0e3341dbe2fff77d1d341da934248b9bb2bda24ab3a10c8"
    ),
    "data/BFCL_v4_live_parallel.json": (
        "sha256:6c26e9fdc3350cf596e6d1ea9c179cbff834761bccf562f4141ed29a839ca421"
    ),
    "data/BFCL_v4_live_parallel_multiple.json": (
        "sha256:21d4b9319c1faac431e22757b367ea28917fe467364c3a4b17f16ec06d4f6e79"
    ),
    "data/BFCL_v4_live_relevance.json": (
        "sha256:e03f9e241657a137cba48a89ee12f47bf3fcb7e4f6274263e9c699a0c974203a"
    ),
    "data/BFCL_v4_live_simple.json": (
        "sha256:1af2ac87dca47556db7b7e37e51e28b459a38b594e3c7b3c792b4903598ca0c4"
    ),
    "data/possible_answer/BFCL_v4_live_multiple.json": (
        "sha256:97e90d59c5bd76c55a2920ce93e5566e9046307d3f558578f085f9d3a56c3084"
    ),
    "data/possible_answer/BFCL_v4_live_parallel.json": (
        "sha256:8a9f189ff0e832ebbbbdade1fd95a7dbcc67406e9177df3f0aad76f59ab00350"
    ),
    "data/possible_answer/BFCL_v4_live_parallel_multiple.json": (
        "sha256:f5b5f360556c5feb51db46fb9f56ee4b304f4b45b161599bbb14161c98a2873f"
    ),
    "data/possible_answer/BFCL_v4_live_simple.json": (
        "sha256:fec9cfa9744a936f9126981e85a2023da1e63e273eafebc81923a1162fad70ce"
    ),
}
_PLUMBING_IDS = {
    "live_simple_0-0-0",
    "live_multiple_0-0-0",
    "live_parallel_0-0-0",
    "live_parallel_multiple_0-0-0",
    "live_irrelevance_0-0-0",
    "live_relevance_0-0-0",
}


def test_live_catalog_identity_uses_exact_verified_wheel_bytes() -> None:
    catalog = load_benchmark_catalog()
    live = catalog.by_id_or_alias("bfcl-v4-live")

    assert live.adapter_id == "bfcl"
    assert live.executable is False
    assert live.default_slice == "plumbing-6"
    assert isinstance(live.identity, BfclPackageDataIdentity)
    assert live.identity.files == _LIVE_FILES
    assert len([row for row in catalog.benchmarks if row.executable]) == 4


def test_live_identity_is_distinct_from_admitted_bfcl() -> None:
    catalog = load_benchmark_catalog()
    canonical = catalog.by_id_or_alias("bfcl-v4")
    live = catalog.by_id_or_alias("bfcl-v4-live")
    assert isinstance(canonical.identity, BfclPackageDataIdentity)
    assert isinstance(live.identity, BfclPackageDataIdentity)

    canonical_version = bfcl_benchmark_identity(
        canonical.identity,
        benchmark_id=canonical.id,
    )
    live_version = bfcl_benchmark_identity(live.identity, benchmark_id=live.id)

    assert canonical_version.startswith("bfcl-v4@")
    assert live_version == (
        "bfcl-v4-live@bfcl-eval-2026.3.23+data-" + combined_data_sha256(_LIVE_FILES)[:16]
    )
    assert live_version.endswith("939b6ed93f816d9b")


def test_live_plumbing_slice_selects_one_real_id_per_category() -> None:
    manifest = load_slice_manifest("config/slices/bfcl-v4-live-plumbing-6.yaml")

    assert manifest.slice.benchmark_id == "bfcl-v4-live"
    assert manifest.slice.purpose == "adapter_smoke"
    assert set(manifest.slice.instances) == _PLUMBING_IDS
    assert manifest.budget.max_instances == 6


def test_canonical_exposure_plumbing_slice_is_the_exact_id_twin_of_live_plumbing() -> None:
    """`smoke-5` scores whole categories; the study needs one exact case per stratum."""
    from bencheval.exposure_study import load_exposure_study

    manifest = load_slice_manifest("config/slices/bfcl-v4-exposure-plumbing-5.yaml")
    study = load_exposure_study("bfcl-v4-live-vs-non-live")

    assert manifest.slice.benchmark_id == "bfcl-v4"
    assert manifest.slice.purpose == "adapter_smoke"
    assert set(manifest.slice.instances) == {
        f"{stratum}_0" for stratum in study.population.canonical_counts
    }
    assert study.canonical.smoke_slice_id == manifest.slice.id == "exposure-plumbing-5"
    assert study.candidate.smoke_slice_id == "plumbing-6"
    assert manifest.budget.max_instances == 5

    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="exposure-plumbing-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11-FC",
    )
    assert [i.instance_id for i in plan.instances] == list(manifest.slice.instances)
    generate = build_bfcl_run_command(
        plan=plan, instance_id="parallel_multiple_0", artifacts_dir=Path("results")
    )
    evaluate = build_bfcl_evaluate_command(
        plan=plan,
        instance_id="parallel_multiple_0",
        result_dir=Path("results"),
        score_dir=Path("scores"),
    )
    assert "--run-ids" in generate and "--test-category" not in generate
    assert evaluate[evaluate.index("--test-category") + 1] == "parallel_multiple"
    assert "--partial-eval" in evaluate


def test_fc_model_is_registered_for_meaningful_bfcl_headroom() -> None:
    model_id = "gpt-5.2-2025-12-11-FC"

    assert load_model_registry().by_id(model_id).provider_route == "bytellm"
    assert model_id in bfcl_supported_models()

    plan = plan_control_plane(
        benchmark_id="bfcl-v4-live",
        slice_id="plumbing-6",
        runtime_id=None,
        model_id=model_id,
        diagnostic=True,
    )
    assert plan.diagnostic is True
    assert plan.benchmark_version == "provisional:bfcl-v4-live/catalog"
    assert [row.instance_id for row in plan.instances] == list(
        load_slice_manifest("config/slices/bfcl-v4-live-plumbing-6.yaml").slice.instances
    )


def test_live_exact_id_uses_run_ids_and_partial_eval_command_shape(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4-live",
        slice_id="plumbing-6",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11-FC",
        diagnostic=True,
    )
    instance_id = "live_simple_0-0-0"

    generate = build_bfcl_run_command(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=tmp_path / "results",
    )
    evaluate = build_bfcl_evaluate_command(
        plan=plan,
        instance_id=instance_id,
        result_dir=tmp_path / "results",
        score_dir=tmp_path / "scores",
    )

    assert "--run-ids" in generate
    assert "--test-category" not in generate
    assert evaluate[evaluate.index("--test-category") + 1] == "live_simple"
    assert "--partial-eval" in evaluate


def test_live_exact_id_runs_through_official_partial_eval_shape(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4-live",
        slice_id="plumbing-6",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11-FC",
        diagnostic=True,
    )
    live = load_benchmark_catalog().by_id_or_alias("bfcl-v4-live")
    assert isinstance(live.identity, BfclPackageDataIdentity)
    seen: list[tuple[str, ...]] = []

    def runner(
        command: tuple[str, ...] | list[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: dict[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec
        command = tuple(command)
        seen.append(command)
        project = Path(env["BFCL_PROJECT_ROOT"])
        assert project.is_relative_to(tmp_path / "art" / "live_simple_0-0-0")
        assert json.loads((project / "test_case_ids_to_generate.json").read_text()) == {
            "live_simple": ["live_simple_0-0-0"]
        }
        if command[1] == "generate":
            result_root = Path(command[command.index("--result-dir") + 1])
            result = (
                result_root / "gpt-5.2-2025-12-11-FC" / "live" / "BFCL_v4_live_simple_result.json"
            )
            result.parent.mkdir(parents=True)
            result.write_text(
                json.dumps({"id": "live_simple_0-0-0", "result": [[]]}) + "\n",
                encoding="utf-8",
            )
        else:
            score_root = Path(command[command.index("--score-dir") + 1])
            score = score_root / "gpt-5.2-2025-12-11-FC" / "live" / "BFCL_v4_live_simple_score.json"
            score.parent.mkdir(parents=True)
            score.write_text(
                json.dumps({"accuracy": 1.0, "correct_count": 1, "total_count": 1}) + "\n",
                encoding="utf-8",
            )
        return BfclCliResult(0, "", "", 0.1, command)

    outcome = run_bfcl_instance(
        plan=plan,
        instance_id="live_simple_0-0-0",
        artifacts_dir=tmp_path / "art",
        repo_root=tmp_path,
        process_runner=runner,
        harness_version=bfcl_pinned_harness_version(),
        benchmark_identity=bfcl_benchmark_identity(live.identity, benchmark_id=live.id),
    )

    assert outcome.primary_pass is True
    assert outcome.instance_id == "live_simple_0-0-0"
    assert outcome.adapter_metadata["benchmark_version"].startswith("bfcl-v4-live@")
    assert len(seen) == 2


def test_live_exact_id_rejects_a_score_without_the_requested_result(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4-live",
        slice_id="plumbing-6",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11-FC",
        diagnostic=True,
    )
    live = load_benchmark_catalog().by_id_or_alias("bfcl-v4-live")
    assert isinstance(live.identity, BfclPackageDataIdentity)

    def runner(
        command: tuple[str, ...] | list[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: dict[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        command = tuple(command)
        if command[1] == "evaluate":
            score_root = Path(command[command.index("--score-dir") + 1])
            score = score_root / "gpt-5.2-2025-12-11-FC" / "live" / "BFCL_v4_live_simple_score.json"
            score.parent.mkdir(parents=True)
            score.write_text(
                json.dumps({"accuracy": 1.0, "correct_count": 1, "total_count": 1}) + "\n",
                encoding="utf-8",
            )
        return BfclCliResult(0, "", "", 0.1, command)

    with pytest.raises(AdapterFailureError, match="requires one official"):
        run_bfcl_instance(
            plan=plan,
            instance_id="live_simple_0-0-0",
            artifacts_dir=tmp_path / "art",
            repo_root=tmp_path,
            process_runner=runner,
            harness_version=bfcl_pinned_harness_version(),
            benchmark_identity=bfcl_benchmark_identity(live.identity, benchmark_id=live.id),
        )


def test_live_exact_id_score_must_describe_one_requested_case() -> None:
    expected = "live_simple_0-0-0"
    two_case_header = json.dumps({"accuracy": 1.0, "correct_count": 2, "total_count": 2})
    wrong_failure = "\n".join(
        (
            json.dumps({"accuracy": 0.0, "correct_count": 0, "total_count": 1}),
            json.dumps({"id": "live_simple_0-0-1", "valid": False}),
        ),
    )

    assert _parse_official_score(two_case_header.encode(), expected_instance_id=expected) is None
    assert _parse_official_score(wrong_failure.encode(), expected_instance_id=expected) is None
