# Benchmark ops manuals

Operator notes for product catalog rows. BenchEval ships control-plane glue and, for admitted rows, smoke **instance ids** inline in `config/slices/*.yaml`. Datasets, Docker images, and Harbor/HF/CAIS caches live on the host (use the 2TB test env for live pulls).

| id | Mode | One-liner shape |
| --- | --- | --- |
| `terminal-bench` | Harbor 2.1 | `--runtime` XOR `--agent` |
| `swe-bench-verified` | native | `--runtime` XOR `--agent` |
| `bfcl-v4` | model-only | no runtime/agent |
| `swe-bench-pro` | **pending** | needs real official task selector from Harbor dataset |
| `gpqa-diamond` | Inspect Evals | model-only; parse official Inspect scores |
| `hle` | CAIS scripts | model-only; `BENCHEVAL_HLE_HOME`; parse judge metrics |
| `exploitgym` | **pending** | needs real official task id/source from host harness |
| `cybergym` | **not executable** | catalog/`adapter_pending` until full official server+submit lifecycle |

Bare `bencheval run <benchmark>` resolves each executable row’s `default_slice` (smoke). Explicit `<benchmark>/<slice>` still works. Pending rows intentionally have no default slice and should fail before execution.

Live full-corpus E2E is **not** a CI gate — prove on the 2TB host after dry-run passes. Tier-0 software ≠ Production v1 for every row.
