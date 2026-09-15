"""X4.1 contracts: the study journey is projected, never reinterpreted.

Roadmap X4.1. The operator surface gains study validation, proof-backed
reporting, and lock verification through typed application operations. Every
number, refusal, and caveat comes from ``exposure_report``; the application
layer adds no second statistics or interpretation implementation, and the
console view renders what the operation returns.

The projection must not become a place where a claim grows. A raw-only or smoke
population stays plumbing-only however it is displayed, a reproduced historical
lock stays a reproduction rather than a fresh endorsement, and the refusals the
domain raises reach the operator with their reasons intact.

SUBSTITUTE_JUSTIFICATION
- substitute: disposable populations, run plans, and real private proofs built
  by ``tests.factories`` (``make_exposure_populations``, ``export_exposure_proof``)
  under ``tmp_path``
- replaces: charged BFCL generation and the operator host's retained study proofs
- necessity: invalid populations, unbound raw evidence, and exclusive-output
  collisions must be forced deterministically, and the operator's permanent
  proof store must not be written by a portable test
- real-option: the proofs are exported and verified through the real
  ``proof_bundle`` path, and every number comes from the real
  ``exposure_report`` functions; no projection is stubbed
- proof-limit: proves the application projection, its refusals, and the table
  rendering of a study result; it does not prove NiceGUI rendering, browser
  behavior, or the scientific validity of any study
- real-proof: the retained X2.4 and X3.5 dev-box proofs and their locks, and the
  operator-host journey recorded in docs/roadmap.md
- covered tests: every test in this module
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.application import OperatorOperations
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_report import (
    build_exposure_report,
    validate_exposure_study,
    write_proof_backed_exposure_report,
)
from tests.factories import (
    LIVE_STUDY_ID,
    export_exposure_proof,
    make_exposure_populations,
    make_selected_exposure_rows,
)

_OPS = OperatorOperations()


def _evidence(path: Path, rows) -> Path:
    from bencheval.evidence import JsonlEvidenceSink

    sink = JsonlEvidenceSink()
    for record in rows:
        sink.append_jsonl(path, record)
    return path


def _populations(tmp_path: Path, *, smoke: bool = True) -> tuple[object, Path, Path]:
    study, canonical, candidate = make_exposure_populations(smoke=smoke)
    return (
        study,
        _evidence(tmp_path / "canonical.jsonl", canonical),
        _evidence(tmp_path / "candidate.jsonl", candidate),
    )


def _proof_pair(tmp_path: Path, *, smoke: bool = False) -> tuple[object, Path, Path]:
    study, canonical, candidate = make_exposure_populations(smoke=smoke)
    return (
        study,
        export_exposure_proof(tmp_path / "canonical-proof", canonical),
        export_exposure_proof(tmp_path / "candidate-proof", candidate),
    )


# --- validation projection -------------------------------------------------------------


def test_study_validation_projects_the_domain_payload_exactly() -> None:
    view = _OPS.study_validate(LIVE_STUDY_ID)

    # The operation is a projection: the payload is the domain function's own
    # output, not a re-derived summary.
    assert view.payload == validate_exposure_study(LIVE_STUDY_ID)
    assert view.study_id == LIVE_STUDY_ID
    assert view.study_sha256 == view.payload["study_sha256"]
    assert view.relation == view.payload["relation"]
    assert view.comparison_mode == view.payload["comparison_mode"]


def test_unknown_study_is_refused_with_the_domain_reason() -> None:
    with pytest.raises(BenchEvalError):
        _OPS.study_validate("no-such-study")


# --- raw-only reporting ----------------------------------------------------------------


def test_raw_only_report_projects_the_domain_report_and_writes_it_once(tmp_path: Path) -> None:
    study, canonical, candidate = _populations(tmp_path)
    output = tmp_path / "report.json"

    view = _OPS.study_report(
        LIVE_STUDY_ID,
        canonical_evidence=canonical,
        candidate_evidence=candidate,
        analysis="raw_only",
        output=output,
        fmt="json",
    )

    _, canonical_rows, candidate_rows = make_exposure_populations()
    expected = build_exposure_report(
        study,  # type: ignore[arg-type]
        canonical=canonical_rows,
        candidate=candidate_rows,
        analysis="raw_only",
    )
    assert view.payload == expected.payload
    assert view.report_sha256 == expected.sha256
    assert view.analysis_mode == "plumbing_only"
    assert view.lock_sha256 is None
    assert json.loads(output.read_text(encoding="utf-8")) == expected.payload
    # Exclusive output: a second run over the same path refuses rather than
    # overwriting a retained artifact.
    with pytest.raises(BenchEvalError):
        _OPS.study_report(
            LIVE_STUDY_ID,
            canonical_evidence=canonical,
            candidate_evidence=candidate,
            analysis="raw_only",
            output=output,
            fmt="json",
        )


def test_raw_evidence_cannot_be_reported_as_a_declared_population(tmp_path: Path) -> None:
    _, canonical, candidate = _populations(tmp_path)
    output = tmp_path / "report.json"

    with pytest.raises(BenchEvalError, match="declared analysis requires proof-backed inputs"):
        _OPS.study_report(
            LIVE_STUDY_ID,
            canonical_evidence=canonical,
            candidate_evidence=candidate,
            analysis="declared",
            output=output,
            fmt="json",
        )

    assert not output.exists()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"analysis": "raw_only"},
        {
            "canonical_evidence": Path("a.jsonl"),
            "canonical_proof": Path("p"),
            "analysis": "raw_only",
        },
        {"canonical_evidence": Path("a.jsonl"), "analysis": "raw_only"},
    ],
    ids=["no-inputs", "mixed-input-kinds", "half-a-pair"],
)
def test_report_needs_exactly_one_complete_input_pair(kwargs, tmp_path: Path) -> None:
    with pytest.raises(BenchEvalError, match="exactly one input pair"):
        _OPS.study_report(LIVE_STUDY_ID, output=tmp_path / "report.json", fmt="json", **kwargs)


def test_lock_output_without_proof_inputs_is_refused(tmp_path: Path) -> None:
    _, canonical, candidate = _populations(tmp_path)

    with pytest.raises(BenchEvalError, match="proof-backed"):
        _OPS.study_report(
            LIVE_STUDY_ID,
            canonical_evidence=canonical,
            candidate_evidence=candidate,
            analysis="raw_only",
            output=tmp_path / "report.json",
            lock_output=tmp_path / "lock.json",
            fmt="json",
        )


# --- proof-backed reporting and reproduction --------------------------------------------


def test_proof_backed_report_writes_report_and_lock_and_projects_both_digests(
    tmp_path: Path,
) -> None:
    _, canonical_proof, candidate_proof = _proof_pair(tmp_path)
    output = tmp_path / "report.json"
    lock_output = tmp_path / "lock.json"

    view = _OPS.study_report(
        LIVE_STUDY_ID,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis="raw_only",
        output=output,
        lock_output=lock_output,
        fmt="json",
    )

    assert output.is_file() and lock_output.is_file()
    assert view.report_sha256 and view.lock_sha256
    assert view.report_path == str(output.resolve())
    assert view.lock_path == str(lock_output.resolve())
    assert view.population_binding is not None
    lock = json.loads(lock_output.read_text(encoding="utf-8"))
    assert lock["report_sha256"] == view.report_sha256


def test_proof_backed_report_requires_both_output_paths(tmp_path: Path) -> None:
    _, canonical_proof, candidate_proof = _proof_pair(tmp_path)

    with pytest.raises(BenchEvalError, match=r"requires both output paths"):
        _OPS.study_report(
            LIVE_STUDY_ID,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            analysis="raw_only",
            output=tmp_path / "report.json",
            fmt="json",
        )


def test_copied_proof_reproduction_verifies_the_lock_without_upgrading_the_claim(
    tmp_path: Path,
) -> None:
    _, canonical_proof, candidate_proof = _proof_pair(tmp_path)
    report = tmp_path / "report.json"
    lock = tmp_path / "lock.json"
    built = write_proof_backed_exposure_report(
        __import__(
            "bencheval.exposure_study", fromlist=["load_exposure_study"]
        ).load_exposure_study(LIVE_STUDY_ID),
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis="raw_only",
        output=report,
        lock_output=lock,
        fmt="json",
    )

    reproduced = tmp_path / "reproduced.json"
    view = _OPS.study_verify(
        lock,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        study=LIVE_STUDY_ID,
        output=reproduced,
    )

    assert view.ok is True
    assert view.report_sha256 == built.report_sha256
    assert view.lock_sha256 == built.lock_sha256
    # Reproducing a retained lock is a reproduction, never a new endorsement:
    # the rebuilt report is the locked one, and its claim travels unchanged.
    assert view.report_payload == built.report.payload
    assert view.analysis_mode == built.report.payload["analysis_mode"]
    assert view.non_claims == tuple(built.report.payload["forbidden_claims"])
    assert json.loads(reproduced.read_text(encoding="utf-8")) == built.report.payload
    labels = {row["field"]: row["value"] for row in view.table_rows()}
    assert labels["reproduced"] == "yes"
    assert labels["analysis mode"] == built.report.payload["analysis_mode"]


def test_reproduction_of_a_tampered_lock_refuses(tmp_path: Path) -> None:
    _, canonical_proof, candidate_proof = _proof_pair(tmp_path)
    report = tmp_path / "report.json"
    lock = tmp_path / "lock.json"
    write_proof_backed_exposure_report(
        __import__(
            "bencheval.exposure_study", fromlist=["load_exposure_study"]
        ).load_exposure_study(LIVE_STUDY_ID),
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis="raw_only",
        output=report,
        lock_output=lock,
        fmt="json",
    )
    payload = json.loads(lock.read_text(encoding="utf-8"))
    payload["report_sha256"] = "sha256:" + "0" * 64
    lock.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(BenchEvalError):
        _OPS.study_verify(
            lock,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            study=LIVE_STUDY_ID,
        )


# --- what the operator sees --------------------------------------------------------------


def test_study_result_renders_as_keyboard_reachable_rows(tmp_path: Path) -> None:
    _, canonical, candidate = _populations(tmp_path)
    view = _OPS.study_report(
        LIVE_STUDY_ID,
        canonical_evidence=canonical,
        candidate_evidence=candidate,
        analysis="raw_only",
        output=tmp_path / "report.json",
        fmt="json",
    )

    rows = view.table_rows()
    labels = {row["field"]: row["value"] for row in rows}
    # Every table row is a plain label/value pair a keyboard table can render.
    assert all(set(row) == {"field", "value"} for row in rows)
    assert labels["relation"] == view.payload["relation"]
    assert labels["analysis mode"] == "plumbing_only"
    assert labels["population scale"] == view.payload["population_scale"]
    assert "raw" in labels["population binding"].lower() or labels["population binding"] == "none"
    # Native per-side scores reach the operator with their intervals.
    assert view.payload["canonical"]["benchmark_id"] in labels["canonical"]
    assert view.payload["candidate"]["benchmark_id"] in labels["candidate"]
    # Non-claims and caveats are shown, never summarized away.
    assert view.non_claims == tuple(view.payload["forbidden_claims"])
    assert view.caveats == tuple(view.payload["caveats"])
    assert view.permitted_interpretation == view.payload["permitted_interpretation"]


def test_paired_study_projects_flips_and_uncertainty_from_the_domain_report(
    tmp_path: Path,
) -> None:
    from tests.factories import PAIR_STUDY_ID

    _, canonical, candidate = make_exposure_populations(PAIR_STUDY_ID, smoke=True)
    canonical_path = _evidence(tmp_path / "canonical.jsonl", canonical)
    candidate_path = _evidence(tmp_path / "candidate.jsonl", candidate)

    view = _OPS.study_report(
        PAIR_STUDY_ID,
        canonical_evidence=canonical_path,
        candidate_evidence=candidate_path,
        analysis="raw_only",
        output=tmp_path / "report.json",
        fmt="json",
    )

    assert view.pairs == view.payload.get("pairs")
    assert view.pairs is not None
    labels = {row["field"]: row["value"] for row in view.table_rows()}
    assert "pairs" in labels


@pytest.mark.parametrize(
    "field",
    ["output", "lock_output"],
    ids=["report-output", "lock-output"],
)
def test_study_writes_reject_symlink_redirects(field: str, tmp_path: Path) -> None:
    _, canonical_proof, candidate_proof = _proof_pair(tmp_path)
    redirect = tmp_path / "redirect"
    redirect.mkdir()
    link = tmp_path / "link"
    link.symlink_to(redirect, target_is_directory=True)
    paths = {
        "output": tmp_path / "report.json",
        "lock_output": tmp_path / "lock.json",
        field: link / "redirected.json",
    }

    with pytest.raises(BenchEvalError, match="symlink"):
        _OPS.study_report(
            LIVE_STUDY_ID,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            analysis="raw_only",
            fmt="json",
            **paths,
        )

    assert list(redirect.iterdir()) == []


def test_reproduction_output_rejects_a_symlink_redirect(tmp_path: Path) -> None:
    _, canonical_proof, candidate_proof = _proof_pair(tmp_path)
    lock = tmp_path / "lock.json"
    _OPS.study_report(
        LIVE_STUDY_ID,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis="raw_only",
        output=tmp_path / "report.json",
        lock_output=lock,
        fmt="json",
    )
    redirect = tmp_path / "redirect"
    redirect.mkdir()
    link = tmp_path / "link"
    link.symlink_to(redirect, target_is_directory=True)

    with pytest.raises(BenchEvalError, match="symlink"):
        _OPS.study_verify(
            lock,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            study=LIVE_STUDY_ID,
            output=link / "reproduced.json",
        )

    assert list(redirect.iterdir()) == []


# --- declared analysis -------------------------------------------------------------------


def test_declared_journey_projects_the_bound_population_and_its_difference(
    tmp_path: Path,
) -> None:
    """The only journey that may carry a rate difference, end to end.

    A declared population needs proof-backed inputs, the retained selection, and
    the full declared counts. The projection must then carry the domain's own
    difference, interval, and binding without recomputing any of them.
    """
    _, canonical, selection = make_selected_exposure_rows(
        "canonical", passes=10, run_id="run-canonical"
    )
    _, candidate, _ = make_selected_exposure_rows("candidate", passes=4, run_id="run-candidate")
    selection_path = tmp_path / "selection.json"
    selection_path.write_text(json.dumps(selection.model_dump(mode="json")), encoding="utf-8")
    canonical_proof = export_exposure_proof(tmp_path / "canonical-proof", canonical)
    candidate_proof = export_exposure_proof(tmp_path / "candidate-proof", candidate)

    view = _OPS.study_report(
        LIVE_STUDY_ID,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis="declared",
        output=tmp_path / "report.json",
        lock_output=tmp_path / "lock.json",
        selection=selection_path,
        fmt="json",
    )

    assert view.analysis_mode == "declared_population"
    assert view.population_scale == "declared"
    assert view.population_binding is not None and len(view.population_binding) == 2
    difference = view.payload["difference"]
    assert difference["method"] == "newcombe_95"
    labels = {row["field"]: row["value"] for row in view.table_rows()}
    # Every number in the difference row is the domain's, verbatim.
    for key, value in difference.items():
        assert f"{key}={value}" in labels["difference"]
    canonical_overall = view.payload["canonical"]["overall"]
    assert f"{canonical_overall['passed']}/{canonical_overall['eligible']}" in labels["canonical"]
    rate = canonical_overall["rate"]
    assert f"{rate['point']:.3f}" in labels["canonical"]
    assert labels["population binding"] == ", ".join(view.population_binding)
    assert view.non_claims == tuple(view.payload["forbidden_claims"])


def test_declared_analysis_without_the_retained_selection_is_refused(tmp_path: Path) -> None:
    _, canonical, _ = make_selected_exposure_rows("canonical", passes=10, run_id="run-canonical")
    _, candidate, _ = make_selected_exposure_rows("candidate", passes=4, run_id="run-candidate")
    output = tmp_path / "report.json"

    with pytest.raises(BenchEvalError, match="selection"):
        _OPS.study_report(
            LIVE_STUDY_ID,
            canonical_proof=export_exposure_proof(tmp_path / "canonical-proof", canonical),
            candidate_proof=export_exposure_proof(tmp_path / "candidate-proof", candidate),
            analysis="declared",
            output=output,
            lock_output=tmp_path / "lock.json",
            fmt="json",
        )

    assert not output.exists()


def test_reproduction_without_a_written_report_says_so_instead_of_showing_a_bare_table(
    tmp_path: Path,
) -> None:
    """Verification alone proves the reproduction; it does not restate the claim."""
    _, canonical_proof, candidate_proof = _proof_pair(tmp_path)
    lock = tmp_path / "lock.json"
    _OPS.study_report(
        LIVE_STUDY_ID,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis="raw_only",
        output=tmp_path / "report.json",
        lock_output=lock,
        fmt="json",
    )

    view = _OPS.study_verify(
        lock,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        study=LIVE_STUDY_ID,
    )

    assert view.ok is True
    assert view.report_payload is None
    assert view.analysis_mode is None
    labels = {row["field"]: row["value"] for row in view.table_rows()}
    assert "report" in labels
    assert "digests match" in labels["report"]


@pytest.mark.parametrize(
    "payload",
    [
        {"relation": "freshness_contrast"},
        {
            "study_id": "s",
            "relation": "r",
            "comparison_mode": "c",
            "analysis_mode": "a",
            "population_scale": "p",
            "retrieval_observed": False,
            "canonical": "not an object",
        },
    ],
    ids=["missing-field", "side-is-not-an-object"],
)
def test_a_report_shape_the_projection_cannot_render_fails_as_an_operator_error(payload) -> None:
    """A renamed or dropped domain field must not reach the operator as a blank cell.

    It also must not escape as an exception type the frontends do not handle:
    every operator-facing failure in this surface is a ``BenchEvalError``.
    """
    from bencheval.application.dto import _study_table_rows

    with pytest.raises(BenchEvalError):
        _study_table_rows(payload)
