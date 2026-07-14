# Internal API contracts

BenchEval has **no public HTTP surface**. Boundaries are Python modules, Pydantic DTOs, and the CLI.

Product spine: `benchmark → (runtime | agent)? → model via provider → evidence`.

## Frozen modules

| Artifact | Role |
| --- | --- |
| [`domain.py`](../../src/bencheval/domain.py) | Shared enums, `RunPlan`, runtime/slice DTOs, failure labels |
| [`evidence.py`](../../src/bencheval/evidence.py) | `EvidenceRecord` JSONL schema |
| [`evidence_compare.py`](../../src/bencheval/evidence_compare.py) | Compare two evidence JSONL runs |
| [`benchmark_registry.py`](../../src/bencheval/benchmark_registry.py) | `config/benchmarks.yaml` → catalog (8 rows; 5 Tier-0 executables) |
| [`runtime_registry.py`](../../src/bencheval/runtime_registry.py) | `config/runtimes/*.yaml` |
| [`agent_registry.py`](../../src/bencheval/agent_registry.py) | `config/agents/*.yaml` |
| [`provider_registry.py`](../../src/bencheval/provider_registry.py) | `config/providers/*.yaml` |
| [`model_registry.py`](../../src/bencheval/model_registry.py) | `config/models.yaml` |
| [`benchmark_plan.py`](../../src/bencheval/benchmark_plan.py) | Phase-1 planner (`RunPlanner`) |
| [`control_plane_executor.py`](../../src/bencheval/control_plane_executor.py) | Adapter dispatch (`AdapterDispatcher`) |
| [`external_agent_adapter.py`](../../src/bencheval/external_agent_adapter.py) | Generic agent CLI runner from agent YAML |
| [`doctor.py`](../../src/bencheval/doctor.py) | Preflight; credentials via model → provider route |
| [`exceptions.py`](../../src/bencheval/exceptions.py) | `BenchEvalError`, `AdapterFailureError`, … |

## CLI surface

```text
bencheval list [--format json]                          # runnable benchmarks (default: 5)
bencheval benchmark list|show|slices …                  # compat catalog
bencheval catalog runtime|provider|agent|model list|show
bencheval doctor --backend … | --profile pilot --model <id>
bencheval run <benchmark>/<slice> --model <id>
            [--runtime <id> | --agent <id>] [--provider <id>]
            [--dry-run | -y] [--output …] [--artifacts-dir …]
bencheval report|compare|export|export-run …
bencheval evidence register …
```

`run` is two-phase: print envelope → confirm (`-y` skips) → execute. `--dry-run` stops after phase 1.

Planning rejects unknown models, provider_route mismatches, runtime/agent XOR violations, and agents whose `supported_harnesses` excludes the benchmark harness.

## Evidence

Primary scoring is `EvidenceRecord` JSONL + `bencheval compare`. Failed adapter attempts must still append a row with a canonical `FailureLabel` (never crash on construct).

## Config bundle

Wheel installs ship `bencheval/_bundled/config/`. `BENCHEVAL_HOME` overrides for a custom bundle.
