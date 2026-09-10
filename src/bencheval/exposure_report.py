"""Read-only validation and rendering of benchmark-exposure studies.

The report never scores, registers, or launches anything. It loads two native
evidence populations, proves they match the closed study manifest (identities,
provenance, constant axes, verifier authority, eligibility, and declared
population), and renders a deterministic JSON authority plus a Markdown
projection. Any drift fails closed with ``BenchEvalError`` before an output
file exists. Inferential (``declared``) analysis is available only when each
side's population is bound to an immutable run plan inside a complete private
proof; raw-only counts are the ceiling for everything else.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from bencheval.benchmark_plan import official_harness_kind
from bencheval.benchmark_registry import BfclPackageDataIdentity, load_benchmark_catalog
from bencheval.domain import RunPlan
from bencheval.evidence import EvidenceRecord, eligible_for_pass_at_k
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_selection import (
    ExposureSelection,
    exposure_selection_sha256,
    parse_exposure_selection,
    verify_selection_against_catalog,
    verify_selection_for_study,
)
from bencheval.exposure_study import (
    ExposureStudyManifest,
    StudySide,
    exposure_study_sha256,
    load_exposure_study,
)
from bencheval.identity_strings import bfcl_benchmark_identity
from bencheval.live_proof import REQUIRED_PROVENANCE_AXES, producer_content_ok
from bencheval.proof_bundle import load_verified_proof_inputs
from bencheval.provenance_gates import (
    is_captured_axis,
    is_captured_harness_version,
    is_provisional_benchmark_version,
)
from bencheval.stats import exact_binomial_two_sided, newcombe_diff, wilson

REPORT_CONTRACT_VERSION = "exposure-report-v1"
EXPOSURE_LOCK_SCHEMA = "exposure-study-lock-v1"
_PROOF_EVIDENCE_NAME = "evidence.jsonl"
_NATIVE_VERIFIER = "native"
_PRODUCER_KEY = "producer_content_sha256"
_DERIVED_LABEL = re.compile(r"^(?P<benchmark>[a-z0-9][a-z0-9-]*)@derived-[0-9a-f]{64}$")
_ACCESS_AXES = ("access_control_source", "egress_control", "repository_history")

Analysis = Literal["raw_only", "declared"]
ReportFormat = Literal["json", "markdown"]
_Side = Literal["canonical", "candidate"]
_Scale = Literal["smoke", "declared"]


@dataclass(frozen=True, slots=True)
class ExposureReport:
    """Deterministic report authority: ``payload`` is the only source of truth."""

    payload: dict[str, object]

    def to_json(self) -> str:
        return json.dumps(self.payload, sort_keys=True, indent=2) + "\n"

    @property
    def sha256(self) -> str:
        return _sha256_text(self.to_json())


@dataclass(frozen=True, slots=True)
class _PopulationBinding:
    """The retained planned population one side's evidence must equal exactly.

    Only the proof-backed path may create one, from the ``run-plan.json`` of a
    verified complete proof; the public raw-evidence API never accepts a
    caller-supplied binding.
    """

    source: str
    benchmark_id: str
    slice_id: str
    instance_ids: frozenset[str]

    @classmethod
    def from_run_plan(cls, plan: RunPlan, *, source: str) -> _PopulationBinding:
        return cls(
            source=source,
            benchmark_id=plan.benchmark_id,
            slice_id=plan.slice_id,
            instance_ids=frozenset(instance.instance_id for instance in plan.instances),
        )


@dataclass(frozen=True, slots=True)
class ProofBackedReport:
    report: ExposureReport
    report_sha256: str
    lock_sha256: str
    lock_payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class _SideRows:
    side: _Side
    rows: dict[str, EvidenceRecord]  # keyed by instance_id
    strata: dict[str, list[EvidenceRecord]]
    run_id: str
    benchmark_version: str
    slice_id: str
    producer: str
    catalog_bound: bool


@dataclass(frozen=True, slots=True)
class _ProofSide:
    proof_id: str
    evidence_sha256: str
    records: tuple[EvidenceRecord, ...]
    binding: _PopulationBinding
    variant_manifest: bytes | None = None
    variant_derived_files: Mapping[str, bytes] = field(default_factory=dict)
    registration_manifest: bytes | None = None


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


# --- validate ------------------------------------------------------------------


def validate_exposure_study(path_or_id: Path | str) -> dict[str, object]:
    study = load_exposure_study(path_or_id)
    return {
        "study_id": study.id,
        "study_sha256": exposure_study_sha256(study),
        "kind": study.kind,
        "relation": study.relation,
        "comparison_mode": study.comparison_mode,
        "canonical": study.canonical.model_dump(mode="json"),
        "candidate": study.candidate.model_dump(mode="json"),
        "valid": True,
    }


# --- side identity -------------------------------------------------------------


def _expected_side_identity(
    benchmark_id: str, *, derived_from: str | None
) -> tuple[str | None, str | None, str | None]:
    """Catalog-derived (adapter, harness, benchmark_version) for one study side.

    A benchmark outside the catalog is accepted only as the declared derivative
    of ``derived_from``: it must run the source's adapter and official harness,
    and its version is checked as a derived label instead of a catalog pin.
    """
    catalog = load_benchmark_catalog()
    try:
        entry = catalog.by_id_or_alias(benchmark_id)
    except BenchEvalError:
        if derived_from is None:
            raise BenchEvalError(
                f"study benchmark {benchmark_id!r} is not in the catalog"
            ) from None
        adapter_id, harness_kind, _ = _expected_side_identity(derived_from, derived_from=None)
        return adapter_id, harness_kind, None
    if entry.id != benchmark_id:
        raise BenchEvalError(
            f"study benchmark id {benchmark_id!r} must be the catalog id, not an alias",
        )
    version = None
    if isinstance(entry.identity, BfclPackageDataIdentity):
        version = bfcl_benchmark_identity(entry.identity, benchmark_id=benchmark_id)
    return entry.adapter_id, official_harness_kind(entry), version


def _require_captured_provenance(side: _Side, record: EvidenceRecord) -> None:
    instance_id = record.instance_id
    for axis in REQUIRED_PROVENANCE_AXES:
        if not is_captured_axis(getattr(record, axis)):
            raise BenchEvalError(f"{side} row {instance_id!r} has no captured {axis}")
    if not is_captured_harness_version(record.harness_version):
        raise BenchEvalError(f"{side} row {instance_id!r} harness_version is a fallback identity")
    if is_provisional_benchmark_version(record.benchmark_version):
        raise BenchEvalError(f"{side} row {instance_id!r} benchmark_version is provisional")
    if not producer_content_ok(record.adapter_metadata.get(_PRODUCER_KEY)):
        raise BenchEvalError(f"{side} row {instance_id!r} has no captured producer identity")


def _require_one_value(side: _Side, name: str, values: set[object]) -> object:
    if len(values) != 1:
        raise BenchEvalError(f"{side} {name} must be one value, got {sorted(map(str, values))}")
    return next(iter(values))


def _stratum_for(instance_id: str, strata: Sequence[str]) -> str | None:
    matches = [name for name in strata if instance_id.startswith(f"{name}_")]
    return max(matches, key=len) if matches else None


def _bind_row(
    side: _Side,
    record: EvidenceRecord,
    *,
    declared: StudySide,
    strata: Sequence[str],
    expected: tuple[str | None, str | None, str | None],
) -> str:
    """Validate one eligible row's identity and return its stratum."""
    instance_id = record.instance_id
    assert instance_id is not None
    _require_captured_provenance(side, record)
    if record.verifier_integrity_label != _NATIVE_VERIFIER:
        raise BenchEvalError(
            f"{side} row {instance_id!r} verifier integrity is "
            f"{record.verifier_integrity_label!r}; an official native verifier is required",
        )
    adapter_id, harness_kind, version = expected
    if adapter_id is not None and record.adapter_id != adapter_id:
        raise BenchEvalError(
            f"{side} row {instance_id!r} adapter {record.adapter_id!r} != {adapter_id!r}",
        )
    if harness_kind is not None and record.harness_kind != harness_kind:
        raise BenchEvalError(
            f"{side} row {instance_id!r} harness_kind {record.harness_kind!r} != {harness_kind!r}",
        )
    if version is not None and record.benchmark_version != version:
        raise BenchEvalError(
            f"{side} row {instance_id!r} benchmark_version {record.benchmark_version!r} is not "
            f"the catalog identity {version!r}",
        )
    if version is None:
        label = _DERIVED_LABEL.fullmatch(str(record.benchmark_version))
        if label is None or label.group("benchmark") != declared.benchmark_id:
            raise BenchEvalError(
                f"{side} row {instance_id!r} benchmark_version must be a derived identity "
                f"{declared.benchmark_id}@derived-<sha256>",
            )
    if instance_id in strata:
        raise BenchEvalError(
            f"{side} row {instance_id!r} is a whole-category aggregate; exposure studies "
            "require exact per-case instance ids",
        )
    stratum = _stratum_for(instance_id, strata)
    if stratum is None:
        raise BenchEvalError(
            f"{side} row {instance_id!r} belongs to no declared stratum {sorted(strata)}",
        )
    return stratum


def _bind_side(
    side: _Side,
    declared: StudySide,
    strata: Sequence[str],
    records: Sequence[EvidenceRecord],
    *,
    derived_from: str | None,
) -> _SideRows:
    if not records:
        raise BenchEvalError(f"{side} evidence is empty")
    expected = _expected_side_identity(declared.benchmark_id, derived_from=derived_from)
    rows: dict[str, EvidenceRecord] = {}
    grouped: dict[str, list[EvidenceRecord]] = {name: [] for name in strata}
    ineligible: list[str] = []
    seen: set[str] = set()
    for record in records:
        instance_id = record.instance_id
        if not instance_id:
            raise BenchEvalError(f"{side} row {record.task_id!r} has no instance_id")
        if record.benchmark_id != declared.benchmark_id:
            raise BenchEvalError(
                f"{side} row {instance_id!r} benchmark {record.benchmark_id!r} "
                f"is not the study benchmark {declared.benchmark_id!r}",
            )
        if instance_id in seen:
            raise BenchEvalError(f"{side} evidence has duplicate instance {instance_id!r}")
        seen.add(instance_id)
        if not eligible_for_pass_at_k(record):
            ineligible.append(f"{instance_id}:{record.failure_class or 'invalid'}")
            continue
        rows[instance_id] = record
        stratum = _bind_row(side, record, declared=declared, strata=strata, expected=expected)
        grouped[stratum].append(record)
    if ineligible:
        raise BenchEvalError(
            f"{side} evidence contains ineligible/infrastructure rows that contaminate "
            f"the declared population: {sorted(ineligible)}",
        )
    values = list(rows.values())
    return _SideRows(
        side=side,
        rows=rows,
        strata=grouped,
        run_id=str(_require_one_value(side, "run_id", {r.run_id for r in values})),
        benchmark_version=str(
            _require_one_value(side, "benchmark_version", {r.benchmark_version for r in values})
        ),
        slice_id=str(_require_one_value(side, "slice_id", {r.slice_id for r in values})),
        producer=str(
            _require_one_value(
                side, _PRODUCER_KEY, {r.adapter_metadata.get(_PRODUCER_KEY) for r in values}
            )
        ),
        catalog_bound=expected[2] is not None,
    )


def _assert_constant_axes(study: ExposureStudyManifest, *sides: _SideRows) -> dict[str, object]:
    axes: dict[str, object] = {}
    for axis in study.required_constant_axes:
        values = {getattr(record, axis) for side in sides for record in side.rows.values()}
        if len(values) != 1:
            raise BenchEvalError(
                f"constant axis {axis!r} drifts across the study: {sorted(map(str, values))}",
            )
        value = next(iter(values))
        if axis in _ACCESS_AXES and value is None:
            raise BenchEvalError(
                f"constant axis {axis!r} is absent (legacy/unknown evidence cannot enter a study)",
            )
        axes[axis] = value
    producers = {side.producer for side in sides}
    if len(producers) != 1:
        raise BenchEvalError(f"producer identity drifts across the study: {sorted(producers)}")
    axes[_PRODUCER_KEY] = next(iter(producers))
    run_ids = [side.run_id for side in sides]
    if len(set(run_ids)) != len(run_ids):
        raise BenchEvalError("canonical and candidate evidence must come from distinct runs")
    return axes


def _population_scale(
    study: ExposureStudyManifest,
    *sides: tuple[_SideRows, dict[str, int]],
) -> _Scale:
    smoke = study.population.smoke_per_stratum
    observed = {
        (side.side, name): len(rows) for side, _ in sides for name, rows in side.strata.items()
    }
    if all(count == smoke for count in observed.values()):
        return "smoke"
    declared = {
        (side.side, name): count for side, counts in sides for name, count in counts.items()
    }
    if observed == declared:
        return "declared"
    mismatch = {
        f"{side}/{name}": (observed[(side, name)], declared[(side, name)])
        for side, name in sorted(declared)
        if observed[(side, name)] != declared[(side, name)]
    }
    raise BenchEvalError(
        "population does not match the declared smoke or study counts "
        f"(observed, declared): {mismatch}",
    )


def _assert_slice(side: _SideRows, declared: StudySide, scale: _Scale) -> None:
    expected = declared.smoke_slice_id if scale == "smoke" else declared.slice_id
    if side.slice_id != expected:
        raise BenchEvalError(
            f"{side.side} slice {side.slice_id!r} is not the study's {scale} slice {expected!r}",
        )


def _assert_bound_population(
    side: _SideRows, declared: StudySide, binding: _PopulationBinding
) -> None:
    if binding.benchmark_id != declared.benchmark_id or binding.slice_id != side.slice_id:
        raise BenchEvalError(
            f"{side.side} population binding ({binding.source}) names "
            f"{binding.benchmark_id}/{binding.slice_id}, not "
            f"{declared.benchmark_id}/{side.slice_id}",
        )
    observed = frozenset(side.rows)
    if observed != binding.instance_ids:
        missing = sorted(binding.instance_ids - observed)
        extra = sorted(observed - binding.instance_ids)
        raise BenchEvalError(
            f"{side.side} eligible instances are not exactly the planned population "
            f"({binding.source}): missing={missing} extra={extra}",
        )


def _assert_paired(canonical: _SideRows, candidate: _SideRows) -> None:
    only_canonical = sorted(set(canonical.rows) - set(candidate.rows))
    only_candidate = sorted(set(candidate.rows) - set(canonical.rows))
    if only_canonical or only_candidate:
        raise BenchEvalError(
            "paired population is asymmetric: every source instance needs one eligible row on "
            f"both sides (canonical-only={only_canonical}, candidate-only={only_candidate})",
        )


def _assert_declared_allowed(
    scale: _Scale,
    bindings: tuple[_PopulationBinding, _PopulationBinding] | None,
    *sides: _SideRows,
    variant: _Variant | None = None,
) -> None:
    if scale != "declared":
        raise BenchEvalError(
            "declared analysis requires the declared study population; a smoke population "
            "may only report raw counts",
        )
    if bindings is None:
        raise BenchEvalError(
            "declared analysis requires both populations bound to an immutable run plan "
            "(proof-backed inputs); raw-only counts are the ceiling for unbound evidence",
        )
    if not all(side.catalog_bound for side in sides) and variant is None:
        raise BenchEvalError(
            "declared analysis requires catalog-bound identities on both sides; a derived "
            "candidate stays raw-only until its retained variant manifest binds its derived "
            "identity and source mapping",
        )


def _assert_selection(
    study: ExposureStudyManifest,
    selection: ExposureSelection,
    scale: _Scale,
    sides: tuple[_SideRows, _SideRows],
    bindings: tuple[_PopulationBinding, _PopulationBinding] | None,
) -> None:
    """selected ids == planned ids == observed eligible ids, per stratum, per side.

    The record is bound first to this exact study (id, digest, algorithm,
    seed) and then to the trusted catalog identity (question-file pins and
    population anchors), so a self-declared candidate universe never counts.
    """
    verify_selection_for_study(study, selection)
    verify_selection_against_catalog(selection)
    if scale != "declared":
        raise BenchEvalError(
            "population selection applies only to the declared population; a smoke "
            "population may only report raw counts",
        )
    declared_sides = (study.canonical, study.candidate)
    bound_sides = (selection.canonical, selection.candidate)
    for index, (side, declared, bound) in enumerate(
        zip(sides, declared_sides, bound_sides, strict=True)
    ):
        if bound.benchmark_id != declared.benchmark_id or bound.slice_id != side.slice_id:
            raise BenchEvalError(
                f"{side.side} selection names {bound.benchmark_id}/{bound.slice_id}, not "
                f"{declared.benchmark_id}/{side.slice_id}",
            )
        if side.catalog_bound and bound.benchmark_version != side.benchmark_version:
            raise BenchEvalError(
                f"{side.side} selection source identity {bound.benchmark_version!r} is not the "
                f"evidence benchmark version {side.benchmark_version!r}",
            )
        for name, stratum in bound.strata.items():
            observed = {r.instance_id for r in side.strata.get(name, ())}
            selected = set(stratum.selected_ids)
            if observed != selected:
                raise BenchEvalError(
                    f"{side.side}/{name} eligible instances are not the selected population: "
                    f"missing={sorted(selected - observed)} extra={sorted(observed - selected)}",
                )
        if bindings is not None and bindings[index].instance_ids != frozenset(bound.selected_ids):
            raise BenchEvalError(
                f"{side.side} planned population ({bindings[index].source}) is not the selected "
                "population",
            )


@dataclass(frozen=True, slots=True)
class _Variant:
    """A retained derived-run variant manifest, parsed from inventory-bound proof bytes."""

    payload: dict[str, object]
    benchmark_version: str
    identity: object  # BfclDerivedDataIdentity
    sha256: str


def _parse_variant(raw: bytes, derived_files: Mapping[str, bytes]) -> _Variant:
    """Parse the retained manifest and bind it to the retained derived data bytes."""
    from bencheval.bfcl_study import parse_variant_manifest

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise BenchEvalError(f"retained variant manifest is not UTF-8: {e}") from e
    identity, overlay = parse_variant_manifest(text, artifacts_dir=Path("."))
    payload = json.loads(text)
    benchmark_version = payload.get("benchmark_version")
    if not isinstance(benchmark_version, str) or not benchmark_version:
        raise BenchEvalError("variant manifest is missing its benchmark_version string")
    _bind_derived_files(identity, overlay, derived_files)
    return _Variant(
        payload=payload,
        benchmark_version=benchmark_version,
        identity=identity,
        sha256=_sha256_text(text),
    )


def _jsonl_ids(data: bytes, *, path: str) -> set[str]:
    ids: set[str] = set()
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeDecodeError as e:
        raise BenchEvalError(f"retained derived file {path} is not UTF-8: {e}") from e
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise BenchEvalError(f"retained derived file {path} is not JSONL: {e}") from e
        instance_id = row.get("id") if isinstance(row, dict) else None
        if not isinstance(instance_id, str):
            raise BenchEvalError(f"retained derived file {path} has a row without a string id")
        ids.add(instance_id)
    return ids


def _bind_derived_files(
    identity: object, overlay: object, derived_files: Mapping[str, bytes]
) -> None:
    """The measured representation must be in the proof and match the manifest and identity.

    Every declared derived file is required, byte-bound to the manifest digest and
    (through the combined digest) to the derived identity, and must contain every
    mapped derived instance id in its own category file.
    """
    from bencheval.bfcl_study import derived_data_sha256, question_file_for
    from bencheval.proof_bundle import variant_derived_proof_path

    package_dir = overlay.package_dir.as_posix()  # type: ignore[attr-defined]
    actual: dict[str, str] = {}
    retained_ids: dict[str, set[str]] = {}
    for rel, pin in sorted(overlay.derived_files.items()):  # type: ignore[attr-defined]
        path = variant_derived_proof_path(package_dir, rel)
        data = derived_files.get(path)
        if data is None:
            raise BenchEvalError(
                f"proof does not retain the derived file {path} declared by the variant manifest"
            )
        digest = f"sha256:{hashlib.sha256(data).hexdigest()}"
        if digest != pin:
            raise BenchEvalError(
                f"retained derived file {path} does not match the variant manifest digest"
            )
        actual[rel] = digest
        retained_ids[rel] = _jsonl_ids(data, path=path)
    if derived_data_sha256(actual) != identity.derived_data_sha256:  # type: ignore[attr-defined]
        raise BenchEvalError("retained derived files do not match the derived identity digest")
    missing = sorted(
        entry.derived_instance_id
        for entry in identity.source_mapping  # type: ignore[attr-defined]
        if entry.derived_instance_id
        not in retained_ids.get(question_file_for(entry.derived_instance_id), set())
    )
    if missing:
        raise BenchEvalError(
            f"retained derived files do not contain the mapped instance ids: {missing[:5]}"
        )


def _assert_variant(
    study: ExposureStudyManifest,
    selection: ExposureSelection | None,
    variant: _Variant,
    canonical: _SideRows,
    candidate: _SideRows,
) -> None:
    """Bind the derived side to its retained content identity, source, study, and mapping."""
    from bencheval.identity_strings import bfcl_benchmark_identity, bfcl_derived_benchmark_identity

    identity = variant.identity
    declared = study.variant
    if study.kind != "representation_pair" or declared is None:
        raise BenchEvalError("a variant manifest belongs only to a representation-pair study")
    if bfcl_derived_benchmark_identity(identity) != variant.benchmark_version:  # type: ignore[arg-type]
        raise BenchEvalError("variant manifest benchmark_version does not match its identity")
    if candidate.benchmark_version != variant.benchmark_version:
        raise BenchEvalError(
            f"candidate evidence benchmark_version {candidate.benchmark_version!r} is not the "
            f"retained derived identity {variant.benchmark_version!r}",
        )
    if (
        identity.benchmark_id != study.candidate.benchmark_id
        or identity.source_benchmark_id != study.canonical.benchmark_id
    ):  # type: ignore[attr-defined]
        raise BenchEvalError(
            "variant identity does not name the study's canonical and candidate benchmarks"
        )
    source_version = bfcl_benchmark_identity(
        identity.source_identity, benchmark_id=study.canonical.benchmark_id
    )  # type: ignore[attr-defined]
    if canonical.benchmark_version != source_version:
        raise BenchEvalError(
            f"variant source identity {source_version!r} is not the canonical evidence "
            f"benchmark version {canonical.benchmark_version!r}",
        )
    expected_digest = exposure_study_sha256(study)
    if identity.study_sha256 != expected_digest:  # type: ignore[attr-defined]
        raise BenchEvalError("variant identity binds a different study digest")
    if identity.seed != study.population.seed:  # type: ignore[attr-defined]
        raise BenchEvalError("variant identity seed is not the study seed")
    if (
        identity.transform_id != declared.transform_id
        or identity.transform_version != declared.transform_version
    ):  # type: ignore[attr-defined]
        raise BenchEvalError("variant identity transform does not match the study variant")
    mapping = {e.derived_instance_id: e.source_instance_id for e in identity.source_mapping}  # type: ignore[attr-defined]
    if any(derived != source for derived, source in mapping.items()):
        raise BenchEvalError("tool-order variant mapping must keep derived ids equal to source ids")
    if selection is not None and set(mapping) != set(selection.candidate.selected_ids):
        raise BenchEvalError("variant mapping is not the selected candidate population")
    if not set(candidate.rows) <= set(mapping):
        extra = sorted(set(candidate.rows) - set(mapping))
        raise BenchEvalError(f"candidate rows outside the variant mapping: {extra}")


# --- configured BFCL registration (architecture §23.4) ---------------------------

_REGISTRATION_LABEL = re.compile(r"^bfcl-eval@([^+\s]+)\+registration-([0-9a-f]{64})$")


@dataclass(frozen=True, slots=True)
class _Registration:
    """A retained ``execution/bfcl-registration.json``, parsed from inventory-bound bytes."""

    payload: dict[str, object]
    sha256: str  # registration digest, sha256:<hex>
    harness_version: str
    base_version: str
    registry_id: str
    api_model: str
    handler: str
    manifest_sha256: str


def _parse_registration(raw: bytes) -> _Registration:
    from bencheval.bfcl_package import parse_registration_manifest

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise BenchEvalError(f"retained registration manifest is not UTF-8: {e}") from e
    spec, payload = parse_registration_manifest(text)
    base = payload["base"]
    assert isinstance(base, dict)
    return _Registration(
        payload=payload,
        sha256=str(payload["registration_sha256"]),
        harness_version=str(payload["harness_version"]),
        base_version=str(base["bfcl_eval_version"]),
        registry_id=spec.registry_id,
        api_model=spec.api_model,
        handler=spec.handler,
        manifest_sha256=_sha256_text(text),
    )


def _side_harness_version(side: _SideRows) -> str | None:
    labels = {record.harness_version for record in side.rows.values()}
    if len(labels) != 1:
        raise BenchEvalError(
            f"{side.side} harness_version drifts within one run: {sorted(map(str, labels))}"
        )
    return next(iter(labels))


def _assert_registration(
    registrations: tuple[_Registration | None, _Registration | None],
    canonical: _SideRows,
    candidate: _SideRows,
) -> _Registration | None:
    """Bind a configured-registration label to retained bytes, shared by both arms.

    A ``+registration-<digest>`` harness label is a claim; only the retained
    manifest with that digest substantiates it, and both arms must carry the
    same registration so the representation delta is the only difference.
    """
    for registration, side in zip(registrations, (canonical, candidate), strict=True):
        label = _side_harness_version(side) or ""
        match = _REGISTRATION_LABEL.fullmatch(label)
        if registration is None:
            if match is not None:
                raise BenchEvalError(
                    f"{side.side} evidence names configured registration {label!r} but its "
                    "proof retains no execution/bfcl-registration.json",
                )
            continue
        if (
            match is None
            or match.group(2) != registration.sha256.removeprefix("sha256:")
            or registration.harness_version != label
        ):
            raise BenchEvalError(
                f"{side.side} retained registration {registration.sha256} does not bind the "
                f"evidence harness_version {label!r}",
            )
    base_reg, cand_reg = registrations
    if (base_reg is None) != (cand_reg is None):
        raise BenchEvalError(
            "a configured registration must be shared by both arms; one side has none"
        )
    if base_reg is not None and cand_reg is not None and base_reg.sha256 != cand_reg.sha256:
        raise BenchEvalError(
            f"registration differs across arms: canonical {base_reg.sha256}, "
            f"candidate {cand_reg.sha256}",
        )
    return base_reg


def _registration_summary(registration: _Registration) -> dict[str, object]:
    return {
        "registration_sha256": registration.sha256,
        "registry_id": registration.registry_id,
        "api_model": registration.api_model,
        "handler": registration.handler,
        "harness_version": registration.harness_version,
        "base_harness_version": f"bfcl-eval@{registration.base_version}",
    }


def _variant_summary(variant: _Variant | None) -> dict[str, object] | None:
    if variant is None:
        return None
    identity = variant.identity
    return {
        "benchmark_version": variant.benchmark_version,
        "transform_id": identity.transform_id,  # type: ignore[attr-defined]
        "transform_version": identity.transform_version,  # type: ignore[attr-defined]
        "derived_data_sha256": identity.derived_data_sha256,  # type: ignore[attr-defined]
        "variant_sha256": variant.sha256,
    }


def _selection_summary(selection: ExposureSelection | None) -> dict[str, object] | None:
    if selection is None:
        return None
    return {
        "schema_version": selection.schema_version,
        "algorithm": selection.algorithm,
        "seed": selection.seed,
        "selection_sha256": exposure_selection_sha256(selection),
    }


# --- analysis ------------------------------------------------------------------


def _counts(rows: Sequence[EvidenceRecord]) -> dict[str, object]:
    return {"eligible": len(rows), "passed": sum(1 for r in rows if r.primary_pass)}


def _with_rate(counts: dict[str, object]) -> dict[str, object]:
    passed = int(counts["passed"])
    eligible = int(counts["eligible"])
    point, low, high = wilson(passed, eligible)
    return {**counts, "rate": {"method": "wilson_95", "point": point, "low": low, "high": high}}


def _side_summary(side: _SideRows, *, declared: bool) -> dict[str, object]:
    strata = {name: _counts(rows) for name, rows in sorted(side.strata.items())}
    overall = _counts(list(side.rows.values()))
    if declared:
        strata = {name: _with_rate(counts) for name, counts in strata.items()}
        overall = _with_rate(overall)
    return {
        "run_id": side.run_id,
        "benchmark_version": side.benchmark_version,
        "slice_id": side.slice_id,
        "strata": strata,
        "overall": overall,
    }


def _difference(canonical: dict[str, object], candidate: dict[str, object]) -> dict[str, object]:
    base = canonical["overall"]["rate"]  # type: ignore[index]
    cand = candidate["overall"]["rate"]  # type: ignore[index]
    delta = cand["point"] - base["point"]
    low, high = newcombe_diff(
        base["point"], base["low"], base["high"], cand["point"], cand["low"], cand["high"], delta
    )
    return {"method": "newcombe_95", "point": delta, "low": low, "high": high}


def _pairs(canonical: _SideRows, candidate: _SideRows) -> dict[str, int]:
    both_pass = both_fail = canonical_only = candidate_only = 0
    for instance_id, base in canonical.rows.items():
        cand = candidate.rows[instance_id]
        if base.primary_pass and cand.primary_pass:
            both_pass += 1
        elif base.primary_pass:
            canonical_only += 1
        elif cand.primary_pass:
            candidate_only += 1
        else:
            both_fail += 1
    return {
        "eligible": len(canonical.rows),
        "both_pass": both_pass,
        "both_fail": both_fail,
        "canonical_only_pass": canonical_only,
        "candidate_only_pass": candidate_only,
    }


def _paired_payload(base: _SideRows, cand: _SideRows, *, declared: bool) -> dict[str, object]:
    pairs = _pairs(base, cand)
    payload: dict[str, object] = {"pairs": pairs}
    if declared:
        canonical_only = pairs["canonical_only_pass"]
        candidate_only = pairs["candidate_only_pass"]
        payload["paired_delta"] = (candidate_only - canonical_only) / pairs["eligible"]
        payload["paired_test"] = {
            "method": "exact_binomial",
            "discordant_pairs": canonical_only + candidate_only,
            "p_value": exact_binomial_two_sided(canonical_only, candidate_only),
        }
    return payload


def _caveats(study: ExposureStudyManifest, *, scale: str, retrieval_observed: bool) -> list[str]:
    caveats = [
        f"relation={study.relation}: a gap measures {study.permitted_interpretation}, "
        "not model cleanliness, cheating, novelty, or a corrected score",
    ]
    if scale == "smoke":
        caveats.append(
            "smoke population proves plumbing only; no rate, interval, or test is emitted"
        )
    if study.comparison_mode == "stratified_unpaired":
        caveats.append(
            "populations are unpaired and stratified; difficulty, language, and category mix "
            "shifts are not separated from freshness",
        )
    if retrieval_observed:
        caveats.append(
            "retrieval_observed on at least one attempt: runtime leakage is possible and no "
            "exposure-hardened interpretation applies",
        )
    return caveats


def build_exposure_report(
    study: ExposureStudyManifest,
    *,
    canonical: Sequence[EvidenceRecord],
    candidate: Sequence[EvidenceRecord],
    analysis: Analysis,
    selection: ExposureSelection | None = None,
) -> ExposureReport:
    """Validate two raw native evidence populations and build a raw-count report.

    Raw evidence carries no population authority, so ``declared`` analysis is
    rejected here; it exists only on the proof-backed path, whose bindings come
    from the retained run plan of a verified complete proof.
    """
    if analysis == "declared":
        raise BenchEvalError(
            "declared analysis requires proof-backed inputs whose populations are bound to a "
            "retained run plan; raw evidence reports raw counts only",
        )
    return _assemble_report(
        study,
        canonical=canonical,
        candidate=candidate,
        analysis=analysis,
        bindings=None,
        selection=selection,
    )


def _assemble_report(
    study: ExposureStudyManifest,
    *,
    canonical: Sequence[EvidenceRecord],
    candidate: Sequence[EvidenceRecord],
    analysis: Analysis,
    bindings: tuple[_PopulationBinding, _PopulationBinding] | None,
    selection: ExposureSelection | None = None,
    variant: _Variant | None = None,
    registrations: tuple[_Registration | None, _Registration | None] = (None, None),
) -> ExposureReport:
    if analysis not in ("raw_only", "declared"):
        raise BenchEvalError(f"unknown analysis {analysis!r}")
    canonical_counts = study.population.canonical_counts
    candidate_counts = study.population.candidate_counts
    derived_from = study.canonical.benchmark_id if study.kind == "representation_pair" else None
    base = _bind_side(
        "canonical", study.canonical, tuple(canonical_counts), canonical, derived_from=None
    )
    cand = _bind_side(
        "candidate",
        study.candidate,
        tuple(candidate_counts),
        candidate,
        derived_from=derived_from,
    )
    axes = _assert_constant_axes(study, base, cand)
    if study.comparison_mode == "paired_by_source_instance":
        _assert_paired(base, cand)
    scale = _population_scale(study, (base, canonical_counts), (cand, candidate_counts))
    _assert_slice(base, study.canonical, scale)
    _assert_slice(cand, study.candidate, scale)
    if bindings is not None:
        _assert_bound_population(base, study.canonical, bindings[0])
        _assert_bound_population(cand, study.candidate, bindings[1])
    if selection is not None:
        _assert_selection(study, selection, scale, (base, cand), bindings)
    if variant is not None:
        _assert_variant(study, selection, variant, base, cand)
    registration = _assert_registration(registrations, base, cand)
    declared = analysis == "declared"
    if declared:
        _assert_declared_allowed(scale, bindings, base, cand, variant=variant)
        if selection is None:
            raise BenchEvalError(
                "declared analysis requires the retained population selection "
                "(exposure-selection-v1) so the report can enforce the seeded population",
            )
    retrieval_observed = any(
        r.retrieval_audit == "retrieval_observed"
        for side in (base, cand)
        for r in side.rows.values()
    )
    payload: dict[str, object] = {
        "report_contract_version": REPORT_CONTRACT_VERSION,
        "study_id": study.id,
        "study_sha256": exposure_study_sha256(study),
        "kind": study.kind,
        "relation": study.relation,
        "comparison_mode": study.comparison_mode,
        "analysis_mode": "declared_population" if declared else "plumbing_only",
        "population_scale": scale,
        "population_binding": (
            None if bindings is None else [bindings[0].source, bindings[1].source]
        ),
        "constant_axes": axes,
        "retrieval_observed": retrieval_observed,
        "canonical": {
            "benchmark_id": study.canonical.benchmark_id,
            **_side_summary(base, declared=declared),
        },
        "candidate": {
            "benchmark_id": study.candidate.benchmark_id,
            **_side_summary(cand, declared=declared),
        },
        "permitted_interpretation": study.permitted_interpretation,
        "forbidden_claims": list(study.forbidden_claims),
        "caveats": _caveats(study, scale=scale, retrieval_observed=retrieval_observed),
    }
    if selection is not None:
        # Only present when a selection was enforced: the raw-only report bytes
        # (and every lock written before selections existed) stay unchanged.
        payload["population_selection"] = _selection_summary(selection)
    if variant is not None:
        payload["variant"] = _variant_summary(variant)
    if registration is not None:
        # Only present for configured-registration runs; historical bytes unchanged.
        payload["registration"] = _registration_summary(registration)
    if study.comparison_mode == "paired_by_source_instance":
        payload.update(_paired_payload(base, cand, declared=declared))
    elif declared:
        payload["difference"] = _difference(payload["canonical"], payload["candidate"])  # type: ignore[arg-type]
    return ExposureReport(payload)


# --- rendering -----------------------------------------------------------------


def _fmt_rate(rate: object) -> str:
    if not isinstance(rate, dict):
        return ""
    return f"{rate['point']:.3f} [{rate['low']:.3f}, {rate['high']:.3f}]"


def _side_lines(label: str, side: dict[str, object]) -> list[str]:
    lines = [
        f"## {label}: `{side['benchmark_id']}`",
        "",
        f"- Run: `{side['run_id']}`",
        f"- Benchmark version: `{side['benchmark_version']}`",
        f"- Slice: `{side['slice_id']}`",
        "",
        "| Stratum | Eligible | Passed | Rate (95% interval) |",
        "| --- | ---: | ---: | --- |",
    ]
    strata = side["strata"]
    assert isinstance(strata, dict)
    overall = side["overall"]
    assert isinstance(overall, dict)
    for name, counts in [*strata.items(), ("**overall**", overall)]:
        rate = _fmt_rate(counts.get("rate"))
        lines.append(f"| {name} | {counts['eligible']} | {counts['passed']} | {rate} |")
    lines.append("")
    return lines


def render_exposure_markdown(report: ExposureReport) -> str:
    p = report.payload
    lines = [
        f"# Exposure study `{p['study_id']}`",
        "",
        f"- Report contract: `{p['report_contract_version']}`",
        f"- Study digest: `{p['study_sha256']}`",
        f"- Kind / relation: {p['kind']} / {p['relation']}",
        f"- Comparison mode: {p['comparison_mode']}",
        f"- Analysis mode: **{p['analysis_mode']}** ({p['population_scale']} population)",
        f"- Population binding: {p['population_binding'] or 'none (raw-only ceiling)'}",
        f"- Permitted interpretation: {p['permitted_interpretation']}",
        f"- Forbidden claims: {', '.join(p['forbidden_claims'])}",  # type: ignore[arg-type]
        f"- Retrieval observed: {str(p['retrieval_observed']).lower()}",
        "",
        "## Constant axes",
        "",
    ]
    axes = p["constant_axes"]
    assert isinstance(axes, dict)
    lines.extend(f"- {axis}: `{value}`" for axis, value in axes.items())
    lines.append("")
    lines.extend(_side_lines("Canonical", p["canonical"]))  # type: ignore[arg-type]
    lines.extend(_side_lines("Candidate", p["candidate"]))  # type: ignore[arg-type]
    if "pairs" in p:
        pairs = p["pairs"]
        assert isinstance(pairs, dict)
        lines.extend(["## Paired outcomes", ""])
        lines.extend(f"- {key}: {value}" for key, value in pairs.items())
        if "paired_delta" in p:
            test = p["paired_test"]
            assert isinstance(test, dict)
            lines.append(f"- paired delta (candidate minus canonical): {p['paired_delta']:+.3f}")
            lines.append(
                f"- {test['method']}: discordant pairs {test['discordant_pairs']}, "
                f"p-value {test['p_value']:.4f}"
            )
        lines.append("")
    if "difference" in p:
        diff = p["difference"]
        assert isinstance(diff, dict)
        lines.extend(
            [
                "## Difference (candidate minus canonical)",
                "",
                f"- {diff['method']}: {diff['point']:+.3f} "
                f"[{diff['low']:+.3f}, {diff['high']:+.3f}]",
                "",
            ],
        )
    lines.extend(["## Caveats", ""])
    lines.extend(f"- {caveat}" for caveat in p["caveats"])  # type: ignore[union-attr]
    lines.append("")
    return "\n".join(lines)


def render_exposure(report: ExposureReport, fmt: ReportFormat) -> str:
    return report.to_json() if fmt == "json" else render_exposure_markdown(report)


# --- exclusive output ----------------------------------------------------------


def _open_exclusive(path: Path) -> int:
    try:
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except OSError as e:
        raise BenchEvalError(f"cannot create exclusive output {path}: {e}") from e


def _write_all_exclusive(targets: Sequence[tuple[Path, str]]) -> None:
    """Create every target exclusively before writing any; unwind on failure."""
    created: list[Path] = []
    pending: list[int] = []
    try:
        for path, _ in targets:
            pending.append(_open_exclusive(path))
            created.append(path)
        for (_, text), fd in zip(targets, list(pending), strict=True):
            pending.remove(fd)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
        created.clear()
    except BaseException as e:
        for fd in pending:
            try:
                os.close(fd)
            except OSError:
                pass
        for path in created:
            try:
                path.unlink()
            except OSError:
                pass
        if isinstance(e, OSError):
            raise BenchEvalError(f"cannot write exposure output: {e}") from e
        raise


def write_exposure_report(report: ExposureReport, *, output: Path, fmt: ReportFormat) -> None:
    _write_all_exclusive([(output, render_exposure(report, fmt))])


# --- proof-backed mode ---------------------------------------------------------


def _load_proof_side(root: Path) -> _ProofSide:
    """Verify a complete proof and bind its population to the retained run plan."""
    inputs = load_verified_proof_inputs(root, require_complete=True)
    if inputs.run_plan is None:
        raise BenchEvalError(f"proof {inputs.proof_id} has no retained run plan")
    return _ProofSide(
        proof_id=inputs.proof_id,
        evidence_sha256=inputs.evidence_sha256,
        records=inputs.records,
        binding=_PopulationBinding.from_run_plan(
            inputs.run_plan, source=f"run-plan.json@{inputs.proof_id}"
        ),
        variant_manifest=inputs.variant_manifest,
        variant_derived_files=inputs.variant_derived_files,
        registration_manifest=inputs.registration_manifest,
    )


def _lock_payload(
    study: ExposureStudyManifest,
    *,
    analysis: Analysis,
    canonical: _ProofSide,
    candidate: _ProofSide,
    report_sha256: str,
    selection: ExposureSelection | None,
    variant: _Variant | None = None,
    registration: _Registration | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": EXPOSURE_LOCK_SCHEMA,
        "study_id": study.id,
        "study_sha256": exposure_study_sha256(study),
        # The exact selected definition travels with the lock so two copied
        # proofs plus this file reproduce the report after the YAML is gone.
        "study": study.model_dump(mode="json"),
        "analysis": analysis,
        "report_contract_version": REPORT_CONTRACT_VERSION,
        "canonical": {
            "proof_id": canonical.proof_id,
            "evidence_path": _PROOF_EVIDENCE_NAME,
            "evidence_sha256": canonical.evidence_sha256,
        },
        "candidate": {
            "proof_id": candidate.proof_id,
            "evidence_path": _PROOF_EVIDENCE_NAME,
            "evidence_sha256": candidate.evidence_sha256,
        },
        "report_sha256": report_sha256,
    }
    if selection is not None:
        # Retained beside the study definition; absent for raw-only plumbing locks.
        payload["selection"] = selection.model_dump(mode="json")
        payload["selection_sha256"] = exposure_selection_sha256(selection)
    if variant is not None:
        # The derived side's retained manifest, as read from inventory-bound proof bytes.
        payload["variant"] = variant.payload
        payload["variant_sha256"] = variant.sha256
    if registration is not None:
        # The shared configured registration, as read from inventory-bound proof bytes.
        payload["registration"] = registration.payload
        payload["registration_sha256"] = registration.sha256
    return payload


def _proof_variant(side: _ProofSide) -> _Variant | None:
    if side.variant_manifest is None:
        return None
    return _parse_variant(side.variant_manifest, side.variant_derived_files)


def _proof_registration(side: _ProofSide) -> _Registration | None:
    if side.registration_manifest is None:
        return None
    return _parse_registration(side.registration_manifest)


def _lock_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _build_proof_backed(
    study: ExposureStudyManifest,
    *,
    canonical_proof: Path,
    candidate_proof: Path,
    analysis: Analysis,
    selection: ExposureSelection | None,
) -> ProofBackedReport:
    canonical = _load_proof_side(canonical_proof)
    candidate = _load_proof_side(candidate_proof)
    if canonical.proof_id == candidate.proof_id:
        raise BenchEvalError("canonical and candidate proofs must be distinct proof objects")
    variant = _proof_variant(candidate)
    registrations = (_proof_registration(canonical), _proof_registration(candidate))
    report = _assemble_report(
        study,
        canonical=canonical.records,
        candidate=candidate.records,
        analysis=analysis,
        bindings=(canonical.binding, candidate.binding),
        selection=selection,
        variant=variant,
        registrations=registrations,
    )
    lock = _lock_payload(
        study,
        analysis=analysis,
        canonical=canonical,
        candidate=candidate,
        report_sha256=report.sha256,
        selection=selection,
        variant=variant,
        registration=registrations[0],
    )
    return ProofBackedReport(report, report.sha256, _sha256_text(_lock_text(lock)), lock)


def write_proof_backed_exposure_report(
    study: ExposureStudyManifest,
    *,
    canonical_proof: Path,
    candidate_proof: Path,
    analysis: Analysis,
    output: Path,
    lock_output: Path,
    fmt: ReportFormat,
    selection: ExposureSelection | None = None,
) -> ProofBackedReport:
    """Verify both proofs, build the report, and write report + lock atomically."""
    if output.resolve() == lock_output.resolve():
        raise BenchEvalError("report output and lock output must differ")
    built = _build_proof_backed(
        study,
        canonical_proof=canonical_proof,
        candidate_proof=candidate_proof,
        analysis=analysis,
        selection=selection,
    )
    _write_all_exclusive(
        [
            (output, render_exposure(built.report, fmt)),
            (lock_output, _lock_text(built.lock_payload)),
        ]
    )
    return built


def _read_lock(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BenchEvalError(f"cannot read exposure study lock {path}: {e}") from e
    if not isinstance(raw, dict) or raw.get("schema_version") != EXPOSURE_LOCK_SCHEMA:
        raise BenchEvalError(f"{path} is not an {EXPOSURE_LOCK_SCHEMA} lock")
    return raw


def _require_lock_field(lock: dict[str, object], key: str, expected: object, *, what: str) -> None:
    if lock.get(key) != expected:
        raise BenchEvalError(
            f"lock {what} does not match: locked {lock.get(key)!r}, actual {expected!r}",
        )


def _require_lock_side(lock: dict[str, object], side: _Side, loaded: _ProofSide) -> None:
    bound = lock.get(side)
    if not isinstance(bound, dict):
        raise BenchEvalError(f"lock is missing the {side} proof binding")
    if bound.get("proof_id") != loaded.proof_id:
        raise BenchEvalError(
            f"{side} proof id does not match the lock: locked {bound.get('proof_id')!r}, "
            f"actual {loaded.proof_id!r}",
        )
    if (
        bound.get("evidence_path") != _PROOF_EVIDENCE_NAME
        or bound.get("evidence_sha256") != loaded.evidence_sha256
    ):
        raise BenchEvalError(f"{side} evidence input does not match the lock")


def _retained_study(lock: dict[str, object]) -> ExposureStudyManifest:
    """The study definition the lock carries, checked against its own digest."""
    raw = lock.get("study")
    if not isinstance(raw, dict):
        raise BenchEvalError("lock is missing the retained study definition")
    try:
        study = ExposureStudyManifest.model_validate(raw)
    except ValidationError as e:
        raise BenchEvalError(f"lock retained study definition is invalid: {e}") from e
    _require_lock_field(lock, "study_sha256", exposure_study_sha256(study), what="study digest")
    _require_lock_field(lock, "study_id", study.id, what="study id")
    return study


def _retained_selection(lock: dict[str, object]) -> ExposureSelection | None:
    """The selection the lock carries (declared locks), checked against its digest."""
    raw = lock.get("selection")
    digest = lock.get("selection_sha256")
    if raw is None and digest is None:
        return None
    if not isinstance(raw, dict):
        raise BenchEvalError("lock is missing the retained population selection")
    selection = parse_exposure_selection(raw, source="lock selection")
    if digest != exposure_selection_sha256(selection):
        raise BenchEvalError("lock selection digest does not match the retained selection")
    return selection


def verify_exposure_study_lock(
    study: ExposureStudyManifest | None,
    *,
    lock_path: Path,
    canonical_proof: Path,
    candidate_proof: Path,
    output: Path | None = None,
    fmt: ReportFormat = "json",
    selection: ExposureSelection | None = None,
) -> dict[str, object]:
    """Reproduce a locked report from copied proof objects and the retained study.

    ``study`` is optional: the lock carries the exact selected definition. A
    supplied manifest must match that retained copy by digest. ``output``
    writes the reproduced report exclusively once every binding holds.
    """
    lock = _read_lock(lock_path)
    analysis = lock.get("analysis")
    if analysis not in ("raw_only", "declared"):
        raise BenchEvalError(f"lock analysis {analysis!r} is not a supported mode")
    retained = _retained_study(lock)
    supplied = study
    if supplied is not None:
        _require_lock_field(
            lock, "study_sha256", exposure_study_sha256(supplied), what="supplied study digest"
        )
    study = retained
    retained_selection = _retained_selection(lock)
    supplied_selection = selection
    if supplied_selection is not None:
        if retained_selection is None:
            raise BenchEvalError("lock retains no population selection to compare against")
        if exposure_selection_sha256(supplied_selection) != exposure_selection_sha256(
            retained_selection
        ):
            raise BenchEvalError("supplied population selection does not match the lock")
    _require_lock_field(
        lock, "report_contract_version", REPORT_CONTRACT_VERSION, what="report contract version"
    )
    canonical = _load_proof_side(canonical_proof)
    candidate = _load_proof_side(candidate_proof)
    _require_lock_side(lock, "canonical", canonical)
    _require_lock_side(lock, "candidate", candidate)
    variant = _proof_variant(candidate)
    if (lock.get("variant_sha256") is not None) != (variant is not None) or (
        variant is not None and lock.get("variant_sha256") != variant.sha256
    ):
        raise BenchEvalError("lock variant binding does not match the candidate proof's manifest")
    registrations = (_proof_registration(canonical), _proof_registration(candidate))
    locked_registration = lock.get("registration_sha256")
    if (locked_registration is not None) != (registrations[0] is not None) or (
        registrations[0] is not None and locked_registration != registrations[0].sha256
    ):
        raise BenchEvalError("lock registration binding does not match the retained proofs")
    report = _assemble_report(
        study,
        canonical=canonical.records,
        candidate=candidate.records,
        analysis=analysis,
        bindings=(canonical.binding, candidate.binding),
        selection=retained_selection,
        variant=variant,
        registrations=registrations,
    )
    _require_lock_field(lock, "report_sha256", report.sha256, what="report digest")
    expected = _lock_payload(
        study,
        analysis=analysis,
        canonical=canonical,
        candidate=candidate,
        report_sha256=report.sha256,
        selection=retained_selection,
        variant=variant,
        registration=registrations[0],
    )
    if lock != expected:
        raise BenchEvalError("lock contains fields outside the exposure-study-lock-v1 contract")
    if output is not None:
        write_exposure_report(report, output=output, fmt=fmt)
    return {
        "ok": True,
        "study_id": study.id,
        "study_sha256": expected["study_sha256"],
        "study_source": "lock" if supplied is None else "supplied",
        "selection_sha256": (
            None if retained_selection is None else exposure_selection_sha256(retained_selection)
        ),
        "selection_source": (
            None
            if retained_selection is None
            else ("lock" if supplied_selection is None else "supplied")
        ),
        "canonical_proof_id": canonical.proof_id,
        "candidate_proof_id": candidate.proof_id,
        "report_sha256": report.sha256,
        "lock_sha256": _sha256_text(_lock_text(expected)),
    }


def resolve_study_reference(value: str) -> Path | str:
    """CLI helper: a path-like argument loads a file, otherwise a repository study id."""
    if "/" in value or value.endswith((".yaml", ".yml")):
        return Path(value)
    return value


__all__ = [
    "EXPOSURE_LOCK_SCHEMA",
    "REPORT_CONTRACT_VERSION",
    "Analysis",
    "ExposureReport",
    "ProofBackedReport",
    "ReportFormat",
    "build_exposure_report",
    "render_exposure",
    "render_exposure_markdown",
    "resolve_study_reference",
    "validate_exposure_study",
    "verify_exposure_study_lock",
    "write_exposure_report",
    "write_proof_backed_exposure_report",
]
