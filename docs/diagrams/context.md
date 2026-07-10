# System Context (C4 L1)

What this shows: BenchEval as one system box, who uses it, and which external systems it depends on — with why each link exists.

```mermaid
flowchart TB
    Op([Operator])
    CI([CI / make check])

    subgraph System["BenchEval"]
        BE["Evaluation control plane<br/>CLI + Python library + YAML config"]
    end

    Harbor["Harbor CLI"]
    Docker["Docker Engine<br/>harness-owned"]
    Inspect["Inspect AI / inspect-evals"]
    SWE["SWE-bench tooling"]
    BFCL["BFCL / Gorilla harness"]
    Provider["LLM providers<br/>Anthropic · OpenAI · ByteLLM · …"]
    OpProfile["Operator run profile + run-root<br/>external-command YAML"]
    Catalog["Public benchmark catalogs<br/>TB · SWE · BFCL · …"]

    Op -->|discovers · plans · runs · compares| BE
    CI -->|Tier 0 gates · unit/integration tests| BE
    BE -->|invokes for Terminal-Bench| Harbor
    Harbor -->|runs agent tasks in| Docker
    BE -->|optional eval extra E0/E1| Inspect
    BE -->|native adapter subprocess| SWE
    BE -->|native adapter subprocess| BFCL
    BE -->|model_id binding; never stores secrets| Provider
    Op -->|supplies profile + private assets| OpProfile
    OpProfile -->|bencheval run --config| BE
    Catalog -->|metadata in config/benchmarks.yaml| BE
    BE -->|EvidenceRecord + reports| Op
```

Notes: No public HTTP API ([`docs/api/internal-contracts.md`](../api/internal-contracts.md)). Secrets stay in `.env`; `config/models.yaml` is non-secret metadata. External-command profiles are **operator artifacts**, not shipped CyBench product assets.
