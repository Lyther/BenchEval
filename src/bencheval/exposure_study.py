"""Closed declarative manifests for benchmark-exposure studies."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from bencheval.benchmark_registry import BfclPackageDataIdentity
from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_SAFE_STRATUM = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_SAFE_INSTANCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_PIN = re.compile(r"^sha256:[0-9a-f]{64}$")
_BFCL_SOURCE_BENCHMARK_ID = "bfcl-v4"
_BFCL_DERIVED_BENCHMARK_ID = "bfcl-v4-tool-order-v1"
_BFCL_TOOL_ORDER_TRANSFORM_ID = "bfcl-tool-order"
_BFCL_TOOL_ORDER_TRANSFORM_VERSION = "1"
_BFCL_TOOL_ORDER_SOURCE_CATEGORIES = ("multiple", "parallel_multiple")
_REQUIRED_CONSTANT_AXES = frozenset(
    {
        "model_id",
        "provider_id",
        "provider_config_hash",
        "harness_kind",
        "harness_version",
        "runtime_id",
        "access_control_source",
        "egress_control",
        "repository_history",
    }
)
_REQUIRED_FORBIDDEN_CLAIMS = frozenset(
    {"clean", "contaminated", "cheating", "decontaminated_score"}
)

ConstantAxis = Literal[
    "model_id",
    "provider_id",
    "provider_config_hash",
    "harness_kind",
    "harness_version",
    "runtime_id",
    "access_control_source",
    "egress_control",
    "repository_history",
]
ForbiddenClaim = Literal[
    "clean",
    "contaminated",
    "cheating",
    "decontaminated_score",
    "novelty",
    "superiority",
    "universal_adjusted_score",
]


class StudySide(BaseModel):
    """One study population: the declared slice and its tiny plumbing slice."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark_id: str = Field(pattern=_SAFE_ID.pattern)
    slice_id: str = Field(pattern=_SAFE_ID.pattern)
    smoke_slice_id: str = Field(pattern=_SAFE_ID.pattern)

    @model_validator(mode="after")
    def _distinct_slices(self) -> Self:
        if self.slice_id == self.smoke_slice_id:
            raise ValueError("smoke and declared slices must differ")
        return self


class StudyPopulation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    selection_algorithm: Literal["sha256_rank_v1"]
    seed: str = Field(min_length=1)
    smoke_per_stratum: int = Field(ge=1)
    canonical_counts: dict[str, int] = Field(min_length=1)
    candidate_counts: dict[str, int] = Field(min_length=1)

    @field_validator("canonical_counts", "candidate_counts")
    @classmethod
    def _valid_counts(cls, counts: dict[str, int]) -> dict[str, int]:
        if any(not _SAFE_STRATUM.fullmatch(name) or count < 1 for name, count in counts.items()):
            raise ValueError("population strata require safe ids and positive counts")
        return counts


class StudyAnalysis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    smoke_mode: Literal["raw_only"]
    interval: Literal["wilson_95"]
    difference_interval: Literal["newcombe_95", "not_applicable"]
    paired_test: Literal["exact_binomial", "not_applicable"]


class StudyVariant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    transform_id: Literal["bfcl-tool-order"]
    transform_version: Literal["1"]
    source_categories: tuple[str, ...] = Field(min_length=1)
    balance_algorithm: Literal["sha256_rotate_v1"]
    source_mapping_required: Literal[True]

    @field_validator("source_categories")
    @classmethod
    def _valid_categories(cls, categories: tuple[str, ...]) -> tuple[str, ...]:
        if categories != _BFCL_TOOL_ORDER_SOURCE_CATEGORIES:
            raise ValueError(
                "BFCL tool-order source categories must be multiple and parallel_multiple",
            )
        return categories


class BfclSourceMappingEntry(BaseModel):
    """One immutable derived-to-source instance mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    derived_instance_id: str = Field(pattern=_SAFE_INSTANCE_ID.pattern)
    source_instance_id: str = Field(pattern=_SAFE_INSTANCE_ID.pattern)


class BfclDerivedDataIdentity(BaseModel):
    """Content identity for the single supported BFCL tool-order derivative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["bfcl-derived-data"] = "bfcl-derived-data"
    benchmark_id: Literal["bfcl-v4-tool-order-v1"] = _BFCL_DERIVED_BENCHMARK_ID
    source_benchmark_id: Literal["bfcl-v4"] = _BFCL_SOURCE_BENCHMARK_ID
    source_identity: BfclPackageDataIdentity
    study_sha256: str = Field(pattern=_SHA256_PIN.pattern)
    transform_id: Literal["bfcl-tool-order"] = _BFCL_TOOL_ORDER_TRANSFORM_ID
    transform_version: Literal["1"] = _BFCL_TOOL_ORDER_TRANSFORM_VERSION
    seed: str = Field(min_length=1)
    source_mapping: tuple[BfclSourceMappingEntry, ...] = Field(min_length=1)
    derived_data_sha256: str = Field(pattern=_SHA256_PIN.pattern)

    @model_validator(mode="after")
    def _mapping_is_one_to_one(self) -> Self:
        derived_ids = [entry.derived_instance_id for entry in self.source_mapping]
        source_ids = [entry.source_instance_id for entry in self.source_mapping]
        if len(set(derived_ids)) != len(derived_ids):
            raise ValueError("derived instance ids must be unique")
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("source instance ids must be unique")
        if derived_ids != sorted(derived_ids):
            raise ValueError("source mapping must use canonical derived-instance order")
        return self


class ExposureStudyManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["0.1"]
    id: str = Field(pattern=_SAFE_ID.pattern)
    kind: Literal["freshness_contrast", "representation_pair"]
    relation: Literal["fresh_parallel", "representation_equivalent"]
    comparison_mode: Literal["stratified_unpaired", "paired_by_source_instance"]
    canonical: StudySide
    candidate: StudySide
    required_constant_axes: tuple[ConstantAxis, ...]
    eligible_population: Literal["native_eligible_only"]
    population: StudyPopulation
    analysis: StudyAnalysis
    permitted_interpretation: Literal["benchmark_specific_dependence"]
    forbidden_claims: tuple[ForbiddenClaim, ...]
    variant: StudyVariant | None = None

    @model_validator(mode="after")
    def _coherent_study(self) -> Self:
        if self.canonical.benchmark_id == self.candidate.benchmark_id:
            raise ValueError("canonical and candidate benchmark ids must differ")
        if not set(self.required_constant_axes) >= _REQUIRED_CONSTANT_AXES:
            raise ValueError("required constant axes are incomplete")
        if len(set(self.required_constant_axes)) != len(self.required_constant_axes):
            raise ValueError("required constant axes must be unique")
        if not set(self.forbidden_claims) >= _REQUIRED_FORBIDDEN_CLAIMS:
            raise ValueError("model-cleanliness claims must be forbidden")
        if len(set(self.forbidden_claims)) != len(self.forbidden_claims):
            raise ValueError("forbidden claims must be unique")
        if self.kind == "freshness_contrast":
            if self.relation != "fresh_parallel" or self.comparison_mode != "stratified_unpaired":
                raise ValueError(
                    "freshness contrast must be fresh_parallel and stratified_unpaired",
                )
            if self.variant is not None or self.analysis.paired_test != "not_applicable":
                raise ValueError("freshness contrast cannot declare a transform or paired test")
            if self.analysis.difference_interval != "newcombe_95":
                raise ValueError("freshness contrast requires Newcombe difference intervals")
        else:
            if (
                self.canonical.benchmark_id != _BFCL_SOURCE_BENCHMARK_ID
                or self.candidate.benchmark_id != _BFCL_DERIVED_BENCHMARK_ID
            ):
                raise ValueError(
                    "representation pair is limited to the BFCL tool-order derivative",
                )
            if (
                self.relation != "representation_equivalent"
                or self.comparison_mode != "paired_by_source_instance"
            ):
                raise ValueError(
                    "representation pair must be representation_equivalent and paired",
                )
            if self.variant is None or self.analysis.paired_test != "exact_binomial":
                raise ValueError("representation pair requires a variant and exact paired test")
            if self.analysis.difference_interval != "not_applicable":
                raise ValueError("representation pair does not use an unpaired difference interval")
            if self.population.canonical_counts != self.population.candidate_counts:
                raise ValueError("paired study populations must match exactly")
        return self


def default_studies_dir() -> Path:
    return repo_root() / "config" / "studies"


def _study_path(path_or_id: Path | str) -> Path:
    if isinstance(path_or_id, Path):
        return path_or_id
    if not _SAFE_ID.fullmatch(path_or_id):
        raise BenchEvalError(f"invalid exposure study id {path_or_id!r}")
    return default_studies_dir() / f"{path_or_id}.yaml"


def load_exposure_study(path_or_id: Path | str) -> ExposureStudyManifest:
    path = _study_path(path_or_id)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise BenchEvalError(f"cannot read exposure study {path}: {e}") from e
    except yaml.YAMLError as e:
        raise BenchEvalError(f"{path.name}: invalid YAML: {e}") from e
    try:
        return ExposureStudyManifest.model_validate(raw)
    except ValidationError as e:
        raise BenchEvalError(f"{path.name}: {e}") from e


def exposure_study_sha256(study: ExposureStudyManifest) -> str:
    canonical = json.dumps(
        study.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def build_bfcl_derived_data_identity(
    *,
    study: ExposureStudyManifest,
    source_identity: BfclPackageDataIdentity,
    source_mapping: Mapping[str, str],
    derived_data_sha256: str,
) -> BfclDerivedDataIdentity:
    """Bind one materialized BFCL tool-order population to its declared source."""
    if study.kind != "representation_pair" or study.variant is None:
        raise BenchEvalError("BFCL derived identity requires a representation-pair study")
    expected_count = sum(study.population.candidate_counts.values())
    if len(source_mapping) != expected_count:
        raise BenchEvalError(
            "BFCL source mapping count does not match the declared candidate population: "
            f"expected {expected_count}, got {len(source_mapping)}",
        )
    try:
        entries = tuple(
            BfclSourceMappingEntry(
                derived_instance_id=derived_id,
                source_instance_id=source_id,
            )
            for derived_id, source_id in sorted(source_mapping.items())
        )
        return BfclDerivedDataIdentity(
            source_identity=source_identity,
            study_sha256=exposure_study_sha256(study),
            transform_id=study.variant.transform_id,
            transform_version=study.variant.transform_version,
            seed=study.population.seed,
            source_mapping=entries,
            derived_data_sha256=derived_data_sha256,
        )
    except ValidationError as e:
        raise BenchEvalError(f"invalid BFCL derived-data identity: {e}") from e


__all__ = [
    "BfclDerivedDataIdentity",
    "BfclSourceMappingEntry",
    "ExposureStudyManifest",
    "StudyAnalysis",
    "StudyPopulation",
    "StudySide",
    "StudyVariant",
    "build_bfcl_derived_data_identity",
    "default_studies_dir",
    "exposure_study_sha256",
    "load_exposure_study",
]
