# Scripts

Planned and implemented wrappers:

- `extract_summary.py` — legacy `.eval` to strict summary JSONL.
- `compare.py` — legacy summary JSONL cross-run deltas.
- `verify_auth.sh` — probe baseline provider credentials (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MOONSHOT_API_KEY`).
- `preflight_disk.sh` — disk check for local `results/raw` (skipped when `BENCHEVAL_RUNTIME=harbor`).
- `run_provider_smoke.sh` — bounded Inspect E0 provider smoke; runs `bencheval doctor` per model; skips known blockers only; fails on invalid smoke config or unexpected doctor errors.

Baseline lane uses Inspect provider env vars only. Any credential-rotation helper for experimental lanes lives outside this directory and must not touch the baseline result path.
