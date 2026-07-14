# Adapter Components (C4 L3)

What this shows: Production v1 executable adapters and harness ownership.

```mermaid
flowchart TB
    CPE["control_plane_executor.execute_control_plane_run"]

    subgraph ProdV1["Production v1 executable adapters<br/>config: executable: true"]
        TB["terminal_bench_harbor.py<br/>adapter_id: terminal-bench-harbor<br/>harness: harbor"]
        SWE["swebench_adapter.py<br/>adapter_id: swebench<br/>harness: swebench-native"]
        BFCL["bfcl_native_adapter.py<br/>adapter_id: bfcl<br/>harness: bfcl-native<br/>generation smoke until evaluate"]
        Agent["external_agent_adapter.py<br/>config/agents/*.yaml command contract"]
    end

    subgraph Outside["Harness / runtime / agent ownership"]
        HCLI["Harbor CLI + Docker"]
        SN["SWE-bench native tooling"]
        BN["BFCL / Gorilla harness"]
        ExtAgent["External agent CLI e.g. momo"]
    end

    CPE -->|adapter_id match| TB & SWE & BFCL
    CPE -->|agent_id set| Agent
    TB --> HCLI
    SWE --> SN
    BFCL --> BN
    Agent --> ExtAgent

    Cat["config/benchmarks.yaml<br/>adapter_id · executable"]
    Cat -.->|declares executability| ProdV1
```

Notes: Research candidates stay in docs (`external-benchmark-catalog.md`), not product YAML. `harness_kind` is adapter-declared run-plan/evidence metadata, not a benchmark YAML knob. BFCL currently runs `bfcl generate` for adapter smoke; official `bfcl evaluate` is not wired yet, so evidence interpretation stays `adapter_smoke`.
