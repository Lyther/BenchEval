# Discovery Sequence

What this shows: catalog discovery commands that need no credentials and emit JSON/text from the resolved config bundle.

```mermaid
sequenceDiagram
    actor Op as Operator
    participant CLI as bencheval CLI
    participant Paths as paths.repo_root
    participant BR as benchmark_registry
    participant RR as runtime_registry
    participant MR as model_registry
    participant BP as benchmark_plan

    Op->>CLI: benchmark list [--execution-support …]
    CLI->>Paths: resolve config root
    Paths-->>CLI: checkout / wheel / BENCHEVAL_HOME
    CLI->>BR: load_benchmark_catalog
    BR-->>CLI: BenchmarkEntry[] + execution_support
    CLI-->>Op: table or JSON

    Op->>CLI: runtime list / model list / adapter list
    CLI->>RR: load RuntimeCatalog
    CLI->>MR: load ModelRegistry
    CLI->>BP: AdapterDescriptor list
    CLI-->>Op: profiles / models / planned adapters

    Op->>CLI: benchmark slices terminal-bench
    CLI->>BR: show entry
    CLI-->>Op: typed slice ids from config/slices
```

Notes: These commands are Tier 0 / laptop-safe. Filtering `--execution-support executable_adapter` is the Production v1 gate surface used by `make check-production-v1`.
