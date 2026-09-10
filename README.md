# BenchEval

Evidence-based evaluation control plane. Product spine:

```text
benchmark  →  (runtime | agent)?  →  model via provider  →  evidence
```

Tier-0 executable software entries: **4** (`terminal-bench`, `gpqa-diamond`, `hle`, `bfcl-v4`). The catalog has **9** rows: `bfcl-v4-live` and `swe-bench-verified` are explicit diagnostic-only identities, while `swe-bench-pro`, `cybergym`, and `exploitgym` remain pending. Diagnostic evidence never inherits admission or registers `passed`. Runtimes are `claude-code` / `codex-cli`, each launched from its closed `launch.harbor` binding; `terminus-2` is the one admitted `kind: harbor` native agent (admitted 2026-09-09 for exactly Terminus-2 2.0.0 × `ollama-qwen3.5-397b-fc` on Terminal-Bench `fix-git`; other combinations are not live-proven), `momo` is a discoverable scaffold; providers are `bytellm` / `ollama-cloud` (both `openai_compatible`; a model row's `api_model` and `backend_bindings.bfcl` make a new model on either route configuration work, see architecture §23). Runtime XOR admitted agent; omit both for model-only benchmarks. Bare `run <benchmark>` uses each executable row’s default smoke slice. Current proof details belong in [`docs/roadmap.md`](docs/roadmap.md); operator commands live in [`docs/ops/benchmarks/`](docs/ops/benchmarks/README.md).

Current concept HLD: [`docs/context/concept-zero.md`](docs/context/concept-zero.md). Historical v0.3 ledger: [`docs/context/concept-hld.md`](docs/context/concept-hld.md). Architecture: [`docs/architecture.md`](docs/architecture.md). Diagrams: [`docs/diagrams/`](docs/diagrams/README.md).

Optional local operator console: [`docs/prototypes/frontend-v1.md`](docs/prototypes/frontend-v1.md)
and [`docs/api/operator-console-contract.md`](docs/api/operator-console-contract.md). Install and
start it with:

```bash
uv sync --extra ui
uv run bencheval ui                # loopback only; opens a capability URL
uv run bencheval ui --no-open      # print the one-process launch URL instead
```

The generated images remain design references rather than screenshots. The CLI remains the stable automation surface; NiceGUI routes and events are private.

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

- `config/benchmarks.yaml` — product catalog (**9** rows; **4** Tier-0 executables)
- `config/studies/` — closed benchmark-exposure study intent; no executable callbacks
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

Before the full contributor gate, install its real export, harness, and console dependencies with `uv sync --dev --extra eval --extra analytics --extra ui`. Use `uv sync --extra eval` for live Inspect / Harbor runs that do not need the analytics or UI gates, and `uv sync --group bfcl` for the pinned BFCL CLI plus its required audio import dependency. BFCL is a repository-owned group because its model-handler graph is large and its audited dependency overrides must travel with the checkout; it can be combined with `eval` when one host needs both harness families. The SWE diagnostic path keeps exact `swebench==5.0.1` in a separate `swe` group because its Docker/evaluator graph is not part of the core or generic Inspect installation; the catalog row stays `executable: false`. Preparation recipes run in a checkout at its `uv.lock` on CPython 3.12 (`.python-version` makes `uv sync` select it even when newer managed interpreters exist; the locked harness wheels have no 3.14 build); an installed wheel or a `BENCHEVAL_HOME` bundle can plan and preflight but cannot `uv sync`, and `bencheval doctor` says so. Readiness gates: [`docs/context/production-readiness.md`](docs/context/production-readiness.md); live procedure: [`docs/ops/dev-box-pilot.md`](docs/ops/dev-box-pilot.md).

## CLI overview

| Group | Commands | Role |
| --- | --- | --- |
| **Product** | `list`, `run`, `benchmark` (compat), `catalog …` | Defined benchmarks → (runtime XOR agent)? → model via provider → evidence |
| **Evidence** | `report`, `compare`, `export`, `export-run`, `evidence register`, `evidence list --current`, `proof export` / `verify` / `import` | Reports, deltas, warehouse, bundles, runs manifest, current-state projection, private proofs |
| **Exposure** | `study validate` / `select` / `report` / `verify` | Read-only benchmark-exposure study validation, deterministic seeded population selection into exact-id slices, deterministic report, and proof-backed lock reproduction; never launches or scores |
| **Preflight** | `doctor` | `doctor <benchmark>[/<slice>] --model … [--runtime\|--agent]` preflights exactly the selection `run` would plan: harness checks, actor binding, credentials (candidate and, for HLE, the pinned judge), the harness's preparation recipe, and the host's config/results roots; `--backend`/`--profile` is the legacy host form. Never prints secrets |

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
