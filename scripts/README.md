# Scripts

## Control plane / release

- `export-config-bundle.sh` — copy full control-plane `config/` tree for `BENCHEVAL_HOME` wheel installs.
- `check-domain-coverage.sh` — local pytest-cov gate (paths, path_safety, control_plane_executor, evidence_compare).
- `verify-performance.sh` — micro-benchmarks for planner/catalog/compare hot paths.
- `check-production-v1.sh` — internal pilot CI gate (`make check-production-v1`).
- `run-live-pilot-matrix.sh` — Phase B live TB/BFCL/SWE matrix; writes `results/preflight/` on blockers.
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

## External command profiles and run records

General APIs: `bencheval run --config`, `bencheval replay`, `bencheval.external_command_adapter`, `bencheval.replay.RunRecordWriter`, `bencheval.presentation` — see [`docs/api/internal-contracts.md`](../docs/api/internal-contracts.md).

- `external-command-run.sh` — generic wrapper for `bencheval run --config <profile.yaml>`.
- `momo-cybench-live.sh` — compatibility wrapper that delegates to `python -m bencheval.momo_cybench` (its default `--config` is the legacy `config/runs/cybench-kilo-showcase.yaml`). New usage should prefer `external-command-run.sh --config config/runs/momo-cybench.yaml` — the **primary/active** CyBench external-command profile (MOMO solver / Claude Code mixed-model runtime; see [`docs/ops/momo-cybench.md`](../docs/ops/momo-cybench.md)). `config/runs/cybench-kilo-showcase.yaml` is the **legacy demo** (Kilo) profile.
- `render-run-video.py` — optional **derived** MP4/ASS from any compatible `events.jsonl` (OpenCV for MP4; `--ass-only` without OpenCV).
- `render-momo-video.py` — compatibility wrapper for `render-run-video.py`.
- `write_preflight.py` — JSON `preflight_v1` artifact helper.
- `doctor-pilot.sh` — Phase B wrapper: `verify_auth.sh` (optional) + `bencheval doctor --profile pilot`
  runs `verify_auth.sh`, then `bencheval doctor`. See `docs/ops/dev-box-pilot.md`.

## Legacy summary lane (non-primary scoring)

- `extract_summary.py` — legacy `.eval` to strict summary JSONL.
- `compare.py` — legacy summary JSONL cross-run deltas.

## Ops / preflight

- `verify_auth.sh` — probe ByteLLM proxy auth (`BYTELLM_API_KEY` /
  `BYTELLM_PROXY_API_KEY`) or baseline provider credentials
  (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MOONSHOT_API_KEY`).
- `preflight_disk.sh` — disk check for local `results/raw` (skipped when `BENCHEVAL_RUNTIME=harbor`).
- `run_provider_smoke.sh` — bounded Inspect E0 provider smoke; runs `bencheval doctor` per model; skips known blockers only; fails on invalid smoke config or unexpected doctor errors.

Baseline lane uses Inspect provider env vars only. Any credential-rotation helper for experimental lanes lives outside this directory and must not touch the baseline result path.
