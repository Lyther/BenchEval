# BenchEval

Private-first, evidence-based evaluation for coding, tool use, agentic coding, and defensive security. Product intent and vNext HLD: [`docs/context/concept-hld.md`](docs/context/concept-hld.md) (v0.3). Legacy v0.2: [`docs/context/concept-zero.md`](docs/context/concept-zero.md).

**Production v1 (executable):** ~50 benchmarks cataloged; **three** have native control-plane adapters: `terminal-bench`, `swe-bench-verified`, `bfcl-v4`. Everything else is `metadata_only` or `manifest_only` until a real adapter and live proof exist. See the tier definitions in [`docs/context/production-readiness.md`](docs/context/production-readiness.md).

> **Scope note:** Core-8 / Core-16 and `bencheval task audit` are an **internal selftest** lane — regression coverage for the control plane itself, **not** the public product narrative. They live in the collapsed [Internal selftest only](#internal-selftest-only-appendix) appendix below.

## 5-minute control plane

The fastest path from clone to a real four-axis execution plan. No credentials, no Docker required for steps 1–4.

```bash
# 1. Install
uv sync

# 2. See which benchmarks actually have a runnable adapter (expect exactly 3)
uv run bencheval benchmark list --execution-support executable_adapter --format json

# 3. Inspect the four axes you can combine
uv run bencheval benchmark show terminal-bench
uv run bencheval runtime list

# 4. Dry-run: get the cost / envelope / caveats plan with no model calls
uv run bencheval run --dry-run \
  --benchmark terminal-bench --slice smoke-5 \
  --runtime claude-code --model <model-id>

# 5. Live run (needs provider creds + Docker + Harbor; see production-readiness tiers)
uv run bencheval run \
  --benchmark terminal-bench --slice smoke-5 \
  --runtime claude-code --model <model-id> \
  --output results/evidence/tb.jsonl --artifacts-dir results/raw/tb
```

Next: [Control-plane quickstart](#control-plane-quickstart-four-axes) · [External benchmarks](#external-benchmarks) · [Production readiness tiers](docs/context/production-readiness.md).

## Control-plane quickstart (four axes)

```bash
uv run bencheval benchmark list --execution-support executable_adapter --format json
uv run bencheval runtime list
uv run bencheval run \
  --benchmark terminal-bench \
  --slice smoke-5 \
  --runtime claude-code \
  --model <model-id> \
  --output results/evidence/tb.jsonl \
  --artifacts-dir results/raw/tb
```

Non-executable benchmarks (e.g. CyBench) fail on `run` before subprocess dispatch; use `run --dry-run` to plan slices and see `execution_support` caveats.

## Layout

- `config/selftest/` — selftest lane task contracts (`core-8/`, `core-16/`); legacy `config/tasks/` fallback in registry
- `BENCHEVAL_HOME` — wheel-only bundle root: `config/benchmarks.yaml`, `config/models.yaml`, `config/suites.yaml`, `config/runtimes/`, `config/slices/`, `config/manifests/` (see `scripts/export-config-bundle.sh`); `config/pricing/` stays editable-checkout only unless you extend the export script
- `config/suites.yaml` — suite membership (core-8, core-16, smoke, calibration, stretch)
- `config/` — legacy manifests, pricing YAML, models YAML (no secrets)
- `src/bencheval/` — library: task contract, registry, planner, evidence JSONL, report/export/compare, legacy summary/compare
- `scripts/` — `check-production-v1.sh`, `run-live-pilot-matrix.sh`, `write_preflight.py`, `compare.py`, `extract_summary.py`, `export-config-bundle.sh`, `check-domain-coverage.sh`, `verify-performance.sh`, `preflight_disk.sh`, `verify_auth.sh`, `run_provider_smoke.sh` (see `scripts/README.md`)
- `tests/` — pytest suite
- `results/` — run artifacts (gitignored where noted)
- `docs/` — architecture, roadmap, concept-zero context, external benchmark catalog

## Setup

```bash
uv sync
```

Use `uv sync --extra eval` only when running real Inspect / Harbor evals.

Internal pilot gates and live matrix: [`docs/context/production-v1-pilot.md`](docs/context/production-v1-pilot.md) (`make check-production-v1`).

## Control-plane commands

Public control-plane surface: catalog, plan, run, report, compare, export. (Selftest-only commands live in the [Internal selftest only](#internal-selftest-only-appendix) appendix.)

```bash
# External benchmark catalog (support metadata, not Core scoring)
uv run bencheval benchmark list --format json
uv run bencheval benchmark show exploitgym
uv run bencheval benchmark show DeepSWE

# Dry-run cost/envelope estimate (no network, no model calls)
uv run bencheval run --dry-run --suite smoke --model anthropic/claude-test

# Manifest-driven single lifecycle: one task at a time, append evidence, clean transient staging.
# Works for large public suites (one task id per line); --cleanup always|on-success removes
# BenchEval-owned transient dirs without deleting evidence.
printf '%s\n' terminal-bench/some-task another-task > /tmp/bencheval-native-smoke.txt
uv run bencheval run \
  --manifest /tmp/bencheval-native-smoke.txt \
  --mode single \
  --cleanup always \
  --model <model-id> \
  --output results/evidence/native-smoke.jsonl \
  --artifacts-dir results/raw/native-smoke

# Preflight for live Inspect/Harbor backends (never prints secret values)
uv sync --extra eval
uv run bencheval doctor --backend inspect --model openai/gpt-test --profile E0
uv run bencheval doctor --backend inspect --model openai/gpt-test --profile E1

# Live provider run (requires credentials + eval extra)
uv run bencheval run \
  --task <task-id> \
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

## Internal selftest only (appendix)

> Core-8 / Core-16 and `task audit` are an **internal regression lane** for the control-plane plumbing (see [`docs/context/production-readiness.md`](docs/context/production-readiness.md) Tier 0). They are never weighted into public-benchmark comparisons and are **not** the product surface. Most readers can skip this section.

<details>
<summary>Selftest commands (click to expand)</summary>

```bash
# Lint / validate / audit a selftest task contract
uv run bencheval task validate be-core-c1-small-logic-patch
uv run bencheval task audit be-core-t1-single-structured-call
uv run bencheval task audit core-8
uv run bencheval task audit core-16  # 16 tasks; exits 1 until expansion sign-off

# Offline local/harness smoke (reference path; not a live model call)
uv run bencheval run \
  --task be-core-t1-single-structured-call \
  --model local/harness \
  --output results/evidence/run-001.jsonl \
  --artifacts-dir results/raw/run-001

# Manifest-driven single lifecycle against selftest tasks
printf '%s\n' \
  be-core-t1-single-structured-call \
  be-core-t2-multi-tool-join \
  > /tmp/bencheval-native-smoke.txt
uv run bencheval run \
  --manifest /tmp/bencheval-native-smoke.txt \
  --mode single \
  --cleanup always \
  --model local/harness \
  --output results/evidence/native-smoke.jsonl \
  --artifacts-dir results/raw/native-smoke

# Inspect E0 with mockllm (deterministic reference stand-in; no inspect_ai import or generate() call)
uv run bencheval run \
  --task be-core-t1-single-structured-call \
  --model mockllm/model \
  --backend inspect \
  --output results/evidence/run-mockllm-001.jsonl \
  --artifacts-dir results/raw/run-mockllm-001
```

</details>

## Provider smoke (live, credential-gated)

Bounded Inspect E0 smoke for real providers. Skips models with known preflight blockers (missing credentials, Docker, Inspect dependency). Invalid config and unknown doctor failures exit non-zero.

```bash
uv sync --extra eval
BENCHEVAL_MODELS="openai/gpt-4o anthropic/claude-sonnet" ./scripts/run_provider_smoke.sh
# or: ./scripts/run_provider_smoke.sh openai/gpt-4o anthropic/claude-sonnet
```

Writes `results/evidence/`, `results/raw/`, and `results/reports/` per model. Requires provider env vars; does not print secret values.

## Legacy summary pipeline

Emit one strict summary row (manifest + stamp JSON + header JSON to JSONL):

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

```python
from bencheval import EvidenceRecord, SummaryRow, TaskContract
from bencheval import read_evidence_jsonl, read_summary_jsonl
```

Public exports include legacy summary/compare types and vNext evidence/task-contract types. vNext modules are also available from submodules (`task_registry`, `planner`, `report`, ...) or via the `bencheval` CLI.

## External benchmarks

Candidate third-party suites for Calibration/Stretch adapters: [`docs/context/external-benchmark-catalog.md`](docs/context/external-benchmark-catalog.md).
Machine-readable support metadata lives in [`config/benchmarks.yaml`](config/benchmarks.yaml) and is exposed via `bencheval benchmark list|show`. The catalog intentionally distinguishes:

- `manifest_available` — BenchEval has at least a committed manifest/control-plane slice.
- `cataloged` — recognized as an integration candidate, adapter still pending.
- `adapter_pending` — high-priority known target, no runnable adapter yet.
- `unverified` — requested name or alias with no distinct canonical benchmark source verified yet.

Use manifest-driven single mode for large public suites: `--manifest` reads one
task id per line, `--mode single` runs tasks sequentially, and `--cleanup
always|on-success` removes BenchEval-owned transient directories such as
`agent-workspace`, `harbor-package`, and `materialized-workspace` after each
attempt. Evidence JSONL, candidate artifacts, and verifier logs are preserved.
The current cleanup policy deliberately does not run Docker image pruning;
external adapters must own and document image cleanup before enabling that.

## Development

```bash
uv run pytest -q
uv run ruff check src tests scripts/
uv run ruff format --check src tests scripts/
shellcheck scripts/*.sh && bash -n scripts/*.sh
uv run bencheval task audit core-8
uv run bencheval task audit core-16  # 16 tasks; exits 1 until expansion sign-off (8/16 admitted today)
```

Live Inspect/Harbor proof requires `uv sync --extra eval`, provider credentials, Docker (E1), and Harbor CLI (S4 live). See [`docs/roadmap.md`](docs/roadmap.md) live blockers.

## License

MIT — see [`LICENSE`](LICENSE).
