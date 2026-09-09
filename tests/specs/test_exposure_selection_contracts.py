"""Behavioral contracts for the deterministic BFCL exposure population selector.

SUBSTITUTE_JUSTIFICATION
- substitute: a disposable ``bfcl_eval``-shaped package tree with synthetic
  question ids and a matching pin identity (`_substitute_package`), plus
  constructed evidence rows and complete proofs built from a selection
  (`_rows_for`, `_proof_for`)
- replaces: the installed pinned bfcl-eval data files, the catalog identity,
  and charged official generate/evaluate evidence for 696 cases
- necessity: duplicate ids, wrong-category ids, missing files, pin drift,
  insufficient populations, same-count substitutions, tampered records, and
  lock/selection drift must be forced deterministically without mutating the
  installed package or paying a provider
- real-option: none; the real package cannot be made to carry duplicates or
  drift without mutation, and a charged run cannot be steered into a
  cherry-picked population
- proof-limit: proves ranking determinism, source binding, record replay, slice
  rendering, and report/lock enforcement only; it proves nothing about the
  real population or the model
- real-proof: the X2.4 dev-box materialization from the pinned package and the
  X2.4b FC study pair with declared report and copied-proof verification
- covered tests: every test in this module
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from bencheval.benchmark_registry import BfclPackageDataIdentity, BfclPopulationPin
from bencheval.cli import main
from bencheval.evidence import EvidenceRecord
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_report import (
    build_exposure_report,
    verify_exposure_study_lock,
    write_proof_backed_exposure_report,
)
from bencheval.exposure_selection import (
    SELECTION_ALGORITHM,
    SELECTION_SCHEMA,
    ExposureSelection,
    SelectionSource,
    SelectionStratumSource,
    build_exposure_selection,
    exposure_selection_sha256,
    load_exposure_selection,
    materialize_exposure_selection,
    parse_exposure_selection,
    population_ids_sha256,
    rank_digest,
    select_stratum,
    write_selection_outputs,
)
from bencheval.exposure_study import (
    ExposureStudyManifest,
    default_studies_dir,
    exposure_study_sha256,
    load_exposure_study,
)
from bencheval.identity_strings import bfcl_benchmark_identity
from bencheval.slice_manifest import load_slice_manifest
from tests.specs.test_exposure_report_contracts import (
    _LIVE_STUDY,
    _benchmark_version,
    _proof_from_rows,
    _row,
)

_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"


def _pool(stratum: str, size: int) -> list[str]:
    return [f"{stratum}_{i}-0-0" for i in range(size)]


def _pools(study: ExposureStudyManifest, *, spare: int = 5) -> dict[str, dict[str, list[str]]]:
    return {
        study.canonical.benchmark_id: {
            s: _pool(s, n + spare) for s, n in study.population.canonical_counts.items()
        },
        study.candidate.benchmark_id: {
            s: _pool(s, n + spare) for s, n in study.population.candidate_counts.items()
        },
    }


def _substitute_package(
    root: Path, pools: dict[str, dict[str, list[str]]]
) -> dict[str, BfclPackageDataIdentity]:
    """Write ``data/BFCL_v4_<stratum>.json`` JSONL files and pin them."""
    identities: dict[str, BfclPackageDataIdentity] = {}
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    for benchmark_id, strata in pools.items():
        files: dict[str, str] = {}
        for stratum, ids in strata.items():
            rel = f"data/BFCL_v4_{stratum}.json"
            text = "".join(json.dumps({"id": i, "question": [[]]}) + "\n" for i in ids)
            (root / rel).write_text(text, encoding="utf-8")
            files[rel] = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        identities[benchmark_id] = BfclPackageDataIdentity(
            kind="bfcl-package-data",
            bfcl_eval_version="2026.3.23",
            upstream_commit=_COMMIT,
            files=files,
            populations={
                f"data/BFCL_v4_{stratum}.json": BfclPopulationPin(
                    count=len(set(ids)), ids_sha256=population_ids_sha256(ids)
                )
                for stratum, ids in strata.items()
            },
        )
    return identities


def _sources_from_pools(
    study: ExposureStudyManifest, pools: dict[str, dict[str, list[str]]]
) -> dict[str, SelectionSource]:
    """Sources carrying the catalog benchmark_version so rows built by `_row` bind."""
    out: dict[str, SelectionSource] = {}
    for side in ("canonical", "candidate"):
        declared = getattr(study, side)
        strata = pools[declared.benchmark_id]
        out[side] = SelectionSource(
            benchmark_version=_benchmark_version(declared.benchmark_id),
            strata={
                name: SelectionStratumSource(
                    source_file=f"data/BFCL_v4_{name}.json",
                    source_sha256="sha256:" + hashlib.sha256(name.encode()).hexdigest(),
                    candidate_ids=tuple(ids),
                )
                for name, ids in strata.items()
            },
        )
    return out


def _rows_for(
    selection: ExposureSelection, side: str, *, passes: int, run_id: str
) -> list[EvidenceRecord]:
    bound = getattr(selection, side)
    return [
        _row(
            benchmark_id=bound.benchmark_id,
            slice_id=bound.slice_id,
            instance_id=instance_id,
            primary_pass=index < passes,
            run_id=run_id,
        )
        for stratum in bound.strata.values()
        for index, instance_id in enumerate(stratum.selected_ids)
    ]


def _selection(study: ExposureStudyManifest | None = None) -> ExposureSelection:
    """Synthetic-source selection: valid by construction, never catalog-anchored."""
    study = study or load_exposure_study(_LIVE_STUDY)
    return build_exposure_selection(study, sources=_sources_from_pools(study, _pools(study)))


def _real_selection() -> ExposureSelection:
    """The checked-in record materialized from the pinned package (catalog-anchored)."""
    return load_exposure_selection(default_studies_dir() / f"{_LIVE_STUDY}.selection.json")


def _forged(selection: ExposureSelection, mutate: Callable[[dict], None]) -> ExposureSelection:
    """A record edited after materialization; must still parse so only the binding fails."""
    payload = selection.model_dump(mode="json")
    mutate(payload)
    return parse_exposure_selection(payload, source="forged")


# --- algorithm -------------------------------------------------------------------


def test_rank_is_the_frozen_sha256_formula_and_input_order_independent() -> None:
    seed, benchmark, stratum = "bencheval-bfcl-live-v1", "bfcl-v4", "simple_python"
    expected = hashlib.sha256(
        json.dumps(
            [SELECTION_ALGORITHM, seed, benchmark, stratum, "simple_python_7"],
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    assert (
        rank_digest(
            seed=seed, benchmark_id=benchmark, stratum=stratum, instance_id="simple_python_7"
        )
        == expected
    )

    pool = _pool(stratum, 50)
    chosen = select_stratum(
        seed=seed, benchmark_id=benchmark, stratum=stratum, candidates=pool, count=10
    )
    shuffled = list(pool)
    random.Random(7).shuffle(shuffled)
    assert (
        select_stratum(
            seed=seed, benchmark_id=benchmark, stratum=stratum, candidates=shuffled, count=10
        )
        == chosen
    )
    assert len(chosen) == 10 and len(set(chosen)) == 10 and set(chosen) <= set(pool)
    by_hand = sorted(
        pool,
        key=lambda i: (
            rank_digest(seed=seed, benchmark_id=benchmark, stratum=stratum, instance_id=i),
            i,
        ),
    )[:10]
    assert list(chosen) == by_hand
    # Seed, benchmark, and stratum all participate in the ranking.
    assert (
        select_stratum(
            seed="other", benchmark_id=benchmark, stratum=stratum, candidates=pool, count=10
        )
        != chosen
    )
    assert (
        select_stratum(
            seed=seed, benchmark_id="bfcl-v4-live", stratum=stratum, candidates=pool, count=10
        )
        != chosen
    )
    with pytest.raises(BenchEvalError, match="insufficient"):
        select_stratum(
            seed=seed, benchmark_id=benchmark, stratum=stratum, candidates=pool[:5], count=10
        )
    with pytest.raises(BenchEvalError, match="duplicate"):
        select_stratum(
            seed=seed,
            benchmark_id=benchmark,
            stratum=stratum,
            candidates=[*pool, pool[0]],
            count=10,
        )


# --- materialization from pinned package data -------------------------------------


def test_materialize_reads_pinned_official_ids_and_rejects_bad_sources(tmp_path: Path) -> None:
    study = load_exposure_study(_LIVE_STUDY)
    pools = _pools(study)
    package = tmp_path / "pkg"
    identities = _substitute_package(package, pools)

    selection = materialize_exposure_selection(study, package_root=package, identities=identities)
    assert selection.schema_version == SELECTION_SCHEMA
    assert selection.algorithm == SELECTION_ALGORITHM
    assert selection.seed == study.population.seed
    assert selection.study_id == study.id
    for side, counts in (
        ("canonical", study.population.canonical_counts),
        ("candidate", study.population.candidate_counts),
    ):
        bound = getattr(selection, side)
        declared = getattr(study, side)
        assert bound.benchmark_id == declared.benchmark_id
        assert bound.slice_id == declared.slice_id
        assert bound.benchmark_version == bfcl_benchmark_identity(
            identities[declared.benchmark_id], benchmark_id=declared.benchmark_id
        )
        assert set(bound.strata) == set(counts)
        for name, count in counts.items():
            stratum = bound.strata[name]
            assert stratum.count == count == len(stratum.selected_ids)
            assert stratum.candidate_ids == tuple(sorted(pools[declared.benchmark_id][name]))
            assert (
                stratum.source_sha256
                == identities[declared.benchmark_id].files[stratum.source_file]
            )
            assert tuple(stratum.selected_ids) == select_stratum(
                seed=study.population.seed,
                benchmark_id=declared.benchmark_id,
                stratum=name,
                candidates=stratum.candidate_ids,
                count=count,
            )
    # File order never matters: rewrite one file reversed, keep its pin current.
    rel = "data/BFCL_v4_multiple.json"
    reversed_text = "".join(
        json.dumps({"id": i, "question": [[]]}) + "\n"
        for i in reversed(pools["bfcl-v4"]["multiple"])
    )
    (package / rel).write_text(reversed_text, encoding="utf-8")
    repinned = identities["bfcl-v4"].model_copy(
        update={
            "files": {
                **identities["bfcl-v4"].files,
                rel: "sha256:" + hashlib.sha256(reversed_text.encode()).hexdigest(),
            }
        }
    )
    again = materialize_exposure_selection(
        study, package_root=package, identities={**identities, "bfcl-v4": repinned}
    )
    assert (
        again.canonical.strata["multiple"].selected_ids
        == selection.canonical.strata["multiple"].selected_ids
    )

    def _broken(mutate: Callable[[Path], None], *, match: str) -> None:
        broken = tmp_path / "broken"
        shutil.rmtree(broken, ignore_errors=True)
        ids = _substitute_package(broken, pools)
        mutate(broken)
        with pytest.raises(BenchEvalError, match=match):
            materialize_exposure_selection(study, package_root=broken, identities=ids)

    def _append(path: Path, line: str) -> None:
        path.write_text(path.read_text(encoding="utf-8") + line + "\n", encoding="utf-8")

    _broken(lambda r: _append(r / rel, json.dumps({"id": "multiple_0-0-0"})), match="drift")
    _broken(lambda r: (r / rel).unlink(), match="missing")
    _broken(lambda r: (r / rel).write_text(""), match="drift")

    def _unpinned_variant(mutate: Callable[[Path], None], *, match: str) -> None:
        variant = tmp_path / "variant"
        shutil.rmtree(variant, ignore_errors=True)
        _substitute_package(variant, pools)
        mutate(variant)
        text = (variant / rel).read_text(encoding="utf-8")
        ids = _substitute_package(tmp_path / "scratch", pools)
        raw_ids = (
            [json.loads(line).get("id", "?") for line in text.splitlines() if line.strip()]
            if "not json" not in text
            else ["?"]
        )
        repin = ids["bfcl-v4"].model_copy(
            update={
                "files": {
                    **ids["bfcl-v4"].files,
                    rel: "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                },
                "populations": {
                    **ids["bfcl-v4"].populations,
                    rel: BfclPopulationPin(
                        count=len(set(raw_ids)), ids_sha256=population_ids_sha256(raw_ids)
                    ),
                },
            }
        )
        with pytest.raises(BenchEvalError, match=match):
            materialize_exposure_selection(
                study, package_root=variant, identities={**ids, "bfcl-v4": repin}
            )

    _unpinned_variant(
        lambda r: _append(r / rel, json.dumps({"id": "multiple_0-0-0"})), match="duplicate"
    )
    _unpinned_variant(
        lambda r: _append(r / rel, json.dumps({"id": "parallel_9-0-0"})), match="category"
    )
    _unpinned_variant(lambda r: _append(r / rel, json.dumps({"question": []})), match="id")
    _unpinned_variant(lambda r: _append(r / rel, "not json"), match="JSON")
    short = {**pools, "bfcl-v4": {**pools["bfcl-v4"], "multiple": _pool("multiple", 3)}}
    short_pkg = tmp_path / "short"
    short_ids = _substitute_package(short_pkg, short)
    with pytest.raises(BenchEvalError, match="insufficient"):
        materialize_exposure_selection(study, package_root=short_pkg, identities=short_ids)
    missing_pin = identities["bfcl-v4"].model_copy(
        update={"files": {k: v for k, v in identities["bfcl-v4"].files.items() if k != rel}}
    )
    with pytest.raises(BenchEvalError, match="pinned"):
        materialize_exposure_selection(
            study, package_root=package, identities={**identities, "bfcl-v4": missing_pin}
        )
    # The candidate universe must equal the catalog anchor derived from the pinned bytes.
    wrong_anchor = repinned.model_copy(
        update={
            "populations": {
                **repinned.populations,
                rel: BfclPopulationPin(count=1, ids_sha256="sha256:" + "0" * 64),
            }
        }
    )
    with pytest.raises(BenchEvalError, match="population anchor"):
        materialize_exposure_selection(
            study, package_root=package, identities={**identities, "bfcl-v4": wrong_anchor}
        )
    no_anchor = repinned.model_copy(update={"populations": {}})
    with pytest.raises(BenchEvalError, match="population anchor"):
        materialize_exposure_selection(
            study, package_root=package, identities={**identities, "bfcl-v4": no_anchor}
        )


# --- record ------------------------------------------------------------------------


def test_selection_record_round_trips_and_rejects_tampering(tmp_path: Path) -> None:
    selection = _selection()
    record = tmp_path / "selection.json"
    record.write_text(
        json.dumps(selection.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
    )
    loaded = load_exposure_selection(record)
    assert loaded == selection
    assert exposure_selection_sha256(loaded) == exposure_selection_sha256(selection)

    def _tampered(mutate: Callable[[dict], None]) -> Path:
        payload = json.loads(record.read_text(encoding="utf-8"))
        mutate(payload)
        path = tmp_path / "tampered.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    stratum = "simple_python"
    canon = selection.canonical.strata[stratum]
    unselected = next(i for i in canon.candidate_ids if i not in canon.selected_ids)

    def _swap(p: dict) -> None:
        ids = p["canonical"]["strata"][stratum]["selected_ids"]
        ids[0] = unselected

    with pytest.raises(BenchEvalError, match="replay"):
        load_exposure_selection(_tampered(_swap))
    with pytest.raises(BenchEvalError, match="replay"):
        load_exposure_selection(_tampered(lambda p: p.__setitem__("seed", "another-seed")))
    with pytest.raises(BenchEvalError):
        load_exposure_selection(
            _tampered(lambda p: p["canonical"]["strata"][stratum].__setitem__("count", 99))
        )
    with pytest.raises(BenchEvalError):
        load_exposure_selection(
            _tampered(lambda p: p["canonical"]["strata"][stratum]["candidate_ids"].reverse())
        )
    with pytest.raises(BenchEvalError):
        load_exposure_selection(_tampered(lambda p: p.__setitem__("algorithm", "sha256_rank_v2")))
    with pytest.raises(BenchEvalError):
        load_exposure_selection(_tampered(lambda p: p.__setitem__("extra", 1)))


def test_selection_binds_the_study_population_and_slices() -> None:
    study = load_exposure_study(_LIVE_STUDY)
    pools = _pools(study)
    other = study.model_copy(
        update={
            "population": study.population.model_copy(
                update={"canonical_counts": {**study.population.canonical_counts, "multiple": 3}}
            )
        }
    )
    with pytest.raises(BenchEvalError, match="stratum"):
        build_exposure_selection(
            study,
            sources={
                **_sources_from_pools(study, pools),
                "candidate": _sources_from_pools(other, pools)["canonical"],
            },
        )
    selection = build_exposure_selection(study, sources=_sources_from_pools(study, pools))
    assert (
        selection.study_sha256
        != build_exposure_selection(other, sources=_sources_from_pools(other, pools)).study_sha256
    )
    assert sum(s.count for s in selection.canonical.strata.values()) == 340
    assert sum(s.count for s in selection.candidate.strata.values()) == 356


# --- outputs -----------------------------------------------------------------------


def test_write_outputs_renders_exact_id_slices_and_record_exclusively(tmp_path: Path) -> None:
    study = load_exposure_study(_LIVE_STUDY)
    selection = _selection(study)
    slices = tmp_path / "slices"
    slices.mkdir()
    record = tmp_path / "selection.json"
    written = write_selection_outputs(
        selection, slices_dir=slices, record_path=record, max_total_cost_usd=10
    )
    assert set(written) == {
        slices / "bfcl-v4-exposure-non-live-v1.yaml",
        slices / "bfcl-v4-live-exposure-live-v1.yaml",
        record,
    }
    assert load_exposure_selection(record) == selection
    for side in ("canonical", "candidate"):
        bound = getattr(selection, side)
        manifest = load_slice_manifest(slices / f"{bound.benchmark_id}-{bound.slice_id}.yaml")
        assert manifest.slice.id == bound.slice_id
        assert manifest.slice.benchmark_id == bound.benchmark_id
        assert manifest.slice.selection_policy == "fixed_instance_ids"
        expected = [i for name in sorted(bound.strata) for i in bound.strata[name].selected_ids]
        assert list(manifest.slice.instances) == expected
        assert manifest.budget.max_instances == len(expected)
        assert float(manifest.budget.max_total_cost_usd) == 10.0
        assert "benchmark_native_claim" in manifest.slice.invalid_for
        assert manifest.labels.contamination_warning is True
    raw = yaml.safe_load((slices / "bfcl-v4-exposure-non-live-v1.yaml").read_text(encoding="utf-8"))
    first_stratum = sorted(selection.canonical.strata)[0]
    assert raw["slice"]["instances"][0] == selection.canonical.strata[first_stratum].selected_ids[0]

    # Exclusive: nothing is overwritten, and a partial failure leaves no new file.
    with pytest.raises(BenchEvalError):
        write_selection_outputs(
            selection, slices_dir=slices, record_path=tmp_path / "other.json", max_total_cost_usd=10
        )
    assert not (tmp_path / "other.json").exists()
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    with pytest.raises(BenchEvalError):
        write_selection_outputs(
            selection, slices_dir=fresh, record_path=record, max_total_cost_usd=10
        )
    assert list(fresh.iterdir()) == []


# --- report enforcement ------------------------------------------------------------


def test_declared_report_requires_exactly_the_selected_population(tmp_path: Path) -> None:
    study = load_exposure_study(_LIVE_STUDY)
    selection = _real_selection()
    canonical = _rows_for(selection, "canonical", passes=200, run_id="run-canonical")
    candidate = _rows_for(selection, "candidate", passes=150, run_id="run-candidate")
    canonical_proof = _proof_from_rows(tmp_path / "canonical", canonical)
    candidate_proof = _proof_from_rows(tmp_path / "candidate", candidate)

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
    assert payload["population_selection"] == {
        "schema_version": SELECTION_SCHEMA,
        "algorithm": SELECTION_ALGORITHM,
        "seed": study.population.seed,
        "selection_sha256": exposure_selection_sha256(selection),
    }
    assert built.lock_payload["selection"] == selection.model_dump(mode="json")
    assert built.lock_payload["selection_sha256"] == exposure_selection_sha256(selection)

    # Declared analysis without the retained selection is refused.
    with pytest.raises(BenchEvalError, match="selection"):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=canonical_proof,
            candidate_proof=candidate_proof,
            analysis="declared",
            output=tmp_path / "no-selection.json",
            lock_output=tmp_path / "no-selection.lock.json",
            fmt="json",
        )
    assert not (tmp_path / "no-selection.json").exists()

    # A same-count replacement of one selected id is not the selected population.
    stratum = "simple_python"
    bound = selection.canonical.strata[stratum]
    unselected = next(i for i in bound.candidate_ids if i not in bound.selected_ids)
    swapped = [
        r
        if r.instance_id != bound.selected_ids[0]
        else _row(
            benchmark_id=r.benchmark_id,
            slice_id=r.slice_id,
            instance_id=unselected,
            primary_pass=r.primary_pass,
            run_id=r.run_id,
        )
        for r in canonical
    ]
    swapped_proof = _proof_from_rows(tmp_path / "swapped", swapped)
    with pytest.raises(BenchEvalError, match="select"):
        write_proof_backed_exposure_report(
            study,
            canonical_proof=swapped_proof,
            candidate_proof=candidate_proof,
            analysis="declared",
            output=tmp_path / "swapped.json",
            lock_output=tmp_path / "swapped.lock.json",
            fmt="json",
            selection=selection,
        )
    # Raw-only still refuses the swapped population once a selection is supplied…
    with pytest.raises(BenchEvalError, match="select"):
        build_exposure_report(
            study, canonical=swapped, candidate=candidate, analysis="raw_only", selection=selection
        )
    # …and a selection whose study digest differs is rejected outright.
    other_study = study.model_copy(update={"id": "another-study"})
    with pytest.raises(BenchEvalError, match="study"):
        build_exposure_report(
            study,
            canonical=canonical,
            candidate=candidate,
            analysis="raw_only",
            selection=_forged(
                selection,
                lambda p: p.update(
                    study_id="another-study", study_sha256=exposure_study_sha256(other_study)
                ),
            ),
        )
    # A record ranked under the original seed cannot serve a study declaring another seed,
    # even when its study-digest reference was rewritten to match.
    reseeded = study.model_copy(
        update={"population": study.population.model_copy(update={"seed": "another-seed"})}
    )
    with pytest.raises(BenchEvalError, match="seed"):
        build_exposure_report(
            reseeded,
            canonical=canonical,
            candidate=candidate,
            analysis="raw_only",
            selection=_forged(
                selection, lambda p: p.update(study_sha256=exposure_study_sha256(reseeded))
            ),
        )
    # Source metadata and the candidate universe bind to the catalog identity, not to
    # whatever the record declares about itself.
    stratum_key = ("canonical", "strata", stratum)

    def _stratum(p: dict) -> dict:
        return p[stratum_key[0]][stratum_key[1]][stratum_key[2]]

    forgeries: list[tuple[str, Callable[[dict], None]]] = [
        ("pin", lambda p: _stratum(p).__setitem__("source_sha256", "sha256:" + "0" * 64)),
        (
            "question file",
            lambda p: _stratum(p).__setitem__("source_file", "data/BFCL_v4_simple_python_v2.json"),
        ),
        (
            "population anchor",
            lambda p: _stratum(p).__setitem__("candidate_ids", sorted(_stratum(p)["selected_ids"])),
        ),
        (
            "population anchor",
            lambda p: _stratum(p).__setitem__(
                "candidate_ids", sorted([*_stratum(p)["candidate_ids"], "simple_python_9999"])
            ),
        ),
        (
            "catalog identity",
            lambda p: p["canonical"].__setitem__(
                "benchmark_version", "bfcl-v4@bfcl-eval-2026.3.23+data-0000000000000000"
            ),
        ),
    ]
    for match, mutate in forgeries:
        forged = _forged(selection, mutate)
        with pytest.raises(BenchEvalError, match=match):
            build_exposure_report(
                study,
                canonical=canonical,
                candidate=candidate,
                analysis="raw_only",
                selection=forged,
            )
    # A selection never applies to a smoke population.
    smoke_c = [
        _row(
            benchmark_id="bfcl-v4",
            slice_id=study.canonical.smoke_slice_id,
            instance_id=f"{s}_0",
            primary_pass=True,
            run_id="run-smoke-canonical",
        )
        for s in study.population.canonical_counts
    ]
    smoke_l = [
        _row(
            benchmark_id="bfcl-v4-live",
            slice_id=study.candidate.smoke_slice_id,
            instance_id=f"{s}_0-0-0",
            primary_pass=True,
            run_id="run-smoke-candidate",
        )
        for s in study.population.candidate_counts
    ]
    with pytest.raises(BenchEvalError, match="declared population"):
        build_exposure_report(
            study, canonical=smoke_c, candidate=smoke_l, analysis="raw_only", selection=selection
        )


def test_lock_retains_the_selection_and_verifies_after_its_file_is_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    selection = _real_selection()
    record = tmp_path / "records" / "selection.json"
    record.parent.mkdir()
    record.write_text(
        json.dumps(selection.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
    )
    canonical = _rows_for(selection, "canonical", passes=200, run_id="run-canonical")
    candidate = _rows_for(selection, "candidate", passes=150, run_id="run-candidate")
    proof_args = [
        "--canonical-proof",
        str(_proof_from_rows(tmp_path / "canonical", canonical)),
        "--candidate-proof",
        str(_proof_from_rows(tmp_path / "candidate", candidate)),
    ]
    report = tmp_path / "report.json"
    lock = tmp_path / "report.lock.json"
    assert (
        main(
            [
                "study",
                "report",
                _LIVE_STUDY,
                *proof_args,
                "--analysis",
                "declared",
                "--selection",
                str(record),
                "--output",
                str(report),
                "--lock-output",
                str(lock),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert json.loads(report.read_text(encoding="utf-8"))["analysis_mode"] == "declared_population"

    shutil.rmtree(record.parent)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    reproduced = elsewhere / "reproduced.json"
    assert (
        main(["study", "verify", *proof_args, "--lock", str(lock), "--output", str(reproduced)])
        == 0
    )
    verified = json.loads(capsys.readouterr().out)
    assert verified["selection_source"] == "lock"
    assert verified["selection_sha256"] == exposure_selection_sha256(selection)
    assert reproduced.read_bytes() == report.read_bytes()

    recovered = elsewhere / "recovered.json"
    recovered.write_text(
        json.dumps(json.loads(lock.read_text(encoding="utf-8"))["selection"]), encoding="utf-8"
    )
    assert (
        main(["study", "verify", *proof_args, "--lock", str(lock), "--selection", str(recovered)])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["selection_source"] == "supplied"

    other = elsewhere / "other.json"
    other.write_text(
        json.dumps(
            _forged(selection, lambda p: p.update(study_id="another-study")).model_dump(mode="json")
        ),
        encoding="utf-8",
    )
    assert (
        main(["study", "verify", *proof_args, "--lock", str(lock), "--selection", str(other)]) != 0
    )

    original = json.loads(lock.read_text(encoding="utf-8"))

    def _mutated(mutate: Callable[[dict], None]) -> Path:
        payload = json.loads(json.dumps(original))
        mutate(payload)
        path = elsewhere / "mutated.lock.json"
        path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
        return path

    with pytest.raises(BenchEvalError, match="selection"):
        verify_exposure_study_lock(
            None,
            lock_path=_mutated(lambda p: p.pop("selection")),
            canonical_proof=Path(proof_args[1]),
            candidate_proof=Path(proof_args[3]),
        )
    with pytest.raises(BenchEvalError, match="selection"):
        verify_exposure_study_lock(
            None,
            lock_path=_mutated(lambda p: p.__setitem__("selection_sha256", "sha256:" + "0" * 64)),
            canonical_proof=Path(proof_args[1]),
            candidate_proof=Path(proof_args[3]),
        )
    with pytest.raises(BenchEvalError, match="selection"):
        verify_exposure_study_lock(
            None,
            lock_path=_mutated(lambda p: p["selection"].__setitem__("seed", "x")),
            canonical_proof=Path(proof_args[1]),
            candidate_proof=Path(proof_args[3]),
        )


# --- historical locks --------------------------------------------------------------

_X24FC = Path(__file__).parent.parent / "fixtures" / "exposure" / "x24fc"


def test_pre_selection_raw_only_lock_still_reproduces(tmp_path: Path) -> None:
    """A retained pre-X2.4 FC plumbing lock (dev-box-cpu, 2026-09-05) must keep verifying.

    The report bytes it binds carry no ``population_selection`` field, so adding
    selections must not touch raw-only serialization.
    """
    lock = json.loads((_X24FC / "x24fc-exposure-report.lock.json").read_text(encoding="utf-8"))
    assert "selection" not in lock and "selection_sha256" not in lock
    reproduced = tmp_path / "reproduced.json"
    verified = verify_exposure_study_lock(
        None,
        lock_path=_X24FC / "x24fc-exposure-report.lock.json",
        canonical_proof=_X24FC / "canonical",
        candidate_proof=_X24FC / "candidate",
        output=reproduced,
    )
    assert verified["ok"] is True
    assert verified["report_sha256"] == lock["report_sha256"]
    assert verified["report_sha256"].startswith("sha256:505b4afe4bbf6cac8283f27c0f6b3f4cc9591d")
    assert verified["selection_source"] is None and verified["selection_sha256"] is None
    assert reproduced.read_bytes() == (_X24FC / "x24fc-exposure-report.json").read_bytes()
    assert "population_selection" not in json.loads(reproduced.read_text(encoding="utf-8"))


# --- representation pair -----------------------------------------------------------

_PAIR = "bfcl-v4-tool-order-v1"


def test_pair_selection_is_selected_once_and_inherited_by_the_derived_side(
    tmp_path: Path,
) -> None:
    study = load_exposure_study(_PAIR)
    pools = {"bfcl-v4": {s: _pool(s, n + 7) for s, n in study.population.canonical_counts.items()}}
    identities = _substitute_package(tmp_path / "pkg", pools)
    selection = materialize_exposure_selection(
        study, package_root=tmp_path / "pkg", identities=identities
    )
    assert selection.candidate_inherits_canonical
    assert selection.candidate.benchmark_id == _PAIR
    assert selection.candidate.slice_id == study.candidate.slice_id
    assert selection.candidate.strata == selection.canonical.strata
    assert selection.candidate.selected_ids == selection.canonical.selected_ids
    assert selection.candidate.benchmark_version == selection.canonical.benchmark_version
    # Ranking the derived side under its own id would pick a different population.
    for name, stratum in selection.canonical.strata.items():
        assert stratum.selected_ids != select_stratum(
            seed=study.population.seed,
            benchmark_id=_PAIR,
            stratum=name,
            candidates=stratum.candidate_ids,
            count=stratum.count,
        )
    with pytest.raises(BenchEvalError, match="once"):
        build_exposure_selection(
            study,
            sources={
                "canonical": _sources_from_pools(study, {**pools, _PAIR: pools["bfcl-v4"]})[
                    "canonical"
                ],
                "candidate": _sources_from_pools(study, {**pools, _PAIR: pools["bfcl-v4"]})[
                    "candidate"
                ],
            },
        )
    record = tmp_path / "pair.json"
    record.write_text(json.dumps(selection.model_dump(mode="json")), encoding="utf-8")
    assert load_exposure_selection(record) == selection


def test_checked_in_pair_record_binds_to_the_catalog_and_the_derived_reference() -> None:
    from bencheval.benchmark_registry import BfclDerivedDataRef, load_benchmark_catalog
    from bencheval.exposure_selection import (
        verify_selection_against_catalog,
        verify_selection_for_study,
    )
    from bencheval.slice_manifest import default_slices_dir, load_slice_manifest

    study = load_exposure_study(_PAIR)
    selection = load_exposure_selection(default_studies_dir() / f"{_PAIR}.selection.json")
    verify_selection_for_study(study, selection)
    verify_selection_against_catalog(selection)
    assert selection.candidate_inherits_canonical
    assert sum(s.count for s in selection.canonical.strata.values()) == 200
    ref = load_benchmark_catalog().by_id_or_alias(_PAIR).identity
    assert isinstance(ref, BfclDerivedDataRef)
    assert ref.study_id == study.id and ref.source_benchmark_id == study.canonical.benchmark_id
    for side in (selection.canonical, selection.candidate):
        manifest = load_slice_manifest(
            default_slices_dir() / f"{side.benchmark_id}-{side.slice_id}.yaml"
        )
        assert list(manifest.slice.instances) == list(side.selected_ids)
    for bench, slice_id in (
        ("bfcl-v4", study.canonical.smoke_slice_id),
        (_PAIR, study.candidate.smoke_slice_id),
    ):
        plumbing = load_slice_manifest(default_slices_dir() / f"{bench}-{slice_id}.yaml")
        assert list(plumbing.slice.instances) == [
            selection.canonical.strata[name].selected_ids[0]
            for name in sorted(selection.canonical.strata)
        ]
