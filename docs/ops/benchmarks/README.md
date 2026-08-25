# Benchmark ops manuals

Operator notes for product catalog rows. BenchEval ships control-plane glue and, for executable rows, smoke selectors or **instance ids** in `config/slices/*.yaml`. Datasets, Docker images, and Harbor/HF/CAIS caches live on the host (use the 2TB test env for live pulls).

| id | Mode | One-liner shape |
| --- | --- | --- |
| `terminal-bench` | Harbor 2.1 (Tier-0) | `--runtime` XOR `--agent` |
| `gpqa-diamond` | Inspect Evals (Tier-0) | model-only; parse official Inspect scores |
| `hle` | CAIS scripts (Tier-0) | model-only; `BENCHEVAL_HLE_HOME`; parse judge metrics |
| `swe-bench-verified` | **demoted** | not executable until official SWE-bench evaluate is wired |
| `bfcl-v4` | BFCL eval (Tier-0) | model-only; official `bfcl generate`+`evaluate` lifecycle, gated on the supported-model manifest |
| `swe-bench-pro` | **pending** | needs real official task selector from Harbor dataset |
| `exploitgym` | **pending** | needs real official task id/source from host harness |
| `cybergym` | **not executable** | catalog/`adapter_pending` until full official server+submit lifecycle |

Bare `bencheval run <benchmark>` resolves each executable row’s `default_slice` (smoke). Explicit `<benchmark>/<slice>` still works. Pending rows intentionally have no default slice and should fail before execution.

Live full-corpus E2E is **not** a CI gate — prove on the 2TB host after dry-run passes. Tier-0 software ≠ Production v1 for every row.
