# Production v1 internal pilot

**Scope:** 81 benchmarks cataloged; **3 executable** (`terminal-bench`, `swe-bench-verified`, `bfcl-v4`). Not a public leaderboard.

## Phase A — ship gates (no live deps)

```bash
make check-production-v1
```

Includes: pytest, ruff, shellcheck, `uv lock --check`, executable catalog count = 3, cybench `run` must fail before execute.

## Phase B — live matrix (credentials + Docker)

**Procedure:** [`docs/ops/dev-box-pilot.md`](../ops/dev-box-pilot.md) (prerequisites, proxy, matrix exit codes, `evidence register`).

**Tier meaning:** Tier 1 = at least one real native-harness instance with a complete `EvidenceRecord`; minimum matrix proof = TB `smoke-5` × two Harbor runtimes + compare + BFCL (see runbook). Details: [`production-readiness.md`](production-readiness.md) §Tier 1–2.

**Artifacts:** `results/evidence/`, `reports/`, `bundles/` (default `--redaction private`); `results/preflight/*.json` on blockers (negative evidence, not fake pass).

**Env:** copy `.env.example` → `.env`; pilot knobs (`BENCHEVAL_PILOT_*`, proxy/shim) are documented in `.env.example` and the runbook §4.

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
