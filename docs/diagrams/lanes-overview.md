# Execution Lanes Overview

What this shows: three coexisting lanes — public control plane, internal selftest, and operator external-command — and what each may claim.

```mermaid
flowchart LR
    subgraph ControlPlane["Lane A — Control plane four-axis"]
        A1["bencheval plan|run<br/>benchmark/slice × runtime × model"]
        A2["Executable adapters only<br/>TB · SWE-Verified · BFCL"]
        A3["EvidenceRecord + interpretation labels"]
        A1 --> A2 --> A3
    end

    subgraph Selftest["Lane B — Selftest / Core"]
        B1["bencheval task · run --task/--suite<br/>--backend local|inspect|harbor"]
        B2["config/selftest core-8/16"]
        B3["Proves plumbing; never weighted<br/>into public benchmark totals"]
        B1 --> B2 --> B3
    end

    subgraph External["Lane C — External command"]
        C1["bencheval run --config profile.yaml"]
        C2["Operator assets + official scorer"]
        C3["events.jsonl + EvidenceRecord<br/>no Production v1 adapter required"]
        C1 --> C2 --> C3
    end

    Claim["Claim discipline"]
    A3 --> Claim
    B3 --> Claim
    C3 --> Claim
    Claim -->|"adapter_smoke ≠ benchmark_native_claim"| Reports["report / compare"]
```

Notes: Architecture §1 demotes Core to selftest. Architecture §11 interpretation labels gate what reports may assert. Metadata-only catalog entries cannot enter Lane A live execution.
