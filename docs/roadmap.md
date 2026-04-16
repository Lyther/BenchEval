# Execution Roadmap

> Source: `concept-zero.md` §6 (Phased Plan). This file tracks executable tasks; the concept file keeps the "why".

## Phase 0 — Bootstrap (Spikes + Plumbing)

- [ ] **Spike**: Verify `inspect-evals` CyBench task manifest shape; extract exact 39-task list → `config/manifests/cybench-39.txt` + sha256.
- [ ] **Spike**: Verify Harbor `scale-ai/swe-bench-pro@2` pulls via `inspect-harbor>=0.4.5`.
- [ ] **Spike**: Confirm `inspect_swe` Claude Code / Codex CLI solvers proxy model calls to Inspect providers in the current version [S1].
- [ ] **Spike**: Probe which reasoning knobs each provider family honors (Anthropic, OpenAI, local). Document per-family support matrix before Phase 2.
- [ ] **Spike (Cursor CLI)**: Verify `cursor-agent -p --output-format stream-json` runs headless inside a Harbor **installed-agent** container (a separate path from `inspect-swe`) using Cursor platform auth (`-a/--api-key` or browser flow). Record CLI version, the **supported-model catalog** visible to `-m`, and any `--print` hang / workspace-trust issues. **Experimental lane only — no summary rows written.** (concept-zero OQ 7–8.)
- [ ] Install deps: `uv sync --extra eval`.
- [ ] **Pin exact versions** in `pyproject.toml` after smoke passes; commit `uv.lock`. Architecture doc claims pinning — this task makes it true.
- [x] **Deconflict stale OAuth paths**: remove `ANTHROPIC_OAUTH_TOKEN` from `.env.example`, remove `auth_refresh.sh` from `scripts/README.md`. VETO in architecture.md §10 demands it.
- [ ] Commit manifests: `cybench-39.txt`, `swebench-verified-500.txt`, `swebench-verified-smoke-10.txt`, `cybench-smoke-5.txt`, `swe-bench-pro-public-r2.txt`.
- [ ] Write `src/bencheval/manifest.py`: load manifest file, compute sha256, return list.
- [ ] Write `scripts/verify_auth.sh`: probe every baseline provider credential present in the environment (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `MOONSHOT_API_KEY` via `MOONSHOT_BASE_URL` — OpenAI-compatible) before long runs. **Blocker for Phase 3 Kimi runs**: if Moonshot support is not implemented here, the Phase 3 Kimi K2.5 baseline must not launch.
- [ ] Preflight: fail if `<100 GB` free disk **when the run uses local Docker**; skip for Harbor remote execution.
- [ ] Smoke run: `swebench-verified-smoke-10` + `cybench-smoke-5` on one Anthropic + one OpenAI model.
- [ ] Confirm `.eval` → summary JSONL round-trip parses cleanly.
- [ ] Freeze `config/pricing/2026-04-15.yaml`.

## Phase 1 — Baseline Collection

- [ ] Define extraction rules (see architecture.md §6 "Provenance sources" table): map each required summary field to its source in the `.eval` log, package metadata, or run-wrapper context. **Must land before strict-writer task below, or Phase 1 deadlocks.**
- [ ] Implement `src/bencheval/summary.py` (`extract_summary`): read `.eval` → emit canonical JSONL row per those rules. Refuse to write if required fields missing.
- [ ] Implement `scripts/extract_summary.py` CLI.
- [ ] Populate `config/models.yaml` with current Anthropic + OpenAI snapshots.
- [ ] Populate `config/benchmarks.yaml` with primary suite entries.
- [ ] Populate `config/experiments.yaml` with the first matrix (baseline lane only).
- [ ] Run SWE-bench Verified 500 on baseline API-key models.
- [ ] Run CyBench 39 on the same set.
- [ ] Commit summary rows to `results/summary/`.
- [ ] Implement `scripts/compare.py`: delta report with bootstrap / Wilson CI.
- [ ] Generate first report under `results/reports/`.

## Phase 2 — Reasoning Experiments

- [ ] **Per-family matrix, not one global grid.** Build a separate sweep per model family using only the knobs that family honors (output of the Phase 0 reasoning spike). Example: Anthropic may get `{effort} × {tokens}`; OpenAI may get `{effort}` only. Do not cross-multiply blindly.
- [ ] Hold scaffold + model snapshot constant within each per-family sweep.
- [ ] Never compare settings across families as if the knobs were equivalent; comparisons stay within a family.
- [ ] Report accuracy, wall time, tokens, cost, uncertainty intervals per setting.
- [ ] Document dominated vs Pareto-efficient settings per benchmark **per family**.

## Phase 3 — Harbor Expansion

- [ ] Add `scale-ai/swe-bench-pro@2` (731) to experiment matrix.
- [ ] Add `terminal-bench/terminal-bench-2@1` (89) to experiment matrix.
- [ ] Record Harbor dataset revision in every row.
- [ ] Add CyberGym (1,507) as on-demand, not default.
- [ ] Decide (write up, don't code): pursue private / commercial access?
- [ ] **Kimi K2.5 baseline collection** (Moonshot API, baseline lane): run the primary suite against Kimi K2.5 using `model_family: moonshot`. This is the only §2.4 cross-eval prep that belongs in Phase 3; the Cursor-bearing deltas wait for Phase 4.

## Phase 4 — Experimental Auth Lane + Scaffold Cross-Eval (Gated on Phase 1 stability)

- [ ] Add `auth_lane: experimental_*` namespace in results.
- [ ] Integrate Claude Code `ANTHROPIC_AUTH_TOKEN` + `apiKeyHelper` path [S6].
- [ ] Integrate standalone Codex CLI sign-in path [S7].
- [ ] **Integrate Cursor CLI installed-agent path** (OQ 7–8): Cursor platform auth (`-a/--api-key` / browser flow), pinned `cursor-agent` version, captured supported-model catalog. Cursor is **not** an `inspect-swe` solver.
- [ ] **Scaffold × model cross-evaluation** (concept-zero §2.4): execute the scaffold-delta, Cursor-harness model-delta, and **Composer 2 vs Kimi K2.5 training-stack delta** [S15] axes in this phase. Every Cursor / Composer row writes under the experimental lane; cross-lane comparisons carry an equivalence note.
- [ ] **RL-only delta** stays blocked — no row until Cursor publishes the pre-RL checkpoint or ablation.
- [ ] Require an equivalence note per experimental run before any baseline comparison.
- [ ] Keep credential rotation helper outside baseline result path.

## Phase 5 — Automation

- [ ] `scripts/run_eval.sh`: one command launches a pinned (benchmark, model, config).
- [ ] Weekly cron: re-run last pinned baseline for drift detection.
- [ ] Model-release detector → queue primary suite pending manual confirmation.
- [ ] Quarterly full primary + selected secondary run.
- [ ] CI gate: smoke manifests must pass before a full-run job is accepted.

## Hot Files (Touched First)

- `config/manifests/*.txt` (new)
- `config/benchmarks.yaml`, `config/models.yaml`, `config/experiments.yaml` (currently stubs)
- `config/pricing/2026-04-15.yaml` (new)
- `src/bencheval/manifest.py`, `src/bencheval/summary.py` (new)
- `scripts/run_eval.sh`, `scripts/extract_summary.py`, `scripts/compare.py`, `scripts/verify_auth.sh` (new)
- `.env.example` (baseline: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_BASE_URL`, plus `MOONSHOT_API_KEY` + `MOONSHOT_BASE_URL` for the Phase 3 Kimi row. No OAuth vars.)
- `scripts/README.md` (remove `auth_refresh.sh`; experimental-lane helpers live under a separate namespace when Phase 4 starts)

## Checkpoints

- **After Phase 0**: tag `checkpoint-phase0-smoke-green` once smoke round-trip passes.
- **After Phase 1**: tag `checkpoint-phase1-baseline` after first full SWE-bench Verified + CyBench rows commit.
- **Before Phase 4**: tag `checkpoint-pre-experimental-auth` — Phase 4 is the risky one.

## Sources

[S1]: https://meridianlabs-ai.github.io/inspect_swe/
[S6]: https://code.claude.com/docs/en/llm-gateway
[S7]: https://developers.openai.com/codex/cli
[S15]: https://cursor.com/resources/Composer2.pdf

## Out of Scope (Say No)

- New eval framework. Use Inspect.
- Public leaderboard. Not until hidden-set access exists.
- Mixing subscription auth into baseline rows. Hard no.
- GAIA, LiveCodeBench. Deferred until baseline is stable.
