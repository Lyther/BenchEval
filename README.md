# BenchEval

Evidence-based evaluation control plane. Product spine:

```text
benchmark  →  (runtime | agent)?  →  model via provider  →  evidence
```

Tier-0 executable software entries: **4** (`terminal-bench`, `gpqa-diamond`, `hle`, `bfcl-v4` — BFCL admitted 2026-08-24 on the diagnostic-labeled dev-box lifecycle demonstration `run-20260824-040631-228703-4756f857` plus the registered `passed` run `run-20260824-045622-854659-a46ae44d`). `swe-bench-verified` stays cataloged but non-executable. A diagnostic lifecycle is wired (`--diagnostic` only): official eval scores the run-owned pinned row, and an executed per-instance `report.json` is retained only when schema-v2 actually executed the instance. That does not admit or promote the row. Catalog also keeps `swe-bench-pro`, `cybergym`, and `exploitgym` as `adapter_pending`. Runtimes `claude-code` / `codex-cli`; no agent is admitted (`momo` is a discoverable scaffold); providers `bytellm` / `ollama-cloud`. Runtime XOR admitted agent; omit both for model-only (GPQA / HLE / BFCL). Bare `run <benchmark>` uses each executable row’s `default_slice` (smoke). Ops: [`docs/ops/benchmarks/`](docs/ops/benchmarks/README.md).

Current concept HLD: [`docs/context/concept-zero.md`](docs/context/concept-zero.md). Historical v0.3 ledger: [`docs/context/concept-hld.md`](docs/context/concept-hld.md). Architecture: [`docs/architecture.md`](docs/architecture.md). Diagrams: [`docs/diagrams/`](docs/diagrams/README.md).

Optional local operator console: [`docs/prototypes/frontend-v1.md`](docs/prototypes/frontend-v1.md)
and [`docs/api/operator-console-contract.md`](docs/api/operator-console-contract.md). Install and
start it with:

```bash
uv sync --extra ui
uv run bencheval ui                # loopback only; opens a capability URL
uv run bencheval ui --no-open      # print the one-process launch URL instead
```

The generated images remain design references rather than screenshots. The CLI
remains the stable automation surface; NiceGUI routes and events are private.

## 5-minute path

```bash
# 1. Install
uv sync

# 2. List runnable benchmarks (expect 4)
uv run bencheval list --format json

# 3. Catalog discovery
uv run bencheval catalog runtime list
uv run bencheval catalog provider list
uv run bencheval catalog agent list

# 4. Dry-run (phase 1 only — envelope/cost/caveats, no execute)
uv run bencheval run gpqa-diamond --model kimi-k2.7-code --provider bytellm --dry-run
uv run bencheval run terminal-bench --runtime claude-code --model <model-id> --dry-run

# 5. Live run (-y skips continue prompt; needs provider/runtime + host caches)
uv run bencheval run gpqa-diamond --model <model-id> --provider bytellm -y
```

Unknown benchmark/runtime/agent/provider ids fail before subprocess. Datasets/images stay on the host — not in this repo. Research catalog: `docs/context/external-benchmark-catalog.md`.

## Layout

- `config/benchmarks.yaml` — product catalog (**8** rows; **4** Tier-0 executables)
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

Before the full contributor gate, install its real export, harness, and console dependencies with `uv sync --dev --extra eval --extra analytics --extra ui`. Use `uv sync --extra eval` for live Inspect / Harbor runs that do not need the analytics or UI gates, and `uv sync --group bfcl` for the pinned BFCL CLI plus its required audio import dependency. BFCL is a repository-owned group because its model-handler graph is large and its audited dependency overrides must travel with the checkout; it can be combined with `eval` when one host needs both harness families. The SWE diagnostic path keeps exact `swebench==5.0.1` in a separate `swe` group because its Docker/evaluator graph is not part of the core or generic Inspect installation; the catalog row stays `executable: false`. Pilot gates: [`docs/context/production-v1-pilot.md`](docs/context/production-v1-pilot.md) (`make check-production-v1`).

## CLI overview

| Group | Commands | Role |
| --- | --- | --- |
| **Product** | `list`, `run`, `benchmark` (compat), `catalog …` | Defined benchmarks → (runtime XOR agent)? → model via provider → evidence |
| **Evidence** | `report`, `compare`, `export`, `export-run`, `evidence register`, `evidence list --current`, `proof export` / `verify` / `import` | Reports, deltas, warehouse, bundles, runs manifest, current-state projection, private proofs |
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

Tiers and honesty gates: [`docs/context/production-readiness.md`](docs/context/production-readiness.md). Tier-0 executable count must stay **4** until another adapter is deliberately admitted in config. Tier-0 ≠ Production v1 live proof for every row.

Research catalog (docs only, not product YAML): [`docs/context/external-benchmark-catalog.md`](docs/context/external-benchmark-catalog.md).
