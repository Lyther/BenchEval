# Four-Axis Run Sequence

What this shows: primary value path — discover axes, plan without model calls, then live execute through an executable adapter into EvidenceRecord JSONL.

```mermaid
sequenceDiagram
    actor Op as Operator
    participant CLI as bencheval CLI
    participant Reg as Registries
    participant Plan as ControlPlanePlanner
    participant Doc as doctor
    participant CPE as control_plane_executor
    participant Ad as Adapter harness
    participant Ev as Evidence JSONL

    Op->>CLI: plan terminal-bench/smoke-5 --runtime … --model …
    CLI->>Reg: load benchmark/slice/runtime/model
    Reg-->>CLI: contracts + instance ids
    CLI->>Plan: plan_control_plane(…)
    Plan-->>CLI: RunPlan + cost envelope + caveats
    CLI-->>Op: JSON dry-run plan (no model calls)

    Op->>CLI: run terminal-bench/smoke-5 --runtime … --model …
    CLI->>Reg: resolve axes + execution_support
    alt metadata_only / not executable
        CLI-->>Op: fail before subprocess (execution_support)
    else executable_adapter
        CLI->>Plan: RunPlan
        CLI->>Doc: require_doctor_ok
        Doc-->>CLI: ok / abort (no evidence)
        CLI->>CPE: execute_control_plane_run(plan)
        loop each instance
            CPE->>Ad: run_*_instance
            Ad-->>CPE: native outcome + artifacts
            CPE->>Ev: append EvidenceRecord
        end
        CPE-->>CLI: ControlPlaneRunSummary
        CLI-->>Op: evidence path under results/
    end
```

Notes: Shorthand `benchmark/slice` and `plan` alias live in [`cli.py`](../../src/bencheval/cli.py). Defaults for `--output` / `--artifacts-dir` land under `results/` when omitted. Doctor failures abort without writing evidence; post-preflight adapter failures still write `primary_pass=false` rows ([architecture §10](../architecture.md)).
