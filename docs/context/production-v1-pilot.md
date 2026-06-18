# Production v1 internal pilot

**Scope:** ~50 benchmarks cataloged; **3 executable** (`terminal-bench`, `swe-bench-verified`, `bfcl-v4`). Not a public leaderboard.

## Phase A — ship gates (no live deps)

```bash
make check-production-v1
```

Includes: pytest, ruff, shellcheck, `uv lock --check`, executable catalog count = 3, cybench `run` must fail before execute.

## Phase B — live matrix (credentials + Docker)

```bash
export BENCHEVAL_PILOT_MODEL='openai/your-model'   # or anthropic/...
./scripts/run-live-pilot-matrix.sh
```

Produces under `results/`:

- `evidence/`, `reports/`, `bundles/` (private redaction default)
- `preflight/*.json` when doctor, Docker, or `mini-extra` blocks a step (negative evidence, not fake pass)

**Terminal-Bench runtime compare:** Only treat `bencheval compare` as **runtime_comparison** when both evidence files share the same `model_id`. Harbor agents may bind models differently; if axes drift, compare exits with dual-axis error.

**Host deps:** `harbor`, Docker, provider env vars; SWE: `mini-extra`; BFCL: `bfcl-eval` package.

## export-run

- Default **`--redaction private`** for internal pilot bundles.
- **`public`** omits raw artifact tree and redacts evidence string fields / `adapter_metadata` secret substrings.

## Answers to sequencing questions

1. **Where to prove live:** Prefer `dev-box-cpu` or VPS with Docker; keep artifacts local under `results/` (gitignored) unless you explicitly publish bundles.
2. **TB compare narrative:** Same `--model` for both Harbor runs; verify `model_id` in JSONL before claiming runtime-only delta.
3. **Commits:** One control-plane PR is fine; keep live `results/` out of git.
4. **Bundles:** `private` default; harden `public` before external share.

## Production readiness tiers

See [`production-readiness.md`](production-readiness.md) and ops runbook [`../ops/dev-box-pilot.md`](../ops/dev-box-pilot.md).

## Register live runs (audit trail, no secrets in git)

```bash
uv run bencheval evidence register \
  --run-id <id> --benchmark terminal-bench --slice smoke-5 \
  --runtime claude-code --model <model-id> \
  --evidence results/evidence/<id>.jsonl \
  --report results/reports/<id>.md \
  --status passed
```

Appends to `results/manifests/runs.jsonl` (gitignored except `results/manifests/README.md`).
