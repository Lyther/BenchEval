"""Repeat protocol: identity, block partition, balanced schedule, multi-proof lock.

The protocol is a separately versioned 400-case identity over the existing
BFCL tool-order representation pair. It never selects, drops, reorders within a
case, or transforms a question: the blocking randomness only groups ids that the
retained selection already chose, and the assignment draw only decides which of
the two canonical-versus-treatment orders each block runs in.

A new lock schema ``exposure-protocol-lock-v1`` binds the protocol record, the
partition, the schedule, all 120 run proofs and the exact report bytes. The
existing two-proof ``exposure-study-lock-v1`` is not extended and not touched.

Specification: ``docs/context/bfcl-repeat-spec.md``.
Method and frozen parameters: ``docs/context/bfcl-repeat-protocol.md``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from bencheval.exceptions import BenchEvalError
from bencheval.exposure_repeat import (
    REPEAT_CONTRACT_VERSION,
    CaseOutcome,
    ProtocolReport,
    build_estimand,
    build_protocol_report,
    observable_block_interval,
    randomization_p_value,
    slot_differences,
)
from bencheval.exposure_selection import ExposureSelection
from bencheval.exposure_study import ExposureStudyManifest, exposure_study_sha256

PROTOCOL_CONTRACT_VERSION = "exposure-protocol-v1"
PROTOCOL_LOCK_SCHEMA = "exposure-protocol-lock-v1"

#: Chronological slot 1 is always the anchor; the treatment and the repeat are
#: randomized over slots 2 and 3, and ``z = +1`` when the treatment holds slot 2.
Arm = Literal["anchor", "treatment", "repeat"]
ARMS: tuple[Arm, ...] = ("anchor", "treatment", "repeat")

_PROOF_EVIDENCE_NAME = "evidence.jsonl"


@dataclass(frozen=True, slots=True)
class ProtocolDefinition:
    """The frozen parameters of one supported protocol.

    Design owns every value here. The implementation may bind them, refuse a
    mismatch, and nothing else.
    """

    protocol_id: str
    #: The representation-pair study that defines the treatment, route and
    #: forbidden claims. The protocol's own id names its 400-case identity.
    study_id: str
    blocks: int
    per_block: int
    rounds: int
    alpha: float
    planning_effect_points: int
    unmet_effect_points: int
    failure_policy: str
    route_identity: dict[str, str]
    #: Drawn once, at freeze, and never redrawn on an outcome.
    draw_seed: str


_PROTOCOLS: dict[str, ProtocolDefinition] = {
    "bfcl-tool-order-repeat-400-v1": ProtocolDefinition(
        protocol_id="bfcl-tool-order-repeat-400-v1",
        study_id="bfcl-v4-tool-order-v1",
        blocks=40,
        per_block=10,
        rounds=1,
        alpha=0.05,
        planning_effect_points=8,
        unmet_effect_points=5,
        failure_policy="strict_invalidate_population",
        route_identity={"model_id": "gpt-5.2-2025-12-11-FC", "provider_id": "bytellm"},
        draw_seed="bencheval-bfcl-tool-order-repeat-400-v1-assignment",
    ),
}


@dataclass(frozen=True, slots=True)
class BlockPartition:
    """One execution block: an ordered, stratum-balanced slice of the cohort."""

    block_id: str
    instance_ids: tuple[str, ...]
    stratum_counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class SlotAssignment:
    """Which arm occupies which chronological slot in one block of one round."""

    block_id: str
    round_index: int
    slots: tuple[Arm, Arm, Arm]

    @property
    def z(self) -> int:
        """+1 when the treatment holds slot 2, -1 when the repeat does."""
        _require_slots(self.block_id, self.slots)
        return 1 if self.slots[1] == "treatment" else -1


@dataclass(frozen=True, slots=True)
class ProtocolSchedule:
    """The drawn schedule, fixed at freeze and never redrawn on an outcome."""

    assignments: tuple[SlotAssignment, ...]
    draw_seed: str
    allocation_space_size: int


@dataclass(frozen=True, slots=True)
class ArmRunRef:
    """One executed slot and the ordinary run proof that stands behind it.

    ``failure_label`` carries the run's own infrastructure verdict. Anything
    other than ``None`` invalidates the whole primary population: it is never
    scored as model behaviour and never dropped.
    """

    block_id: str
    round_index: int
    arm: Arm
    run_id: str
    proof_id: str
    evidence_sha256: str
    failure_label: str | None = None


@dataclass(frozen=True, slots=True)
class ProtocolManifest:
    """The frozen protocol record. Identity only; it holds no observed outcome."""

    protocol_id: str
    study_id: str
    selection_sha256: str
    source_population_sha256: str
    blocking_seed: str
    blocks: int
    per_block: int
    rounds: int
    alpha: float
    planning_effect_points: int
    unmet_effect_points: int
    failure_policy: str
    route_identity: dict[str, str]
    # The two digests the manifest freezes, so a post-hoc edit to either the
    # block membership or the slot order is a mismatch rather than a surprise.
    partition_sha256: str
    schedule_sha256: str

    @property
    def sha256(self) -> str:
        return _sha256_text(_canonical_json(self.payload))

    @property
    def payload(self) -> dict[str, object]:
        return dataclasses.asdict(self)


def _sha256_text(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _rank_key(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()


def _stratum_of(instance_id: str) -> str:
    """Official BFCL category of an id: everything before the trailing ``_<index>``.

    Same rule the selection path uses to read the official question files; the
    per-stratum balance is independently checked against the retained selection
    in :func:`verify_protocol_population`.
    """
    head, _, _ = instance_id.rpartition("_")
    return head


def _require_slots(block_id: str, slots: tuple[str, ...]) -> None:
    if len(slots) != 3 or sorted(slots) != sorted(ARMS) or slots[0] != "anchor":
        raise BenchEvalError(f"{block_id}: slots must be the three arms with the anchor first")


# --- the cohort partition ----------------------------------------------------------


def partition_cohort(
    instance_ids: tuple[str, ...], *, blocks: int, blocking_seed: str
) -> tuple[BlockPartition, ...]:
    """Deal the cohort into ``blocks`` stratum-balanced blocks by hash rank.

    The blocking randomness only groups already-selected ids. It never selects,
    drops, reorders within a case, or transforms a question.
    """
    instance_ids = tuple(instance_ids)
    if blocks < 1:
        raise BenchEvalError("a partition needs at least one block")
    if not instance_ids:
        raise BenchEvalError("a partition needs a non-empty cohort")
    if len(set(instance_ids)) != len(instance_ids):
        raise BenchEvalError("the cohort repeats an instance id")
    strata: dict[str, list[str]] = {}
    for instance_id in instance_ids:
        strata.setdefault(_stratum_of(instance_id), []).append(instance_id)
    groups: list[list[str]] = [[] for _ in range(blocks)]
    for stratum in sorted(strata):
        ordered = sorted(strata[stratum], key=lambda i: _rank_key(blocking_seed, stratum, i))
        if len(ordered) % blocks:
            raise BenchEvalError(
                f"stratum {stratum!r} holds {len(ordered)} ids, which does not divide "
                f"into {blocks} balanced blocks",
            )
        per_stratum = len(ordered) // blocks
        for index in range(blocks):
            groups[index].extend(ordered[index * per_stratum : (index + 1) * per_stratum])
    partition: list[BlockPartition] = []
    for index, group in enumerate(groups, start=1):
        counts: dict[str, int] = {}
        for instance_id in group:
            counts[_stratum_of(instance_id)] = counts.get(_stratum_of(instance_id), 0) + 1
        partition.append(BlockPartition(f"block-{index:02d}", tuple(group), counts))
    return tuple(partition)


def partition_sha256(partition: tuple[BlockPartition, ...]) -> str:
    """Digest binding block membership and order."""
    return _sha256_text(_canonical_json(_partition_payload(partition)))


def _partition_payload(partition: tuple[BlockPartition, ...]) -> list[dict[str, object]]:
    return [
        {
            "block_id": block.block_id,
            "instance_ids": list(block.instance_ids),
            "stratum_counts": dict(sorted(block.stratum_counts.items())),
        }
        for block in partition
    ]


def _partition_from_payload(raw: object) -> tuple[BlockPartition, ...]:
    if not isinstance(raw, list) or not raw:
        raise BenchEvalError("retained partition is missing or empty")
    partition: list[BlockPartition] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise BenchEvalError("retained partition entry is not an object")
        try:
            partition.append(
                BlockPartition(
                    block_id=str(entry["block_id"]),
                    instance_ids=tuple(str(i) for i in entry["instance_ids"]),
                    stratum_counts={str(k): int(v) for k, v in entry["stratum_counts"].items()},
                )
            )
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise BenchEvalError(f"retained partition entry is invalid: {e}") from e
    return tuple(partition)


# --- the assignment draw -----------------------------------------------------------


def draw_schedule(
    partition: tuple[BlockPartition, ...], *, rounds: int, draw_seed: str
) -> ProtocolSchedule:
    """Draw one balanced slot assignment per round. Drawn once, at freeze."""
    partition = tuple(partition)
    if rounds < 1:
        raise BenchEvalError("a schedule needs at least one round")
    if len(partition) % 2:
        raise BenchEvalError(
            f"{len(partition)} blocks cannot carry a balanced assignment; the reference "
            "space is the balanced allocation space",
        )
    assignments: list[SlotAssignment] = []
    for round_index in range(rounds):
        ranked = sorted(partition, key=lambda b: _rank_key(draw_seed, round_index, b.block_id))
        treatment_first = {block.block_id for block in ranked[: len(ranked) // 2]}
        for block in partition:
            slots: tuple[Arm, Arm, Arm] = (
                ("anchor", "treatment", "repeat")
                if block.block_id in treatment_first
                else ("anchor", "repeat", "treatment")
            )
            assignments.append(SlotAssignment(block.block_id, round_index, slots))
    return ProtocolSchedule(
        assignments=tuple(assignments),
        draw_seed=draw_seed,
        allocation_space_size=math.comb(len(partition), len(partition) // 2) ** rounds,
    )


def schedule_sha256(schedule: ProtocolSchedule) -> str:
    """Digest binding every slot, its order, and the draw seed."""
    return _sha256_text(_canonical_json(_schedule_payload(schedule)))


def _schedule_payload(schedule: ProtocolSchedule) -> dict[str, object]:
    return {
        "assignments": [
            [assignment.block_id, assignment.round_index, list(assignment.slots)]
            for assignment in schedule.assignments
        ],
        "draw_seed": schedule.draw_seed,
        "allocation_space_size": schedule.allocation_space_size,
    }


def _schedule_from_payload(raw: object) -> ProtocolSchedule:
    if not isinstance(raw, dict):
        raise BenchEvalError("retained schedule is missing")
    try:
        assignments = tuple(
            SlotAssignment(str(block_id), int(round_index), tuple(str(s) for s in slots))  # type: ignore[arg-type]
            for block_id, round_index, slots in raw["assignments"]
        )
        return ProtocolSchedule(
            assignments=assignments,
            draw_seed=str(raw["draw_seed"]),
            allocation_space_size=int(raw["allocation_space_size"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise BenchEvalError(f"retained schedule is invalid: {e}") from e


# --- the protocol record -----------------------------------------------------------


def protocol_definition(protocol_id: object) -> ProtocolDefinition:
    """The frozen parameters of ``protocol_id``; an unknown id is a refusal."""
    definition = _PROTOCOLS.get(str(protocol_id))
    if definition is None:
        raise BenchEvalError(
            f"{protocol_id!r} is not a defined repeat protocol; defined: {sorted(_PROTOCOLS)}",
        )
    return definition


def _retained_identity(
    lock: dict[str, object], definition: ProtocolDefinition, *, source: str
) -> tuple[ExposureStudyManifest, ExposureSelection]:
    """The study and selection a lock carries, checked rather than trusted.

    Replaying a caller-supplied ranking only proves self-consistency. The
    retained selection is therefore bound to this exact study (id, digest,
    algorithm, seed) and then to the **installed catalog**: official question
    files, their content pins, and the population anchors the candidate universe
    must match. None of that needs the repository's study files, so the lock
    stays portable without becoming self-asserting.
    """
    from bencheval.exposure_selection import (
        parse_exposure_selection,
        verify_selection_against_catalog,
        verify_selection_for_study,
    )
    from bencheval.exposure_study import parse_exposure_study

    study = parse_exposure_study(lock.get("study"), source=f"{source} study")
    if study.id != definition.protocol_id:
        raise BenchEvalError(
            f"the lock retains study {study.id!r}, not the protocol's {definition.protocol_id!r}",
        )
    if lock.get("study_sha256") != exposure_study_sha256(study):
        raise BenchEvalError("lock study digest does not match the retained study definition")
    selection = parse_exposure_selection(lock.get("selection"), source=f"{source} selection")
    verify_selection_for_study(study, selection)
    verify_selection_against_catalog(selection)
    return study, selection


def protocol_identity(
    definition: ProtocolDefinition,
) -> tuple[ExposureStudyManifest, ExposureSelection]:
    """The protocol's study and 400-case selection, read through the real path.

    The record must replay its own rank algorithm, bind this exact study by
    digest, and match the catalog's pinned question files and population
    anchors. Only the repository-resident path calls this; a lock carries its
    own retained copies, checked the same way.
    """
    from bencheval.exposure_selection import (
        load_exposure_selection,
        verify_selection_against_catalog,
        verify_selection_for_study,
    )
    from bencheval.exposure_study import default_studies_dir, load_exposure_study

    study = load_exposure_study(definition.protocol_id)
    selection = load_exposure_selection(
        default_studies_dir() / f"{definition.protocol_id}.selection.json"
    )
    verify_selection_for_study(study, selection)
    verify_selection_against_catalog(selection)
    return study, selection


def protocol_selection(definition: ProtocolDefinition) -> ExposureSelection:
    """The protocol's retained 400-case selection alone."""
    return protocol_identity(definition)[1]


def _declared_population(
    definition: ProtocolDefinition, selection: ExposureSelection
) -> tuple[tuple[str, ...], str, str]:
    """Ordered instance ids, the selection digest, and the population digest."""
    from bencheval.exposure_selection import exposure_selection_sha256, population_ids_sha256

    if selection.study_id != definition.protocol_id:
        raise BenchEvalError(
            f"the selection names study {selection.study_id!r}, not the protocol's "
            f"{definition.protocol_id!r}",
        )
    ids = selection.canonical.selected_ids
    if sorted(ids) != sorted(selection.candidate.selected_ids):
        raise BenchEvalError(
            f"{definition.protocol_id}: the paired sides do not name the same source cases",
        )
    if len(ids) != definition.blocks * definition.per_block:
        raise BenchEvalError(
            f"{definition.protocol_id}: selection holds {len(ids)} cases, not "
            f"{definition.blocks * definition.per_block}",
        )
    return ids, exposure_selection_sha256(selection), population_ids_sha256(ids)


def protocol_cohort(definition: ProtocolDefinition) -> tuple[tuple[str, ...], str, str]:
    """The declared population of a protocol, read from the repository selection."""
    return _declared_population(definition, protocol_selection(definition))


_REQUIRED_MANIFEST_FIELDS = ("protocol_id", "study_id", "partition_sha256", "schedule_sha256")
_OPTIONAL_MANIFEST_FIELDS = (
    "blocks",
    "per_block",
    "rounds",
    "alpha",
    "planning_effect_points",
    "unmet_effect_points",
    "failure_policy",
    "route_identity",
    "blocking_seed",
    "selection_sha256",
    "source_population_sha256",
)


def build_protocol_manifest(**fields: object) -> ProtocolManifest:
    """Validate and build the frozen protocol record.

    Every design parameter is read from the protocol definition. A supplied
    value is only ever checked against it, never adopted: a manifest naming a
    stale study, selection, route binding, or source-population digest is
    refused here, before any run is planned.
    """
    unknown = set(fields) - set(_REQUIRED_MANIFEST_FIELDS) - set(_OPTIONAL_MANIFEST_FIELDS)
    if unknown:
        raise BenchEvalError(f"unknown protocol manifest fields: {sorted(unknown)}")
    missing = [name for name in _REQUIRED_MANIFEST_FIELDS if name not in fields]
    if missing:
        raise BenchEvalError(f"protocol manifest is missing {missing}")
    definition = protocol_definition(fields["protocol_id"])
    blocking_seed = fields.get("blocking_seed")
    if blocking_seed is not None and not str(blocking_seed).strip():
        raise BenchEvalError("the blocking seed must be a non-empty string")

    _require_declared(fields, "study_id", definition.study_id)
    _require_declared(fields, "blocks", definition.blocks)
    _require_declared(fields, "per_block", definition.per_block)
    _require_declared(fields, "rounds", definition.rounds)
    _require_declared(fields, "alpha", definition.alpha)
    _require_declared(fields, "planning_effect_points", definition.planning_effect_points)
    _require_declared(fields, "unmet_effect_points", definition.unmet_effect_points)
    _require_declared(fields, "failure_policy", definition.failure_policy)
    _require_declared(fields, "route_identity", definition.route_identity)

    _, selection_sha256, population_sha256 = protocol_cohort(definition)
    _require_declared(fields, "selection_sha256", selection_sha256)
    _require_declared(fields, "source_population_sha256", population_sha256)

    return ProtocolManifest(
        protocol_id=definition.protocol_id,
        study_id=definition.study_id,
        selection_sha256=selection_sha256,
        source_population_sha256=population_sha256,
        blocking_seed=str(blocking_seed) if blocking_seed is not None else "",
        blocks=definition.blocks,
        per_block=definition.per_block,
        rounds=definition.rounds,
        alpha=definition.alpha,
        planning_effect_points=definition.planning_effect_points,
        unmet_effect_points=definition.unmet_effect_points,
        failure_policy=definition.failure_policy,
        route_identity=dict(definition.route_identity),
        partition_sha256=str(fields["partition_sha256"]),
        schedule_sha256=str(fields["schedule_sha256"]),
    )


def _require_declared(fields: dict[str, object], name: str, declared: object) -> None:
    """A supplied design parameter must equal the declared one, or be absent."""
    if name in fields and fields[name] != declared:
        raise BenchEvalError(
            f"protocol {name} {fields[name]!r} is not the declared {declared!r}",
        )


def _manifest_from_payload(raw: object) -> ProtocolManifest:
    if not isinstance(raw, dict):
        raise BenchEvalError("retained protocol manifest is missing")
    names = {f.name for f in dataclasses.fields(ProtocolManifest)}
    if set(raw) != names:
        raise BenchEvalError("retained protocol manifest does not carry exactly its own fields")
    try:
        return ProtocolManifest(**raw)  # type: ignore[arg-type]
    except TypeError as e:
        raise BenchEvalError(f"retained protocol manifest is invalid: {e}") from e


# --- the executed population -------------------------------------------------------


def verify_protocol_population(
    manifest: ProtocolManifest,
    partition: tuple[BlockPartition, ...],
    schedule: ProtocolSchedule,
    refs: tuple[ArmRunRef, ...],
) -> None:
    """Refuse a population that is not exactly the declared one.

    Missing, duplicate or foreign instance ids; a slot without a run; two slots
    sharing a proof id; a schedule that does not match its retained digest; or a
    stale study, selection or route identity are all refusals, not warnings.
    """
    definition = protocol_definition(manifest.protocol_id)
    _verify_population(
        manifest, partition, schedule, refs, selection=protocol_selection(definition)
    )


def _verify_population(
    manifest: ProtocolManifest,
    partition: tuple[BlockPartition, ...],
    schedule: ProtocolSchedule,
    refs: tuple[ArmRunRef, ...],
    *,
    selection: ExposureSelection,
) -> None:
    """The same refusals against a selection record, wherever it was read from."""
    definition = protocol_definition(manifest.protocol_id)
    declared, selection_sha256, population_sha256 = _declared_population(definition, selection)
    if manifest.selection_sha256 != selection_sha256:
        raise BenchEvalError("the manifest names a selection that is not the retained one")
    if manifest.source_population_sha256 != population_sha256:
        raise BenchEvalError("the manifest names a source population that is not the retained one")
    # Every design parameter is checked against the definition here as well as at
    # build time, so a lock carrying a self-consistently edited record -- a
    # relaxed effect target, a second round, another route -- is still refused.
    for name, declared_value in (
        ("study_id", definition.study_id),
        ("blocks", definition.blocks),
        ("per_block", definition.per_block),
        ("rounds", definition.rounds),
        ("alpha", definition.alpha),
        ("planning_effect_points", definition.planning_effect_points),
        ("unmet_effect_points", definition.unmet_effect_points),
        ("failure_policy", definition.failure_policy),
        ("route_identity", definition.route_identity),
    ):
        if getattr(manifest, name) != declared_value:
            raise BenchEvalError(
                f"the manifest's {name} is {getattr(manifest, name)!r}, not the declared "
                f"{declared_value!r}",
            )
    if partition_sha256(partition) != manifest.partition_sha256:
        raise BenchEvalError("the partition does not match the digest the manifest froze")
    if schedule_sha256(schedule) != manifest.schedule_sha256:
        raise BenchEvalError("the schedule does not match the digest the manifest froze")

    # A digest only proves the record has not changed since it was written. The
    # blocking and assignment seeds are what make the record *earned*, so both
    # are replayed from their declared rules here: a hand-built partition or a
    # hand-swapped assignment is refused even when every digest is consistent.
    if schedule.draw_seed != definition.draw_seed:
        raise BenchEvalError(
            f"the schedule was drawn under seed {schedule.draw_seed!r}, not the protocol's "
            f"{definition.draw_seed!r}",
        )
    replayed = partition_cohort(
        declared, blocks=manifest.blocks, blocking_seed=manifest.blocking_seed
    )
    if partition_sha256(replayed) != manifest.partition_sha256:
        raise BenchEvalError(
            "the partition does not replay from its declared population and blocking seed",
        )
    redrawn = draw_schedule(partition, rounds=manifest.rounds, draw_seed=schedule.draw_seed)
    if schedule_sha256(redrawn) != manifest.schedule_sha256:
        raise BenchEvalError(
            "the schedule does not replay from its declared partition, rounds and draw seed",
        )

    _verify_partition_population(manifest, partition, declared)
    _verify_slot_references(manifest, schedule, refs)


def _verify_partition_population(
    manifest: ProtocolManifest, partition: tuple[BlockPartition, ...], declared: tuple[str, ...]
) -> None:
    if len(partition) != manifest.blocks:
        raise BenchEvalError(f"the partition holds {len(partition)} blocks, not {manifest.blocks}")
    if len({block.block_id for block in partition}) != len(partition):
        raise BenchEvalError("two blocks share a block id")
    declared_set = set(declared)
    seen: set[str] = set()
    for block in partition:
        if len(block.instance_ids) != manifest.per_block:
            raise BenchEvalError(
                f"{block.block_id} holds {len(block.instance_ids)} cases, not {manifest.per_block}",
            )
        if len(set(block.instance_ids)) != len(block.instance_ids):
            raise BenchEvalError(f"{block.block_id} repeats an instance id")
        counts: dict[str, int] = {}
        for instance_id in block.instance_ids:
            if instance_id not in declared_set:
                raise BenchEvalError(
                    f"{instance_id} is not in the declared population of {manifest.protocol_id}",
                )
            if instance_id in seen:
                raise BenchEvalError(f"{instance_id} appears in more than one block")
            seen.add(instance_id)
            counts[_stratum_of(instance_id)] = counts.get(_stratum_of(instance_id), 0) + 1
        if block.stratum_counts != counts:
            raise BenchEvalError(f"{block.block_id} does not carry its own stratum counts")
    if seen != declared_set:
        missing = sorted(declared_set - seen)
        raise BenchEvalError(
            f"the partition is not the declared population: {len(missing)} missing, "
            f"first {missing[:3]}",
        )


def _verify_slot_references(
    manifest: ProtocolManifest, schedule: ProtocolSchedule, refs: tuple[ArmRunRef, ...]
) -> None:
    expected_slots = {
        (assignment.block_id, assignment.round_index, arm)
        for assignment in schedule.assignments
        for arm in ARMS
    }
    if len(expected_slots) != manifest.blocks * manifest.rounds * len(ARMS):
        raise BenchEvalError("the schedule does not carry one assignment per block and round")
    executed = [(ref.block_id, ref.round_index, ref.arm) for ref in refs]
    if len(set(executed)) != len(executed):
        raise BenchEvalError("one slot is reported more than once")
    if set(executed) != expected_slots:
        unrun = sorted(expected_slots - set(executed))
        foreign = sorted(set(executed) - expected_slots)
        raise BenchEvalError(
            f"the executed slots are not exactly the scheduled slots: {len(unrun)} without a "
            f"run, {len(foreign)} unscheduled",
        )
    if len({ref.proof_id for ref in refs}) != len(refs):
        raise BenchEvalError("two slots name the same proof; each slot keeps its own proof object")
    if len({ref.run_id for ref in refs}) != len(refs):
        raise BenchEvalError("two slots name the same run; each slot is a distinct ordinary run")
    failed = [ref for ref in refs if ref.failure_label is not None]
    if failed:
        raise BenchEvalError(
            f"{failed[0].run_id} failed with {failed[0].failure_label!r}: an infrastructure "
            f"failure invalidates the whole primary population ({manifest.failure_policy})",
        )


# --- the multi-proof lock ----------------------------------------------------------


def build_protocol_lock(
    manifest: ProtocolManifest,
    partition: tuple[BlockPartition, ...],
    schedule: ProtocolSchedule,
    refs: tuple[ArmRunRef, ...],
    *,
    report: object,
) -> dict[str, object]:
    """Bind manifest, partition, schedule, every run proof, and the report bytes.

    The lock retains the report payload as well as its digest, so the two
    together reproduce the report after the working tree is gone -- the same
    contract the two-proof ``exposure-study-lock-v1`` already honours for the
    study definition.
    """
    if not isinstance(report, ProtocolReport):
        raise BenchEvalError("a protocol lock binds a ProtocolReport")
    definition = protocol_definition(manifest.protocol_id)
    study, selection = protocol_identity(definition)
    _verify_population(manifest, partition, schedule, refs, selection=selection)
    return _lock_payload(
        manifest, partition, schedule, refs, report=report, study=study, selection=selection
    )


def _lock_payload(
    manifest: ProtocolManifest,
    partition: tuple[BlockPartition, ...],
    schedule: ProtocolSchedule,
    refs: tuple[ArmRunRef, ...],
    *,
    report: ProtocolReport,
    study: ExposureStudyManifest,
    selection: ExposureSelection,
) -> dict[str, object]:
    return {
        "schema_version": PROTOCOL_LOCK_SCHEMA,
        "protocol_contract_version": PROTOCOL_CONTRACT_VERSION,
        "repeat_contract_version": REPEAT_CONTRACT_VERSION,
        "protocol_id": manifest.protocol_id,
        "study_id": manifest.study_id,
        # The exact frozen record travels with the lock, so the copied proofs
        # plus this file reproduce the report after the working tree is gone.
        "manifest": manifest.payload,
        "manifest_sha256": manifest.sha256,
        # The declared study and its 400-case population travel with the lock, so
        # the copied proofs plus this file verify after the config tree is gone.
        # Both are re-bound to the installed catalog on the way back in.
        "study": study.model_dump(mode="json"),
        "study_sha256": exposure_study_sha256(study),
        "selection": selection.model_dump(mode="json"),
        "partition": _partition_payload(partition),
        "schedule": _schedule_payload(schedule),
        "runs": [
            {
                "block_id": ref.block_id,
                "round_index": ref.round_index,
                "arm": ref.arm,
                "run_id": ref.run_id,
                "proof_id": ref.proof_id,
                "evidence_path": _PROOF_EVIDENCE_NAME,
                "evidence_sha256": ref.evidence_sha256,
            }
            for ref in refs
        ],
        "report": report.payload,
        "report_sha256": report.sha256,
    }


def lock_text(payload: dict[str, object]) -> str:
    """The exact bytes a protocol lock is written as."""
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def _read_lock(path: Path) -> dict[str, object]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise BenchEvalError(f"cannot read protocol lock {path}: {e}") from e
    if not isinstance(raw, dict) or raw.get("schema_version") != PROTOCOL_LOCK_SCHEMA:
        raise BenchEvalError(f"{path} is not an {PROTOCOL_LOCK_SCHEMA} lock")
    return raw


#: Which side of the representation pair each arm runs. A and C are the
#: canonical representation; B is the fixed tool-order treatment.
_ARM_SIDE: dict[Arm, str] = {"anchor": "canonical", "treatment": "candidate", "repeat": "canonical"}


@dataclass(frozen=True, slots=True)
class _VerifiedSlot:
    """One slot's proof after the study's own population and identity rules ran."""

    ref: ArmRunRef
    rows: object  # exposure_report._SideRows
    variant: object | None  # exposure_report._Variant
    passes: dict[str, bool] = field(default_factory=dict)


def _slot_ref(row: object) -> ArmRunRef:
    if not isinstance(row, dict):
        raise BenchEvalError("lock run reference is not an object")
    try:
        ref = ArmRunRef(
            block_id=str(row["block_id"]),
            round_index=int(row["round_index"]),
            arm=str(row["arm"]),  # type: ignore[arg-type]
            run_id=str(row["run_id"]),
            proof_id=str(row["proof_id"]),
            evidence_sha256=str(row["evidence_sha256"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        raise BenchEvalError(f"lock run reference is invalid: {e}") from e
    if row.get("evidence_path") != _PROOF_EVIDENCE_NAME:
        raise BenchEvalError(f"{ref.run_id}: the lock names an evidence path outside the proof")
    if ref.arm not in ARMS:
        raise BenchEvalError(f"{ref.run_id}: {ref.arm!r} is not an arm of this protocol")
    return ref


def _load_slot(
    proofs_dir: Path,
    row: object,
    block_ids: dict[str, tuple[str, ...]],
    *,
    study: ExposureStudyManifest,
) -> _VerifiedSlot:
    """Read one slot's proof and bind it to the arm it claims to be.

    A complete private proof establishes file integrity and consistency with its
    own run plan. It does **not** establish that the run is eligible for this
    study, so every rule the two-proof study path applies is applied here too:
    infrastructure rows veto the population, and the adapter, harness, benchmark
    version and verifier identity must be the declared ones.

    The arm is bound to the population its **own** retained block plan names, not
    to a cohort slice label: the 40 blocks are executed as ordinary ten-case
    slices, so their planner output legitimately carries a per-block slice id.
    """
    from bencheval.exposure_report import (
        assert_bound_population,
        bind_side_rows,
        load_proof_side,
        proof_variant,
    )

    ref = _slot_ref(row)
    declared_ids = block_ids.get(ref.block_id)
    if declared_ids is None:
        raise BenchEvalError(f"{ref.run_id}: block {ref.block_id} is not in the retained partition")

    # Each slot keeps its own proof object: a concatenated aggregate has no
    # inventory and is refused here by the unchanged production reader.
    proof = load_proof_side(Path(proofs_dir) / ref.run_id)
    carried = proof.records[0].run_id if proof.records else None
    if carried != ref.run_id:
        raise BenchEvalError(f"{ref.run_id}: the proof there carries run {carried!r}")
    if proof.proof_id != ref.proof_id:
        raise BenchEvalError(f"{ref.run_id}: proof id does not match the lock")
    if proof.evidence_sha256 != ref.evidence_sha256:
        raise BenchEvalError(f"{ref.run_id}: evidence digest does not match the lock")

    side = _ARM_SIDE[ref.arm]
    declared = study.candidate if side == "candidate" else study.canonical
    strata = tuple(sorted(study.population.canonical_counts))
    rows = bind_side_rows(
        side,  # type: ignore[arg-type]
        declared,
        strata,
        proof.records,
        derived_from=study.canonical.benchmark_id if side == "candidate" else None,
    )
    # planned = block = observed. ``assert_bound_population`` ties the retained
    # plan to the declared benchmark, to the slice the evidence actually ran and
    # to the eligible rows; the block check closes it onto frozen membership. A
    # smoke or foreign slice fails on its cases, which is what the arm is made of.
    assert_bound_population(rows, declared, proof.binding)
    frozen = frozenset(declared_ids)
    if proof.binding.instance_ids != frozen:
        missing = sorted(frozen - proof.binding.instance_ids)
        extra = sorted(proof.binding.instance_ids - frozen)
        raise BenchEvalError(
            f"{ref.run_id}: the retained plan ({proof.binding.source}) does not plan block "
            f"{ref.block_id}'s frozen membership: missing={missing} extra={extra}",
        )
    if tuple(sorted(rows.rows)) != tuple(sorted(declared_ids)):
        raise BenchEvalError(
            f"{ref.run_id}: the proof population is not block {ref.block_id}'s declared cases",
        )

    variant = proof_variant(proof)
    if ref.arm == "treatment" and variant is None:
        raise BenchEvalError(
            f"{ref.run_id}: a treatment slot must retain the variant manifest that measured "
            "its representation; without it the arm is unbound",
        )
    if ref.arm != "treatment" and variant is not None:
        raise BenchEvalError(
            f"{ref.run_id}: a canonical {ref.arm} slot must not carry a derived variant manifest",
        )
    return _VerifiedSlot(
        ref=ref,
        rows=rows,
        variant=variant,
        passes={i: r.primary_pass for i, r in rows.rows.items()},
    )


def _bind_slots_to_protocol(
    definition: ProtocolDefinition,
    study: ExposureStudyManifest,
    selection: ExposureSelection,
    slots: list[_VerifiedSlot],
) -> None:
    """Every arm must be the declared route, and every treatment the fixed bytes."""
    from bencheval.exposure_report import assert_constant_axes, assert_variant

    axes = assert_constant_axes(study, *[slot.rows for slot in slots])
    for axis, declared in definition.route_identity.items():
        if axes.get(axis) != declared:
            raise BenchEvalError(
                f"the population ran {axis} {axes.get(axis)!r}, not the protocol's declared "
                f"{declared!r}",
            )
    anchors = {slot.ref.block_id: slot for slot in slots if slot.ref.arm == "anchor"}
    variants: set[str] = set()
    for slot in slots:
        if slot.ref.arm != "treatment":
            continue
        anchor = anchors.get(slot.ref.block_id)
        if anchor is None:
            raise BenchEvalError(f"{slot.ref.run_id}: the block has no anchor slot to compare to")
        assert_variant(study, selection, slot.variant, anchor.rows, slot.rows)
        variants.add(slot.variant.sha256)  # type: ignore[union-attr]
    if len(variants) != 1:
        raise BenchEvalError(
            f"the treatment is fixed, but the population carries {len(variants)} distinct "
            "variant manifests",
        )


def verify_protocol_lock(
    *, lock_path: Path, proofs_dir: Path, output: Path | None = None
) -> dict[str, object]:
    """Reproduce the locked report from copied proof objects.

    Never concatenates per-run artifacts into a fabricated aggregate proof: each
    slot keeps its own ``private_proof_v1`` object, is read through the unchanged
    inventory-bound reader, and the report is **recomputed** from those verified
    evidence rows rather than copied out of the lock.
    """
    lock = _read_lock(lock_path)
    manifest = _manifest_from_payload(lock.get("manifest"))
    if lock.get("manifest_sha256") != manifest.sha256:
        raise BenchEvalError("lock manifest digest does not match the retained record")
    definition = protocol_definition(manifest.protocol_id)
    # The retained study and selection are checked against the installed catalog,
    # not taken on the lock's word, so portability never means self-assertion.
    study, selection = _retained_identity(lock, definition, source=str(lock_path))
    partition = _partition_from_payload(lock.get("partition"))
    schedule = _schedule_from_payload(lock.get("schedule"))
    runs = lock.get("runs")
    if not isinstance(runs, list) or not runs:
        raise BenchEvalError("lock carries no run references")

    block_ids = {block.block_id: block.instance_ids for block in partition}
    slots = [_load_slot(Path(proofs_dir), row, block_ids, study=study) for row in runs]
    refs = tuple(slot.ref for slot in slots)
    _verify_population(manifest, partition, schedule, refs, selection=selection)
    _bind_slots_to_protocol(definition, study, selection, slots)

    report = _recompute_report(manifest, partition, schedule, slots)
    if lock.get("report_sha256") != report.sha256:
        raise BenchEvalError("the copied proofs do not reproduce the locked report")
    expected = _lock_payload(
        manifest, partition, schedule, refs, report=report, study=study, selection=selection
    )
    if lock != expected:
        raise BenchEvalError(f"lock contains fields outside the {PROTOCOL_LOCK_SCHEMA} contract")
    if output is not None:
        _write_exclusive(Path(output), report.to_json())
    return {
        "ok": True,
        "protocol_id": manifest.protocol_id,
        "study_id": manifest.study_id,
        "manifest_sha256": manifest.sha256,
        "selection_sha256": manifest.selection_sha256,
        "source_population_sha256": manifest.source_population_sha256,
        "runs": len(refs),
        "proof_ids": sorted({ref.proof_id for ref in refs}),
        "report_sha256": report.sha256,
        "lock_sha256": _sha256_text(lock_text(expected)),
    }


def _recompute_report(
    manifest: ProtocolManifest,
    partition: tuple[BlockPartition, ...],
    schedule: ProtocolSchedule,
    slots: list[_VerifiedSlot],
) -> ProtocolReport:
    """Rebuild the report from the verified evidence rows, not from the lock."""
    observed = {(slot.ref.block_id, slot.ref.arm): slot.passes for slot in slots}
    outcomes = tuple(
        CaseOutcome(
            instance_id,
            block.block_id,
            anchor_pass=observed[(block.block_id, "anchor")][instance_id],
            treatment_pass=observed[(block.block_id, "treatment")][instance_id],
            repeat_pass=observed[(block.block_id, "repeat")][instance_id],
        )
        for block in partition
        for instance_id in block.instance_ids
    )
    arms = {assignment.block_id: assignment.slots for assignment in schedule.assignments}
    diffs = slot_differences(outcomes, arms)
    z = tuple(assignment.z for assignment in schedule.assignments)
    return build_protocol_report(
        build_estimand(outcomes),
        randomization_p_value(diffs, z),
        observable_block_interval(diffs, z, per_block=manifest.per_block, rounds=manifest.rounds),
        population_valid=True,
    )


def _write_exclusive(path: Path, text: str) -> None:
    """Write ``text`` to a new file the caller owns; never clobber an existing one."""
    from bencheval.run_isolation import open_owned_dir_fd, write_text_at_exclusive

    if path.exists() or path.is_symlink():
        raise BenchEvalError(f"output already exists: {path}")
    dir_fd = open_owned_dir_fd(path.parent, role="protocol output directory")
    try:
        write_text_at_exclusive(dir_fd, path.name, text)
    except OSError as e:
        raise BenchEvalError(f"cannot write {path}: {e}") from e
    finally:
        os.close(dir_fd)


# --- the protocol record a run is planned from -------------------------------------


def build_protocol_record(protocol_id: str, *, blocking_seed: str) -> dict[str, object]:
    """Partition, schedule and freeze one protocol; identity only, no outcome."""
    definition = protocol_definition(protocol_id)
    cohort, _, _ = protocol_cohort(definition)
    partition = partition_cohort(cohort, blocks=definition.blocks, blocking_seed=blocking_seed)
    schedule = draw_schedule(partition, rounds=definition.rounds, draw_seed=definition.draw_seed)
    manifest = build_protocol_manifest(
        protocol_id=definition.protocol_id,
        study_id=definition.study_id,
        blocking_seed=blocking_seed,
        partition_sha256=partition_sha256(partition),
        schedule_sha256=schedule_sha256(schedule),
    )
    return {
        "protocol_contract_version": PROTOCOL_CONTRACT_VERSION,
        "protocol_id": manifest.protocol_id,
        "manifest": manifest.payload,
        "manifest_sha256": manifest.sha256,
        "partition": [list(block.instance_ids) for block in partition],
        "schedule": [list(assignment.slots) for assignment in schedule.assignments],
        "blocks": [
            {
                "block_id": assignment.block_id,
                "round_index": assignment.round_index,
                "slots": list(assignment.slots),
                "z": assignment.z,
                "instance_ids": list(block.instance_ids),
            }
            for block, assignment in zip(partition, schedule.assignments, strict=True)
        ],
    }


def write_protocol_record(
    protocol_id: str, *, blocking_seed: str, output: Path
) -> dict[str, object]:
    """Build the protocol record and write it exclusively."""
    record = build_protocol_record(protocol_id, blocking_seed=blocking_seed)
    _write_exclusive(Path(output), json.dumps(record, sort_keys=True, indent=2) + "\n")
    return record


__all__ = [
    "ARMS",
    "PROTOCOL_CONTRACT_VERSION",
    "PROTOCOL_LOCK_SCHEMA",
    "Arm",
    "ArmRunRef",
    "BlockPartition",
    "ProtocolDefinition",
    "ProtocolManifest",
    "ProtocolSchedule",
    "SlotAssignment",
    "build_protocol_lock",
    "build_protocol_manifest",
    "build_protocol_record",
    "draw_schedule",
    "lock_text",
    "partition_cohort",
    "partition_sha256",
    "protocol_cohort",
    "protocol_definition",
    "schedule_sha256",
    "verify_protocol_lock",
    "verify_protocol_population",
    "write_protocol_record",
]
