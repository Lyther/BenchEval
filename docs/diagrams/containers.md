# Container View (C4 L2)

What this shows: deployable/runnable units — the CLI process, library modules, config bundle, external harness processes, and on-disk artifact stores.

```mermaid
flowchart TB
    Op([Operator])

    subgraph Host["Operator host / CI / dev-box"]
        CLI["bencheval process<br/>src/bencheval/cli.py"]
        Lib["bencheval library<br/>src/bencheval/*.py"]
        Cfg["Config bundle<br/>checkout config/ OR<br/>wheel bencheval/_bundled/config/ OR<br/>BENCHEVAL_HOME"]
        Res[(results/<br/>evidence/*.jsonl<br/>raw/*/events.jsonl<br/>live_state.sqlite)]
        Env[".env secrets<br/>provider keys"]
    end

    subgraph ExternalProcs["External processes BenchEval launches"]
        HarborProc["harbor run …"]
        NativeProc["swebench / bfcl CLIs"]
        InspectProc["inspect eval …"]
        ExtProc["operator argv_prefix<br/>solver / runtime CLI"]
        Docker["Docker containers<br/>owned by Harbor or profile cleanup"]
    end

    Op --> CLI
    CLI --> Lib
    Lib -->|repo_root resolution| Cfg
    Lib -->|reads keys; never prints| Env
    Lib -->|writes evidence + run records| Res
    Lib -->|control-plane adapters| HarborProc
    Lib -->|control-plane adapters| NativeProc
    Lib -->|selftest / inspect path| InspectProc
    Lib -->|external_command_adapter| ExtProc
    HarborProc --> Docker
    ExtProc -.->|optional profile cleanup cmds| Docker
    HarborProc -->|stdout/stderr/native results| Res
    NativeProc --> Res
    ExtProc -->|events + evidence| Res
```

Notes: Single-process CLI tool — no microservices, no PostgreSQL. Analytics export (`export` → Parquet/DuckDB) is a **derived** warehouse, not the store of record. Wheel install ships public control-plane YAML via hatch `force-include` ([`pyproject.toml`](../../pyproject.toml)); pricing and selftest fixtures stay checkout-only.
