# Architecture Diagrams

Start here: [System Overview](./system-overview.md)

Layered Mermaid set for BenchEval v0.3. Product spine: **benchmark → (runtime XOR agent)? → model via provider → evidence**. Source of truth: [`docs/architecture.md`](../architecture.md).

| Diagram | Level | Shows |
|---|---|---|
| [system-overview](./system-overview.md) | overview | Product spine |
| [context](./context.md) | C4 L1 | Operators and external systems |
| [containers](./containers.md) | C4 L2 | CLI, library, config, harnesses, artifacts |
| [control-plane-components](./control-plane-components.md) | C4 L3 | Registries, planner, doctor, executor |
| [adapters-components](./adapters-components.md) | C4 L3 | Production v1 adapters |
| [config-resolution](./config-resolution.md) | structure | Wheel bundle / `BENCHEVAL_HOME` |
| [lanes-overview](./lanes-overview.md) | structure | Product spine (research catalog docs-only) |
| [four-axis-run-sequence](./four-axis-run-sequence.md) | runtime | Primary `run` dry-run / execute path |
| [discovery-sequence](./discovery-sequence.md) | runtime | Catalog discovery |
| [data-model](./data-model.md) | ERD | Catalogs, RunPlan, EvidenceRecord |
| [attempt-lifecycle-state](./attempt-lifecycle-state.md) | state | Attempt validity / pass@k |
| [deployment](./deployment.md) | topology | Laptop Tier 0 vs dev-box Tier 1 |

## Reading order

1. Overview → Context → Containers
2. Lanes → Control-plane components → Adapters
3. Product run sequence before changing `run`
4. Data model before touching evidence
