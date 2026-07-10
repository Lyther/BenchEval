# System Overview

What this shows: BenchEval as a four-axis evaluation control plane — plan, run, normalize evidence, compare — with harness-owned sandboxes outside the product.

```mermaid
flowchart TB
    Op([Operator / CI])

    subgraph BE["BenchEval control plane"]
        CLI["bencheval CLI<br/>plan · run · doctor · compare · replay"]
        Reg["Registries<br/>benchmark · slice · runtime · model"]
        Plan["Run Planner → RunPlan"]
        Doc["Preflight / Doctor"]
        Disp["Adapter dispatcher<br/>control_plane_executor"]
        Ev["Evidence JSONL<br/>EvidenceRecord v0.3"]
        Out["Report · Compare · Export · Replay"]
    end

    subgraph Ext["Outside BenchEval ownership"]
        Harbor["Harbor CLI + Docker<br/>Terminal-Bench"]
        Native["Native harnesses<br/>SWE-bench · BFCL"]
        Inspect["Inspect AI optional eval extra"]
        Solver["Operator solver / runtime CLI<br/>external-command profile"]
        LLM["Model providers<br/>API keys in .env only"]
    end

    Art[(results/<br/>evidence · raw · live_state)]

    Op -->|install · list · plan · run| CLI
    CLI --> Reg
    Reg --> Plan
    Plan --> Doc
    Doc --> Disp
    Disp -->|executable adapters| Harbor
    Disp -->|executable adapters| Native
    Disp -->|selftest / E0| Inspect
    Disp -->|run --config| Solver
    Harbor --> LLM
    Native --> LLM
    Inspect --> LLM
    Solver --> LLM
    Harbor -->|native artifacts| Art
    Native -->|native artifacts| Art
    Solver -->|events.jsonl + evidence| Art
    Disp --> Ev
    Ev --> Art
    Art --> Out
    Out --> Op
```

Notes: Four-axis identity is `benchmark/slice × model × runtime × adapter/harness` ([architecture §2](../architecture.md)). BenchEval does **not** ship a Docker orchestration plane; Harbor/runtimes own containers. Executable Production v1 adapters today: `terminal-bench`, `swe-bench-verified`, `bfcl-v4` (config-declared `executable: true`). CyBench and other catalog entries stay metadata-only unless an operator supplies an external-command profile.
