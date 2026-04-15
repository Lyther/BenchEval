# System overview

High-level data flow: Inspect orchestrates evaluation; BenchEval owns manifests, summaries, and comparisons.

## Diagram

```mermaid
flowchart LR
    subgraph External["Upstream (not owned)"]
        IE[inspect-evals / Harbor tasks]
        IN[Inspect AI runtime]
    end

    subgraph BenchEval["BenchEval (this repo)"]
        CFG[config/*.yaml + manifests]
        WR[run wrapper scripts]
        EX[SummaryBuilder + extract CLI]
        CMP[ComparisonReporter]
    end

    subgraph Artifacts["Artifacts"]
        EVAL[results/raw/*.eval]
        JSL[results/summary/*.jsonl]
        RPT[results/reports/*.md]
    end

    CFG --> WR
    WR --> IN
    IE --> IN
    IN --> EVAL
    EVAL --> EX
    CFG --> EX
    EX --> JSL
    JSL --> CMP
    CMP --> RPT
```

## Components

- **config + manifests**: Committed task ids + hashes; stamp every run (`task_manifest_hash`).
- **run wrapper**: Sets `RunStamp` / env; invokes `inspect eval`; never writes summary rows directly.
- **extract**: Implements `EvalLogSource` + `SummaryBuilder`; emits validated `SummaryRow` JSONL.
- **compare**: Enforces §7 guardrails; emits `ComparisonReport` → Markdown.

## Notes

- Baseline auth lane uses Inspect provider env vars only; experimental lane is isolated at the row level (`auth_lane`, cost XOR).
