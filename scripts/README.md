# Scripts

## Control plane / release

- `export-config-bundle.sh` — copy full control-plane `config/` tree for `BENCHEVAL_HOME` wheel installs.
- `check-domain-coverage.sh` — local pytest-cov gate (paths, path_safety, control_plane_executor, evidence_compare).
- `verify-performance.sh` — micro-benchmarks for planner/catalog/compare hot paths.
- `check-production-v1.sh` — internal pilot CI gate (`make check-production-v1`).
- `run-live-pilot-matrix.sh` — Phase B live TB/BFCL/SWE matrix; writes `results/preflight/` on blockers.
  Set `BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM=1` for Anthropic-compatible
  routers that require top-level `system` instead of `messages[].role=system`.
  Set `BENCHEVAL_CLAUDE_CODE_NPM_REGISTRY` when the default npm registry is
  slow from the task container.
- `write_preflight.py` — JSON `preflight_v1` artifact helper.

## Legacy summary lane (non-primary scoring)

- `extract_summary.py` — legacy `.eval` to strict summary JSONL.
- `compare.py` — legacy summary JSONL cross-run deltas.

## Ops / preflight

- `verify_auth.sh` — probe baseline provider credentials (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MOONSHOT_API_KEY`).
- `preflight_disk.sh` — disk check for local `results/raw` (skipped when `BENCHEVAL_RUNTIME=harbor`).
- `run_provider_smoke.sh` — bounded Inspect E0 provider smoke; runs `bencheval doctor` per model; skips known blockers only; fails on invalid smoke config or unexpected doctor errors.

Baseline lane uses Inspect provider env vars only. Any credential-rotation helper for experimental lanes lives outside this directory and must not touch the baseline result path.
