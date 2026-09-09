"""Behavioral contracts for the read-only benchmark-exposure report boundary.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed model-only BFCL ``EvidenceRecord`` rows, crafted
  ``RunPlan`` populations, and disposable private-proof directories
  (`_row`, `_rows`, `_plan_for`, `_proof_from_rows`)
- replaces: official BFCL generate/evaluate evidence and operator-host proofs
- necessity: wrong slices, forged identities, missing provenance, mixed runs,
  cherry-picked populations, asymmetric pairs, infrastructure contamination,
  overclaiming smoke, legacy proofs, tampered proofs, and lock/report drift
  must be forced without charging a provider or rewriting retained proof
- real-option: none; a charged run cannot be steered into these invalid states
- proof-limit: deterministic validation, rendering, and lock reproduction only;
  it proves nothing about BFCL scores, freshness, or model dependence
- real-proof: the X2.3/X2.4 dev-box BFCL Live runs and their imported proofs
- covered tests: every test in this module
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from bencheval.benchmark_plan import plan_control_plane
from bencheval.cli import main
from bencheval.domain import RunPlan, RunPlanInstance
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_report import (
    EXPOSURE_LOCK_SCHEMA,
    REPORT_CONTRACT_VERSION,
    build_exposure_report,
    render_exposure_markdown,
    validate_exposure_study,
    verify_exposure_study_lock,
    write_exposure_report,
    write_proof_backed_exposure_report,
)
from bencheval.exposure_study import (
    ExposureStudyManifest,
    StudySide,
    exposure_study_sha256,
    load_exposure_study,
)
from bencheval.identity_strings import bfcl_benchmark_identity, catalog_benchmark_identity
from bencheval.live_run_manifest import LiveRunRecord, append_live_run
from bencheval.proof_bundle import export_private_proof, load_verified_proof_inputs
from bencheval.stats import exact_binomial_two_sided, newcombe_diff, wilson

_TS = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
_LIVE_STUDY = "bfcl-v4-live-vs-non-live"
_PAIR_STUDY = "bfcl-v4-tool-order-v1"
_PRODUCER = "sha256:" + "7" * 64
_MODEL = "kimi-k2.7-code"


def _benchmark_version(benchmark_id: str) -> str:
    identity = catalog_benchmark_identity(benchmark_id) if benchmark_id != _PAIR_STUDY else None
    if identity is None:
        return f"{benchmark_id}@derived-{'d' * 64}"
    return bfcl_benchmark_identity(identity, benchmark_id=benchmark_id)  # type: ignore[arg-type]


def _row(
    *,
    benchmark_id: str,
    slice_id: str,
    instance_id: str,
    primary_pass: bool,
    run_id: str = "run-exposure",
    **overrides: object,
) -> EvidenceRecord:
    fields: dict[str, object] = {
        "run_id": run_id,
        "task_id": instance_id,
        "model_id": _MODEL,
        "execution_profile": "E0",
        "backend": "inspect",
        "primary_pass": primary_pass,
        "partial_score": 1.0 if primary_pass else 0.0,
        "cost_usd": 0.0,
        "latency_sec": 1.0,
        "failure_labels": [] if primary_pass else ["model_wrong_solution"],
        "artifact_paths": ["raw/score.json"],
        "verifier_log_path": "raw/score.json",
        "adapter_metadata": {"producer_content_sha256": _PRODUCER},
        "created_at": _TS,
        "benchmark_id": benchmark_id,
        "benchmark_version": _benchmark_version(benchmark_id),
        "slice_id": slice_id,
        "adapter_id": "bfcl",
        "harness_kind": "bfcl-native",
        "harness_version": "bfcl-eval==2026.3.23",
        "provider_id": "bytellm",
        "provider_config_hash": "sha256:" + "1" * 64,
        "instance_id": instance_id,
        "interpretation_label": "diagnostic",
        "verifier_integrity_label": "native",
        "failure_class": None if primary_pass else "model_wrong_solution",
        "access_control_source": "not_applicable",
        "egress_control": "not_applicable",
        "repository_history": "not_applicable",
        "retrieval_audit": "not_run",
    }
    fields.update(overrides)
    return EvidenceRecord.model_validate(fields)


def _rows(
    side: StudySide,
    counts: dict[str, int],
    *,
    smoke: int | None,
    passes: int,
    run_id: str,
) -> list[EvidenceRecord]:
    slice_id = side.smoke_slice_id if smoke is not None else side.slice_id
    return [
        _row(
            benchmark_id=side.benchmark_id,
            slice_id=slice_id,
            instance_id=f"{stratum}_{index}-0-0",
            primary_pass=index < passes,
            run_id=run_id,
        )
        for stratum, declared in counts.items()
        for index in range(smoke if smoke is not None else declared)
    ]


def _sides(
    study_id: str = _LIVE_STUDY, *, smoke: bool = True
) -> tuple[ExposureStudyManifest, list[EvidenceRecord], list[EvidenceRecord]]:
    study = load_exposure_study(study_id)
    per = study.population.smoke_per_stratum if smoke else None
    canonical = _rows(
        study.canonical,
        study.population.canonical_counts,
        smoke=per,
        passes=1 if smoke else 10,
        run_id="run-canonical",
    )
    candidate = _rows(
        study.candidate,
        study.population.candidate_counts,
        smoke=per,
        passes=0 if smoke else 4,
        run_id="run-candidate",
    )
    return study, canonical, candidate


def _plan_for(rows: list[EvidenceRecord]) -> RunPlan:
    """A retained-plan substitute: the product planner's shape with this population."""
    first = rows[0]
    assert first.benchmark_id and first.slice_id
    derived = first.benchmark_id == _PAIR_STUDY
    live = first.benchmark_id == "bfcl-v4-live"
    plan = plan_control_plane(
        benchmark_id="bfcl-v4" if derived else first.benchmark_id,
        slice_id="plumbing-6" if live else "smoke-5",
        runtime_id=None,
        model_id=first.model_id,
        diagnostic=live,
    )
    return plan.model_copy(
        update={
            "benchmark_id": first.benchmark_id,
            "slice_id": first.slice_id,
            "diagnostic": live or derived,
            "instances": tuple(
                RunPlanInstance(instance_id=r.instance_id) for r in rows if r.instance_id
            ),
        },
    )


def _proof_report(
    tmp_path: Path,
    study: ExposureStudyManifest,
    canonical: list[EvidenceRecord],
    candidate: list[EvidenceRecord],
    *,
    analysis: str,
    selection: object | None = None,
) -> dict[str, object]:
    """Run the real proof-backed path over disposable complete proofs."""
    built = write_proof_backed_exposure_report(
        study,
        canonical_proof=_proof_from_rows(tmp_path / "canonical", canonical),
        candidate_proof=_proof_from_rows(tmp_path / "candidate", candidate),
        analysis=analysis,  # type: ignore[arg-type]
        output=tmp_path / "report.json",
        lock_output=tmp_path / "lock.json",
        fmt="json",
        selection=selection,  # type: ignore[arg-type]
    )
    return built.report.payload


def _rows_from_real_selection(
    side: str, *, passes: int, run_id: str
) -> tuple[ExposureStudyManifest, list[EvidenceRecord], object]:
    """Rows over the checked-in, catalog-anchored selection of the live study."""
    from bencheval.exposure_selection import load_exposure_selection
    from bencheval.exposure_study import default_studies_dir

    selection = load_exposure_selection(default_studies_dir() / f"{_LIVE_STUDY}.selection.json")
    bound = getattr(selection, side)
    rows = [
        _row(
            benchmark_id=bound.benchmark_id,
            slice_id=bound.slice_id,
            instance_id=instance_id,
            primary_pass=index < passes,
            run_id=run_id,
        )
        for name in sorted(bound.strata)
        for index, instance_id in enumerate(bound.strata[name].selected_ids)
    ]
    return load_exposure_study(_LIVE_STUDY), rows, selection


def _proof_from_rows(
    root: Path,
    rows: list[EvidenceRecord],
    *,
    with_plan: bool = True,
    extra_raw: dict[str, str] | None = None,
) -> Path:
    run_id = rows[0].run_id
    raw = root / "raw"
    (raw / "raw").mkdir(parents=True)
    (raw / "raw" / "score.json").write_text('{"accuracy": 0.0}\n', encoding="utf-8")
    for rel, text in (extra_raw or {}).items():
        (raw / rel).parent.mkdir(parents=True, exist_ok=True)
        (raw / rel).write_text(text, encoding="utf-8")
    if with_plan:
        (raw / "run-plan.json").write_text(
            _plan_for(rows).model_dump_json() + "\n", encoding="utf-8"
        )
    evidence = root / "evidence.jsonl"
    sink = JsonlEvidenceSink()
    for record in rows:
        sink.append_jsonl(evidence, record)
    manifest = root / "runs.jsonl"
    append_live_run(
        manifest,
        LiveRunRecord(
            run_id=run_id,
            host="test-host",
            benchmark=rows[0].benchmark_id,
            slice_id=rows[0].slice_id,
            model_id=rows[0].model_id,
            evidence_path=str(evidence),
            status="completed",
            generated_at=_TS,
        ),
    )
    exported = export_private_proof(
        run_id=run_id,
        evidence_path=evidence,
        artifacts_dir=raw,
        manifest_path=manifest,
        output_dir=root / "proof",
    )
    return exported.root


def _forbidden_language(text: str) -> list[str]:
    lowered = text.lower()
    return [w for w in ("significan", "confidence", "p-value", "p_value", "wilson") if w in lowered]


# --- validate -----------------------------------------------------------------


def test_validate_reports_digest_and_rejects_malformed_manifest(tmp_path: Path) -> None:
    result = validate_exposure_study(_LIVE_STUDY)
    assert result["study_id"] == _LIVE_STUDY
    assert result["study_sha256"] == exposure_study_sha256(load_exposure_study(_LIVE_STUDY))
    assert result["comparison_mode"] == "stratified_unpaired"
    assert result["candidate"]["smoke_slice_id"] == "plumbing-6"  # type: ignore[index]

    broken = tmp_path / "broken.yaml"
    broken.write_text("id: broken\nkind: freshness_contrast\n", encoding="utf-8")
    with pytest.raises(BenchEvalError):
        validate_exposure_study(broken)


# --- smoke / raw-only ---------------------------------------------------------


def test_smoke_freshness_report_is_raw_counts_only() -> None:
    study, canonical, candidate = _sides()
    report = build_exposure_report(
        study, canonical=canonical, candidate=candidate, analysis="raw_only"
    )
    payload = report.payload
    assert payload["report_contract_version"] == REPORT_CONTRACT_VERSION
    assert payload["analysis_mode"] == "plumbing_only"
    assert payload["population_scale"] == "smoke"
    assert payload["population_binding"] is None
    assert payload["canonical"]["strata"]["multiple"] == {"eligible": 1, "passed": 1}
    assert payload["candidate"]["strata"]["live_relevance"] == {"eligible": 1, "passed": 0}
    assert payload["canonical"]["run_id"] == "run-canonical"
    assert payload["constant_axes"]["producer_content_sha256"] == _PRODUCER
    assert "rate" not in payload["canonical"]["overall"]
    assert "difference" not in payload
    assert "contaminated" in payload["forbidden_claims"]
    markdown = render_exposure_markdown(report)
    assert "plumbing_only" in markdown
    assert _forbidden_language(markdown) == []
    assert _forbidden_language(report.to_json()) == []


def test_smoke_population_cannot_request_declared_analysis(tmp_path: Path) -> None:
    study, canonical, candidate = _sides()
    with pytest.raises(BenchEvalError, match="smoke"):
        _proof_report(tmp_path, study, canonical, candidate, analysis="declared")
    assert not (tmp_path / "report.json").exists()
    assert not (tmp_path / "lock.json").exists()


def test_report_json_is_deterministic_and_order_independent() -> None:
    study, canonical, candidate = _sides()
    first = build_exposure_report(
        study, canonical=canonical, candidate=candidate, analysis="raw_only"
    )
    second = build_exposure_report(
        study,
        canonical=list(reversed(canonical)),
        candidate=list(reversed(candidate)),
        analysis="raw_only",
    )
    assert first.to_json() == second.to_json()
    assert first.sha256 == "sha256:" + hashlib.sha256(first.to_json().encode()).hexdigest()


# --- declared population ------------------------------------------------------


def test_raw_evidence_can_never_request_declared_analysis() -> None:
    study, canonical, candidate = _sides(smoke=False)
    with pytest.raises(BenchEvalError, match="proof-backed"):
        build_exposure_report(study, canonical=canonical, candidate=candidate, analysis="declared")
    # The same full-size population is fine as raw counts.
    payload = build_exposure_report(
        study, canonical=canonical, candidate=candidate, analysis="raw_only"
    ).payload
    assert payload["analysis_mode"] == "plumbing_only"
    assert payload["population_scale"] == "declared"
    assert "rate" not in payload["canonical"]["overall"]


def test_declared_freshness_report_emits_rates_intervals_and_difference(
    tmp_path: Path,
) -> None:
    study, canonical, selection = _rows_from_real_selection(
        "canonical", passes=10, run_id="run-canonical"
    )
    _, candidate, _ = _rows_from_real_selection("candidate", passes=4, run_id="run-candidate")
    with pytest.raises(BenchEvalError, match="selection"):
        _proof_report(tmp_path / "unselected", study, canonical, candidate, analysis="declared")
    payload = _proof_report(
        tmp_path, study, canonical, candidate, analysis="declared", selection=selection
    )
    assert payload["analysis_mode"] == "declared_population"
    assert payload["population_selection"]["algorithm"] == "sha256_rank_v1"
    assert payload["population_scale"] == "declared"
    lock = json.loads((tmp_path / "lock.json").read_text(encoding="utf-8"))
    assert payload["population_binding"] == [
        f"run-plan.json@{lock['canonical']['proof_id']}",
        f"run-plan.json@{lock['candidate']['proof_id']}",
    ]
    canon = payload["canonical"]["overall"]
    assert canon["eligible"] == 340 and canon["passed"] == 50
    assert 0.0 < canon["rate"]["low"] < canon["rate"]["point"] < canon["rate"]["high"] < 1.0
    diff = payload["difference"]
    assert diff["method"] == "newcombe_95"
    assert diff["low"] < diff["point"] < diff["high"]
    assert diff["point"] == pytest.approx(
        payload["candidate"]["overall"]["rate"]["point"] - canon["rate"]["point"]
    )


def test_population_must_match_smoke_or_declared_counts_exactly() -> None:
    study, canonical, candidate = _sides(smoke=False)
    with pytest.raises(BenchEvalError, match="population"):
        build_exposure_report(
            study, canonical=canonical[:-1], candidate=candidate, analysis="raw_only"
        )


def test_missing_side_is_rejected() -> None:
    study, canonical, candidate = _sides()
    with pytest.raises(BenchEvalError, match="candidate"):
        build_exposure_report(study, canonical=canonical, candidate=[], analysis="raw_only")
    with pytest.raises(BenchEvalError, match="canonical"):
        build_exposure_report(study, canonical=[], candidate=candidate, analysis="raw_only")


def test_slice_must_match_the_study_scale() -> None:
    study, canonical, candidate = _sides()
    wrong = [r.model_copy(update={"slice_id": "wrong-slice"}) for r in canonical]
    with pytest.raises(BenchEvalError, match="slice"):
        build_exposure_report(study, canonical=wrong, candidate=candidate, analysis="raw_only")
    # A smoke-sized population on the declared slice is not the plumbing slice either.
    declared_slice = [
        r.model_copy(update={"slice_id": study.canonical.slice_id}) for r in canonical
    ]
    with pytest.raises(BenchEvalError, match="smoke slice"):
        build_exposure_report(
            study, canonical=declared_slice, candidate=candidate, analysis="raw_only"
        )


def test_forged_benchmark_version_is_rejected_even_when_uniform() -> None:
    study, canonical, candidate = _sides()
    forged = [r.model_copy(update={"benchmark_version": "bfcl-v4@forged"}) for r in canonical]
    with pytest.raises(BenchEvalError, match="catalog identity"):
        build_exposure_report(study, canonical=forged, candidate=candidate, analysis="raw_only")
    provisional = [
        r.model_copy(update={"benchmark_version": "provisional:bfcl-v4-live/x"}) for r in candidate
    ]
    with pytest.raises(BenchEvalError, match=r"provisional|catalog identity"):
        build_exposure_report(
            study, canonical=canonical, candidate=provisional, analysis="raw_only"
        )


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"provider_id": None, "provider_config_hash": None}, "captured provider_id"),
        ({"harness_kind": None}, "captured harness_kind"),
        ({"harness_version": None}, "captured harness_version"),
        ({"harness_version": "bfcl-eval==2026.3.23-dirty"}, "fallback"),
        ({"adapter_metadata": {}}, "producer"),
        ({"adapter_id": "gpqa"}, "adapter"),
        ({"harness_kind": "harbor"}, "harness_kind"),
    ],
)
def test_missing_or_wrong_provenance_is_rejected(update: dict[str, object], message: str) -> None:
    study, canonical, candidate = _sides()
    broken = [r.model_copy(update=update) for r in canonical]
    with pytest.raises(BenchEvalError, match=message):
        build_exposure_report(study, canonical=broken, candidate=candidate, analysis="raw_only")


def test_each_side_is_one_run_and_sides_are_distinct_runs() -> None:
    study, canonical, candidate = _sides()
    stitched = [canonical[0].model_copy(update={"run_id": "run-other"}), *canonical[1:]]
    with pytest.raises(BenchEvalError, match="run_id"):
        build_exposure_report(study, canonical=stitched, candidate=candidate, analysis="raw_only")
    same_run = [r.model_copy(update={"run_id": "run-canonical"}) for r in candidate]
    with pytest.raises(BenchEvalError, match="distinct runs"):
        build_exposure_report(study, canonical=canonical, candidate=same_run, analysis="raw_only")


def test_unexpected_duplicate_and_aggregate_instances_are_rejected() -> None:
    study, canonical, candidate = _sides()
    stray = canonical[0].model_copy(
        update={"instance_id": "live_simple_0-0-0", "task_id": "live_simple_0-0-0"}
    )
    with pytest.raises(BenchEvalError, match="stratum"):
        build_exposure_report(
            study, canonical=[*canonical, stray], candidate=candidate, analysis="raw_only"
        )
    with pytest.raises(BenchEvalError, match="duplicate"):
        build_exposure_report(
            study, canonical=[*canonical, canonical[0]], candidate=candidate, analysis="raw_only"
        )
    aggregate = canonical[0].model_copy(update={"instance_id": "multiple", "task_id": "multiple"})
    with pytest.raises(BenchEvalError, match="aggregate"):
        build_exposure_report(
            study, canonical=[aggregate, *canonical[1:]], candidate=candidate, analysis="raw_only"
        )


def test_benchmark_identity_mismatch_is_rejected() -> None:
    study, _canonical, candidate = _sides()
    with pytest.raises(BenchEvalError, match="benchmark"):
        build_exposure_report(study, canonical=candidate, candidate=candidate, analysis="raw_only")


@pytest.mark.parametrize(
    "update",
    [
        {"model_id": "other-model"},
        {"provider_config_hash": "sha256:" + "2" * 64},
        {"harness_version": "bfcl-eval==2025.1.1"},
        {"egress_control": "uncontrolled"},
        {"access_control_source": None},
        {"adapter_metadata": {"producer_content_sha256": "sha256:" + "8" * 64}},
    ],
)
def test_constant_axis_drift_is_rejected(update: dict[str, object]) -> None:
    study, canonical, candidate = _sides()
    drifted = [candidate[0].model_copy(update=update), *candidate[1:]]
    with pytest.raises(BenchEvalError, match=r"axis|producer|one value"):
        build_exposure_report(study, canonical=canonical, candidate=drifted, analysis="raw_only")


def test_infrastructure_and_non_native_rows_are_rejected() -> None:
    study, canonical, candidate = _sides()
    infra = candidate[0].model_copy(
        update={"failure_class": "harness_failure", "failure_labels": ["harness_failure"]},
    )
    with pytest.raises(BenchEvalError, match="ineligible"):
        build_exposure_report(
            study, canonical=canonical, candidate=[infra, *candidate[1:]], analysis="raw_only"
        )
    unofficial = candidate[0].model_copy(update={"verifier_integrity_label": "bencheval"})
    with pytest.raises(BenchEvalError, match="verifier"):
        build_exposure_report(
            study, canonical=canonical, candidate=[unofficial, *candidate[1:]], analysis="raw_only"
        )


def test_retrieval_observed_is_retained_as_a_caveat_without_changing_counts() -> None:
    study, canonical, candidate = _sides()
    flagged = [
        candidate[0].model_copy(update={"retrieval_audit": "retrieval_observed"}),
        *candidate[1:],
    ]
    report = build_exposure_report(
        study, canonical=canonical, candidate=flagged, analysis="raw_only"
    )
    assert report.payload["retrieval_observed"] is True
    assert report.payload["candidate"]["strata"]["live_simple"] == {"eligible": 1, "passed": 0}
    assert any("retrieval" in c for c in report.payload["caveats"])


# --- paired mode --------------------------------------------------------------


def test_paired_smoke_reports_concordance_only() -> None:
    study, canonical, candidate = _sides(_PAIR_STUDY)
    report = build_exposure_report(
        study, canonical=canonical, candidate=candidate, analysis="raw_only"
    )
    payload = report.payload
    assert payload["comparison_mode"] == "paired_by_source_instance"
    # smoke: index 0 of each stratum passes on the canonical side only.
    assert payload["pairs"] == {
        "eligible": 2,
        "both_pass": 0,
        "both_fail": 0,
        "canonical_only_pass": 2,
        "candidate_only_pass": 0,
    }
    assert "paired_delta" not in payload
    assert "paired_test" not in payload
    assert payload["candidate"]["benchmark_version"].startswith("bfcl-v4-tool-order-v1@derived-")


def test_paired_asymmetric_population_is_rejected() -> None:
    study, canonical, candidate = _sides(_PAIR_STUDY)
    with pytest.raises(BenchEvalError, match="pair"):
        build_exposure_report(
            study, canonical=canonical, candidate=candidate[:1], analysis="raw_only"
        )
    renamed = [
        candidate[0].model_copy(
            update={"instance_id": "multiple_9-0-0", "task_id": "multiple_9-0-0"}
        ),
        *candidate[1:],
    ]
    with pytest.raises(BenchEvalError, match="pair"):
        build_exposure_report(study, canonical=canonical, candidate=renamed, analysis="raw_only")


def test_derived_candidate_cannot_unlock_declared_interpretation(tmp_path: Path) -> None:
    study, canonical, candidate = _sides(_PAIR_STUDY, smoke=False)
    with pytest.raises(BenchEvalError, match="derived"):
        _proof_report(tmp_path, study, canonical, candidate, analysis="declared")
    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"benchmark_version": "bfcl-v4-tool-order-v1@derived-garbage"}, "derived identity"),
        ({"benchmark_version": f"bfcl-v4@derived-{'d' * 64}"}, "derived identity"),
        ({"benchmark_version": "bfcl-v4-tool-order-v1@x"}, "derived identity"),
        ({"adapter_id": "gpqa"}, "adapter"),
        ({"harness_kind": "inspect"}, "harness_kind"),
    ],
)
def test_derived_candidate_identity_is_closed_even_for_raw_counts(
    update: dict[str, object], message: str
) -> None:
    study, canonical, candidate = _sides(_PAIR_STUDY)
    broken = [r.model_copy(update=update) for r in candidate]
    with pytest.raises(BenchEvalError, match=message):
        build_exposure_report(study, canonical=canonical, candidate=broken, analysis="raw_only")


def test_exact_binomial_two_sided_is_symmetric_and_bounded() -> None:
    assert exact_binomial_two_sided(0, 0) == 1.0
    assert exact_binomial_two_sided(3, 3) == 1.0
    assert exact_binomial_two_sided(0, 10) == exact_binomial_two_sided(10, 0)
    assert exact_binomial_two_sided(0, 10) == pytest.approx(2 / 1024)
    assert 0.0 < exact_binomial_two_sided(2, 9) < 1.0


def test_newcombe_method_10_matches_independent_vectors() -> None:
    # Newcombe (1998) method 10, z = 1.96, delta = candidate - baseline.
    def interval(k_b: int, n_b: int, k_c: int, n_c: int) -> tuple[float, float]:
        p_b, lo_b, hi_b = wilson(k_b, n_b)
        p_c, lo_c, hi_c = wilson(k_c, n_c)
        return newcombe_diff(p_b, lo_b, hi_b, p_c, lo_c, hi_c, p_c - p_b)

    # 1/10 vs 4/10: crosses zero.
    low, high = interval(1, 10, 4, 10)
    assert low == pytest.approx(-0.08243, abs=1e-4)
    assert high == pytest.approx(0.59884, abs=1e-4)
    assert low < 0.0 < high
    # 4/10 vs 1/10: mirror image.
    low_m, high_m = interval(4, 10, 1, 10)
    assert low_m == pytest.approx(-high, abs=1e-9)
    assert high_m == pytest.approx(-low, abs=1e-9)
    # 56/70 vs 48/80 (Newcombe 1998 table, method 10): [0.0524, 0.3339].
    low_t, high_t = interval(48, 80, 56, 70)
    assert low_t == pytest.approx(0.0524, abs=2e-4)
    assert high_t == pytest.approx(0.3339, abs=2e-4)
    assert low_t > 0.0


# --- outputs, locks, and proof-backed reproduction ---------------------------


def test_write_report_is_exclusive_and_leaves_no_partial_output(tmp_path: Path) -> None:
    study, canonical, candidate = _sides()
    report = build_exposure_report(
        study, canonical=canonical, candidate=candidate, analysis="raw_only"
    )
    output = tmp_path / "report.json"
    write_exposure_report(report, output=output, fmt="json")
    assert json.loads(output.read_text(encoding="utf-8")) == report.payload
    with pytest.raises(BenchEvalError):
        write_exposure_report(report, output=output, fmt="json")
    assert output.read_text(encoding="utf-8") == report.to_json()
    link = tmp_path / "link.json"
    link.symlink_to(tmp_path / "missing.json")
    with pytest.raises(BenchEvalError):
        write_exposure_report(report, output=link, fmt="json")
    assert not (tmp_path / "missing.json").exists()


def test_verified_proof_inputs_bind_parsed_bytes_to_the_inventory(tmp_path: Path) -> None:
    _study, canonical, _candidate = _sides()
    root = _proof_from_rows(tmp_path / "canonical", canonical)
    inputs = load_verified_proof_inputs(root, require_complete=True)
    evidence_bytes = (root / "evidence.jsonl").read_bytes()
    assert inputs.evidence_sha256 == "sha256:" + hashlib.sha256(evidence_bytes).hexdigest()
    assert [r.instance_id for r in inputs.records] == [r.instance_id for r in canonical]
    assert inputs.run_plan is not None and inputs.run_plan.slice_id == canonical[0].slice_id

    legacy = _proof_from_rows(tmp_path / "legacy", canonical, with_plan=False)
    assert load_verified_proof_inputs(legacy, require_complete=False).run_plan is None
    with pytest.raises(BenchEvalError, match="complete"):
        load_verified_proof_inputs(legacy, require_complete=True)


def test_proof_backed_report_requires_complete_proofs(tmp_path: Path) -> None:
    study, canonical, candidate = _sides()
    legacy = _proof_from_rows(tmp_path / "canonical", canonical, with_plan=False)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate)
    with pytest.raises(BenchEvalError, match="complete"):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=legacy,
            candidate_proof=candidate_proof,
            analysis="raw_only",
            output=tmp_path / "report.json",
            lock_output=tmp_path / "lock.json",
            fmt="json",
        )
    assert not (tmp_path / "report.json").exists()
    assert not (tmp_path / "lock.json").exists()


def test_proof_backed_declared_report_rejects_a_cherry_picked_population(
    tmp_path: Path,
) -> None:
    """Swapping one planned id for a same-stratum id breaks the retained proof binding."""
    study, canonical, candidate = _sides(smoke=False)
    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate)
    evidence = canonical_proof / "evidence.jsonl"
    evidence.write_text(
        evidence.read_text(encoding="utf-8").replace("multiple_0-0-0", "multiple_999-0-0"),
        encoding="utf-8",
    )
    with pytest.raises(BenchEvalError, match="proof"):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            analysis="declared",
            output=tmp_path / "report.json",
            lock_output=tmp_path / "lock.json",
            fmt="json",
        )
    assert not (tmp_path / "report.json").exists()


def test_proof_backed_report_writes_lock_and_reproduces_offline(tmp_path: Path) -> None:
    study, canonical, candidate = _sides()
    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate)
    output = tmp_path / "report.json"
    lock = tmp_path / "report.lock.json"

    written = write_proof_backed_exposure_report(
        study,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis="raw_only",
        output=output,
        lock_output=lock,
        fmt="json",
    )
    lock_payload = json.loads(lock.read_text(encoding="utf-8"))
    assert lock_payload["schema_version"] == EXPOSURE_LOCK_SCHEMA
    assert lock_payload["study_sha256"] == exposure_study_sha256(study)
    assert lock_payload["report_sha256"] == written.report_sha256
    assert lock_payload["canonical"]["proof_id"] != lock_payload["candidate"]["proof_id"]
    assert lock_payload["canonical"]["evidence_sha256"] == (
        "sha256:" + hashlib.sha256((canonical_proof / "evidence.jsonl").read_bytes()).hexdigest()
    )
    assert lock_payload["report_contract_version"] == REPORT_CONTRACT_VERSION

    copied = tmp_path / "copied"
    shutil.copytree(canonical_proof, copied / "canonical")
    shutil.copytree(candidate_proof, copied / "candidate")
    shutil.copy2(lock, copied / "lock.json")
    shutil.rmtree(tmp_path / "canonical")
    shutil.rmtree(tmp_path / "candidate")
    verified = verify_exposure_study_lock(
        study,
        lock_path=copied / "lock.json",
        canonical_proof=copied / "canonical",
        candidate_proof=copied / "candidate",
    )
    assert verified["report_sha256"] == written.report_sha256
    assert verified["lock_sha256"] == written.lock_sha256


def test_lock_verification_rejects_every_changed_input(tmp_path: Path) -> None:
    study, canonical, candidate = _sides()
    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate)
    lock = tmp_path / "lock.json"
    write_proof_backed_exposure_report(
        study,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis="raw_only",
        output=tmp_path / "report.json",
        lock_output=lock,
        fmt="json",
    )
    original = json.loads(lock.read_text(encoding="utf-8"))

    def _rewrite(mutate: Callable[[dict], None]) -> Path:
        payload = json.loads(json.dumps(original))
        mutate(payload)
        path = tmp_path / "mutated.json"
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return path

    def _verify(
        lock_path: Path,
        canonical_root: Path = canonical_proof,
        candidate_root: Path = candidate_proof,
        target: ExposureStudyManifest = study,
    ) -> dict[str, object]:
        return verify_exposure_study_lock(
            target,
            lock_path=lock_path,
            canonical_proof=canonical_root,
            candidate_proof=candidate_root,
        )

    zero = "sha256:" + "0" * 64
    with pytest.raises(BenchEvalError, match="proof"):
        _verify(_rewrite(lambda p: p["canonical"].__setitem__("proof_id", zero)))
    with pytest.raises(BenchEvalError, match="proof"):
        _verify(
            _rewrite(lambda p: p["candidate"].__setitem__("proof_id", p["canonical"]["proof_id"]))
        )
    with pytest.raises(BenchEvalError, match="evidence"):
        _verify(_rewrite(lambda p: p["candidate"].__setitem__("evidence_sha256", zero)))
    with pytest.raises(BenchEvalError, match="study"):
        _verify(_rewrite(lambda p: p.__setitem__("study_sha256", zero)))
    with pytest.raises(BenchEvalError, match="study"):
        _verify(lock, target=load_exposure_study(_PAIR_STUDY))
    # The retained definition is digest-bound: editing it without the digest, editing
    # the digest without it, dropping it, or re-digesting a changed definition all fail.
    with pytest.raises(BenchEvalError, match="study"):
        _verify(_rewrite(lambda p: p["study"].__setitem__("id", "renamed-study")))
    with pytest.raises(BenchEvalError, match="study"):
        _verify(_rewrite(lambda p: p.pop("study")))
    with pytest.raises(BenchEvalError, match="study"):
        _verify(_rewrite(lambda p: p["study"].__setitem__("unknown_field", 1)))

    def _reseed(p: dict) -> None:
        p["study"]["population"]["seed"] = "someone-elses-seed"
        p["study_sha256"] = exposure_study_sha256(ExposureStudyManifest.model_validate(p["study"]))

    with pytest.raises(BenchEvalError, match="report"):
        _verify(_rewrite(_reseed), target=None)
    with pytest.raises(BenchEvalError, match="report"):
        _verify(_rewrite(lambda p: p.__setitem__("report_sha256", zero)))
    with pytest.raises(BenchEvalError, match="analysis"):
        _verify(_rewrite(lambda p: p.__setitem__("analysis", "declared")))
    with pytest.raises(BenchEvalError, match="lock"):
        _verify(_rewrite(lambda p: p.__setitem__("schema_version", "exposure-study-lock-v0")))
    with pytest.raises(BenchEvalError, match="lock"):
        _verify(_rewrite(lambda p: p.__setitem__("extra", "field")))
    with pytest.raises(BenchEvalError, match="proof"):
        _verify(lock, canonical_root=candidate_proof, candidate_root=canonical_proof)
    evidence = candidate_proof / "evidence.jsonl"
    evidence.write_text(
        evidence.read_text(encoding="utf-8").replace(
            '"primary_pass":false', '"primary_pass":true', 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(BenchEvalError, match="proof"):
        _verify(lock)


def test_proof_backed_report_leaves_no_partial_output_when_lock_path_exists(
    tmp_path: Path,
) -> None:
    study, canonical, candidate = _sides()
    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate)
    lock = tmp_path / "lock.json"
    lock.write_text("occupied\n", encoding="utf-8")
    output = tmp_path / "report.json"
    with pytest.raises(BenchEvalError):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            analysis="raw_only",
            output=output,
            lock_output=lock,
            fmt="json",
        )
    assert not output.exists()
    assert lock.read_text(encoding="utf-8") == "occupied\n"


# --- CLI ---------------------------------------------------------------------


def test_cli_study_validate_report_and_verify(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["study", "validate", _LIVE_STUDY]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["study_id"] == _LIVE_STUDY and out["valid"] is True

    study, canonical, candidate = _sides()
    sink = JsonlEvidenceSink()
    canonical_path = tmp_path / "canonical.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    for record in canonical:
        sink.append_jsonl(canonical_path, record)
    for record in candidate:
        sink.append_jsonl(candidate_path, record)
    output = tmp_path / "report.md"
    evidence_args = [
        "--canonical-evidence",
        str(canonical_path),
        "--candidate-evidence",
        str(candidate_path),
    ]
    assert (
        main(
            [
                "study",
                "report",
                _LIVE_STUDY,
                *evidence_args,
                "--format",
                "markdown",
                "--output",
                str(output),
            ],
        )
        == 0
    )
    assert "plumbing_only" in output.read_text(encoding="utf-8")

    # Declared analysis is never available on raw evidence paths.
    rejected = tmp_path / "rejected.json"
    assert (
        main(
            [
                "study",
                "report",
                _LIVE_STUDY,
                *evidence_args,
                "--analysis",
                "declared",
                "--output",
                str(rejected),
            ],
        )
        != 0
    )
    assert not rejected.exists()

    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate)
    report_json = tmp_path / "proof-report.json"
    lock = tmp_path / "proof-report.lock.json"
    proof_args = [
        "--canonical-proof",
        str(canonical_proof),
        "--candidate-proof",
        str(candidate_proof),
    ]
    assert (
        main(
            [
                "study",
                "report",
                _LIVE_STUDY,
                *proof_args,
                "--output",
                str(report_json),
                "--lock-output",
                str(lock),
            ],
        )
        == 0
    )
    capsys.readouterr()
    assert main(["study", "verify", _LIVE_STUDY, *proof_args, "--lock", str(lock)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["ok"] is True and verified["report_sha256"].startswith("sha256:")
    assert (
        main(
            [
                "study",
                "report",
                _LIVE_STUDY,
                "--canonical-evidence",
                str(canonical_path),
                "--candidate-proof",
                str(candidate_proof),
                "--output",
                str(tmp_path / "mixed.json"),
            ],
        )
        != 0
    )
    assert not (tmp_path / "mixed.json").exists()
    assert study.canonical.smoke_slice_id == canonical[0].slice_id


def test_lock_retains_the_selected_study_and_verifies_without_its_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two copied proofs plus the lock recover a custom study after its YAML is gone."""
    template, canonical, candidate = _sides()
    study = template.model_copy(update={"id": "custom-freshness-probe"})
    studies = tmp_path / "studies"
    studies.mkdir()
    source = studies / "custom.yaml"
    source.write_text(yaml.safe_dump(study.model_dump(mode="json")), encoding="utf-8")
    assert load_exposure_study(source) == study

    proof_args = [
        "--canonical-proof",
        str(_proof_from_rows(tmp_path / "canonical", canonical)),
        "--candidate-proof",
        str(_proof_from_rows(tmp_path / "candidate", candidate)),
    ]
    report = tmp_path / "report.json"
    lock = tmp_path / "report.lock.json"
    args = [str(source), *proof_args, "--output", str(report), "--lock-output", str(lock)]
    assert main(["study", "report", *args]) == 0
    capsys.readouterr()
    lock_payload = json.loads(lock.read_text(encoding="utf-8"))
    assert lock_payload["study"] == study.model_dump(mode="json")
    assert lock_payload["study_sha256"] == exposure_study_sha256(
        ExposureStudyManifest.model_validate(lock_payload["study"])
    )

    shutil.rmtree(studies)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    reproduced = elsewhere / "reproduced.json"
    assert (
        main(["study", "verify", *proof_args, "--lock", str(lock), "--output", str(reproduced)])
        == 0
    )
    verified = json.loads(capsys.readouterr().out)
    assert verified["ok"] is True and verified["study_id"] == "custom-freshness-probe"
    assert verified["study_source"] == "lock"
    assert reproduced.read_bytes() == report.read_bytes()

    # The retained definition round-trips into an ordinary study manifest.
    recovered = elsewhere / "recovered.yaml"
    recovered.write_text(yaml.safe_dump(lock_payload["study"]), encoding="utf-8")
    assert main(["study", "validate", str(recovered)]) == 0
    assert json.loads(capsys.readouterr().out)["study_sha256"] == lock_payload["study_sha256"]
    assert main(["study", "verify", str(recovered), *proof_args, "--lock", str(lock)]) == 0
    assert json.loads(capsys.readouterr().out)["study_source"] == "supplied"
    # A supplied definition that disagrees with the retained one is refused.
    assert main(["study", "verify", _LIVE_STUDY, *proof_args, "--lock", str(lock)]) != 0
    # Reproduction output stays exclusive.
    assert (
        main(["study", "verify", *proof_args, "--lock", str(lock), "--output", str(reproduced)])
        != 0
    )
    assert reproduced.read_bytes() == report.read_bytes()
