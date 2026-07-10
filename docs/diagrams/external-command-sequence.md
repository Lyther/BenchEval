# External-Command Sequence

What this shows: one attempt under `run --config` — progress deadlines, dual write lanes (events vs live_state), verification, and cleanup.

```mermaid
sequenceDiagram
    actor Op as Operator
    participant CLI as bencheval CLI
    participant Ext as external_command_adapter
    participant Proc as Solver / runtime process
    participant RR as RunRecordWriter
    participant LS as live_state.sqlite
    participant Ev as Evidence JSONL

    Op->>CLI: run --config profile.yaml [--run-root …]
    CLI->>Ext: load ExternalRunConfig + validate run-root
    Ext->>RR: write header (run_id, axes, integrity)
    loop each instance × attempt
        Ext->>Proc: spawn argv_prefix + args_template
        loop stream lines
            Proc-->>Ext: stdout/stderr
            alt lifecycle / scoring event
                Ext->>RR: append event (seq++)
            else high-volume llm/tool/debug
                Ext->>LS: upsert monitor state
            end
            opt no_progress_sec exceeded
                Ext->>Proc: SIGTERM → grace → SIGKILL
                Ext->>RR: runtime_no_progress_stall
            end
        end
        Ext->>Ext: verify observed vs expected policy
        Ext->>Ev: EvidenceRecord + adapter_metadata
        Ext->>Ext: cleanup.commands (e.g. docker rm -f)
        Ext->>RR: attempt footer fields as needed
    end
    Ext->>RR: write footer
    CLI-->>Op: evidence + events paths
```

Notes: `events.jsonl` stays the complete un-compacted lifecycle/scoring record; `live_state.sqlite` is a mutable monitor lane only. Stall kills classify `runtime_no_progress_stall` as invalid for pass@k. Profile `cleanup:` is first-class — process-group kill cannot reach dockerd containers.
