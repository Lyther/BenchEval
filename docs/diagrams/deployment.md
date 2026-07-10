# Deployment Topology

What this shows: where BenchEval runs vs where harness sandboxes live — Tier 0 laptop vs Tier 1 live proof on a operator host.

```mermaid
flowchart TB
    subgraph Laptop["Developer laptop — Tier 0"]
        Dev["uv sync / uv tool install"]
        Unit["pytest · ruff · make check-production-v1"]
        PlanOnly["bencheval plan · benchmark list\nno Docker required"]
        Dev --> Unit
        Dev --> PlanOnly
    end

    subgraph DevBox["dev-box-cpu / operator host — Tier 1 live proof"]
        BE["bencheval run …"]
        Creds[".env provider credentials"]
        Eval["uv sync --extra eval optional"]
        Harbor["Harbor CLI"]
        Dock["Docker Engine"]
        Native["SWE / BFCL native tools"]
        Disk[(results/ evidence + raw)]

        BE --> Creds
        BE --> Eval
        BE --> Harbor
        Harbor --> Dock
        BE --> Native
        BE --> Disk
    end

    subgraph NotOurs["Not a BenchEval plane"]
        NoOrch["No BenchEval-owned\nDocker orchestration / image prune"]
    end

    Laptop -.->|same wheel/CLI| DevBox
    DevBox --> NotOurs
```

Notes: See [`docs/ops/dev-box-pilot.md`](../ops/dev-box-pilot.md) and [`production-readiness.md`](../context/production-readiness.md). Green Tier 0 tests are not live benchmark proof. Cleanup policy removes BenchEval-owned temp dirs only; image pruning stays harness/operator-owned.
