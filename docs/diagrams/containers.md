# Container View (C4 L2)

What this shows: deployable/runnable units — the CLI process, library modules, config bundle, external harness processes, and on-disk artifact stores.

```mermaid
flowchart TB
    Op([Operator])

    subgraph Host["Operator host / CI / dev-box"]
        CLI["bencheval process<br/>src/bencheval/cli.py"]
        Lib["bencheval library<br/>src/bencheval/*.py"]
        Cfg["Config bundle<br/>checkout config/ OR<br/>wheel bencheval/_bundled/config/ OR<br/>BENCHEVAL_HOME"]
        Res[(results/<br/>evidence/*.jsonl<br/>raw/*/)]
        Env[".env secrets<br/>provider keys"]
    end

    subgraph ExternalProcs["External processes BenchEval launches"]
        HarborProc["harbor run …"]
        NativeProc["swebench / bfcl CLIs"]
        AgentProc["agent CLI from config/agents"]
        Docker["Docker containers<br/>owned by Harbor / runtime"]
    end

    Op --> CLI
    CLI --> Lib
    Lib -->|repo_root resolution| Cfg
    Lib -->|reads keys; never prints| Env
    Lib -->|writes evidence| Res
    Lib -->|control-plane adapters| HarborProc
    Lib -->|control-plane adapters| NativeProc
    Lib -->|external_agent_adapter| AgentProc
    HarborProc --> Docker
    HarborProc -->|stdout/stderr/native results| Res
    NativeProc --> Res
    AgentProc --> Res
```

Notes: Single-process CLI tool — no microservices, no PostgreSQL. Analytics export (`export` → Parquet/DuckDB) is a **derived** warehouse, not the store of record. Wheel install ships public control-plane YAML via hatch `force-include` ([`pyproject.toml`](../../pyproject.toml)).
