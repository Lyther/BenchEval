# System overview

High-level data flow: legacy path uses Inspect `.eval` → summary JSONL; vNext path uses task contracts → evidence JSONL → export/compare.

## Legacy summary pipeline (2026-04-15)

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

## vNext evidence pipeline (2026-05-29)

```mermaid
flowchart LR
    subgraph Tasks["Task contract"]
        TC[config/tasks/core-8/*.yaml]
        WS[workspaces + verify.py]
    end

    subgraph Run["Execution"]
        LH[local/harness]
        INS[Inspect adapter]
        HAR[Harbor adapter POC]
        DOC[bencheval doctor]
    end

    subgraph Out["Outputs"]
        EV[results/evidence/*.jsonl]
        RAW[results/raw/*]
        WH[warehouse/ Parquet or DuckDB]
        RPT2[results/reports/*.md]
    end

    TC --> WS
    DOC --> INS
    TC --> LH
    TC --> INS
    TC --> HAR
    LH --> EV
    INS --> EV
    HAR --> EV
    EV --> RAW
    EV --> WH
    EV --> RPT2
    EV --> CMP2[bencheval compare]
    CMP2 --> RPT2
```

## Components

### Legacy

- **config + manifests**: Committed task ids + hashes; stamp every run (`task_manifest_hash`).
- **run wrapper**: Sets `RunStamp` / env; invokes `inspect eval`; never writes summary rows directly.
- **extract**: Implements `EvalLogSource` + `SummaryBuilder`; emits validated `SummaryRow` JSONL.
- **compare** (`scripts/compare.py`): Enforces §7 guardrails; emits `ComparisonReport` → Markdown.

### vNext (current)

- **task contract + registry**: YAML v0.2 under `config/tasks/`; `bencheval task lint|validate|audit`.
- **executor**: `local/harness` offline reference path; Inspect/Harbor adapters for live runs.
- **mockllm/model**: Deterministic Inspect E0 stand-in (no `inspect_ai` required); not live provider proof.
- **doctor**: Preflight JSON for Inspect/Harbor; `--profile E0|E1|E2`.
- **evidence + report**: `EvidenceRecord` JSONL; Markdown via `bencheval report`.
- **export + compare**: `bencheval export` (Parquet/DuckDB); `bencheval compare` (vNext evidence deltas).
- **provider smoke**: `scripts/run_provider_smoke.sh` — credential-gated multi-model T1 E0 orchestrator.

## Notes

- Baseline auth lane uses Inspect provider env vars only; experimental lane is isolated at the row level (`auth_lane`, cost XOR).
- Core-8: 8/8 admitted offline (2026-05-29). Live provider, Docker E1, and Harbor jobs blocked on environment.
- Core-16: planned in `docs/context/core-16-expansion-plan.md`; not implemented.
