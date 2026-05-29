# BenchEval

Private-first, evidence-based evaluation for coding, tool use, agentic coding, and defensive security. Product intent and vNext HLD: [`concept-zero.md`](concept-zero.md) → [`docs/context/concept-zero.md`](docs/context/concept-zero.md) (v0.2, 2026-05-29).

## Layout

- `config/tasks/` — vNext task contracts (Core-8 under `core-8/`)
- `config/suites.yaml` — suite membership (core-8, smoke, calibration, stretch)
- `config/` — legacy manifests, pricing YAML (no secrets)
- `src/bencheval/` — library: task contract, registry, planner, evidence JSONL, legacy summary/compare
- `scripts/` — `compare.py`, `extract_summary.py`, `preflight_disk.sh`, `verify_auth.sh`, `run_provider_smoke.sh`
- `tests/` — pytest suite
- `results/` — run artifacts (gitignored where noted)
- `docs/` — architecture, roadmap, concept-zero context, Core-16 expansion plan

## Setup

```bash
uv sync
```

Use `uv sync --extra eval` only when running real Inspect / Harbor evals (vNext P1+).

## vNext CLI

```bash
# Lint / validate / audit a task contract
uv run bencheval task validate be-core-c1-small-logic-patch
uv run bencheval task audit be-core-t1-single-structured-call
uv run bencheval task audit core-8

# Dry-run cost/envelope estimate (no network, no model calls)
uv run bencheval run --dry-run --suite smoke --model anthropic/claude-test

# Offline local/harness smoke (reference path; not a live model call)
uv run bencheval run \
  --task be-core-t1-single-structured-call \
  --model local/harness \
  --output results/evidence/run-001.jsonl \
  --artifacts-dir results/raw/run-001

# All eight Core-8 tasks are admitted; offline harness supports T1/T2 (E0) and C1/C2/A1/A2/S1/S4 (E1).
uv run bencheval task audit core-8

# Preflight for live Inspect/Harbor backends (never prints secret values)
uv sync --extra eval
uv run bencheval doctor --backend inspect --model openai/gpt-test --profile E0
uv run bencheval doctor --backend inspect --model openai/gpt-test --profile E1

# Inspect E0 with mockllm (deterministic reference stand-in; no inspect_ai import or generate() call)
uv run bencheval run \
  --task be-core-t1-single-structured-call \
  --model mockllm/model \
  --backend inspect \
  --output results/evidence/run-mockllm-001.jsonl \
  --artifacts-dir results/raw/run-mockllm-001

# Live provider run (requires credentials + eval extra; distinct from local/harness and mockllm)
uv run bencheval run \
  --task be-core-t1-single-structured-call \
  --model openai/gpt-test \
  --backend inspect \
  --output results/evidence/run-inspect-001.jsonl \
  --artifacts-dir results/raw/run-inspect-001

# Export evidence to warehouse tables (requires analytics extra)
uv sync --extra analytics
uv run bencheval export results/evidence/run-001.jsonl \
  --format parquet \
  --output warehouse/run-001

# Markdown report from evidence JSONL
uv run bencheval report results/evidence/run-001.jsonl \
  --output results/reports/run-001.md

# Compare two vNext evidence JSONL runs (legacy summary compare stays in scripts/compare.py)
uv run bencheval compare results/evidence/baseline.jsonl results/evidence/current.jsonl \
  --format md \
  --output results/reports/delta.md
```

## Provider smoke (live, credential-gated)

Bounded Inspect E0 smoke for real providers. Skips models with known preflight blockers (missing credentials, Docker, Inspect dependency). Invalid config and unknown doctor failures exit non-zero.

```bash
uv sync --extra eval
BENCHEVAL_MODELS="openai/gpt-4o anthropic/claude-sonnet" ./scripts/run_provider_smoke.sh
# or: ./scripts/run_provider_smoke.sh openai/gpt-4o anthropic/claude-sonnet
```

Writes `results/evidence/`, `results/raw/`, and `results/reports/` per model. Requires provider env vars; does not print secret values.

## Legacy summary pipeline

Emit one strict summary row (manifest + stamp JSON + header JSON → JSONL):

```bash
uv run python scripts/extract_summary.py \
  --eval-log results/raw/run-001.eval \
  --manifest config/manifests/swebench-verified-smoke-10.txt \
  --stamp-json path/to/stamp.json \
  --header-json path/to/header.json \
  --output results/summary/run-001.jsonl
```

Compare two JSONL summary files:

```bash
uv run python scripts/compare.py \
  --baseline results/summary/baseline.jsonl \
  --current results/summary/current.jsonl \
  --format md \
  --output results/reports/delta.md
```

## Package

Public exports (`from bencheval import …`) match `bencheval.__all__` — legacy summary/compare types. vNext modules (`task_contract`, `task_registry`, `planner`, `evidence`, `report`) are imported from submodules or via the `bencheval` CLI.

## Development

```bash
uv run pytest -q                    # 283 tests (2026-05-29)
uv run ruff check src tests scripts/
uv run ruff format --check src tests scripts/
shellcheck scripts/*.sh && bash -n scripts/*.sh
uv run bencheval task audit core-8  # 8/8 admitted
```

Live Inspect/Harbor proof requires `uv sync --extra eval`, provider credentials, Docker (E1), and Harbor CLI (S4 live). See [`docs/roadmap.md`](docs/roadmap.md) live blockers.

## License

MIT — see [`LICENSE`](LICENSE).
