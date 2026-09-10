# Benchmark ops manuals

Operator notes for product catalog rows. BenchEval ships control-plane glue and, for executable rows, smoke selectors or **instance ids** in `config/slices/*.yaml`. Datasets, Docker images, and Harbor/HF/CAIS caches live on the host (use the 2TB test env for live pulls).

| id | Mode | One-liner shape |
| --- | --- | --- |
| `terminal-bench` | Harbor 2.1 (Tier-1 `fix-git` on both admitted runtimes and the admitted `terminus-2` native agent) | `--runtime` XOR `--agent` |
| `gpqa-diamond` | Inspect Evals (Tier-1: `run-20260825-160511-036214-304c2cee`) | model-only; parse official Inspect scores |
| `hle` | CAIS scripts (Tier-1 registered) | model-only; `BENCHEVAL_HLE_HOME`; parse judge metrics |
| `swe-bench-verified` | **demoted** | `--diagnostic` dispatch materializes the pinned row and injects a real runner; catalog stays non-executable and cannot register `passed` |
| `bfcl-v4` | BFCL eval (Tier-1 registered) | model-only; official `bfcl generate`+`evaluate` lifecycle, gated on the supported-model manifest |
| `bfcl-v4-live` | **diagnostic only** | model-only; one exact official id per Live category; distinct ten-file identity and no inherited admission |
| `swe-bench-pro` | **pending** | needs real official task selector from Harbor dataset |
| `exploitgym` | **pending** | needs real official task id/source from host harness |
| `cybergym` | **not executable** | catalog/`adapter_pending` until full official server+submit lifecycle |

Bare `bencheval run <benchmark>` resolves each executable row’s `default_slice` (smoke). Explicit `<benchmark>/<slice>` still works. Pending rows intentionally have no default slice and should fail before execution.

Preflight a row with the selection you would run: `uv run bencheval doctor <benchmark>[/<slice>] --model <id> [--runtime <id> | --agent <id>] [--provider <id>]`. It resolves the plan exactly as `run --dry-run` (same admission, model-only, provider, and diagnostic refusals), then reports the harness checks, the credential checks, the resolved selection with binding digests, the harness’s preparation recipe, and the host roots. Every real run performs the same preflight before it reserves an evidence file or artifacts directory. Recipes (`uv sync --extra eval`; `uv sync --group bfcl`) run in a BenchEval checkout at its `uv.lock`; an installed wheel or exported bundle plans and preflights but cannot prepare, and the report’s `host.preparation` says which case applies.

Live full-corpus E2E is **not** a CI gate — prove on the 2TB host after dry-run passes. Tier-0 software ≠ Production v1 for every row.
