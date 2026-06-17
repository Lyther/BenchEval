# Execution Roadmap (vNext)

> **Source:** [`docs/context/concept-zero.md`](context/concept-zero.md) §20 (2026-05-29)
> **Status (2026-05-29):** P0, P3, and P4 complete. Core-8 offline MVP is strong: 8/8 admitted, local harness smoke, Inspect mockllm E0 (no `inspect_ai` required), evidence/report/export/compare, and provider-smoke orchestrator (`scripts/run_provider_smoke.sh`). **283** pytest tests green. Live Inspect E0/E1, Harbor jobs, and real provider evidence remain blocked on credentials, Docker, and Harbor CLI.

## P0 — Scope freeze and task contract

- [x] Accept v0.2 concept-zero as design source (`docs/context/concept-zero.md`)
- [x] Promote root `concept-zero.md` pointer; update `docs/architecture.md` for vNext
- [x] Implement `src/bencheval/task_contract.py` (schema v0.2)
- [x] Implement `src/bencheval/task_registry.py` (load, lint, suites)
- [x] Commit Core-8 task YAMLs under `config/tasks/core-8/`
- [x] Add `config/suites.yaml` (core-8, core-16 placeholder, smoke alias, calibration, stretch)
- [x] CLI: `bencheval task lint`, `bencheval task validate`, `bencheval task audit`
- [x] Core-8 admission artifact: `docs/context/core-8-admission.yaml` (automated gates + human sign-off recorded 2026-05-29)
- [x] Human review: Core-8 human sign-off gate closed for all eight tasks

## P1 — Harness skeleton

- [x] E0 offline single-task runner for T1 + T2 (`local/harness` reference path)
- [x] E1 offline local-harness runner for C1, C2, A1, A2, S1, S4 (not Inspect/Docker)
- [x] Inspect adapter module + `bencheval doctor --backend inspect --profile E0|E1|E2`
- [x] CLI `--backend local|inspect|harbor` on `bencheval run`
- [x] Inspect E0 mockllm path (`mockllm/model`) — deterministic reference stand-in; skips Inspect doctor; no `inspect_ai` import or `generate()` call
- [x] Adapter failure evidence policy (`adapter_error`, `model_output_invalid`; preflight aborts without evidence)
- [ ] E0: live T1 via Inspect adapter with real provider (gated on eval extra + credentials)
- [ ] E1: live C1 via Inspect + Docker (gated on Docker + credentials)
- [x] Capture JSONL `EvidenceRecord` rows from offline and adapter-backed runs
- [x] Wire `bencheval run --task|--suite … --output …` for smoke batches
- [x] Eval extra documented: `uv sync --extra eval`

## P1.5 — Harbor POC

- [x] Harbor packaging/export slice for S4 (`harbor_adapter.py`)
- [x] Harbor revision metadata on evidence when adapter runner is used
- [ ] Live Harbor agent execution via `harbor jobs start`
- [x] Interim decision: keep Harbor **Stretch/Calibration-first** until live jobs land

## P2 — Core-8 Smoke

- [x] All 8 tasks pass admission gates — 8/8 admitted
- [x] CLI: `bencheval report <evidence.jsonl> --output …` with backend/model table
- [x] Provider-smoke orchestrator: `scripts/run_provider_smoke.sh` (doctor per model; skip known blockers only; fail on config/doctor errors)
- [ ] End-to-end runs for ≥3 models without manual intervention (orchestrator ready; blocked on credentials)
- [ ] Markdown evidence report from real provider runs under `results/reports/` (blocked on credentials)
- [x] Task contracts disable internet; admission confirms no LLM judge for primary scoring

## P3 — Verifier hardening

- [x] Reference oracle + negative control for every Core-8 task
- [x] Hidden validation cases (workspace verifiers)
- [x] Replay determinism checks (same artifact → same score)
- [x] Reward-hack review: `docs/context/core-8-reward-hack-review.md`

## P4 — DuckDB/Parquet analytics

- [x] `bencheval export <evidence.jsonl> --format parquet|duckdb --output warehouse/…`
- [x] Parquet tables: attempts, failures, adapter_metadata, task_versions
- [x] DuckDB view: `warehouse/views/attempt_scores.sql`
- [x] Cross-run compare CLI beyond legacy summary JSONL (`bencheval compare <baseline.jsonl> <current.jsonl> --format md|json --output …`)

## P5 — Core-16

- [x] Expansion plan: `docs/context/core-16-expansion-plan.md` (eight task IDs, profiles, verifier strategy)
- [x] Add remaining 8 tasks (two per category per concept-zero §9)
- [x] `core-16` suite lists all 16 tasks (Core-8 + expansion) per HLD
- [x] Automated admission gates pass for all eight expansion tasks (`bencheval task audit core-16`; exit 1 until expansion sign-off)
- [ ] Human sign-off for all eight expansion tasks
- [ ] Stable evidence panels; variant families designed but canonical-only in normal runs

## P6 — Calibration Pack

- [ ] Public micro-slices as appendix-only diagnostics
- [ ] Never import into `weighted_total`
- [ ] Contamination warnings on every calibration row

## P7 — Scale-out

- [ ] Optional Modal/Kubernetes backends without task semantic changes
- [ ] Weekly drift detection cron (after baseline stable)

## Hot files (vNext)

- `docs/context/concept-zero.md` — authoritative HLD
- `docs/context/core-16-expansion-plan.md` — Core-16 task plan (8/8 implemented; sign-off pending)
- `config/tasks/core-8/*.yaml`, `config/tasks/core-16/*.yaml`, `config/suites.yaml`
- `src/bencheval/task_contract.py`, `task_registry.py`, `planner.py`, `evidence.py`, `report.py`, `export.py`, `evidence_compare.py`, `cli.py`, `executor.py`, `doctor.py`, `inspect_adapter.py`, `harbor_adapter.py`
- `scripts/run_provider_smoke.sh` — bounded live provider smoke (credential-gated)
- `tests/test_task_*.py`, `tests/test_planner.py`, `tests/test_evidence.py`, `tests/test_report.py`, `tests/test_export.py`, `tests/test_evidence_compare.py`, `tests/test_inspect_adapter.py`, `tests/test_inspect_harbor.py`, `tests/test_provider_smoke_script.py`, `tests/test_cli_task.py`

## Live blockers (2026-05-29)

| Gate | Status |
|------|--------|
| Provider credentials (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) | Required for live Inspect E0/E1 and P2 multi-model smoke |
| Docker daemon | Required for Inspect E1 / Harbor doctor |
| Harbor CLI (`harbor jobs start` contract) | Not installed on dev host; live runner not wired |

## Legacy tracker (maintained, not expanded)

The 2026-04-15 Inspect/Harbor summary pipeline (`SummaryRow`, `extract_summary.py`, `compare.py`) stays for existing JSONL rollups. Do not prioritize CyBench/Harbor spikes or baseline credential probes ahead of vNext P1 unless explicitly requested.

## Checkpoints

- **After P2:** tag `checkpoint-vnext-core8-smoke`
- **After P3:** tag `checkpoint-vnext-verifiers`
- **Before P6:** tag `checkpoint-pre-calibration`
