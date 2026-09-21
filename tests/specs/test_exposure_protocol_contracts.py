"""X6.2 RED contracts: protocol identity, schedule, population, and the multi-proof lock.

SUBSTITUTE_JUSTIFICATION
- substitute: synthetic three-arm BFCL outcome content (``_arm_pass`` and the
  evidence rows it drives), exported through the production private-proof path
- replaces: the observed outcomes of 120 charged anchor/treatment/repeat runs
- necessity: missing, duplicated, tampered and infrastructure-failed slots must
  be forced deterministically, one mutation at a time, without paying a provider
- real-option: none until X6.3 exists; the real path is X6.4's authorized run.
  The proof format and its reader are **not** substituted: every object below is
  a real ``private_proof_v1`` built by ``export_private_proof`` and accepted by
  the unchanged ``load_verified_proof_inputs`` before the protocol API sees it,
  and every proof id and evidence digest is read back off those objects
- proof-limit: proves identity, refusal and round-trip binding only; the outcome
  content is contract data and is never research evidence
- real-proof: none yet -- this is a RED packet, and every protocol contract
  below fails until X6.3 implements ``bencheval.exposure_protocol``
- covered tests: every test in this module except the two retained-lock guards,
  which read the real CF1.3 proof bytes

Each contract starts from one VALID baseline -- 40 blocks, 120 distinct verified
proof objects, one accepted population -- and mutates exactly one condition, so a
validator that rejects everything, or one that only notices an empty reference
list, cannot pass. Refusal tests mutate a copy; the verified population is never
edited in place.

Specification: ``docs/context/bfcl-repeat-spec.md``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path
from typing import NamedTuple

import pytest
import yaml

from bencheval.benchmark_plan import plan_control_plane
from bencheval.cli import main
from bencheval.domain import RunPlan
from bencheval.evidence import EvidenceRecord
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_protocol import (
    ARMS,
    PROTOCOL_LOCK_SCHEMA,
    Arm,
    ArmRunRef,
    BlockPartition,
    ProtocolDefinition,
    ProtocolManifest,
    ProtocolSchedule,
    _schedule_from_payload,
    build_protocol_lock,
    build_protocol_manifest,
    draw_schedule,
    partition_cohort,
    partition_sha256,
    protocol_cohort,
    protocol_definition,
    protocol_identity,
    schedule_sha256,
    verify_protocol_lock,
    verify_protocol_population,
)
from bencheval.exposure_repeat import (
    CaseOutcome,
    ProtocolReport,
    build_estimand,
    build_protocol_report,
    observable_block_interval,
    randomization_p_value,
    slot_differences,
)
from bencheval.exposure_report import EXPOSURE_LOCK_SCHEMA, verify_exposure_study_lock
from bencheval.exposure_study import StudySide
from bencheval.paths import repo_root
from bencheval.proof_bundle import load_verified_proof_inputs
from tests.factories import export_exposure_proof, make_exposure_evidence_row
from tests.specs.test_exposure_pair_contracts import _variant

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "exposure" / "cf13"
_PROTOCOL = "bfcl-tool-order-repeat-400-v1"
_BLOCKING_SEED = "bencheval-bfcl-repeat-blocking-v1"
_BLOCKS = 40
_PER_BLOCK = 10
_SLOTS = _BLOCKS * len(ARMS)
_VARIANT_REL = "study/variant-manifest.json"
_DERIVED_DIR = "overlay/pkg/bfcl_eval"
_DERIVED_RELS = ("data/BFCL_v4_multiple.json", "data/BFCL_v4_parallel_multiple.json")
_DERIVED_PATHS = tuple(f"{_DERIVED_DIR}/{rel}" for rel in _DERIVED_RELS)


def _definition() -> ProtocolDefinition:
    return protocol_definition(_PROTOCOL)


def _cohort() -> tuple[str, ...]:
    """The protocol's declared 400 cases, read from its retained selection."""
    return protocol_cohort(_definition())[0]


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _arm_pass(block_index: int, case_index: int, arm: Arm) -> bool:
    """A deterministic three-arm pattern carrying a real, non-degenerate effect.

    One anchor failure per block, two to four treatment failures, one or two
    repeat failures, so the per-block difference varies across blocks and the
    interval is not silently degenerate.
    """
    if arm == "anchor":
        return case_index != 9
    if arm == "treatment":
        return case_index >= 2 + block_index % 3
    return case_index >= 1 + block_index % 2


def _arm_side(arm: Arm) -> StudySide:
    study, _ = protocol_identity(_definition())
    return study.candidate if arm == "treatment" else study.canonical


def _rows(
    block: BlockPartition,
    block_index: int,
    arm: Arm,
    run_id: str,
    *,
    derived_version: str,
    overrides: dict[str, object] | None = None,
    case_overrides: dict[int, dict[str, object]] | None = None,
) -> list[EvidenceRecord]:
    """One arm's ten rows, carrying the identities the protocol declares.

    The treatment rows reference the retained variant manifest and both derived
    data files, exactly as a real derived run does, so private proof retains the
    bytes that measured the representation.
    """
    side = _arm_side(arm)
    route = _definition().route_identity
    fields: dict[str, object] = {
        "model_id": route["model_id"],
        "provider_id": route["provider_id"],
    }
    if arm == "treatment":
        fields["benchmark_version"] = derived_version
        fields["artifact_paths"] = ["raw/score.json", _VARIANT_REL, *_DERIVED_PATHS]
    fields.update(overrides or {})
    rows = []
    for case_index, instance_id in enumerate(block.instance_ids):
        row = dict(fields)
        # A per-case override models one bad row among nine ordinary ones.
        row.update(case_overrides.get(case_index, {}) if case_overrides else {})
        row.setdefault("primary_pass", _arm_pass(block_index, case_index, arm))
        row.setdefault("slice_id", side.slice_id)
        rows.append(
            make_exposure_evidence_row(
                benchmark_id=side.benchmark_id,
                instance_id=instance_id,
                run_id=run_id,
                **row,
            )
        )
    return rows


class _Baseline(NamedTuple):
    """One accepted protocol and the verified proof population standing behind it."""

    blocks: tuple[BlockPartition, ...]
    schedule: ProtocolSchedule
    manifest: ProtocolManifest
    refs: tuple[ArmRunRef, ...]
    proofs: Path
    outcomes: tuple[CaseOutcome, ...]


#: 120 real exports cost seconds, and every contract starts from the same accepted
#: population, so it is built once per session and never mutated in place.
_POPULATIONS: dict[str, tuple[Path, tuple[ArmRunRef, ...], tuple[CaseOutcome, ...]]] = {}
#: The measured treatment representation, materialized once for the same reason.
_TREATMENT: dict[str, object] = {}


@pytest.fixture(scope="session")
def proof_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Session-scoped home for the exported proof population."""
    return tmp_path_factory.mktemp("x62-protocol-proofs")


def _treatment_files(root: Path) -> dict[str, str]:
    """The retained variant manifest and derived data, materialized once per session.

    Built through the production overlay materializer over a substitute package,
    and bound to the real catalog source pins, so the mapping covers all 400
    declared cases and the identity names this protocol's study.
    """
    cached = _TREATMENT.get("files")
    if cached is None:
        study, selection = protocol_identity(_definition())
        cached = _variant(root / "variant", study, selection)
        _TREATMENT["files"] = cached
        _TREATMENT["version"] = json.loads(cached[_VARIANT_REL])["benchmark_version"]
    return cached  # type: ignore[return-value]


def _treatment_version(root: Path) -> str:
    _treatment_files(root)
    return str(_TREATMENT["version"])


def _export_slot(
    build: Path,
    proofs: Path,
    block: BlockPartition,
    block_index: int,
    arm: Arm,
    *,
    root: Path,
    run_id: str | None = None,
    overrides: dict[str, object] | None = None,
    case_overrides: dict[int, dict[str, object]] | None = None,
    treatment_files: dict[str, str] | None = None,
    run_plan: RunPlan | None = None,
) -> tuple[ArmRunRef, dict[str, bool]]:
    """Export one slot's real proof and read its identity back off the object.

    ``run_plan`` retains an unmodified ``plan_control_plane`` result, so a slot
    can be built the way the execution design actually plans a block.
    """
    run_id = run_id or f"run-{block.block_id}-{arm}"
    rows = _rows(
        block,
        block_index,
        arm,
        run_id,
        derived_version=_treatment_version(root),
        overrides=overrides,
        case_overrides=case_overrides,
    )
    exported = export_exposure_proof(
        build / run_id,
        rows,
        extra_raw=(treatment_files or _treatment_files(root)) if arm == "treatment" else None,
        run_plan=run_plan,
    )
    shutil.move(str(exported), proofs / run_id)
    loaded = load_verified_proof_inputs(proofs / run_id, require_complete=True)
    assert loaded.run_id == run_id
    assert loaded.classification == "complete"
    assert len(loaded.records) == _PER_BLOCK
    ref = ArmRunRef(
        block_id=block.block_id,
        round_index=0,
        arm=arm,
        run_id=run_id,
        proof_id=loaded.proof_id,
        evidence_sha256=loaded.evidence_sha256,
    )
    return ref, {r.instance_id: r.primary_pass for r in loaded.records if r.instance_id}


def _verified_population(
    root: Path, blocks: tuple[BlockPartition, ...]
) -> tuple[Path, tuple[ArmRunRef, ...], tuple[CaseOutcome, ...]]:
    """Export one real ``private_proof_v1`` per slot and verify it before using it.

    Every object is read back through the unchanged production reader with
    ``require_complete=True``; the reference's proof id and evidence digest are
    the ones that reader returns, not invented labels. The three-arm outcomes are
    read off the verified evidence rows, so the report below describes exactly
    the bytes the lock binds.
    """
    key = hashlib.sha256(
        json.dumps([[b.block_id, list(b.instance_ids)] for b in blocks]).encode("utf-8")
    ).hexdigest()[:16]
    cached = _POPULATIONS.get(key)
    if cached is not None:
        return cached

    build = root / f"build-{key}"
    proofs = root / f"proofs-{key}"
    proofs.mkdir(parents=True)
    refs: list[ArmRunRef] = []
    outcomes: list[CaseOutcome] = []
    for block_index, block in enumerate(blocks):
        observed: dict[Arm, dict[str, bool]] = {}
        for arm in ARMS:
            ref, passes = _export_slot(build, proofs, block, block_index, arm, root=root)
            refs.append(ref)
            observed[arm] = passes
        outcomes.extend(
            CaseOutcome(
                instance_id,
                block.block_id,
                anchor_pass=observed["anchor"][instance_id],
                treatment_pass=observed["treatment"][instance_id],
                repeat_pass=observed["repeat"][instance_id],
            )
            for instance_id in block.instance_ids
        )
    shutil.rmtree(build)
    _POPULATIONS[key] = (proofs, tuple(refs), tuple(outcomes))
    return _POPULATIONS[key]


def _baseline(root: Path) -> _Baseline:
    """A wholly valid protocol: 40 blocks, one round, 120 verified proof objects."""
    definition = _definition()
    blocks = partition_cohort(_cohort(), blocks=_BLOCKS, blocking_seed=_BLOCKING_SEED)
    schedule = draw_schedule(blocks, rounds=1, draw_seed=definition.draw_seed)
    manifest = build_protocol_manifest(
        protocol_id=_PROTOCOL,
        study_id="bfcl-v4-tool-order-v1",
        blocks=_BLOCKS,
        per_block=_PER_BLOCK,
        rounds=1,
        blocking_seed=_BLOCKING_SEED,
        planning_effect_points=8,
        unmet_effect_points=5,
        partition_sha256=partition_sha256(blocks),
        schedule_sha256=schedule_sha256(schedule),
    )
    proofs, refs, outcomes = _verified_population(root, blocks)
    return _Baseline(blocks, schedule, manifest, refs, proofs, outcomes)


def _report(base: _Baseline) -> ProtocolReport:
    """The report for exactly the evidence rows the 120 verified proofs carry."""
    slots = {a.block_id: a.slots for a in base.schedule.assignments}
    diffs = slot_differences(base.outcomes, slots)
    z = tuple(a.z for a in base.schedule.assignments)
    return build_protocol_report(
        build_estimand(base.outcomes),
        randomization_p_value(diffs, z),
        observable_block_interval(diffs, z, per_block=_PER_BLOCK),
        population_valid=True,
    )


def _locked(base: _Baseline, tmp_path: Path) -> tuple[Path, ProtocolReport]:
    """Build the report, lock it, and write the lock where a verifier can read it."""
    report = _report(base)
    lock = build_protocol_lock(base.manifest, base.blocks, base.schedule, base.refs, report=report)
    lock_path = tmp_path / "protocol-lock.json"
    lock_path.write_text(json.dumps(lock, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return lock_path, report


def _replaced_slot(
    base: _Baseline,
    tmp_path: Path,
    *,
    block_index: int,
    arm: Arm,
    root: Path,
    as_arm: Arm | None = None,
    overrides: dict[str, object] | None = None,
    case_overrides: dict[int, dict[str, object]] | None = None,
    treatment_files: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    """Swap exactly one slot's proof for a differently-built one, and relock.

    Returns the forged lock and the proofs directory it names. Everything else --
    the other 119 proofs, the partition, the schedule, the seeds -- is the
    accepted baseline, so whatever the verifier refuses, it refuses because of
    this one slot.
    """
    proofs = tmp_path / "proofs"
    shutil.copytree(base.proofs, proofs)
    block = base.blocks[block_index]
    victim = next(r for r in base.refs if r.block_id == block.block_id and r.arm == arm)
    shutil.rmtree(proofs / victim.run_id)
    ref, _ = _export_slot(
        tmp_path / "build",
        proofs,
        block,
        block_index,
        as_arm or arm,
        root=root,
        run_id=victim.run_id,
        overrides=overrides,
        case_overrides=case_overrides,
        treatment_files=treatment_files,
    )
    # The slot keeps its scheduled identity; only the proof behind it changed.
    ref = dataclasses.replace(ref, arm=arm)
    refs = tuple(ref if r.run_id == victim.run_id else r for r in base.refs)
    lock = build_protocol_lock(
        base.manifest, base.blocks, base.schedule, refs, report=_report(base)
    )
    lock_path = tmp_path / "forged-lock.json"
    lock_path.write_text(json.dumps(lock, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return lock_path, proofs


def _forged_lock(base: _Baseline, tmp_path: Path, mutate) -> Path:
    """An honest lock, edited, then re-digested so only a replay check can catch it."""
    lock_path, _ = _locked(base, tmp_path)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    mutate(lock)
    lock["manifest_sha256"] = ProtocolManifest(**lock["manifest"]).sha256
    forged = tmp_path / "re-digested-lock.json"
    forged.write_text(json.dumps(lock, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return forged


# --- fixture control: the inputs are real proofs (expected GREEN) ------------------


def test_slot_proof_fixtures_are_real_private_proof_objects(tmp_path: Path) -> None:
    """The contract inputs are produced by the production exporter and read by the
    production reader, and the digests the references carry are the object's own.

    This guard does not touch the protocol API, so it keeps holding the inputs to
    the real proof boundary independently of the rest of this module.
    """
    ids = tuple(f"multiple_{i}" for i in range(5)) + tuple(
        f"parallel_multiple_{i}" for i in range(5)
    )
    block = BlockPartition("block-01", ids, {"multiple": 5, "parallel_multiple": 5})
    run_id = "run-block-01-anchor"
    exported = export_exposure_proof(
        tmp_path / run_id, _rows(block, 0, "anchor", run_id, derived_version="unused")
    )

    loaded = load_verified_proof_inputs(exported, require_complete=True)
    assert loaded.classification == "complete"
    assert loaded.run_id == run_id
    assert tuple(r.instance_id for r in loaded.records) == ids
    assert loaded.proof_id == _digest((exported / "inventory.json").read_bytes())
    assert loaded.evidence_sha256 == _digest((exported / "evidence.jsonl").read_bytes())


# --- P-01, P-02: the partition -----------------------------------------------------


def test_partition_is_an_exact_stratum_balanced_disjoint_cover() -> None:
    """P-01. 400 ids become 40 blocks of 10, five per stratum, losing nothing."""
    cohort = _cohort()
    blocks = partition_cohort(cohort, blocks=_BLOCKS, blocking_seed=_BLOCKING_SEED)
    assert len(blocks) == _BLOCKS
    flat = [i for block in blocks for i in block.instance_ids]
    assert sorted(flat) == sorted(cohort)
    assert len(set(flat)) == len(flat)
    for block in blocks:
        assert len(block.instance_ids) == _PER_BLOCK
        assert block.stratum_counts == {"multiple": 5, "parallel_multiple": 5}


def test_partition_is_reproducible_from_the_seed_alone() -> None:
    """P-01. Same cohort and seed, same blocks, same order, same digest."""
    cohort = _cohort()
    first = partition_cohort(cohort, blocks=_BLOCKS, blocking_seed=_BLOCKING_SEED)
    second = partition_cohort(cohort, blocks=_BLOCKS, blocking_seed=_BLOCKING_SEED)
    assert partition_sha256(first) == partition_sha256(second)
    assert [b.instance_ids for b in first] == [b.instance_ids for b in second]


def test_a_different_blocking_seed_regroups_without_changing_the_cohort() -> None:
    """P-02. Blocking only groups selected ids; it never selects or transforms."""
    cohort = _cohort()
    default = partition_cohort(cohort, blocks=_BLOCKS, blocking_seed=_BLOCKING_SEED)
    other = partition_cohort(cohort, blocks=_BLOCKS, blocking_seed="some-other-seed-v1")
    assert partition_sha256(default) != partition_sha256(other)
    assert sorted(i for b in default for i in b.instance_ids) == sorted(
        i for b in other for i in b.instance_ids
    )


def test_partition_refuses_a_cohort_that_does_not_divide() -> None:
    """P-01. 399 ids into 40 blocks is a refusal, not a short block."""
    with pytest.raises(BenchEvalError):
        partition_cohort(_cohort()[:-1], blocks=_BLOCKS, blocking_seed=_BLOCKING_SEED)


# --- P-03, P-04: the schedule ------------------------------------------------------


def test_schedule_is_balanced_anchor_first_and_recorded_with_its_space(proof_root: Path) -> None:
    """P-03. Slot 1 is always the anchor; treatment and repeat split 20/20."""
    base = _baseline(proof_root)
    assert len(base.schedule.assignments) == _BLOCKS
    assert base.schedule.allocation_space_size == 137_846_528_820
    assert all(a.slots[0] == "anchor" for a in base.schedule.assignments)
    assert sum(a.z for a in base.schedule.assignments) == 0
    assert {a.block_id for a in base.schedule.assignments} == {b.block_id for b in base.blocks}


def test_schedule_draw_is_reproducible_and_its_digest_binds_slot_order(proof_root: Path) -> None:
    """P-04. Reordering a slot changes the digest; it is not silently accepted."""
    base = _baseline(proof_root)
    assert schedule_sha256(base.schedule) == schedule_sha256(
        draw_schedule(base.blocks, rounds=1, draw_seed=_definition().draw_seed)
    )
    first = base.schedule.assignments[0]
    swapped = dataclasses.replace(first, slots=(first.slots[0], first.slots[2], first.slots[1]))
    edited = dataclasses.replace(
        base.schedule, assignments=(swapped, *base.schedule.assignments[1:])
    )
    assert schedule_sha256(edited) != schedule_sha256(base.schedule)


def test_valid_protocol_population_is_accepted(proof_root: Path) -> None:
    """Positive control. The baseline must pass, or every refusal below is vacuous."""
    base = _baseline(proof_root)
    assert len(base.refs) == _SLOTS == 120
    assert len({r.proof_id for r in base.refs}) == _SLOTS
    assert len({r.evidence_sha256 for r in base.refs}) == _SLOTS
    verify_protocol_population(base.manifest, base.blocks, base.schedule, base.refs)


def test_post_hoc_schedule_edit_is_refused_against_the_retained_digest(proof_root: Path) -> None:
    """P-04. Only the schedule changes; the 120 references stay valid and complete."""
    base = _baseline(proof_root)
    reversed_schedule = dataclasses.replace(
        base.schedule, assignments=tuple(reversed(base.schedule.assignments))
    )
    with pytest.raises(BenchEvalError):
        verify_protocol_population(base.manifest, base.blocks, reversed_schedule, base.refs)


# --- P-05, P-06, P-07, E-01, E-02: identity and population -------------------------


def test_two_slots_sharing_a_proof_is_refused(proof_root: Path) -> None:
    """P-05. A and C may not be two names for one proof; one mutation only."""
    base = _baseline(proof_root)
    shared = list(base.refs)
    shared[2] = dataclasses.replace(shared[2], proof_id=shared[1].proof_id)
    with pytest.raises(BenchEvalError):
        verify_protocol_population(base.manifest, base.blocks, base.schedule, tuple(shared))


def test_two_slots_sharing_a_run_id_is_refused(proof_root: Path) -> None:
    """P-05. Distinct runs, not one run reported twice."""
    base = _baseline(proof_root)
    shared = list(base.refs)
    shared[5] = dataclasses.replace(shared[5], run_id=shared[4].run_id)
    with pytest.raises(BenchEvalError):
        verify_protocol_population(base.manifest, base.blocks, base.schedule, tuple(shared))


def test_a_slot_without_a_run_is_refused(proof_root: Path) -> None:
    """E-01. 119 of 120 is an invalid population, not a smaller study."""
    base = _baseline(proof_root)
    with pytest.raises(BenchEvalError):
        verify_protocol_population(base.manifest, base.blocks, base.schedule, base.refs[:-1])


@pytest.mark.parametrize("damage", ["foreign", "missing", "duplicate"])
def test_foreign_missing_and_duplicate_ids_invalidate_the_population(
    proof_root: Path, damage: str
) -> None:
    """E-01. The population is exact; the schedule and references stay valid."""
    base = _baseline(proof_root)
    original = base.blocks[0]
    kept = original.instance_ids[:-1]
    broken = {
        "foreign": (*kept, "live_irrelevance_1"),
        "missing": kept,
        "duplicate": (*kept, kept[0]),
    }[damage]
    damaged = (
        dataclasses.replace(original, instance_ids=broken),
        *base.blocks[1:],
    )
    with pytest.raises(BenchEvalError):
        verify_protocol_population(base.manifest, damaged, base.schedule, base.refs)


def test_any_infrastructure_failure_invalidates_the_whole_population(proof_root: Path) -> None:
    """E-02. One timed-out slot invalidates 120 runs; it is never scored or dropped.

    The accepted baseline already carries scored model failures, so this is the
    infrastructure/model distinction rather than "any failure label refuses".
    """
    base = _baseline(proof_root)
    verify_protocol_population(base.manifest, base.blocks, base.schedule, base.refs)
    assert sum(not o.treatment_pass for o in base.outcomes) > 0
    assert sum(not o.anchor_pass for o in base.outcomes) == _BLOCKS

    failed = list(base.refs)
    failed[77] = dataclasses.replace(failed[77], failure_label="runtime_output_unparseable")
    with pytest.raises(BenchEvalError):
        verify_protocol_population(base.manifest, base.blocks, base.schedule, tuple(failed))


def test_manifest_records_the_effect_targets_as_declared_not_derived(proof_root: Path) -> None:
    """P-07. Eight points planned, five points recorded unmet; neither from data."""
    base = _baseline(proof_root)
    assert base.manifest.planning_effect_points == 8
    assert base.manifest.unmet_effect_points == 5
    assert base.manifest.alpha == pytest.approx(0.05)


def test_stale_selection_identity_is_refused_before_planning() -> None:
    """P-06. A manifest naming a drifted selection does not reach a run."""
    blocks = partition_cohort(_cohort(), blocks=_BLOCKS, blocking_seed=_BLOCKING_SEED)
    schedule = draw_schedule(blocks, rounds=1, draw_seed=_definition().draw_seed)
    with pytest.raises(BenchEvalError):
        build_protocol_manifest(
            protocol_id="bfcl-tool-order-repeat-400-v1",
            study_id="bfcl-v4-tool-order-v1",
            blocks=_BLOCKS,
            per_block=_PER_BLOCK,
            rounds=1,
            selection_sha256="sha256:" + "0" * 64,
            partition_sha256=partition_sha256(blocks),
            schedule_sha256=schedule_sha256(schedule),
        )


# --- E-03, E-04, E-05: the multi-proof lock ----------------------------------------


def test_protocol_lock_binds_every_one_of_the_distinct_slots(proof_root: Path) -> None:
    """E-03. 120 references, 120 distinct proof ids, all carried by the lock."""
    base = _baseline(proof_root)
    lock = build_protocol_lock(
        base.manifest, base.blocks, base.schedule, base.refs, report=_report(base)
    )
    assert lock["schema_version"] == PROTOCOL_LOCK_SCHEMA
    assert len(lock["runs"]) == _SLOTS
    assert {r["proof_id"] for r in lock["runs"]} == {r.proof_id for r in base.refs}


def test_protocol_lock_refuses_to_build_from_an_incomplete_population(proof_root: Path) -> None:
    """E-03. One mutation from the accepted baseline: a single missing slot."""
    base = _baseline(proof_root)
    with pytest.raises(BenchEvalError):
        build_protocol_lock(
            base.manifest, base.blocks, base.schedule, base.refs[:-1], report=_report(base)
        )


def test_protocol_lock_round_trips_the_exact_report_bytes(proof_root: Path, tmp_path: Path) -> None:
    """E-04. Build, lock, verify: the written bytes carry the locked digest.

    This is the anti-cheat contract for the verifier. A verifier that returns
    ``{"ok": True}`` without writing anything fails on the output assertions, and
    one that writes a different report fails on the digest.
    """
    base = _baseline(proof_root)
    lock_path, report = _locked(base, tmp_path)

    output = tmp_path / "reproduced.json"
    verified = verify_protocol_lock(lock_path=lock_path, proofs_dir=base.proofs, output=output)
    assert verified["ok"] is True
    assert output.is_file(), "verification must write the reproduced report"
    assert _digest(output.read_bytes()) == report.sha256
    assert verified["report_sha256"] == report.sha256


@pytest.mark.parametrize("target", ["evidence.jsonl", "run-plan.json", "proof.json"])
def test_tampered_proof_bytes_break_the_reproduction(
    proof_root: Path, tmp_path: Path, target: str
) -> None:
    """E-04, E-05. One byte changed in one of 120 proofs is a refusal.

    Both the evidence and the rest of the object are covered. A verifier that
    only re-hashes the evidence file the lock names misses the other two, which
    is why each slot must be read through the production inventory-bound reader
    rather than through a private format. The tamper is applied to a copy: the
    verified population is never edited.
    """
    base = _baseline(proof_root)
    lock_path, _ = _locked(base, tmp_path)
    proofs = tmp_path / "proofs"
    shutil.copytree(base.proofs, proofs)
    victim = proofs / base.refs[13].run_id / target
    victim.write_bytes(victim.read_bytes() + b"tampered\n")

    with pytest.raises(BenchEvalError):
        verify_protocol_lock(lock_path=lock_path, proofs_dir=proofs, output=tmp_path / "out.json")


def test_aggregated_fake_run_proof_is_refused(proof_root: Path, tmp_path: Path) -> None:
    """E-05. One concatenated directory standing in for 120 proofs is not a proof."""
    base = _baseline(proof_root)
    lock_path, _ = _locked(base, tmp_path)

    aggregate = tmp_path / "aggregate"
    aggregate.mkdir()
    (aggregate / "evidence.jsonl").write_bytes(
        b"".join((base.proofs / r.run_id / "evidence.jsonl").read_bytes() for r in base.refs)
    )
    with pytest.raises(BenchEvalError):
        verify_protocol_lock(lock_path=lock_path, proofs_dir=aggregate, output=tmp_path / "o.json")


# --- P-05: a block is planned as an ordinary ten-case slice ------------------------


def _block_slice_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    arm: Arm,
    block: BlockPartition,
    slice_id: str,
) -> RunPlan:
    """Plan one block the way the execution design does: a real, distinctly named
    ten-case slice in a supported config bundle, through the unmodified planner.

    Nothing about the returned plan is edited afterwards -- no ``model_copy`` of
    its slice or instances -- so a slot built from it is exactly what a normal
    ``bencheval run`` of that block would retain.
    """
    root = repo_root()
    side = _arm_side(arm)
    bundle = tmp_path / f"bundle-{slice_id}"
    shutil.copytree(root / "config", bundle / "config")
    slices = bundle / "config" / "slices"
    source = next(
        path
        for path in sorted(slices.glob("*.yaml"))
        if (raw := yaml.safe_load(path.read_text(encoding="utf-8")))["slice"]["id"] == side.slice_id
        and raw["slice"]["benchmark_id"] == side.benchmark_id
    )
    declared = yaml.safe_load(source.read_text(encoding="utf-8"))
    declared["slice"]["id"] = slice_id
    declared["slice"]["instances"] = list(block.instance_ids)
    (slices / f"{slice_id}.yaml").write_text(yaml.safe_dump(declared), encoding="utf-8")

    monkeypatch.setenv("BENCHEVAL_HOME", str(bundle))
    try:
        return plan_control_plane(
            benchmark_id=side.benchmark_id,
            slice_id=slice_id,
            runtime_id=None,
            model_id=str(_definition().route_identity["model_id"]),
            diagnostic=side.benchmark_id != "bfcl-v4",
        )
    finally:
        monkeypatch.delenv("BENCHEVAL_HOME")


@pytest.mark.parametrize("arm", ["anchor", "treatment"])
def test_a_real_ten_case_block_plan_carries_its_arm(
    proof_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arm: Arm
) -> None:
    """P-05. The protocol consumes 40 ten-case block runs, not one cohort run.

    The slot below is an unmodified planner result over a real block slice whose
    name is its own. The arm is bound by the population its plan names, so the
    verifier must accept it and reproduce the same report bytes.
    """
    base = _baseline(proof_root)
    block = base.blocks[0]
    slice_id = f"bfcl-repeat-block-01-{arm}"
    plan = _block_slice_plan(tmp_path, monkeypatch, arm=arm, block=block, slice_id=slice_id)
    assert plan.slice_id == slice_id
    assert plan.slice_id != _arm_side(arm).slice_id
    assert tuple(i.instance_id for i in plan.instances) == block.instance_ids

    proofs = tmp_path / "proofs"
    shutil.copytree(base.proofs, proofs)
    victim = next(r for r in base.refs if r.block_id == block.block_id and r.arm == arm)
    shutil.rmtree(proofs / victim.run_id)
    ref, _ = _export_slot(
        tmp_path / "build",
        proofs,
        block,
        0,
        arm,
        root=proof_root,
        run_id=victim.run_id,
        overrides={"slice_id": slice_id},
        run_plan=plan,
    )
    assert ref.proof_id != victim.proof_id
    refs = tuple(ref if r.run_id == victim.run_id else r for r in base.refs)
    lock = build_protocol_lock(
        base.manifest, base.blocks, base.schedule, refs, report=_report(base)
    )
    lock_path = tmp_path / "block-slice-lock.json"
    lock_path.write_text(json.dumps(lock, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    output = tmp_path / "reproduced.json"
    result = verify_protocol_lock(lock_path=lock_path, proofs_dir=proofs, output=output)
    assert result["report_sha256"] == _report(base).sha256
    assert output.read_bytes() == _report(base).to_json().encode("utf-8")


def test_a_real_block_plan_for_other_cases_cannot_fill_a_slot(
    proof_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-05. Accepting the block's own slice name is not accepting any slice.

    This slot is an equally real planner result over an equally real block slice
    -- of the *wrong* block. Its plan and its evidence agree with each other, so
    only the frozen partition membership can refuse it.
    """
    base = _baseline(proof_root)
    victim_block, other = base.blocks[0], base.blocks[1]
    slice_id = "bfcl-repeat-block-02-anchor"
    plan = _block_slice_plan(tmp_path, monkeypatch, arm="anchor", block=other, slice_id=slice_id)

    proofs = tmp_path / "proofs"
    shutil.copytree(base.proofs, proofs)
    victim = next(r for r in base.refs if r.block_id == victim_block.block_id and r.arm == "anchor")
    shutil.rmtree(proofs / victim.run_id)
    ref, _ = _export_slot(
        tmp_path / "build",
        proofs,
        other,
        1,
        "anchor",
        root=proof_root,
        run_id=victim.run_id,
        overrides={"slice_id": slice_id},
        run_plan=plan,
    )
    ref = dataclasses.replace(ref, block_id=victim_block.block_id)
    refs = tuple(ref if r.run_id == victim.run_id else r for r in base.refs)
    lock = build_protocol_lock(
        base.manifest, base.blocks, base.schedule, refs, report=_report(base)
    )
    lock_path = tmp_path / "wrong-block-lock.json"
    lock_path.write_text(json.dumps(lock, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(BenchEvalError, match="frozen membership"):
        verify_protocol_lock(lock_path=lock_path, proofs_dir=proofs, output=tmp_path / "o.json")


# --- E-02, P-06: a complete proof is not an eligible one ---------------------------


def test_an_infrastructure_row_inside_a_complete_proof_invalidates_the_population(
    proof_root: Path, tmp_path: Path
) -> None:
    """E-02. File integrity is not eligibility.

    The proof below is complete, inventory-bound, and consistent with its own run
    plan; one of its ten rows is a provider/harness failure. It is not an
    ordinary wrong answer and must never be scored as one.
    """
    base = _baseline(proof_root)
    lock_path, proofs = _replaced_slot(
        base,
        tmp_path,
        block_index=3,
        arm="treatment",
        root=proof_root,
        overrides={
            "primary_pass": False,
            "failure_class": "remote_infra_failure",
            "failure_labels": ["remote_infra_failure"],
            "attempt_validity": "invalid",
            "invalid_reason": "remote_infra_failure",
            "counts_toward_pass_at_k": False,
        },
    )
    with pytest.raises(BenchEvalError, match="ineligible"):
        verify_protocol_lock(lock_path=lock_path, proofs_dir=proofs, output=tmp_path / "o.json")


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"model_id": "kimi-k2.7-code"}, "model_id"),
        ({"provider_config_hash": "sha256:" + "5" * 64}, "drifts"),
        ({"harness_version": "bfcl-eval==2026.3.24"}, "drifts"),
    ],
)
def test_a_slot_served_differently_from_the_rest_is_refused(
    proof_root: Path, tmp_path: Path, overrides: dict[str, object], expected: str
) -> None:
    """P-06. One declared route, one set of constant serving settings, 120 runs.

    ``model_id`` is checked against the protocol's declared route; the other
    axes are checked for drift across the population, which is what the study's
    ``required_constant_axes`` mean.
    """
    base = _baseline(proof_root)
    lock_path, proofs = _replaced_slot(
        base, tmp_path, block_index=1, arm="anchor", root=proof_root, overrides=overrides
    )
    with pytest.raises(BenchEvalError, match=expected):
        verify_protocol_lock(lock_path=lock_path, proofs_dir=proofs, output=tmp_path / "o.json")


def test_a_canonical_proof_cannot_stand_in_for_a_treatment_slot(
    proof_root: Path, tmp_path: Path
) -> None:
    """P-06/E-02. Same cases, same outcomes, wrong representation: still a refusal."""
    base = _baseline(proof_root)
    lock_path, proofs = _replaced_slot(
        base, tmp_path, block_index=2, arm="treatment", root=proof_root, as_arm="anchor"
    )
    with pytest.raises(BenchEvalError, match="not the study benchmark"):
        verify_protocol_lock(lock_path=lock_path, proofs_dir=proofs, output=tmp_path / "o.json")


def test_a_treatment_slot_without_its_measured_representation_is_refused(
    proof_root: Path, tmp_path: Path
) -> None:
    """E-02. A treatment arm unbound from the bytes that transformed it is unusable."""
    base = _baseline(proof_root)
    lock_path, proofs = _replaced_slot(
        base,
        tmp_path,
        block_index=4,
        arm="treatment",
        root=proof_root,
        overrides={"artifact_paths": ["raw/score.json"]},
    )
    with pytest.raises(BenchEvalError, match="variant manifest"):
        verify_protocol_lock(lock_path=lock_path, proofs_dir=proofs, output=tmp_path / "o.json")


def test_the_treatment_mapping_must_cover_the_whole_declared_population(
    proof_root: Path, tmp_path: Path
) -> None:
    """E-02. The historical 200-case mapping cannot measure a 400-case protocol.

    Same transform, same seed, byte-identical derived data -- but a manifest that
    maps half the cohort measures half the cohort, and the protocol's treatment
    arm is not bound by it.
    """
    from bencheval.exposure_selection import load_exposure_selection
    from bencheval.exposure_study import default_studies_dir, load_exposure_study

    historical = load_exposure_study("bfcl-v4-tool-order-v1")
    historical_selection = load_exposure_selection(
        default_studies_dir() / "bfcl-v4-tool-order-v1.selection.json"
    )
    assert len(historical_selection.candidate.selected_ids) == 200
    files = _variant(tmp_path / "historical-variant", historical, historical_selection)
    version = json.loads(files[_VARIANT_REL])["benchmark_version"]

    base = _baseline(proof_root)
    lock_path, proofs = _replaced_slot(
        base,
        tmp_path,
        block_index=5,
        arm="treatment",
        root=proof_root,
        overrides={"benchmark_version": version},
        treatment_files=files,
    )
    with pytest.raises(BenchEvalError, match="variant"):
        verify_protocol_lock(lock_path=lock_path, proofs_dir=proofs, output=tmp_path / "o.json")


# --- P-06, E-03: the retained identity is checked, not trusted ---------------------


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("source_sha256", "sha256:" + "a" * 64, "catalog pin"),
        ("study_sha256", "sha256:" + "b" * 64, "study digest"),
    ],
)
def test_a_lock_cannot_assert_its_own_population_identity(
    proof_root: Path, tmp_path: Path, field: str, value: str, expected: str
) -> None:
    """P-06. Replaying a caller-supplied ranking is not proof of its source.

    The retained selection is re-bound to the installed catalog's pinned question
    files and population anchors, so a lock that re-digests itself consistently
    is still refused.
    """
    base = _baseline(proof_root)

    def mutate(lock: dict[str, object]) -> None:
        selection = lock["selection"]
        if field == "study_sha256":
            selection[field] = value  # type: ignore[index]
        else:
            for side in ("canonical", "candidate"):
                for stratum in selection[side]["strata"].values():  # type: ignore[index]
                    stratum[field] = value

    forged = _forged_lock(base, tmp_path, mutate)
    with pytest.raises(BenchEvalError, match=expected):
        verify_protocol_lock(lock_path=forged, proofs_dir=base.proofs, output=tmp_path / "o.json")


# --- P-03, P-04: the seeds constrain the record, not just its digest ---------------


def test_a_schedule_that_does_not_replay_from_its_seed_is_refused(
    proof_root: Path, tmp_path: Path
) -> None:
    """P-03. Swapping two oppositely assigned blocks keeps every digest consistent.

    It also moves the p-value without a single new observation, which is exactly
    why a self-consistent digest cannot be the only check.
    """
    base = _baseline(proof_root)
    first = next(a for a in base.schedule.assignments if a.z == 1)
    second = next(a for a in base.schedule.assignments if a.z == -1)
    swapped = {
        first.block_id: list(second.slots),
        second.block_id: list(first.slots),
    }

    def mutate(lock: dict[str, object]) -> None:
        for row in lock["schedule"]["assignments"]:  # type: ignore[index]
            if row[0] in swapped:
                row[2] = swapped[row[0]]
        edited = _schedule_from_payload(lock["schedule"])
        lock["manifest"]["schedule_sha256"] = schedule_sha256(edited)  # type: ignore[index]

    forged = _forged_lock(base, tmp_path, mutate)
    with pytest.raises(BenchEvalError, match="replay"):
        verify_protocol_lock(lock_path=forged, proofs_dir=base.proofs, output=tmp_path / "o.json")


def test_a_partition_that_does_not_replay_from_its_seed_is_refused(proof_root: Path) -> None:
    """P-01/P-04. A hand-built partition of the right ids is still not the drawn one."""
    base = _baseline(proof_root)
    first, second = base.blocks[0], base.blocks[1]
    hand_built = (
        dataclasses.replace(first, instance_ids=(second.instance_ids[0], *first.instance_ids[1:])),
        dataclasses.replace(second, instance_ids=(first.instance_ids[0], *second.instance_ids[1:])),
        *base.blocks[2:],
    )
    schedule = draw_schedule(hand_built, rounds=1, draw_seed=_definition().draw_seed)
    manifest = build_protocol_manifest(
        protocol_id=_PROTOCOL,
        study_id="bfcl-v4-tool-order-v1",
        blocking_seed=_BLOCKING_SEED,
        partition_sha256=partition_sha256(hand_built),
        schedule_sha256=schedule_sha256(schedule),
    )
    with pytest.raises(BenchEvalError, match="replay"):
        verify_protocol_population(manifest, hand_built, schedule, base.refs)


def test_a_schedule_drawn_under_another_seed_is_refused(proof_root: Path) -> None:
    """P-03. The assignment seed is part of the protocol, not an operator choice."""
    base = _baseline(proof_root)
    other = draw_schedule(base.blocks, rounds=1, draw_seed="some-other-draw-seed-v1")
    manifest = build_protocol_manifest(
        protocol_id=_PROTOCOL,
        study_id="bfcl-v4-tool-order-v1",
        blocking_seed=_BLOCKING_SEED,
        partition_sha256=partition_sha256(base.blocks),
        schedule_sha256=schedule_sha256(other),
    )
    with pytest.raises(BenchEvalError, match="drawn under seed"):
        verify_protocol_population(manifest, base.blocks, other, base.refs)


# --- CLI entry points --------------------------------------------------------------


def test_study_protocol_command_writes_the_protocol_record(tmp_path: Path) -> None:
    """CLI. ``bencheval study protocol`` exists and produces a real record."""
    output = tmp_path / "protocol.json"
    code = main(
        [
            "study",
            "protocol",
            "bfcl-tool-order-repeat-400-v1",
            "--blocking-seed",
            _BLOCKING_SEED,
            "--output",
            str(output),
        ]
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["protocol_id"] == "bfcl-tool-order-repeat-400-v1"
    assert len(payload["partition"]) == _BLOCKS
    assert len(payload["schedule"]) == _BLOCKS


def test_study_protocol_verify_command_reproduces_the_locked_report(
    proof_root: Path, tmp_path: Path
) -> None:
    """CLI. ``bencheval study protocol-verify`` writes the bytes the lock names."""
    base = _baseline(proof_root)
    lock_path, report = _locked(base, tmp_path)
    output = tmp_path / "reproduced.json"

    code = main(
        [
            "study",
            "protocol-verify",
            "--lock",
            str(lock_path),
            "--proofs",
            str(base.proofs),
            "--output",
            str(output),
        ]
    )
    assert code == 0
    assert _digest(output.read_bytes()) == report.sha256


def test_study_protocol_verify_command_fails_on_a_missing_lock(tmp_path: Path) -> None:
    """CLI. A nonexistent lock is a nonzero exit, not a silent success."""
    assert (
        main(
            [
                "study",
                "protocol-verify",
                "--lock",
                str(tmp_path / "absent.json"),
                "--proofs",
                str(tmp_path / "proofs"),
            ]
        )
        != 0
    )


# --- E-06: the retained two-proof format is untouched (expected GREEN) -------------


def test_retained_two_proof_lock_still_reproduces_its_report_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E-06. The CF1.3 lock reproduces byte-identically through the unchanged reader."""
    copied = tmp_path / "copied"
    shutil.copytree(_FIXTURE / "canonical", copied / "canonical")
    shutil.copytree(_FIXTURE / "candidate", copied / "candidate")
    shutil.copy2(_FIXTURE / "lock.json", copied / "lock.json")
    monkeypatch.chdir(copied)
    verified = verify_exposure_study_lock(
        None,
        lock_path=copied / "lock.json",
        canonical_proof=copied / "canonical",
        candidate_proof=copied / "candidate",
        output=copied / "reproduced.json",
    )
    assert verified["ok"] is True
    assert (copied / "reproduced.json").read_bytes() == (_FIXTURE / "report.json").read_bytes()


def test_retained_two_proof_reader_refuses_the_new_protocol_schema(tmp_path: Path) -> None:
    """E-06. The old reader must not learn to accept the multi-proof lock."""
    assert PROTOCOL_LOCK_SCHEMA != EXPOSURE_LOCK_SCHEMA
    intruder = tmp_path / "protocol-lock.json"
    intruder.write_text(json.dumps({"schema_version": PROTOCOL_LOCK_SCHEMA}), encoding="utf-8")
    with pytest.raises(BenchEvalError, match=EXPOSURE_LOCK_SCHEMA):
        verify_exposure_study_lock(
            None,
            lock_path=intruder,
            canonical_proof=tmp_path / "canonical",
            candidate_proof=tmp_path / "candidate",
        )
