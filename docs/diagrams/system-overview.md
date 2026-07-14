# System Overview

What this shows: BenchEval product spine — defined benchmark → (runtime XOR agent)? → model via provider → evidence — with harness-owned sandboxes outside the product.

```mermaid
flowchart TB
    Op([Operator / CI])

    subgraph BE["BenchEval control plane"]
        CLI["bencheval CLI<br/>list · run · catalog · compare"]
        Reg["Registries<br/>benchmark · slice · runtime · agent · provider · model"]
        Plan["Run Planner → RunPlan"]
        Doc["Preflight / Doctor"]
        Disp["Adapter dispatcher"]
        Ev["Evidence JSONL"]
        Out["Report · Compare · Export"]
    end

    subgraph Ext["Outside BenchEval ownership"]
        Harbor["Harbor + Docker<br/>Terminal-Bench"]
        Native["Native harnesses<br/>SWE-bench · BFCL"]
        MOMO["MOMO agent CLI"]
        LLM["Providers<br/>ByteLLM · Ollama"]
    end

    Art[(results/)]

    Op -->|list · run · catalog| CLI
    CLI --> Reg
    Reg --> Plan
    Plan --> Doc
    Doc --> Disp
    Disp -->|runtime path| Harbor
    Disp -->|runtime path| Native
    Disp -->|agent path| MOMO
    Harbor --> LLM
    Native --> LLM
    MOMO --> LLM
    Harbor --> Art
    Native --> Art
    MOMO --> Art
    Disp --> Ev
    Ev --> Art
    Art --> Out
    Out --> Op
```

Notes: Model-only (BFCL) records `runtime_id=null` / `agent_id=null`. Executable adapters: `terminal-bench`, `swe-bench-verified`, `bfcl-v4`. No BenchEval-owned Docker plane.
