"""Behavioral contracts for the closed benchmark-exposure study registry."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from bencheval.benchmark_registry import BfclPackageDataIdentity, load_benchmark_catalog
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_study import (
    ExposureStudyManifest,
    build_bfcl_derived_data_identity,
    exposure_study_sha256,
    load_exposure_study,
)
from bencheval.identity_strings import bfcl_derived_benchmark_identity

_DERIVED_DATA_A = "sha256:" + "a" * 64
_DERIVED_DATA_B = "sha256:" + "b" * 64


def _tool_order_mapping(study: ExposureStudyManifest | None = None) -> dict[str, str]:
    study = study or load_exposure_study("bfcl-v4-tool-order-v1")
    mapping: dict[str, str] = {}
    for category, count in study.population.candidate_counts.items():
        for index in range(count):
            instance_id = f"{category}_{index}-0-0"
            mapping[instance_id] = instance_id
    return mapping


def _canonical_bfcl_identity() -> BfclPackageDataIdentity:
    identity = load_benchmark_catalog().by_id_or_alias("bfcl-v4").identity
    assert isinstance(identity, BfclPackageDataIdentity)
    return identity


def test_bfcl_studies_load_with_closed_analysis_modes() -> None:
    live = load_exposure_study("bfcl-v4-live-vs-non-live")
    order = load_exposure_study("bfcl-v4-tool-order-v1")

    assert live.kind == "freshness_contrast"
    assert live.relation == "fresh_parallel"
    assert live.comparison_mode == "stratified_unpaired"
    assert live.analysis.difference_interval == "newcombe_95"
    assert live.analysis.paired_test == "not_applicable"
    assert order.kind == "representation_pair"
    assert order.relation == "representation_equivalent"
    assert order.comparison_mode == "paired_by_source_instance"
    assert order.analysis.paired_test == "exact_binomial"
    assert order.variant is not None
    assert order.population.canonical_counts == order.population.candidate_counts


def test_study_digest_is_canonical_and_population_bound(tmp_path: Path) -> None:
    study = load_exposure_study("bfcl-v4-live-vs-non-live")
    first = exposure_study_sha256(study)
    reordered = study.model_dump(mode="json")
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(reordered, sort_keys=False), encoding="utf-8")

    assert exposure_study_sha256(load_exposure_study(path)) == first

    changed = deepcopy(reordered)
    changed["population"]["candidate_counts"]["live_simple"] += 1
    path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")
    assert exposure_study_sha256(load_exposure_study(path)) != first


@pytest.mark.parametrize(
    "mutation",
    [
        {"kind": "representation_pair"},
        {"relation": "representation_equivalent"},
        {"comparison_mode": "paired_by_source_instance"},
        {"plugin": "arbitrary.callback"},
        {"path": "arbitrary/transform.py"},
        {"canonical": {"benchmark_id": "bfcl-v4-live", "slice_id": "study-v1"}},
    ],
)
def test_freshness_study_rejects_ambiguous_or_executable_fields(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    raw = load_exposure_study("bfcl-v4-live-vs-non-live").model_dump(mode="json")
    raw.update(mutation)
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(BenchEvalError):
        load_exposure_study(path)


def test_representation_study_requires_equal_populations_and_variant(tmp_path: Path) -> None:
    raw = load_exposure_study("bfcl-v4-tool-order-v1").model_dump(mode="json")
    raw["population"]["candidate_counts"]["multiple"] -= 1
    raw["variant"] = None
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(BenchEvalError):
        load_exposure_study(path)


def test_every_study_forbids_model_cleanliness_claims() -> None:
    required = {"clean", "contaminated", "cheating", "decontaminated_score"}

    for name in ("bfcl-v4-live-vs-non-live", "bfcl-v4-tool-order-v1"):
        study = load_exposure_study(name)
        assert required <= set(study.forbidden_claims)


def test_bfcl_derived_identity_is_deterministic_and_source_bound() -> None:
    study = load_exposure_study("bfcl-v4-tool-order-v1")
    source = _canonical_bfcl_identity()
    mapping = _tool_order_mapping()

    identity = build_bfcl_derived_data_identity(
        study=study,
        source_identity=source,
        source_mapping=mapping,
        derived_data_sha256=_DERIVED_DATA_A,
    )
    reordered = build_bfcl_derived_data_identity(
        study=study,
        source_identity=source,
        source_mapping=dict(reversed(tuple(mapping.items()))),
        derived_data_sha256=_DERIVED_DATA_A,
    )

    assert identity.source_benchmark_id == "bfcl-v4"
    assert identity.benchmark_id == "bfcl-v4-tool-order-v1"
    assert identity.transform_id == "bfcl-tool-order"
    assert identity.transform_version == "1"
    assert identity.seed == study.population.seed
    assert identity.study_sha256 == exposure_study_sha256(study)
    assert bfcl_derived_benchmark_identity(identity) == bfcl_derived_benchmark_identity(reordered)


def test_bfcl_derived_identity_changes_on_every_bound_input() -> None:
    study = load_exposure_study("bfcl-v4-tool-order-v1")
    source = _canonical_bfcl_identity()
    mapping = _tool_order_mapping()

    def label(
        *,
        selected_study=study,
        selected_source=source,
        selected_mapping=mapping,
        derived_data_sha256: str = _DERIVED_DATA_A,
    ) -> str:
        identity = build_bfcl_derived_data_identity(
            study=selected_study,
            source_identity=selected_source,
            source_mapping=selected_mapping,
            derived_data_sha256=derived_data_sha256,
        )
        return bfcl_derived_benchmark_identity(identity)

    original = label()
    source_files = dict(source.files)
    source_files[next(iter(source_files))] = _DERIVED_DATA_B
    changed_source = source.model_copy(update={"files": source_files})
    changed_population = study.population.model_copy(update={"seed": "different-seed"})
    changed_seed_study = study.model_copy(update={"population": changed_population})
    canonical_counts = dict(study.population.canonical_counts)
    candidate_counts = dict(study.population.candidate_counts)
    canonical_counts["multiple"] += 1
    candidate_counts["multiple"] += 1
    resized_population = study.population.model_copy(
        update={
            "canonical_counts": canonical_counts,
            "candidate_counts": candidate_counts,
        },
    )
    resized_study = study.model_copy(update={"population": resized_population})
    changed_mapping = dict(mapping)
    changed_mapping[next(iter(changed_mapping))] = "different-source_0-0-0"

    assert label(selected_source=changed_source) != original
    assert label(selected_study=changed_seed_study) != original
    assert (
        label(
            selected_study=resized_study,
            selected_mapping=_tool_order_mapping(resized_study),
        )
        != original
    )
    assert label(selected_mapping=changed_mapping) != original
    assert label(derived_data_sha256=_DERIVED_DATA_B) != original


@pytest.mark.parametrize(
    "mutation",
    [
        {"transform_id": "arbitrary-transform"},
        {"transform_version": "2"},
        {"source_categories": ["simple_python"]},
    ],
)
def test_tool_order_variant_contract_is_closed(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    raw = load_exposure_study("bfcl-v4-tool-order-v1").model_dump(mode="json")
    raw["variant"].update(mutation)
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(BenchEvalError):
        load_exposure_study(path)


@pytest.mark.parametrize(
    "mutation",
    [
        {"comparison_mode": "stratified_unpaired"},
        {
            "candidate": {
                "benchmark_id": "another-derived-benchmark",
                "slice_id": "tool-order-derived-v1",
            },
        },
    ],
)
def test_tool_order_study_cannot_select_another_relation_or_candidate(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    raw = load_exposure_study("bfcl-v4-tool-order-v1").model_dump(mode="json")
    raw.update(mutation)
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    with pytest.raises(BenchEvalError):
        load_exposure_study(path)


def test_bfcl_derived_identity_rejects_incomplete_or_ambiguous_mapping() -> None:
    study = load_exposure_study("bfcl-v4-tool-order-v1")
    source = _canonical_bfcl_identity()
    mapping = _tool_order_mapping()

    incomplete = dict(mapping)
    incomplete.pop(next(iter(incomplete)))
    duplicate_source = dict(mapping)
    first, second = tuple(duplicate_source)[:2]
    duplicate_source[first] = duplicate_source[second]
    unsafe = dict(mapping)
    unsafe["../escape"] = unsafe.pop(first)

    for invalid in (incomplete, duplicate_source, unsafe):
        with pytest.raises(BenchEvalError):
            build_bfcl_derived_data_identity(
                study=study,
                source_identity=source,
                source_mapping=invalid,
                derived_data_sha256=_DERIVED_DATA_A,
            )

    with pytest.raises(BenchEvalError):
        build_bfcl_derived_data_identity(
            study=study,
            source_identity=source,
            source_mapping=mapping,
            derived_data_sha256="sha256:short",
        )
