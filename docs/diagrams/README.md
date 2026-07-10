# Architecture Diagrams

Start here: [System Overview](./system-overview.md)

Layered Mermaid set for BenchEval v0.3 (evaluation control plane). Each diagram is focused; the set covers the whole system. Source of truth for product decisions: [`docs/architecture.md`](../architecture.md) and [`docs/context/concept-hld.md`](../context/concept-hld.md).

| Diagram | Level | Shows |
|---|---|---|
| [system-overview](./system-overview.md) | overview | Whole system at a glance: actors, control plane, adapters, evidence |
| [context](./context.md) | C4 L1 | Operators and external systems around BenchEval |
| [containers](./containers.md) | C4 L2 | Runnable units: CLI, library, config, harnesses, artifact stores |
| [control-plane-components](./control-plane-components.md) | C4 L3 | Registries, planner, doctor, executor, evidence/report path |
| [adapters-components](./adapters-components.md) | C4 L3 | Production v1 + Inspect/Harbor/selftest adapter families |
| [external-command-components](./external-command-components.md) | C4 L3 | Config-driven external-command + run-record/replay lane |
| [config-resolution](./config-resolution.md) | structure | How `repo_root()` / wheel bundle / `BENCHEVAL_HOME` resolve config |
| [lanes-overview](./lanes-overview.md) | structure | Control-plane vs selftest vs external-command lanes |
| [four-axis-run-sequence](./four-axis-run-sequence.md) | runtime | Primary `plan` / `run <benchmark>/<slice>` path |
| [external-command-sequence](./external-command-sequence.md) | runtime | `run --config` attempt lifecycle + live_state vs events.jsonl |
| [discovery-sequence](./discovery-sequence.md) | runtime | Catalog discovery (`benchmark`/`runtime`/`model`/`adapter` list) |
| [data-model](./data-model.md) | ERD | Core entities: catalogs, RunPlan, EvidenceRecord, run record |
| [attempt-lifecycle-state](./attempt-lifecycle-state.md) | state | Attempt validity / pass@k / failure classes |
| [deployment](./deployment.md) | topology | Laptop Tier 0 vs dev-box Tier 1; no BenchEval Docker plane |

## Reading order

1. Overview → Context → Containers
2. Control-plane components → Adapters → External-command (as needed)
3. Sequences for the flow you are changing
4. Data model + attempt state before touching evidence/replay contracts
