# Scripts

Planned wrappers (see `concept-zero.md` §4.2 and `docs/architecture.md`):

- `run_eval.sh` — preflight → `inspect eval` → summary extraction
- `extract_summary.py` — `.eval` → JSONL summaries
- `compare.py` — cross-run deltas
- `verify_auth.sh` — probe every baseline provider credential present: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `MOONSHOT_API_KEY` (OpenAI-compatible via `MOONSHOT_BASE_URL`, needed for the Phase 3 Kimi K2.5 row). Must cover all baseline providers before a Phase 3 Kimi run launches — not Phase-1-only.
- `preflight_disk.sh` — when `BENCHEVAL_RUNTIME=local` (default), require ≥100 GiB free on the filesystem hosting `results/raw` (`BENCHEVAL_RESULTS_RAW` overrides the relative path from repo root). When `BENCHEVAL_RUNTIME=harbor`, exits 0 without checking disk.
- `run_provider_smoke.sh` — bounded Inspect E0 provider smoke for Core-8 T1. Runs `bencheval doctor` per model; **skips** only known blockers (missing credentials, Docker unavailable, Inspect dependency unavailable); **fails** on invalid `BENCHEVAL_SMOKE_BACKEND`/`BENCHEVAL_SMOKE_PROFILE` or unexpected doctor errors. Writes `results/evidence/`, `results/raw/`, `results/reports/`. Example: `BENCHEVAL_MODELS="openai/gpt-4o anthropic/claude-sonnet" ./scripts/run_provider_smoke.sh`

Baseline lane uses Inspect provider env vars only (Anthropic, OpenAI, Moonshot). Any credential-rotation helper
for the experimental lane (Phase 4 — Cursor CLI, Claude Code gateway, Codex sign-in) lives outside this directory
and must not touch the baseline result path.

Implemented now: `extract_summary.py`, `compare.py` (legacy summary JSONL), `verify_auth.sh`, `preflight_disk.sh`, `run_provider_smoke.sh` (see bullets above).
