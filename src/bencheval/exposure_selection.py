"""Deterministic BFCL exposure population selection (``sha256_rank_v1``).

One BFCL-specific selector, not a sampling framework: it verifies the pinned
package data, reads the official question ids of each declared stratum, ranks
them with a frozen seeded digest, and emits two ordinary exact-id slice
manifests plus one replayable selection record. Runs stay study-agnostic; the
record is supplied to ``study report`` and retained in the study lock.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bencheval.benchmark_registry import BfclPackageDataIdentity
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_study import ExposureStudyManifest, exposure_study_sha256
from bencheval.run_isolation import open_owned_dir_fd, write_text_at_exclusive

SELECTION_ALGORITHM = "sha256_rank_v1"
SELECTION_SCHEMA = "exposure-selection-v1"
_SHA256_PIN = r"^sha256:[0-9a-f]{64}$"
_SAFE_ID = r"^[a-z0-9][a-z0-9-]*$"
_QUESTION_FILE = "data/BFCL_v4_{stratum}.json"
_DEFAULT_WALL_CLOCK_SEC = 300


# --- frozen algorithm ------------------------------------------------------------


def rank_digest(*, seed: str, benchmark_id: str, stratum: str, instance_id: str) -> str:
    """sha256 over compact UTF-8 JSON ``[algorithm, seed, benchmark, stratum, id]``."""
    payload = json.dumps(
        [SELECTION_ALGORITHM, seed, benchmark_id, stratum, instance_id],
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def select_stratum(
    *,
    seed: str,
    benchmark_id: str,
    stratum: str,
    candidates: Iterable[str],
    count: int,
) -> tuple[str, ...]:
    """First ``count`` ids of ``candidates`` ordered by ``(digest, id)``; order-free."""
    pool = list(candidates)
    unique = set(pool)
    if len(unique) != len(pool):
        duplicates = sorted({i for i in pool if pool.count(i) > 1})
        raise BenchEvalError(f"{benchmark_id}/{stratum}: duplicate candidate ids {duplicates}")
    if count < 1 or count > len(unique):
        raise BenchEvalError(
            f"{benchmark_id}/{stratum}: insufficient population for {count} "
            f"(available {len(unique)})",
        )
    ranked = sorted(
        unique,
        key=lambda i: (
            rank_digest(seed=seed, benchmark_id=benchmark_id, stratum=stratum, instance_id=i),
            i,
        ),
    )
    return tuple(ranked[:count])


def population_ids_sha256(ids: Iterable[str]) -> str:
    """Trusted-universe digest: sorted unique ids, newline-joined, trailing newline."""
    text = "\n".join(sorted(set(ids))) + "\n"
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


# --- record --------------------------------------------------------------------


class SelectionStratum(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_file: str = Field(min_length=1)
    source_sha256: str = Field(pattern=_SHA256_PIN)
    candidate_ids: tuple[str, ...] = Field(min_length=1)
    count: int = Field(ge=1)
    selected_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _sorted_unique_candidates(self) -> Self:
        if list(self.candidate_ids) != sorted(set(self.candidate_ids)):
            raise ValueError("candidate_ids must be sorted and unique")
        if self.count != len(self.selected_ids):
            raise ValueError("count must equal the number of selected ids")
        return self


class SelectionSide(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark_id: str = Field(pattern=_SAFE_ID)
    slice_id: str = Field(pattern=_SAFE_ID)
    benchmark_version: str = Field(min_length=1)
    strata: dict[str, SelectionStratum] = Field(min_length=1)

    @property
    def selected_ids(self) -> tuple[str, ...]:
        """Selected ids in canonical order: strata by name, then rank order."""
        return tuple(i for name in sorted(self.strata) for i in self.strata[name].selected_ids)


class ExposureSelection(BaseModel):
    """Replayable population selection; invalid unless every stratum replays."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["exposure-selection-v1"]
    study_id: str = Field(pattern=_SAFE_ID)
    study_sha256: str = Field(pattern=_SHA256_PIN)
    algorithm: Literal["sha256_rank_v1"]
    seed: str = Field(min_length=1)
    canonical: SelectionSide
    candidate: SelectionSide

    @property
    def candidate_inherits_canonical(self) -> bool:
        """A representation pair copies the canonical strata onto the derived side."""
        return (
            self.candidate.benchmark_id != self.canonical.benchmark_id
            and self.candidate.strata == self.canonical.strata
        )

    @model_validator(mode="after")
    def _replays(self) -> Self:
        inherited = self.candidate_inherits_canonical
        for side in (self.canonical, self.candidate):
            ranked_as = (
                self.canonical.benchmark_id
                if inherited and side is self.candidate
                else side.benchmark_id
            )
            for name, stratum in side.strata.items():
                expected = select_stratum(
                    seed=self.seed,
                    benchmark_id=ranked_as,
                    stratum=name,
                    candidates=stratum.candidate_ids,
                    count=stratum.count,
                )
                if expected != stratum.selected_ids:
                    raise ValueError(
                        f"{side.benchmark_id}/{name}: selected ids do not replay "
                        f"{SELECTION_ALGORITHM} over the recorded candidates",
                    )
        return self


def exposure_selection_sha256(selection: ExposureSelection) -> str:
    canonical = json.dumps(
        selection.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def load_exposure_selection(path: Path) -> ExposureSelection:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BenchEvalError(f"cannot read exposure selection {path}: {e}") from e
    return parse_exposure_selection(raw, source=str(path))


def parse_exposure_selection(raw: object, *, source: str) -> ExposureSelection:
    try:
        return ExposureSelection.model_validate(raw)
    except ValidationError as e:
        raise BenchEvalError(f"{source}: invalid exposure selection: {e}") from e


# --- building ----------------------------------------------------------------


class SelectionStratumSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_file: str = Field(min_length=1)
    source_sha256: str = Field(pattern=_SHA256_PIN)
    candidate_ids: tuple[str, ...] = Field(min_length=1)


class SelectionSource(BaseModel):
    """Verified candidate populations for one study side."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark_version: str = Field(min_length=1)
    strata: dict[str, SelectionStratumSource] = Field(min_length=1)


def build_exposure_selection(
    study: ExposureStudyManifest, *, sources: Mapping[str, SelectionSource]
) -> ExposureSelection:
    """Rank every declared stratum from verified sources.

    A representation pair is selected once: the candidate side inherits the
    canonical side's exact source ids (same universe, same seed ranking) so the
    derived population pairs case-for-case instead of being ranked again under
    the derived benchmark id.
    """
    sides: dict[str, SelectionSide] = {}
    paired = study.kind == "representation_pair"
    if paired and "candidate" in sources:
        raise BenchEvalError(
            "a representation pair selects the canonical population once; do not supply a "
            "candidate source",
        )
    for side_name, counts in (
        ("canonical", study.population.canonical_counts),
        ("candidate", study.population.candidate_counts),
    ):
        declared = getattr(study, side_name)
        if paired and side_name == "candidate":
            canonical = sides["canonical"]
            sides["candidate"] = SelectionSide(
                benchmark_id=declared.benchmark_id,
                slice_id=declared.slice_id,
                benchmark_version=canonical.benchmark_version,
                strata=canonical.strata,
            )
            continue
        source = sources.get(side_name)
        if source is None:
            raise BenchEvalError(f"selection source for the {side_name} side is missing")
        if set(source.strata) != set(counts):
            raise BenchEvalError(
                f"{side_name} sources name strata {sorted(source.strata)}, "
                f"not the study's stratum set {sorted(counts)}",
            )
        strata = {
            name: SelectionStratum(
                source_file=source.strata[name].source_file,
                source_sha256=source.strata[name].source_sha256,
                candidate_ids=tuple(sorted(set(source.strata[name].candidate_ids))),
                count=count,
                selected_ids=select_stratum(
                    seed=study.population.seed,
                    benchmark_id=declared.benchmark_id,
                    stratum=name,
                    candidates=source.strata[name].candidate_ids,
                    count=count,
                ),
            )
            for name, count in counts.items()
        }
        sides[side_name] = SelectionSide(
            benchmark_id=declared.benchmark_id,
            slice_id=declared.slice_id,
            benchmark_version=source.benchmark_version,
            strata=strata,
        )
    return ExposureSelection(
        schema_version="exposure-selection-v1",
        study_id=study.id,
        study_sha256=exposure_study_sha256(study),
        algorithm="sha256_rank_v1",
        seed=study.population.seed,
        canonical=sides["canonical"],
        candidate=sides["candidate"],
    )


def _read_official_ids(path: Path, *, stratum: str, label: str) -> tuple[str, ...]:
    """Ids of one official JSONL question file; every row must carry a stratum id."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise BenchEvalError(f"{label}: cannot read question file {path}: {e}") from e
    ids: list[str] = []
    prefix = f"{stratum}_"
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise BenchEvalError(f"{label}: line {number} is not JSON: {e}") from e
        instance_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(instance_id, str) or not instance_id:
            raise BenchEvalError(f"{label}: line {number} has no string id")
        if not instance_id.startswith(prefix) or _category_of(instance_id) != stratum:
            raise BenchEvalError(
                f"{label}: id {instance_id!r} is not in category {stratum!r}",
            )
        ids.append(instance_id)
    if not ids:
        raise BenchEvalError(f"{label}: question file {path} holds no ids")
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise BenchEvalError(f"{label}: duplicate ids in {path}: {duplicates}")
    return tuple(ids)


def _category_of(instance_id: str) -> str:
    """Official BFCL category of an id: everything before the trailing ``_<index>``."""
    head, _, _ = instance_id.rpartition("_")
    return head


def source_from_package(
    *,
    benchmark_id: str,
    identity: BfclPackageDataIdentity,
    package_root: Path,
    strata: Iterable[str],
) -> SelectionSource:
    """Verify every pinned file, then read the candidate ids of each stratum."""
    from bencheval.bfcl_native_adapter import verify_bfcl_package_data
    from bencheval.identity_strings import bfcl_benchmark_identity

    verify_bfcl_package_data(package_root=package_root, files=identity.files)
    out: dict[str, SelectionStratumSource] = {}
    for stratum in strata:
        rel = _QUESTION_FILE.format(stratum=stratum)
        pin = identity.files.get(rel)
        if pin is None:
            raise BenchEvalError(
                f"{benchmark_id}/{stratum}: question file {rel} is not pinned by the catalog "
                "identity; refusing to select from unpinned data",
            )
        ids = _read_official_ids(
            package_root / rel, stratum=stratum, label=f"{benchmark_id}/{stratum}"
        )
        _require_population_anchor(identity, rel, ids, label=f"{benchmark_id}/{stratum}")
        out[stratum] = SelectionStratumSource(source_file=rel, source_sha256=pin, candidate_ids=ids)
    return SelectionSource(
        benchmark_version=bfcl_benchmark_identity(identity, benchmark_id=benchmark_id),
        strata=out,
    )


def _require_population_anchor(
    identity: BfclPackageDataIdentity, rel: str, ids: Iterable[str], *, label: str
) -> None:
    anchor = identity.populations.get(rel)
    if anchor is None:
        raise BenchEvalError(
            f"{label}: question file {rel} has no catalog population anchor; refusing to "
            "select from an unanchored candidate universe",
        )
    ids = tuple(ids)
    digest = population_ids_sha256(ids)
    if anchor.count != len(set(ids)) or anchor.ids_sha256 != digest:
        raise BenchEvalError(
            f"{label}: candidate population does not match the catalog population anchor "
            f"(count {len(set(ids))} vs {anchor.count}, ids {digest} vs {anchor.ids_sha256})",
        )


def verify_selection_sources(
    selection: ExposureSelection,
    identities: Mapping[str, BfclPackageDataIdentity],
) -> None:
    """Bind every side of a record to trusted identity pins and population anchors.

    A record is caller-supplied; its candidate pools, source paths, and pins are
    only trusted once they equal the reviewed catalog identity of the side's
    benchmark. Hashing the record's own list again would prove nothing.
    """
    from bencheval.identity_strings import bfcl_benchmark_identity

    for side in (selection.canonical, selection.candidate):
        identity = identities.get(side.benchmark_id)
        if identity is None:
            raise BenchEvalError(
                f"{side.benchmark_id} has no bfcl package-data identity to bind the selection to",
            )
        # A derived benchmark's selection is bound to its source package data; its
        # own content-bound label is checked by the report's variant binding.
        source_id = _derived_source_benchmark_id(side.benchmark_id) or side.benchmark_id
        expected_version = bfcl_benchmark_identity(identity, benchmark_id=source_id)
        if side.benchmark_version != expected_version:
            raise BenchEvalError(
                f"{side.benchmark_id} selection source identity {side.benchmark_version!r} is "
                f"not the catalog identity {expected_version!r}",
            )
        for name, stratum in side.strata.items():
            label = f"{side.benchmark_id}/{name}"
            expected_file = _QUESTION_FILE.format(stratum=name)
            if stratum.source_file != expected_file:
                raise BenchEvalError(
                    f"{label}: selection source file {stratum.source_file!r} is not the official "
                    f"question file {expected_file!r}",
                )
            pin = identity.files.get(expected_file)
            if pin is None or stratum.source_sha256 != pin:
                raise BenchEvalError(
                    f"{label}: selection source pin {stratum.source_sha256} does not match the "
                    f"catalog pin {pin}",
                )
            _require_population_anchor(identity, expected_file, stratum.candidate_ids, label=label)


def verify_selection_against_catalog(selection: ExposureSelection) -> None:
    identities: dict[str, BfclPackageDataIdentity] = {}
    for side in (selection.canonical, selection.candidate):
        identity = _catalog_bfcl_identity(side.benchmark_id)
        if identity is not None:
            identities[side.benchmark_id] = identity
    verify_selection_sources(selection, identities)


def verify_selection_for_study(study: ExposureStudyManifest, selection: ExposureSelection) -> None:
    """The record must name this exact study: id, digest, algorithm, and seed."""
    expected_digest = exposure_study_sha256(study)
    if selection.study_sha256 != expected_digest:
        raise BenchEvalError(
            f"population selection binds study digest {selection.study_sha256}, "
            f"not this study's {expected_digest}",
        )
    if selection.study_id != study.id:
        raise BenchEvalError(
            f"population selection names study {selection.study_id!r}, not {study.id!r}",
        )
    if selection.algorithm != study.population.selection_algorithm:
        raise BenchEvalError(
            f"population selection algorithm {selection.algorithm!r} is not the study's "
            f"{study.population.selection_algorithm!r}",
        )
    if selection.seed != study.population.seed:
        raise BenchEvalError(
            f"population selection seed {selection.seed!r} is not the study seed "
            f"{study.population.seed!r}",
        )


def materialize_exposure_selection(
    study: ExposureStudyManifest,
    *,
    package_root: Path | None = None,
    identities: Mapping[str, BfclPackageDataIdentity] | None = None,
) -> ExposureSelection:
    """Select the study population from the pinned installed package data.

    ``identities`` defaults to the catalog pins and ``package_root`` to the
    installed ``bfcl_eval`` distribution; both are only overridden by tests.
    """
    sources: dict[str, SelectionSource] = {}
    for side_name, counts in (
        ("canonical", study.population.canonical_counts),
        ("candidate", study.population.candidate_counts),
    ):
        if side_name == "candidate" and study.kind == "representation_pair":
            continue
        declared = getattr(study, side_name)
        identity = (
            identities.get(declared.benchmark_id)
            if identities is not None
            else _catalog_bfcl_identity(declared.benchmark_id)
        )
        if identity is None:
            raise BenchEvalError(
                f"{declared.benchmark_id} has no bfcl package-data identity to select from",
            )
        root = package_root if package_root is not None else _installed_package_root()
        sources[side_name] = source_from_package(
            benchmark_id=declared.benchmark_id,
            identity=identity,
            package_root=root,
            strata=counts,
        )
    return build_exposure_selection(study, sources=sources)


def _derived_source_benchmark_id(benchmark_id: str) -> str | None:
    """The pinned source benchmark of a catalog derived-ref identity, else None."""
    from bencheval.benchmark_registry import BfclDerivedDataRef
    from bencheval.identity_strings import catalog_benchmark_identity

    try:
        identity = catalog_benchmark_identity(benchmark_id)
    except BenchEvalError:
        return None
    return identity.source_benchmark_id if isinstance(identity, BfclDerivedDataRef) else None


def _catalog_bfcl_identity(benchmark_id: str) -> BfclPackageDataIdentity | None:
    """Package-data identity of ``benchmark_id`` or, for a derived ref, of its source."""
    from bencheval.identity_strings import catalog_benchmark_identity

    source_id = _derived_source_benchmark_id(benchmark_id)
    identity = catalog_benchmark_identity(source_id or benchmark_id)
    return identity if isinstance(identity, BfclPackageDataIdentity) else None


def _installed_package_root() -> Path:
    from bencheval.bfcl_native_adapter import _bfcl_package_root

    return _bfcl_package_root()


# --- outputs -----------------------------------------------------------------


def _slice_payload(side: SelectionSide, *, max_total_cost_usd: int) -> dict[str, object]:
    ids = list(side.selected_ids)
    return {
        "schema_version": "0.1",
        "slice": {
            "id": side.slice_id,
            "benchmark_id": side.benchmark_id,
            "purpose": "rough_regression",
            "selection_policy": "fixed_instance_ids",
            "instances": ids,
            "valid_for": ["rough_regression"],
            "invalid_for": ["benchmark_native_claim", "model_comparison"],
        },
        "budget": {
            "max_instances": len(ids),
            "max_wall_clock_sec_per_instance": _DEFAULT_WALL_CLOCK_SEC,
            "max_total_cost_usd": max_total_cost_usd,
        },
        "labels": {
            "contamination_warning": True,
            "public_benchmark": True,
            "full_suite_required_for_public_claim": True,
        },
    }


def render_selection_slice(side: SelectionSide, *, max_total_cost_usd: int) -> str:
    return yaml.safe_dump(
        _slice_payload(side, max_total_cost_usd=max_total_cost_usd), sort_keys=False
    )


def render_selection_record(selection: ExposureSelection) -> str:
    return json.dumps(selection.model_dump(mode="json"), sort_keys=True, indent=2) + "\n"


def write_selection_outputs(
    selection: ExposureSelection,
    *,
    slices_dir: Path,
    record_path: Path,
    max_total_cost_usd: int,
) -> tuple[Path, ...]:
    """Exclusively write both slice manifests and the record; unwind on failure."""
    if max_total_cost_usd < 1:
        raise BenchEvalError("max_total_cost_usd must be a positive integer")
    targets: list[tuple[Path, str, str]] = [
        (
            slices_dir,
            f"{side.benchmark_id}-{side.slice_id}.yaml",
            render_selection_slice(side, max_total_cost_usd=max_total_cost_usd),
        )
        for side in (selection.canonical, selection.candidate)
    ]
    targets.append((record_path.parent, record_path.name, render_selection_record(selection)))
    for directory, name, _ in targets:
        if (directory / name).exists() or (directory / name).is_symlink():
            raise BenchEvalError(f"selection output already exists: {directory / name}")
    created: list[Path] = []
    try:
        for directory, name, text in targets:
            dir_fd = open_owned_dir_fd(directory, role="exposure selection output directory")
            try:
                write_text_at_exclusive(dir_fd, name, text)
            finally:
                os.close(dir_fd)
            created.append(directory / name)
    except BaseException as e:
        for path in created:
            try:
                path.unlink()
            except OSError:
                pass
        if isinstance(e, OSError):
            raise BenchEvalError(f"cannot write selection output: {e}") from e
        raise
    return tuple(created)


__all__ = [
    "SELECTION_ALGORITHM",
    "SELECTION_SCHEMA",
    "ExposureSelection",
    "SelectionSide",
    "SelectionSource",
    "SelectionStratum",
    "SelectionStratumSource",
    "build_exposure_selection",
    "exposure_selection_sha256",
    "load_exposure_selection",
    "materialize_exposure_selection",
    "parse_exposure_selection",
    "population_ids_sha256",
    "rank_digest",
    "render_selection_record",
    "render_selection_slice",
    "select_stratum",
    "source_from_package",
    "verify_selection_against_catalog",
    "verify_selection_for_study",
    "verify_selection_sources",
    "write_selection_outputs",
]
