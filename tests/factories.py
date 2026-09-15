"""Shared test factories for control-plane evidence rows and crafted plans."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from bencheval.benchmark_plan import plan_control_plane
from bencheval.domain import RunPlan
from bencheval.evidence import EvidenceRecord
from bencheval.lifecycle import CleanupPolicy

_CP_TS = datetime(2026, 6, 1, tzinfo=UTC)


def make_control_plane_evidence_record(
    *,
    instance_id: str,
    model_id: str = "runtime-default",
    runtime_id: str = "claude-code",
    primary_pass: bool = True,
    attempt_validity: Literal["valid", "invalid"] | None = None,
    counts_toward_pass_at_k: bool | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"run-{runtime_id}-{model_id}-{instance_id}",
        task_id=instance_id,
        model_id=model_id,
        execution_profile="E1",
        backend="harbor",
        primary_pass=primary_pass,
        partial_score=1.0 if primary_pass else 0.0,
        cost_usd=0.1,
        latency_sec=10.0,
        created_at=_CP_TS,
        benchmark_id="terminal-bench",
        benchmark_version="terminal-bench@2.1",
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@1",
        runtime_id=runtime_id,
        runtime_kind="cli_agent",
        runtime_version=f"{runtime_id}@1",
        runtime_config_hash=f"sha256:{runtime_id}",
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm-test",
        instance_id=instance_id,
        interpretation_label="runtime_comparison",
        attempt_validity=attempt_validity,
        counts_toward_pass_at_k=counts_toward_pass_at_k,
    )


def make_scaffold_agent_plan(
    *,
    benchmark_id: str = "terminal-bench",
    slice_id: str = "smoke-5",
    model_id: str = "kimi-k2.7-code",
    cleanup_policy: CleanupPolicy = "always",
) -> RunPlan:
    """Craft a MOMO plan without using the product planner.

    The planner rejects scaffold agents. Retained adapter tests still need a
    typed plan that looks like the old admitted path.
    """
    plan = plan_control_plane(
        benchmark_id=benchmark_id,
        slice_id=slice_id,
        runtime_id="claude-code",
        model_id=model_id,
        cleanup_policy=cleanup_policy,
    )
    return plan.model_copy(
        update={
            "runtime_id": None,
            "runtime_kind": None,
            "agent_id": "momo",
            "model_binding": "bencheval_injected",
            "network_policy": "benchmark_required",
        },
    )


def write_swe_generation_log(
    instance_dir: Path,
    *,
    model: str,
    base_url: str | None,
    instance_id: str = "django__django-11099",
    event_model: str | None = None,
    patch: str = "diff --git a/a b/a\n",
    name: str = "generation.eval",
    setup: str | None = None,
    setup_result: int = 0,
    setup_after_model: bool = False,
) -> Path:
    """One real Inspect ``.eval`` log shaped like the Codex bridge generation retains it.

    ``model`` is the Inspect selector (``openai/<api_model>``); the sample holds
    one model event (``event_model`` when it must contradict the selector) and
    the ``swe_bench_scorer`` metadata that carries ``model_patch``. ``setup`` is
    the per-sample preparation script Inspect retains on the sample and runs as
    ``env <tempfile>`` before the solver; ``setup_result`` and
    ``setup_after_model`` express a failed or late preparation.
    """
    from inspect_ai.event import ModelEvent, SandboxEvent
    from inspect_ai.log import (
        EvalConfig,
        EvalDataset,
        EvalLog,
        EvalSample,
        EvalSpec,
        write_eval_log,
    )
    from inspect_ai.model import GenerateConfig, ModelOutput
    from inspect_ai.scorer import Score

    spec = EvalSpec(
        created=datetime.now(UTC).isoformat(),
        task="inspect_evals/swe_bench",
        model=model,
        model_base_url=base_url,
        dataset=EvalDataset(),
        config=EvalConfig(),
        solver="inspect_swe/codex_cli",
        solver_args={"version": "0.148.0"},
    )
    event = ModelEvent(
        model=event_model or model,
        input=[],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content(model=model.split("/", 1)[-1], content="done"),
    )
    events: list[ModelEvent | SandboxEvent] = [event]
    if setup is not None:
        setup_event = SandboxEvent(
            action="exec",
            cmd="env /tmp/9d1c2f6a4b7e4d8fa0c3e5b7d9f1a3c5",
            result=setup_result,
        )
        events = [*events, setup_event] if setup_after_model else [setup_event, *events]
    sample = EvalSample(
        id=instance_id,
        epoch=1,
        input="fix the issue",
        target="",
        setup=setup,
        scores={"swe_bench_scorer": Score(value=0, metadata={"model_patch": patch})},
        events=events,
    )
    instance_dir.mkdir(parents=True, exist_ok=True)
    path = instance_dir / name
    write_eval_log(EvalLog(eval=spec, samples=[sample], status="success"), str(path))
    return path


def write_swe_generation_log_for_plan(
    instance_dir: Path,
    plan: RunPlan,
    *,
    instance_id: str = "django__django-11099",
    patch: str = "diff --git a/a b/a\n",
    name: str = "generation.eval",
    setup: str | None = None,
    setup_result: int = 0,
    setup_after_model: bool = False,
) -> Path:
    """The matching generation log for ``plan``'s confirmed binding."""
    snapshot = plan.model_binding_snapshot
    if snapshot is None:
        raise ValueError("plan has no model binding snapshot")
    return write_swe_generation_log(
        instance_dir,
        model=f"openai/{snapshot.api_model}",
        base_url=snapshot.base_url,
        instance_id=instance_id,
        patch=patch,
        name=name,
        setup=setup,
        setup_result=setup_result,
        setup_after_model=setup_after_model,
    )


# --- exposure study fixtures ----------------------------------------------------------

_EXPOSURE_TS = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
_EXPOSURE_PRODUCER = "sha256:" + "7" * 64
_EXPOSURE_MODEL = "kimi-k2.7-code"
LIVE_STUDY_ID = "bfcl-v4-live-vs-non-live"
PAIR_STUDY_ID = "bfcl-v4-tool-order-v1"


def _exposure_benchmark_version(benchmark_id: str) -> str:
    from bencheval.identity_strings import bfcl_benchmark_identity, catalog_benchmark_identity

    identity = catalog_benchmark_identity(benchmark_id) if benchmark_id != PAIR_STUDY_ID else None
    if identity is None:
        return f"{benchmark_id}@derived-{'d' * 64}"
    return bfcl_benchmark_identity(identity, benchmark_id=benchmark_id)


def make_exposure_evidence_row(
    *,
    benchmark_id: str,
    slice_id: str,
    instance_id: str,
    primary_pass: bool,
    run_id: str = "run-exposure",
    **overrides: object,
) -> EvidenceRecord:
    """One native BFCL-shaped row an exposure study population is built from."""
    fields: dict[str, object] = {
        "run_id": run_id,
        "task_id": instance_id,
        "model_id": _EXPOSURE_MODEL,
        "execution_profile": "E0",
        "backend": "inspect",
        "primary_pass": primary_pass,
        "partial_score": 1.0 if primary_pass else 0.0,
        "cost_usd": 0.0,
        "latency_sec": 1.0,
        "failure_labels": [] if primary_pass else ["model_wrong_solution"],
        "artifact_paths": ["raw/score.json"],
        "verifier_log_path": "raw/score.json",
        "adapter_metadata": {"producer_content_sha256": _EXPOSURE_PRODUCER},
        "created_at": _EXPOSURE_TS,
        "benchmark_id": benchmark_id,
        "benchmark_version": _exposure_benchmark_version(benchmark_id),
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


def make_selected_exposure_rows(
    side: str,
    *,
    passes: int,
    run_id: str,
    study_id: str = LIVE_STUDY_ID,
):
    """Rows over the checked-in, catalog-anchored selection of ``study_id``.

    A declared population is exactly the selected ids, so these rows are what a
    proof-backed declared report is allowed to bind.
    """
    from bencheval.exposure_selection import load_exposure_selection
    from bencheval.exposure_study import default_studies_dir, load_exposure_study

    selection = load_exposure_selection(default_studies_dir() / f"{study_id}.selection.json")
    bound = getattr(selection, side)
    rows = [
        make_exposure_evidence_row(
            benchmark_id=bound.benchmark_id,
            slice_id=bound.slice_id,
            instance_id=instance_id,
            primary_pass=index < passes,
            run_id=run_id,
        )
        for name in sorted(bound.strata)
        for index, instance_id in enumerate(bound.strata[name].selected_ids)
    ]
    return load_exposure_study(study_id), rows, selection


def make_exposure_populations(
    study_id: str = LIVE_STUDY_ID,
    *,
    smoke: bool = True,
    canonical_passes: int | None = None,
    candidate_passes: int | None = None,
):
    """The study manifest plus one canonical and one candidate population."""
    from bencheval.exposure_study import load_exposure_study

    study = load_exposure_study(study_id)
    per = study.population.smoke_per_stratum if smoke else None

    def side_rows(side, counts, passes: int, run_id: str) -> list[EvidenceRecord]:
        slice_id = side.smoke_slice_id if per is not None else side.slice_id
        return [
            make_exposure_evidence_row(
                benchmark_id=side.benchmark_id,
                slice_id=slice_id,
                instance_id=f"{stratum}_{index}-0-0",
                primary_pass=index < passes,
                run_id=run_id,
            )
            for stratum, declared in counts.items()
            for index in range(per if per is not None else declared)
        ]

    default_canonical = 1 if smoke else 10
    default_candidate = 0 if smoke else 4
    canonical = side_rows(
        study.canonical,
        study.population.canonical_counts,
        canonical_passes if canonical_passes is not None else default_canonical,
        "run-canonical",
    )
    candidate = side_rows(
        study.candidate,
        study.population.candidate_counts,
        candidate_passes if candidate_passes is not None else default_candidate,
        "run-candidate",
    )
    return study, canonical, candidate


def make_exposure_run_plan(rows: list[EvidenceRecord]) -> RunPlan:
    """A retained-plan stand-in with the product planner's shape and this population."""
    from bencheval.domain import RunPlanInstance

    first = rows[0]
    if not first.benchmark_id or not first.slice_id:
        raise ValueError("exposure rows need a benchmark and slice")
    derived = first.benchmark_id == PAIR_STUDY_ID
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


def export_exposure_proof(
    root: Path, rows: list[EvidenceRecord], *, with_plan: bool = True
) -> Path:
    """Export one real complete private proof over a disposable population."""
    from bencheval.evidence import JsonlEvidenceSink
    from bencheval.live_run_manifest import LiveRunRecord, append_live_run
    from bencheval.proof_bundle import export_private_proof

    run_id = rows[0].run_id
    raw = root / "raw"
    (raw / "raw").mkdir(parents=True)
    (raw / "raw" / "score.json").write_text('{"accuracy": 0.0}\n', encoding="utf-8")
    if with_plan:
        (raw / "run-plan.json").write_text(
            make_exposure_run_plan(rows).model_dump_json() + "\n", encoding="utf-8"
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
            generated_at=_EXPOSURE_TS,
        ),
    )
    return export_private_proof(
        run_id=run_id,
        evidence_path=evidence,
        artifacts_dir=raw,
        manifest_path=manifest,
        output_dir=root / "proof",
    ).root
