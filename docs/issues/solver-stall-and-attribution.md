# External-command solver stalls + model attribution — problem brief

**Status:** RESOLVED (design landed) · **Component:** external-command run lane (`src/bencheval/external_command_adapter.py`) + run profiles · **Type:** actionable defect brief

> **Resolution (current design).** The problem statement below describes the state
> *before* this work; it is retained for context. What shipped:
>
> - **Progress-aware stall handling + honest classification** — `ExternalDeadlineConfig.no_progress_sec`
>   detects a wedged solver by lack of output and classifies it `runtime_no_progress_stall`
>   (invalid, excluded from pass@k), distinct from a task-difficulty fail. `wall_clock_sec`
>   is an operator-supplied ceiling (`--wall-clock-sec`), never a committed guess.
> - **Container-safe termination** — process-group SIGTERM→grace→SIGKILL reaps native
>   children. Because `killpg` cannot reach dockerd-managed containers, container removal
>   is a **first-class BenchEval step** (`ExternalCleanupConfig`, run after every attempt),
>   *not* a per-profile shell `trap`. This satisfies acceptance item 3's "supported pattern
>   without per-profile workarounds": the profile only declares the launch command; BenchEval
>   owns termination, cleanup, and classification.
> - **First-class model provenance** — evidence carries `configured_model_id`,
>   `served_model_id`, and `model_attribution` (`authoritative` / `mixed_model` /
>   `attribution_not_captured`); an uncaptured stream is never silently attributed to the request.
>
> **Remaining limitation:** a solver descendant that double-forks into its own session
> (`setsid`) escapes the group kill; the container case is covered by first-class cleanup.

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
