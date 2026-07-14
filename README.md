# BenchEval

Evidence-based evaluation control plane. Product spine:

```text
benchmark  →  (runtime | agent)?  →  model via provider  →  evidence
```

Tier-0 executable software entries: **5** (`terminal-bench`, `swe-bench-verified`, `bfcl-v4`, `gpqa-diamond`, `hle`). Catalog keeps `swe-bench-pro`, `cybergym`, and `exploitgym` as `adapter_pending` until real official task selectors are wired. Runtimes `claude-code` / `codex-cli`; agent `momo`; providers `bytellm` / `ollama-cloud`. Runtime XOR agent; omit both for model-only (BFCL / GPQA / HLE). Bare `run <benchmark>` uses each executable row’s `default_slice` (smoke). Ops: [`docs/ops/benchmarks/`](docs/ops/benchmarks/README.md).

Intent / HLD: [`docs/context/concept-hld.md`](docs/context/concept-hld.md) (v0.3). Architecture: [`docs/architecture.md`](docs/architecture.md). Diagrams: [`docs/diagrams/`](docs/diagrams/README.md).

## 5-minute path

```bash
# 1. Install
uv sync

# 2. List runnable benchmarks (expect 5)
uv run bencheval list --format json

# 3. Catalog discovery
uv run bencheval catalog runtime list
uv run bencheval catalog provider list
uv run bencheval catalog agent list

# 4. Dry-run (phase 1 only — envelope/cost/caveats, no execute)
uv run bencheval run gpqa-diamond --model kimi-k2.7-code --provider bytellm --dry-run
uv run bencheval run bfcl-v4 --model <model-id> --dry-run
uv run bencheval run terminal-bench --runtime claude-code --model <model-id> --dry-run

# 5. Live run (-y skips continue prompt; needs provider/runtime + host caches)
uv run bencheval run bfcl-v4 --model <model-id> --provider bytellm -y
```

Unknown benchmark/runtime/agent/provider ids fail before subprocess. Datasets/images stay on the host — not in this repo. Research catalog: `docs/context/external-benchmark-catalog.md`.

## Layout

- `config/benchmarks.yaml` — product catalog (**8** rows; **5** Tier-0 executables)
- `config/runtimes/` · `config/agents/` · `config/providers/` · `config/slices/` · `config/models.yaml`
- Wheel install is self-contained: public config ships as `bencheval/_bundled/config/`; `BENCHEVAL_HOME` is an optional override
- `src/bencheval/` — library + CLI
- `results/` — evidence + raw artifacts (gitignored where noted)
- `docs/` — architecture, roadmap, ops, diagrams

## Setup

```bash
uv sync
# or: uv tool install bencheval
uv run bencheval list --format json
```

Use `uv sync --extra eval` only for live Inspect / Harbor runs. Pilot gates: [`docs/context/production-v1-pilot.md`](docs/context/production-v1-pilot.md) (`make check-production-v1`).

## CLI overview

| Group | Commands | Role |
| --- | --- | --- |
| **Product** | `list`, `run`, `benchmark` (compat), `catalog …` | Defined benchmarks → (runtime XOR agent)? → model via provider → evidence |
| **Evidence** | `report`, `compare`, `export`, `export-run`, `evidence register` | Reports, deltas, warehouse, bundles, runs manifest |
| **Preflight** | `doctor` | Backend/runtime/provider checks (never prints secrets) |

`run` is two-phase: print envelope → confirm (`-y` skips) → execute. `--dry-run` stops after phase 1. There is no separate `plan` command.

BenchEval does **not** ship a Docker orchestration plane. Isolation comes from the benchmark’s official harness/runtime. Tier 1 live proof is expected on **dev-box-cpu** — see [`docs/ops/dev-box-pilot.md`](docs/ops/dev-box-pilot.md).

## Evidence & compare

```bash
uv run bencheval report results/evidence/run-001.jsonl --output results/reports/run-001.md
uv run bencheval compare results/evidence/baseline.jsonl results/evidence/current.jsonl \
  --format md --output results/reports/delta.md
uv run bencheval export-run \
  --evidence results/evidence/run-001.jsonl \
  --raw-dir results/raw/run-001 \
  --output results/bundles/run-001 \
  --redaction private
```

## Production readiness

Tiers and honesty gates: [`docs/context/production-readiness.md`](docs/context/production-readiness.md). Tier-0 executable count must stay **5** until another adapter is deliberately admitted in config. Tier-0 ≠ Production v1 live proof for every row.

Research catalog (docs only, not product YAML): [`docs/context/external-benchmark-catalog.md`](docs/context/external-benchmark-catalog.md).
