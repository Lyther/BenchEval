# BenchEval

Version-controlled tracker for LLM benchmark evaluation (Inspect AI and Harbor). Product intent and stack notes live in [`concept-zero.md`](concept-zero.md).

## Layout

- `config/` — manifests, pricing YAML, experiment matrix (no secrets)
- `src/bencheval/` — library: DTOs, strict summary build, JSONL I/O, comparison, pricing
- `scripts/` — `compare.py`, `extract_summary.py`, `preflight_disk.sh`, `verify_auth.sh`, and `scripts/README.md`
- `tests/` — pytest suite
- `results/raw/` — Inspect `.eval` logs (gitignored)
- `results/summary/` — JSONL rollups
- `results/reports/` — comparison output
- `docs/` — architecture and roadmap

## Setup

```bash
uv sync
```

Use `uv sync --extra eval` only when running real Inspect / Harbor evals; offline CLIs and the default test suite do not need that extra.

Copy `.env.example` to `.env` and fill values. Never commit `.env`.

## Quickstart

Emit one strict summary row (manifest + stamp JSON + header JSON → JSONL):

```bash
uv run python scripts/extract_summary.py \
  --eval-log results/raw/run-001.eval \
  --manifest config/manifests/swebench-verified-smoke-10.txt \
  --stamp-json path/to/stamp.json \
  --header-json path/to/header.json \
  --output results/summary/run-001.jsonl
```

Compare two JSONL summary files (Markdown or JSON report):

```bash
uv run python scripts/compare.py \
  --baseline results/summary/baseline.jsonl \
  --current results/summary/current.jsonl \
  --equivalence-note "optional note for cross-lane compares" \
  --format md \
  --output results/reports/delta.md
```

Omit `--output` on `compare.py` to print to stdout.

## Package

Public exports (`from bencheval import …`) match `bencheval.__all__`:

- **Errors:** `BenchEvalError` (base), `ComparisonError`, `EvalLogError`, `ManifestError`, `SummaryValidationError`
- **DTOs:** `ComparisonReport`, `DeltaRow`, `ManifestDigest`, `ModelFamily`, `RunStamp`, `SummaryRow`
- **Manifest:** digest types above; load task lists with `bencheval.manifest.load_manifest` (submodule, not re-exported)
- **Summary:** `StrictSummaryBuilder` — header dict + `RunStamp` + `ManifestDigest` → `SummaryRow`
- **JSONL:** `JsonlSummarySink` (append), `read_summary_jsonl` (strict read)
- **Comparison:** `GuardedComparisonReporter` — §7 deltas with Newcombe–Wilson CI on `resolved_rate`
- **Pricing:** `ModelPrice`, `PricingSheet`, `load_pricing`

## Development

```bash
uv run pytest -q
uv run ruff check src tests scripts/
```

The Makefile `lint` / `test` targets omit `scripts/`; use the commands above for CI parity with this repo.

## License

MIT — see [`LICENSE`](LICENSE).
