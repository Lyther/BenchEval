"""Paired representation-study report contracts: variant binding, pairs, and the lock.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed BFCL evidence rows for both sides of the checked-in
  tool-order selection, complete disposable proofs (`_proof_from_rows`), and a
  variant manifest plus the two derived data files rendered from a
  substitute-package overlay (200 synthetic rows per category so every selected
  id exists) whose identity binds the real catalog source pins (`_variant`)
- replaces: the charged canonical and derived official runs and their proofs
- necessity: missing, drifted, re-seeded, and mismatched variant manifests,
  missing or altered derived files, and asymmetric pairs must be forced
  deterministically without paying a provider
- real-option: none; the X3.5 dev-box plumbing pair is the real proof of this
  path over official bytes
- proof-limit: proves report/lock binding and pairing arithmetic only
- real-proof: X3.5 dev-box tool-order plumbing pair and the reviewed 200+200 study
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from bencheval.benchmark_registry import BfclPackageDataIdentity
from bencheval.bfcl_study import materialize_tool_order_overlay, render_variant_manifest
from bencheval.cli import main
from bencheval.evidence import EvidenceRecord
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_report import (
    build_exposure_report,
    verify_exposure_study_lock,
    write_proof_backed_exposure_report,
)
from bencheval.exposure_selection import ExposureSelection, load_exposure_selection
from bencheval.exposure_study import (
    ExposureStudyManifest,
    build_bfcl_derived_data_identity,
    default_studies_dir,
    load_exposure_study,
)
from bencheval.identity_strings import catalog_benchmark_identity
from tests.specs.test_bfcl_study_contracts import _row as _bfcl_row
from tests.specs.test_bfcl_study_contracts import _substitute_package
from tests.specs.test_exposure_report_contracts import _benchmark_version, _proof_from_rows, _row

_PAIR = "bfcl-v4-tool-order-v1"
_VARIANT_REL = "study/variant-manifest.json"
_DERIVED_DIR = "overlay/pkg/bfcl_eval"
_DERIVED_RELS = ("data/BFCL_v4_multiple.json", "data/BFCL_v4_parallel_multiple.json")
_DERIVED_PATHS = tuple(f"{_DERIVED_DIR}/{rel}" for rel in _DERIVED_RELS)


def _study_and_selection() -> tuple[ExposureStudyManifest, ExposureSelection]:
    return load_exposure_study(_PAIR), load_exposure_selection(
        default_studies_dir() / f"{_PAIR}.selection.json"
    )


def _full_rows(count: int = 200) -> dict[str, list[dict[str, object]]]:
    return {
        "multiple": [_bfcl_row("multiple", i, 2 + i % 3) for i in range(count)],
        "parallel_multiple": [_bfcl_row("parallel_multiple", i, 2 + i % 2) for i in range(count)],
    }


def _variant(
    tmp_path: Path,
    study: ExposureStudyManifest,
    selection: ExposureSelection,
    *,
    seed: str | None = None,
    rows: dict[str, list[dict[str, object]]] | None = None,
) -> dict[str, str]:
    """Raw-relative proof files: the manifest and the overlay's derived data files.

    The overlay comes from a substitute package; the identity binds the real
    catalog source pins.
    """
    rows = rows or _full_rows()
    _substitute_package(tmp_path / "site", rows=rows)
    overlay = materialize_tool_order_overlay(
        package_root=tmp_path / "site" / "bfcl_eval",
        identity=_substitute_package(tmp_path / "site2", rows=rows),
        seed=seed or study.population.seed,
        output_root=tmp_path / "overlay",
    )
    source = catalog_benchmark_identity("bfcl-v4")
    assert isinstance(source, BfclPackageDataIdentity)
    identity = build_bfcl_derived_data_identity(
        study=study,
        source_identity=source,
        source_mapping={i: i for i in selection.candidate.selected_ids},
        derived_data_sha256=overlay.derived_data_sha256,
    )
    if seed is not None:
        identity = identity.model_copy(update={"seed": seed})
    files = {_VARIANT_REL: render_variant_manifest(identity, overlay)}
    for rel in _DERIVED_RELS:
        files[f"{_DERIVED_DIR}/{rel}"] = (overlay.package_dir / rel).read_text(encoding="utf-8")
    return files


def _rows(
    selection: ExposureSelection,
    side: str,
    *,
    version: str,
    passes: set[str],
    run_id: str,
    with_variant: bool = True,
    references: tuple[str, ...] | None = None,
) -> list[EvidenceRecord]:
    bound = getattr(selection, side)
    if references is None:
        references = (_VARIANT_REL, *_DERIVED_PATHS)
    return [
        _row(
            benchmark_id=bound.benchmark_id,
            slice_id=bound.slice_id,
            instance_id=instance_id,
            primary_pass=instance_id in passes,
            run_id=run_id,
            benchmark_version=version,
            # A real derived row references the manifest and both derived files
            # so private proof retains them.
            artifact_paths=["raw/score.json", *references]
            if side == "candidate" and with_variant
            else ["raw/score.json"],
        )
        for name in sorted(bound.strata)
        for instance_id in bound.strata[name].selected_ids
    ]


def _pair(tmp_path: Path) -> tuple[ExposureStudyManifest, ExposureSelection, Path, Path, str]:
    study, selection = _study_and_selection()
    files = _variant(tmp_path, study, selection)
    version = json.loads(files[_VARIANT_REL])["benchmark_version"]
    ids = list(selection.canonical.selected_ids)
    canonical = _rows(
        selection,
        "canonical",
        version=_benchmark_version("bfcl-v4"),
        passes=set(ids[:150]),
        run_id="run-canonical",
    )
    candidate = _rows(
        selection, "candidate", version=version, passes=set(ids[20:160]), run_id="run-candidate"
    )
    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate, extra_raw=files)
    return study, selection, canonical_proof, candidate_proof, version


def test_paired_declared_report_binds_the_retained_variant_and_reproduces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    study, selection, canonical_proof, candidate_proof, version = _pair(tmp_path)
    built = write_proof_backed_exposure_report(
        study,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis="declared",
        output=tmp_path / "report.json",
        lock_output=tmp_path / "lock.json",
        fmt="json",
        selection=selection,
    )
    payload = built.report.payload
    assert payload["analysis_mode"] == "declared_population"
    assert payload["comparison_mode"] == "paired_by_source_instance"
    assert payload["variant"]["benchmark_version"] == version
    assert payload["variant"]["transform_id"] == "bfcl-tool-order"
    assert payload["candidate"]["benchmark_id"] == _PAIR
    pairs = payload["pairs"]
    assert pairs["eligible"] == 200
    assert pairs["both_pass"] == 130 and pairs["canonical_only_pass"] == 20
    assert pairs["candidate_only_pass"] == 10 and pairs["both_fail"] == 40
    assert payload["paired_delta"] == pytest.approx((10 - 20) / 200)
    assert payload["paired_test"]["method"] == "exact_binomial"
    assert payload["paired_test"]["discordant_pairs"] == 30
    assert 0.0 < payload["paired_test"]["p_value"] < 1.0
    lock = built.lock_payload
    assert lock["variant_sha256"] == payload["variant"]["variant_sha256"]
    assert lock["variant"]["benchmark_version"] == version
    assert lock["selection_sha256"] == payload["population_selection"]["selection_sha256"]

    copied = tmp_path / "copied"
    shutil.copytree(canonical_proof, copied / "canonical")
    shutil.copytree(candidate_proof, copied / "candidate")
    shutil.copy2(tmp_path / "lock.json", copied / "lock.json")
    monkeypatch.chdir(copied)
    assert (
        main(
            [
                "study",
                "verify",
                "--canonical-proof",
                str(copied / "canonical"),
                "--candidate-proof",
                str(copied / "candidate"),
                "--lock",
                str(copied / "lock.json"),
                "--output",
                str(copied / "reproduced.json"),
            ]
        )
        == 0
    )
    verified = json.loads(capsys.readouterr().out)
    assert verified["report_sha256"] == built.report_sha256
    assert (copied / "reproduced.json").read_bytes() == (tmp_path / "report.json").read_bytes()

    original = json.loads((tmp_path / "lock.json").read_text(encoding="utf-8"))

    def _mutated(mutate: Callable[[dict], None]) -> Path:
        p = json.loads(json.dumps(original))
        mutate(p)
        path = copied / "mutated.json"
        path.write_text(json.dumps(p, sort_keys=True), encoding="utf-8")
        return path

    for mutate in (
        lambda p: p.__setitem__("variant_sha256", "sha256:" + "0" * 64),
        lambda p: p.pop("variant"),
        lambda p: p["variant"]["identity"].__setitem__("seed", "x"),
    ):
        with pytest.raises(BenchEvalError):
            verify_exposure_study_lock(
                None,
                lock_path=_mutated(mutate),
                canonical_proof=copied / "canonical",
                candidate_proof=copied / "candidate",
            )


def test_derived_candidate_stays_raw_only_without_a_retained_variant(tmp_path: Path) -> None:
    study, selection = _study_and_selection()
    files = _variant(tmp_path, study, selection)
    version = json.loads(files[_VARIANT_REL])["benchmark_version"]
    ids = list(selection.canonical.selected_ids)
    canonical = _rows(
        selection,
        "canonical",
        version=_benchmark_version("bfcl-v4"),
        passes=set(ids[:150]),
        run_id="run-canonical",
    )
    candidate = _rows(
        selection,
        "candidate",
        version=version,
        passes=set(ids[:150]),
        run_id="run-candidate",
        with_variant=False,
    )
    # Raw evidence: counts only, never a paired delta or test.
    payload = build_exposure_report(
        study, canonical=canonical, candidate=candidate, analysis="raw_only", selection=selection
    ).payload
    assert payload["analysis_mode"] == "plumbing_only"
    assert "paired_delta" not in payload and "variant" not in payload
    assert payload["pairs"]["both_pass"] == 150
    # A complete proof without the manifest cannot unlock declared analysis.
    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate)
    with pytest.raises(BenchEvalError, match="variant"):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            analysis="declared",
            output=tmp_path / "r.json",
            lock_output=tmp_path / "l.json",
            fmt="json",
            selection=selection,
        )
    assert not (tmp_path / "r.json").exists()


@pytest.mark.parametrize(
    ("label", "seed", "version_override", "match"),
    [
        ("reseeded identity", "another-seed", None, "seed"),
        ("label drift", None, "bfcl-v4-tool-order-v1@derived-" + "e" * 64, "derived identity"),
    ],
)
def test_variant_binding_rejects_mismatched_manifests(
    tmp_path: Path, label: str, seed: str | None, version_override: str | None, match: str
) -> None:
    study, selection = _study_and_selection()
    files = _variant(tmp_path, study, selection, seed=seed)
    version = version_override or json.loads(files[_VARIANT_REL])["benchmark_version"]
    ids = list(selection.canonical.selected_ids)
    canonical = _rows(
        selection,
        "canonical",
        version=_benchmark_version("bfcl-v4"),
        passes=set(ids[:150]),
        run_id="run-canonical",
    )
    candidate = _rows(
        selection, "candidate", version=version, passes=set(ids[:150]), run_id="run-candidate"
    )
    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate, extra_raw=files)
    with pytest.raises(BenchEvalError, match=match):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            analysis="raw_only",
            output=tmp_path / "r.json",
            lock_output=tmp_path / "l.json",
            fmt="json",
            selection=selection,
        )
    assert not (tmp_path / "r.json").exists(), label


def _retained(tmp_path: Path) -> dict[str, str]:
    raw = tmp_path / "candidate" / "raw"
    return {rel: (raw / rel).read_text(encoding="utf-8") for rel in (_VARIANT_REL, *_DERIVED_PATHS)}


def _candidate_rows(
    selection: ExposureSelection, version: str, *, references: tuple[str, ...] | None = None
) -> list[EvidenceRecord]:
    ids = list(selection.canonical.selected_ids)
    return _rows(
        selection,
        "candidate",
        version=version,
        passes=set(ids[:10]),
        run_id="run-candidate",
        references=references,
    )


def _expect_rejected(
    tmp_path: Path,
    study: ExposureStudyManifest,
    selection: ExposureSelection,
    canonical_proof: Path,
    candidate_proof: Path,
    *,
    match: str,
) -> None:
    with pytest.raises(BenchEvalError, match=match):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            analysis="declared",
            output=tmp_path / "r.json",
            lock_output=tmp_path / "l.json",
            fmt="json",
            selection=selection,
        )
    assert not (tmp_path / "r.json").exists()


def test_declared_pair_requires_every_declared_derived_file(tmp_path: Path) -> None:
    """A manifest alone is not the measured representation; the derived bytes must be in proof."""
    study, selection, canonical_proof, _candidate_proof, version = _pair(tmp_path)
    files = _retained(tmp_path)
    # Rows that reference only what the proof retains: the proof exports cleanly,
    # so the report is the gate that must notice the missing representation.
    for path in _DERIVED_PATHS:
        partial = {k: v for k, v in files.items() if k != path}
        proof = _proof_from_rows(
            tmp_path / f"missing-{path.replace('/', '-')}",
            _candidate_rows(selection, version, references=tuple(partial)),
            extra_raw=partial,
        )
        _expect_rejected(
            tmp_path, study, selection, canonical_proof, proof, match="does not retain"
        )
    manifest_only = _proof_from_rows(
        tmp_path / "manifest-only",
        _candidate_rows(selection, version, references=(_VARIANT_REL,)),
        extra_raw={_VARIANT_REL: files[_VARIANT_REL]},
    )
    _expect_rejected(
        tmp_path, study, selection, canonical_proof, manifest_only, match="does not retain"
    )


def test_declared_pair_rejects_derived_files_that_do_not_match_the_manifest(
    tmp_path: Path,
) -> None:
    study, selection, canonical_proof, _candidate_proof, version = _pair(tmp_path)
    files = _retained(tmp_path)
    altered = dict(files)
    key = f"{_DERIVED_DIR}/{_DERIVED_RELS[0]}"
    first, rest = altered[key].split("\n", 1)
    row = json.loads(first)
    row["function"].reverse()  # a different order than the manifest's digest binds
    altered[key] = json.dumps(row, ensure_ascii=False) + "\n" + rest
    proof = _proof_from_rows(
        tmp_path / "altered", _candidate_rows(selection, version), extra_raw=altered
    )
    _expect_rejected(
        tmp_path, study, selection, canonical_proof, proof, match="does not match the variant"
    )


def test_declared_pair_rejects_derived_files_lacking_the_mapped_ids(tmp_path: Path) -> None:
    """Digest-consistent files that omit selected ids cannot be the measured representation."""
    study, selection = _study_and_selection()
    files = _variant(tmp_path, study, selection, rows=_full_rows(count=40))
    version = json.loads(files[_VARIANT_REL])["benchmark_version"]
    ids = list(selection.canonical.selected_ids)
    canonical = _rows(
        selection,
        "canonical",
        version=_benchmark_version("bfcl-v4"),
        passes=set(ids[:150]),
        run_id="run-canonical",
    )
    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    proof = _proof_from_rows(
        tmp_path / "short", _candidate_rows(selection, version), extra_raw=files
    )
    _expect_rejected(
        tmp_path, study, selection, canonical_proof, proof, match="mapped instance ids"
    )


def test_variant_manifest_without_benchmark_version_is_a_report_error(tmp_path: Path) -> None:
    study, selection, canonical_proof, _candidate_proof, version = _pair(tmp_path)
    files = _retained(tmp_path)
    manifest = json.loads(files[_VARIANT_REL])
    del manifest["benchmark_version"]
    files[_VARIANT_REL] = json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    proof = _proof_from_rows(
        tmp_path / "no-version", _candidate_rows(selection, version), extra_raw=files
    )
    _expect_rejected(tmp_path, study, selection, canonical_proof, proof, match="benchmark_version")


def test_asymmetric_pair_is_rejected_even_with_a_valid_variant(tmp_path: Path) -> None:
    study, selection, canonical_proof, _candidate_proof, version = _pair(tmp_path)
    dropped = _candidate_rows(selection, version)[1:]
    dropped_proof = _proof_from_rows(tmp_path / "dropped", dropped, extra_raw=_retained(tmp_path))
    with pytest.raises(BenchEvalError):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=canonical_proof,
            candidate_proof=dropped_proof,
            analysis="declared",
            output=tmp_path / "r.json",
            lock_output=tmp_path / "l.json",
            fmt="json",
            selection=selection,
        )
    assert not (tmp_path / "r.json").exists()
