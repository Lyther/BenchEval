# Scripts

## Control plane / release

- `export-config-bundle.sh` — copy control-plane `config/` tree for `BENCHEVAL_HOME` installs.
- `check-domain-coverage.sh` — full-package Coverage.py gate plus an uninstrumented planner timing assertion.
- `verify-performance.sh` — micro-benchmarks for planner/catalog/compare hot paths.
- `check-production-v1.sh` — Tier 0 gate (`make check-production-v1`); requires the
  `analytics` extra so PyArrow/DuckDB round trips cannot skip.
- `run-live-pilot-matrix.sh` — Phase B live Terminal-Bench runtime matrix; writes
  `results/preflight/` on blockers. BFCL and SWE-Bench remain non-executable.
  Set `BYTELLM_API_KEY` for ByteLLM pilots; the script keeps real auth on the
  host shim and passes only dummy runtime keys into Harbor containers.
  Set `BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM=1` for Anthropic-compatible
  routers that require top-level `system` instead of `messages[].role=system`.
  Set `BENCHEVAL_CLAUDE_CODE_NPM_REGISTRY` when the default npm registry is
  slow from the task container.
  Set `BENCHEVAL_PILOT_CLAUDE_MODEL` / `BENCHEVAL_PILOT_CODEX_MODEL` when
  Anthropic and Responses routers need different model aliases.
  Set `BENCHEVAL_CLAUDE_CODE_ALLOWED_TOOLS` when a router rejects advanced
  Claude Code tool schemas and only basic terminal/edit tools are needed.
- `write_preflight.py` — JSON `preflight_v1` artifact helper (`--runtime` optional for model-only).
- `doctor-pilot.sh` — Phase B wrapper: optional `verify_auth.sh` + `bencheval doctor --profile pilot`.

## Ops / preflight

- `verify_auth.sh` — probe ByteLLM proxy auth or baseline provider credentials.
- `preflight_disk.sh` — disk check for local `results/raw`.
