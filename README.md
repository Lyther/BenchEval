# BenchEval

Private-first, evidence-based evaluation for coding, tool use, agentic coding, and defensive security. Product intent and vNext HLD: [`docs/context/concept-hld.md`](docs/context/concept-hld.md) (v0.3).

**Production v1 (executable):** 81 benchmarks cataloged; **three** have native control-plane adapters: `terminal-bench`, `swe-bench-verified`, `bfcl-v4`. Everything else is `metadata_only` or `manifest_only` until a real adapter and live proof exist. See the tier definitions in [`docs/context/production-readiness.md`](docs/context/production-readiness.md).

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

# 5. Live run (dev-box: provider creds + eval extra; harness owns sandbox — docs/ops/dev-box-pilot.md)
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
- `src/bencheval/` — library: task contract, registry, planner, evidence JSONL, run record/replay, report/export/compare, legacy summary/compare
- `scripts/` — production gates, live pilot matrix, legacy summary scripts, optional external-project recording helpers (see `scripts/README.md`)
- `tests/` — pytest suite
- `results/` — run artifacts (gitignored where noted)
- `docs/` — architecture, roadmap, context specs, ops runbooks

## Setup

```bash
uv sync
```

Use `uv sync --extra eval` only when running real Inspect / Harbor evals.

Internal pilot gates and live matrix: [`docs/context/production-v1-pilot.md`](docs/context/production-v1-pilot.md) (`make check-production-v1`).

## CLI overview

`bencheval` is grouped by concern. Use `--help` on any subcommand; JSON output is available on most discovery/plan commands via `--format json`.

| Group | Commands | Typical use |
| --- | --- | --- |
| **Catalog** | `benchmark`, `runtime`, `model`, `adapter` | List/show benchmarks, runtimes, models, planned adapters |
| **Plan & run** | `run` | `--dry-run` (no network) or live execution → `EvidenceRecord` JSONL |
| **Evidence** | `report`, `compare`, `export`, `export-run`, `evidence register` | Reports, deltas, Parquet/DuckDB, publishable bundles, runs manifest |
| **Run record** | `replay` | Terminal replay of `events.jsonl` + optional evidence binding check |
| **Preflight** | `doctor` | Backend/runtime checks before live runs (never prints secrets) |
| **Selftest** | `task` | Internal Core-8/16 contracts only ([appendix](#internal-selftest-only-appendix)) |

> **CLI ergonomics:** The flat `run` flag surface is large. Structured flag groups, profiles, and shorter entrypoints are **in active refactor** (peer lane); library APIs (`planner`, `replay`, `evidence`) remain stable meanwhile.

BenchEval does **not** ship a separate Docker orchestration plane. Isolation comes from the **benchmark’s official harness/runtime** (Harbor, Inspect sandbox, upstream images). Tier 0 development needs no Docker; Tier 1 live proof is expected on **dev-box-cpu** (or equivalent operator host), not every laptop — see [`docs/ops/dev-box-pilot.md`](docs/ops/dev-box-pilot.md).

## Control-plane commands

Public control-plane surface: catalog, plan, run, report, compare, export, bundles, replay. (Selftest-only commands live in the [Internal selftest only](#internal-selftest-only-appendix) appendix.)

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

# Bundle evidence + report + optional raw tree for handoff (public redaction available)
uv run bencheval export-run \
  --evidence results/evidence/run-001.jsonl \
  --raw-dir results/raw/run-001 \
  --output results/bundles/run-001 \
  --redaction private

# Append a completed live run to the runs manifest JSONL
uv run bencheval evidence register \
  --run-id run-001 \
  --model openai/gpt-test \
  --benchmark terminal-bench \
  --slice smoke-5 \
  --runtime claude-code \
  --evidence results/evidence/run-001.jsonl \
  --report results/reports/run-001.md

# Replay a canonical run record (stdout only; optional evidence cross-check)
uv run bencheval replay results/raw/run-001/events.jsonl
uv run bencheval replay results/raw/run-001/events.jsonl --verify-evidence

# Config-first external runtime run (recommended for external projects)
uv run bencheval run \
  --config config/runs/cybench-kilo-showcase.yaml \
  --dry-run

uv run bencheval run \
  --config config/runs/cybench-kilo-showcase.yaml \
  --run-root /path/to/prepared/benchmark/root
```

## External command runs and run records

BenchEval can run external projects through a structured profile:
`uv run bencheval run --config <yaml>`. The profile owns the benchmark id,
runtime id, model id, command template, stream parser, verification policy, and
artifact layout. This keeps the CLI short while preserving the full four-axis
metadata in evidence.

Any external runner can emit **`bencheval_run_record_v1`** JSONL (`events.jsonl`: header/event/footer, raw audit lane) and bind rows in `EvidenceRecord` JSONL. The control plane exposes this without requiring a Production v1 benchmark adapter:

- **Library:** `bencheval.external_command_adapter` (`ExternalRunConfig`, `run_external_command`) and `bencheval.replay` (`RunRecordWriter`, `load_run_record`, `replay`, `verify_bound_evidence`).
- **CLI:** `bencheval run --config`, `bencheval replay`, `bencheval export-run`.
- **Contract:** [`docs/api/internal-contracts.md`](docs/api/internal-contracts.md) § Replay.

`config/runs/cybench-kilo-showcase.yaml` is an example external-command profile
for a private CyBench/Kilo run. It is **not** a fourth Production v1 adapter and
is **not** weighted into public benchmark comparisons unless the benchmark is
separately admitted with real native evidence.

Optional derived artifacts (MP4, public transcripts) use presentation helpers
or `scripts/render-run-video.py` (`--ass-only` works without OpenCV). Canonical
logs/evidence remain raw and private; redaction belongs only to explicitly
derived public artifacts.

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

Bounded Inspect E0 smoke for real providers. Skips models with known preflight blockers (missing credentials, harness sandbox unavailable, Inspect dependency). Invalid config and unknown doctor failures exit non-zero.

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

Tier 0 (default): `uv sync` + `make check-production-v1` — no credentials, no harness sandbox.

Tier 1 live proof: run on **dev-box** per [`docs/ops/dev-box-pilot.md`](docs/ops/dev-box-pilot.md) (`uv sync --extra eval`, provider credentials, harness CLIs such as Harbor/BFCL where the adapter requires them). BenchEval itself does not add a parallel Docker control plane.

## License

MIT — see [`LICENSE`](LICENSE).
