"""Contracts for executing the derived BFCL tool-order benchmark through the run-owned overlay.

SUBSTITUTE_JUSTIFICATION
- substitute: a disposable ``bfcl_eval``-shaped package tree and pin identity
  (`_substitute_package` from the materializer contracts) bound into a
  `DerivedSource`, plus a stub ``process_runner`` that records the launch
  environment and writes official-shaped result/score files
- replaces: the installed pinned bfcl-eval distribution, the catalog source
  pins, and the charged official generate/evaluate subprocesses
- necessity: overlay reuse across instances, launch-environment binding,
  retained variant manifest, and mid-run overlay tampering must be forced
  deterministically without paying a provider or mutating site-packages
- real-option: none locally; the real route is the X0.2 loader probe plus the
  X3.5 dev-box plumbing run through this exact adapter path
- proof-limit: proves BenchEval-side sequencing, binding, retention, and
  fail-closed behavior only; it proves nothing about BFCL scoring
- real-proof: X3.5 dev-box `bfcl-v4-tool-order-v1/tool-order-derived-plumbing-2`
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import BfclDerivedDataRef, load_benchmark_catalog
from bencheval.bfcl_native_adapter import (
    BfclCliResult,
    bfcl_pinned_harness_version,
    run_bfcl_instance,
)
from bencheval.bfcl_study import (
    OVERLAY_DIR,
    VARIANT_MANIFEST_FILE,
    DerivedSource,
    parse_variant_manifest,
    tree_digests,
)
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.exposure_selection import load_exposure_selection
from bencheval.exposure_study import default_studies_dir, load_exposure_study
from bencheval.live_run_manifest import LiveRunRecord, append_live_run
from bencheval.proof_bundle import export_private_proof, load_verified_proof_inputs
from tests.specs.test_bfcl_study_contracts import _substitute_package

_DERIVED = "bfcl-v4-tool-order-v1"
_MODEL = "gpt-5.2-2025-12-11-FC"
_LABEL = re.compile(r"^bfcl-v4-tool-order-v1@derived-[0-9a-f]{64}$")


def _source(tmp_path: Path) -> DerivedSource:
    ref = load_benchmark_catalog().by_id_or_alias(_DERIVED).identity
    assert isinstance(ref, BfclDerivedDataRef)
    identity = _substitute_package(tmp_path / "site")
    return DerivedSource(
        ref=ref,
        source_identity=identity,
        study=load_exposure_study(ref.study_id),
        selection=load_exposure_selection(default_studies_dir() / f"{ref.study_id}.selection.json"),
        package_root=tmp_path / "site" / "bfcl_eval",
    )


def _plan(slice_id: str = "tool-order-derived-plumbing-2"):
    return plan_control_plane(
        benchmark_id=_DERIVED, slice_id=slice_id, runtime_id=None, model_id=_MODEL, diagnostic=True
    )


def _runner(envs: list[dict[str, str]], *, during_generate: Callable[[Path], None] | None = None):
    def runner(
        command: tuple[str, ...] | list[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: dict[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec
        command = tuple(command)
        envs.append(dict(env))
        project = Path(env["BFCL_PROJECT_ROOT"])
        ids = json.loads((project / "test_case_ids_to_generate.json").read_text())
        category, (instance_id,) = next(iter(ids.items()))
        if command[1] == "generate":
            result_root = Path(command[command.index("--result-dir") + 1])
            result = result_root / _MODEL / "non_live" / f"BFCL_v4_{category}_result.json"
            result.parent.mkdir(parents=True)
            result.write_text(json.dumps({"id": instance_id, "result": [[]]}) + "\n")
            if during_generate is not None:
                during_generate(Path(env["PYTHONPATH"]))
        else:
            score_root = Path(command[command.index("--score-dir") + 1])
            score = score_root / _MODEL / "non_live" / f"BFCL_v4_{category}_score.json"
            score.parent.mkdir(parents=True)
            score.write_text(
                json.dumps({"accuracy": 1.0, "correct_count": 1, "total_count": 1}) + "\n"
            )
        return BfclCliResult(0, "", "", 0.1, command)

    return runner


def test_derived_run_launches_from_a_verified_overlay_and_retains_the_variant(
    tmp_path: Path,
) -> None:
    source = _source(tmp_path)
    envs: list[dict[str, str]] = []
    art = tmp_path / "art"
    outcome = run_bfcl_instance(
        plan=_plan(),
        instance_id="multiple_19",
        artifacts_dir=art,
        repo_root=tmp_path,
        process_runner=_runner(envs),
        harness_version=bfcl_pinned_harness_version(),
        derived_source=source,
    )
    assert outcome.primary_pass is True
    version = outcome.adapter_metadata["benchmark_version"]
    assert _LABEL.fullmatch(version)
    manifest_path = art / "study" / VARIANT_MANIFEST_FILE
    identity, overlay = parse_variant_manifest(
        manifest_path.read_text(encoding="utf-8"), artifacts_dir=art
    )
    assert json.loads(manifest_path.read_text())["benchmark_version"] == version
    assert identity.source_identity == source.source_identity
    assert identity.seed == source.study.population.seed
    assert {e.derived_instance_id for e in identity.source_mapping} == set(
        source.selection.candidate.selected_ids
    )
    # Both phases imported the official package from the run-owned overlay only.
    assert len(envs) == 2
    for env in envs:
        assert env["PYTHONPATH"] == str(art / OVERLAY_DIR / "pkg")
        assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert overlay.package_dir == art / OVERLAY_DIR / "pkg" / "bfcl_eval"
    source_digests = tree_digests(source.package_root)
    overlay_digests = tree_digests(overlay.package_dir)
    assert {rel for rel in overlay_digests if overlay_digests[rel] != source_digests[rel]} == {
        "data/BFCL_v4_multiple.json",
        "data/BFCL_v4_parallel_multiple.json",
    }
    assert tree_digests(source.package_root) == source_digests
    retained = set(outcome.study_artifact_paths)
    assert any(p.endswith("study/variant-manifest.json") for p in retained)
    assert any(p.endswith("overlay/pkg/bfcl_eval/data/BFCL_v4_multiple.json") for p in retained)
    assert any(
        p.endswith("overlay/pkg/bfcl_eval/data/BFCL_v4_parallel_multiple.json") for p in retained
    )
    assert (
        json.loads((art / "study" / "benchmark-identity.json").read_text())["benchmark_version"]
        == version
    )

    # A later instance reuses and re-verifies the same overlay; nothing is rewritten.
    manifest_bytes = manifest_path.read_bytes()
    second = run_bfcl_instance(
        plan=_plan(),
        instance_id="parallel_multiple_125",
        artifacts_dir=art,
        repo_root=tmp_path,
        process_runner=_runner(envs),
        harness_version=bfcl_pinned_harness_version(),
        derived_source=source,
    )
    assert second.adapter_metadata["benchmark_version"] == version
    assert manifest_path.read_bytes() == manifest_bytes
    assert tree_digests(overlay.package_dir) == overlay_digests


@pytest.mark.parametrize(
    ("label", "tamper"),
    [
        (
            "scorer",
            lambda pkg: (pkg / "eval_checker" / "eval_runner.py").write_text(
                "def runner():\n    return 0\n"
            ),
        ),
        (
            "derived data",
            lambda pkg: (pkg / "data" / "BFCL_v4_multiple.json").write_text("{}\n"),
        ),
        (
            "ground truth",
            lambda pkg: (pkg / "data" / "possible_answer" / "BFCL_v4_multiple.json").write_text(
                "{}\n"
            ),
        ),
        ("symlinked answers", lambda pkg: _symlink_answers(pkg)),
    ],
)
def test_overlay_tampering_between_instances_fails_closed(
    tmp_path: Path, label: str, tamper: Callable[[Path], None]
) -> None:
    source = _source(tmp_path)
    art = tmp_path / "art"
    run_bfcl_instance(
        plan=_plan(),
        instance_id="multiple_19",
        artifacts_dir=art,
        repo_root=tmp_path,
        process_runner=_runner([]),
        harness_version=bfcl_pinned_harness_version(),
        derived_source=source,
    )
    tamper(art / OVERLAY_DIR / "pkg" / "bfcl_eval")
    launches: list[dict[str, str]] = []
    with pytest.raises(AdapterFailureError) as excinfo:
        run_bfcl_instance(
            plan=_plan(),
            instance_id="parallel_multiple_125",
            artifacts_dir=art,
            repo_root=tmp_path,
            process_runner=_runner(launches),
            harness_version=bfcl_pinned_harness_version(),
            derived_source=source,
        )
    # The prelaunch failure itself is preserved: nothing launched, and no launch
    # concurrency is claimed for a launch that never happened.
    assert excinfo.value.failure_label == "runtime_config_drift", label
    assert launches == []
    assert "bfcl_num_threads" not in excinfo.value.adapter_metadata


def _symlink_answers(pkg: Path) -> None:
    import shutil

    target = pkg / "data" / "possible_answer"
    shutil.rmtree(target)
    target.symlink_to(
        pkg.parent.parent.parent.parent / "site" / "bfcl_eval" / "data" / "possible_answer"
    )


def test_overlay_mutation_during_generation_is_never_scored(tmp_path: Path) -> None:
    source = _source(tmp_path)
    envs: list[dict[str, str]] = []

    def mutate(pythonpath: Path) -> None:
        (pythonpath / "bfcl_eval" / "data" / "BFCL_v4_multiple.json").write_text("{}\n")

    with pytest.raises(AdapterFailureError) as excinfo:
        run_bfcl_instance(
            plan=_plan(),
            instance_id="multiple_19",
            artifacts_dir=tmp_path / "art",
            repo_root=tmp_path,
            process_runner=_runner(envs, during_generate=mutate),
            harness_version=bfcl_pinned_harness_version(),
            derived_source=source,
        )
    assert excinfo.value.failure_label == "runtime_config_drift"
    assert [len(envs)] == [1]


def test_derived_source_must_match_the_catalog_reference(tmp_path: Path) -> None:
    source = _source(tmp_path)
    other_ref = source.ref.model_copy(update={"study_id": "bfcl-v4-live-vs-non-live"})
    with pytest.raises(AdapterFailureError) as excinfo:
        run_bfcl_instance(
            plan=_plan(),
            instance_id="multiple_19",
            artifacts_dir=tmp_path / "art",
            repo_root=tmp_path,
            process_runner=_runner([]),
            harness_version=bfcl_pinned_harness_version(),
            derived_source=DerivedSource(
                ref=other_ref,
                source_identity=source.source_identity,
                study=source.study,
                selection=source.selection,
                package_root=source.package_root,
            ),
        )
    assert excinfo.value.failure_label == "runtime_config_drift"
    canonical = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="tool-order-canonical-plumbing-2",
        runtime_id=None,
        model_id=_MODEL,
    )
    with pytest.raises(BenchEvalError, match="not a derived benchmark"):
        run_bfcl_instance(
            plan=canonical,
            instance_id="multiple_19",
            artifacts_dir=tmp_path / "canonical",
            repo_root=tmp_path,
            process_runner=_runner([]),
            harness_version=bfcl_pinned_harness_version(),
            derived_source=source,
        )


def test_executor_retains_the_variant_manifest_inside_a_complete_proof(tmp_path: Path) -> None:
    source = _source(tmp_path)
    plan = _plan()
    evidence = tmp_path / "results" / "evidence" / "run.jsonl"
    artifacts = tmp_path / "results" / "raw" / "run"
    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=artifacts,
        bfcl_process_runner=_runner([]),
        bfcl_derived_source=source,
        run_id="run-derived-test",
    )
    assert summary.passed_count == 2
    rows = read_evidence_jsonl(evidence)
    versions = {r.benchmark_version for r in rows}
    assert len(versions) == 1 and _LABEL.fullmatch(next(iter(versions)))
    assert all(r.benchmark_id == _DERIVED for r in rows)
    manifest = tmp_path / "runs.jsonl"
    append_live_run(
        manifest,
        LiveRunRecord(
            run_id="run-derived-test",
            host="test-host",
            benchmark=_DERIVED,
            slice_id=plan.slice_id,
            model_id=_MODEL,
            evidence_path=str(evidence),
            status="completed",
            generated_at=rows[0].created_at,
        ),
    )
    exported = export_private_proof(
        run_id="run-derived-test",
        evidence_path=evidence,
        artifacts_dir=artifacts,
        manifest_path=manifest,
        output_dir=tmp_path / "proof",
    )
    assert exported.classification == "complete"
    inputs = load_verified_proof_inputs(exported.root, require_complete=True)
    assert inputs.variant_manifest is not None
    identity, _ = parse_variant_manifest(
        inputs.variant_manifest.decode("utf-8"), artifacts_dir=Path(".")
    )
    assert identity.source_identity == source.source_identity
    assert (
        exported.root
        / "artifacts"
        / "raw"
        / "overlay"
        / "pkg"
        / "bfcl_eval"
        / "data"
        / "BFCL_v4_multiple.json"
    ).is_file()
