# Product Run Sequence

What this shows: primary value path — list runnable benchmarks, dry-run (phase 1 of `run`), then live execute into EvidenceRecord JSONL.

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

    Op->>CLI: list / catalog …
    CLI-->>Op: executable adapters (default 3)

    Op->>CLI: run gpqa-diamond/smoke --model … --dry-run
    CLI->>Reg: resolve scaffold (runtime XOR agent; else model-only)
    CLI->>Plan: plan_control_plane(…)
    Plan-->>CLI: RunPlan + envelope + caveats
    CLI-->>Op: JSON phase-1 (no model calls)

    Op->>CLI: run terminal-bench/smoke-5 --runtime … --model … -y
    CLI->>Reg: execution_support gate
    alt unknown / not executable
        CLI-->>Op: fail before subprocess
    else executable_adapter
        CLI->>Plan: RunPlan
        CLI->>Doc: require_doctor_ok when needed
        Doc-->>CLI: ok / abort
        CLI->>CPE: execute_control_plane_run(plan)
        loop each instance
            CPE->>Ad: run_*_instance or momo
            Ad-->>CPE: native outcome + artifacts
            CPE->>Ev: append EvidenceRecord
        end
        CPE-->>CLI: summary
        CLI-->>Op: evidence under results/
    end
```

Notes: Harbor requires explicit `--runtime` (`claude-code` | `codex-cli`). GPQA/HLE omit runtime/agent. `--agent momo` is XOR with `--runtime`. Defaults for `--output` / `--artifacts-dir` under `results/`.
