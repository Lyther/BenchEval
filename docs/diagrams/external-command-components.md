# External-Command Components (C4 L3)

What this shows: the config-driven external project lane — profile → subprocess → run record + evidence — without shipping benchmark-specific CyBench profiles.

```mermaid
flowchart TB
    CLI["cli.py<br/>run --config profile.yaml"]

    subgraph Adapter["external_command_adapter.py"]
        Cfg["ExternalRunConfig<br/>command · stream · verify · deadline · cleanup"]
        Root["validate_external_run_root<br/>prompts · keys · manifests"]
        Run["run_external_command<br/>per-instance attempts"]
        Ver["verification policy<br/>official scorer preferred;<br/>includes-fallback labeled"]
        Meta["adapter_metadata<br/>variant · telemetry_id · trace_id"]
    end

    subgraph Record["replay.py run-record lane"]
        W["RunRecordWriter<br/>header / event / footer"]
        LS["live_state.sqlite<br/>high-volume llm/tool/debug"]
        L["load_run_record · replay<br/>verify_bound_evidence"]
    end

    Ev[(EvidenceRecord JSONL)]
    Events[(events.jsonl<br/>canonical audit)]
    Pres["presentation.py<br/>derived public redaction only"]

    CLI --> Cfg
    Cfg --> Root --> Run
    Run -->|lifecycle/scoring events| W
    Run -->|mid-step reasoning| LS
    Run --> Ver --> Ev
    Run --> Meta --> Ev
    W --> Events
    Events --> L
    Ev --> L
    Events -.->|never for scoring| Pres
```

Notes: Canonical `events.jsonl` is raw/private; redaction is only for derived public artifacts ([internal-contracts § Replay](../api/internal-contracts.md)). Operator profiles live outside the repo unless they become official reusable adapters. Exit-code policy maps process exits to failure labels without inventing benchmark scores.
