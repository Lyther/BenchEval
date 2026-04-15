# Scripts

Planned wrappers (see `concept-zero.md` §4.2 and `docs/architecture.md`):

- `run_eval.sh` — preflight → `inspect eval` → summary extraction
- `extract_summary.py` — `.eval` → JSONL summaries
- `compare.py` — cross-run deltas
- `verify_auth.sh` — probe every baseline provider credential present: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `MOONSHOT_API_KEY` (OpenAI-compatible via `MOONSHOT_BASE_URL`, needed for the Phase 3 Kimi K2.5 row). Must cover all baseline providers before a Phase 3 Kimi run launches — not Phase-1-only.

Baseline lane uses Inspect provider env vars only (Anthropic, OpenAI, Moonshot). Any credential-rotation helper
for the experimental lane (Phase 4 — Cursor CLI, Claude Code gateway, Codex sign-in) lives outside this directory
and must not touch the baseline result path.

No executable implementations in the bootstrap scaffold.
