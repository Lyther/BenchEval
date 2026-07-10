# Adapter Components (C4 L3)

What this shows: adapter families BenchEval ships, which are Production v1 executable, and how they map to harness ownership.

```mermaid
flowchart TB
    CPE["control_plane_executor.execute_control_plane_run"]

    subgraph ProdV1["Production v1 executable adapters<br/>config: executable: true"]
        TB["terminal_bench_harbor.py<br/>adapter_id: terminal-bench-harbor<br/>harness: harbor"]
        SWE["swebench_adapter.py<br/>adapter_id: swebench<br/>harness: swebench-native"]
        BFCL["bfcl_native_adapter.py<br/>adapter_id: bfcl<br/>harness: bfcl-native"]
    end

    subgraph Other["Other adapter modules present"]
        Harbor["harbor_adapter.py<br/>generic Harbor invoke helper"]
        Inspect["inspect_adapter.py<br/>Inspect + mockllm E0 path"]
        Ext["external_command_adapter.py<br/>run --config lane"]
        Self["runner.py · executor.py<br/>selftest Core-8/16"]
    end

    subgraph Outside["Harness / runtime ownership"]
        HCLI["Harbor CLI + Docker"]
        SN["SWE-bench native tooling"]
        BN["BFCL native / Gorilla"]
        IA["inspect_ai optional"]
        Op["Operator solver process"]
    end

    CPE -->|adapter_id match| TB & SWE & BFCL
    TB --> Harbor
    Harbor --> HCLI
    SWE --> SN
    BFCL --> BN
    Self --> Inspect
    Inspect --> IA
    Ext --> Op

    Cat["config/benchmarks.yaml<br/>adapter_id · harness_kind · executable"]
    Cat -.->|declares executability| ProdV1
```

Notes: Executable set is **config-declared**, not hard-coded in Python ([`production-readiness.md`](../context/production-readiness.md) Tier 0 gate: exactly `terminal-bench`, `swe-bench-verified`, `bfcl-v4`). LiveCodeBench/BigCodeBench may carry `adapter_id` metadata while remaining non-executable until admitted. Metadata-only benchmarks (e.g. CyBench) fail before subprocess dispatch on four-axis `run`.
