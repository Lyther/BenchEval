# External-command solver stalls + model attribution — problem brief

**Status:** SUPERSEDED (2026-07 product-spine prune) · **Component:** historical external-command lane (removed) · **Type:** archived defect brief

> **Supersession.** `src/bencheval/external_command_adapter.py`, `bencheval run --config`, and the
> generic external-command profile lane are **removed** from the admitted product spine. Do not
> treat the "design landed" claims below as current implementation. Live product path is
> `benchmark → (runtime | agent)? → model via provider → evidence` (see README / architecture).
> This file is retained only as historical problem context.
>
> **Historical resolution note (pre-prune).** The problem statement described the state *before*
> external-command stall/attribution work. That lane previously shipped progress-aware stall
> handling, container-safe cleanup, and model provenance fields — then the whole external-command
> product surface was pruned. Re-admit only via a deliberate new adapter design if needed.

## Summary

When an external-command solver subprocess hangs or returns a degenerate/empty result — typically because the model calls it makes stall upstream — BenchEval's only levers are a wall-clock timeout and a blunt process kill, and the model that actually served each request is only recoverable via a fragile opt-in telemetry join. A stalled attempt is scored as an ordinary failure, indistinguishable from "the challenge was too hard," and a run's benchmark number can silently over-attribute to a single model that did not serve every request.

## Symptom

1. **Stalls look like failures.** A solver subprocess can run for a long time producing no useful output (wedged waiting on a stalled upstream), or return an empty/degenerate final answer. BenchEval times it out on wall-clock, kills it, and scores it as a failure — with no signal distinguishing an **infrastructure stall** from a **genuine task-difficulty failure**.
2. **Kill path strands children.** The per-attempt timeout SIGTERM→SIGKILLs the subprocess. A killed attempt can strand child processes / dockerd-managed containers, which is why run profiles carry a backgrounded-launch + `trap` cleanup wrapper. That wrapper is operator/profile-owned (BenchEval ships no container plane) — it is scar tissue around BenchEval's kill semantics, not a BenchEval capability.
3. **Model attribution is best-effort.** A run declares a requested `model_id`, but the model that actually serves each request may differ (an upstream gateway may substitute/fallback). BenchEval injects per-attempt correlation headers (`X-Experiment-ID` / `X-Request-ID`, deterministic `telemetry_id = {run_id}:{instance_id}:attempt{N}` via `_telemetry_id`) and records `variant` / `configured_model_id` / `telemetry_id` / `trace_id` in evidence `adapter_metadata`, so the actual mix can be reconciled from the gateway's telemetry **after the fact**. This is fragile: it depends on header propagation and gateway logging being enabled; historical runs predate it and are attribution-ambiguous; and a "mixed-model" run does not cleanly attribute a single benchmark number to one model.

## The real problem to solve

1. **Progress-aware stall handling.** Detect a wedged solver by a progress signal (no stdout/stderr/heartbeat for N seconds), not only by total wall-clock — and **record the distinction** so a stall is reported differently from a solve failure.
2. **Honest run classification.** An attempt that failed due to an infra stall (solver hung, upstream unavailable) must be distinguishable in the report from one that failed on task difficulty. Otherwise the benchmark number silently conflates infra flakiness with capability.
3. **Container-safe termination as a first-class capability** (or a documented, supported profile pattern), so operators don't each reinvent the cleanup trap.
4. **First-class model provenance.** Attribution should not depend on a fragile opt-in header↔log join. Make the served-model record part of the run evidence contract, and define how **mixed-model** runs are reported (per-request breakdown vs a single label) so a number is never over-attributed to one model.
5. **Coordinated deadlines.** The per-attempt timeout, any upstream/gateway timeout, and any client disconnect are uncoordinated clocks. Define layered, coherent deadlines with clear ownership: who kills first, and is the kill graceful and attributed?

## Constraints / acceptance

- A stalled/degenerate attempt is **classified and reported distinctly** from a task-difficulty failure.
- Model attribution is authoritative (part of the evidence contract), not a best-effort side-channel; **mixed-model runs are reported honestly** with no single-model over-claim.
- Historical runs lacking attribution are labeled "attribution not captured," never silently attributed to the requested model.
- Termination is container-safe **without** per-profile workarounds.

## Key code

- `src/bencheval/external_command_adapter.py` — external-command invocation, per-attempt timeout + process kill, `_telemetry_id`, evidence `adapter_metadata` (`variant` / `configured_model_id` / `telemetry_id` / `trace_id`), stdout parser, `manifest-value-regex` verification.
- Profile-owned launch/cleanup wrapper lives in the run profile YAML (operator domain), not in BenchEval core — the container-cleanup `trap` there is the workaround this brief refers to.
