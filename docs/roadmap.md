# Execution Roadmap (vNext v0.3)

> **Source:** [`docs/context/concept-hld.md`](context/concept-hld.md) §11.2, §14 + [`docs/architecture.md`](architecture.md) §17
> **Status (2026-06-18):** v0.2 selftest + v0.3 control-plane P1–P6/P5.1/P5.3/P9.2 implemented (**511** tests green). Remaining: P5.2 LiveCodeBench, P7–P8 security/GUI, Phase 0 live spikes — see §Live blockers.
> **Principle:** additive only. Never break the v0.2 `EvidenceRecord` flat contract. Never delete working coverage to reach a new shape.

## Phase 0 — Validation (research spikes, no code)

- [ ] **S0.1** Spike: confirm Harbor CLI install path + `harbor run --dataset terminal-bench@2.0 --agent claude-code` works locally with Docker (credential-gated). Capture exact `--agent` enum, exit codes, result-file layout. *Block:* if Harbor CLI result schema is unstable, freeze TB adapter at adapter-smoke only.
- [ ] **S0.2** Spike: verify `claude-code` and `codex-cli` noninteractive launch + version capture + ephemeral workspace isolation on this host. *Risk:* runtime auth/subscription gating.
- [ ] **S0.3** Spike: confirm additive `EvidenceRecord` v0.3 fields keep all v0.2 JSONL fixtures parseable (run `read_evidence_jsonl` over existing results). *Block:* if any v0.2 row breaks, fix the field defaults before proceeding.
- [ ] **S0.4** Spike: enumerate which of the 80 `config/benchmarks.yaml` entries already have a native/Inspect/Harbor harness vs. which are metadata-only. Produce a runnable-adapter coverage gap report.

> Constraint: no feature code in Phase 0. Output is notes + a coverage-gap table under `docs/context/`.

## Phase 1 — MVP (control-plane walking skeleton)

> Goal: `benchmark list|show`, `runtime list|show`, and `run --dry-run` produce correct four-axis execution plans. **No live execution yet.**

- [x] **P1.1** `runtime_registry.py` + Pydantic `RuntimeProfile` (frozen, extra="forbid") per architecture §7.3. Ship `config/runtimes/claude-code.yaml`, `codex-cli.yaml`, `inspect-api.yaml`, `harbor-agent.yaml`, `native-api.yaml`, `mini-swe-agent.yaml` (best-effort, marked `admission: draft`).
- [x] **P1.2** CLI: `bencheval runtime list`, `bencheval runtime show <id>`, `bencheval model list`, `bencheval model show <id>`, `bencheval adapter list`.
- [x] **P1.3** `SliceManifest` typed wrapper (`slice_manifest.py`) over existing plain-text `config/manifests/*.txt`. Fields: id, benchmark_id, purpose, selection_policy, instances_source, budget, labels.
- [x] **P1.4** CLI: `bencheval benchmark slices <id>` reading typed slice manifests.
- [x] **P1.5** Extend `planner.py` to four-axis plan: (benchmark, slice, model, runtime) → `RunPlan` with harness_kind, adapter_id, instance_count, cost envelope, disk/cache, network policy, cleanup policy, caveats, comparison-validity verdict.
- [x] **P1.6** CLI: `bencheval run --dry-run --benchmark <id> --slice <id> --runtime <id> --model <id>`. Dry-run output per HLD §8.2 (9 fields + comparison-validity line). Keep `--task/--manifest/--backend` for selftest.
- [x] **P1.7** Additive `EvidenceRecord` v0.3 fields (architecture §7.4). Update `tests/test_evidence.py` for new optional fields; prove v0.2 fixtures still parse.
- [x] **P1.8** Reposition Core-8/16 as `selftest`: add `selftest` lane flag to `config/suites.yaml` entries; keep all verifiers/admission green. No task deletion.

> Constraint: no "nice to haves" (no dashboard, no weighted portfolio, no leaderboard).

## Phase 2 — First runtime benchmark adapter (Terminal-Bench via Harbor)

> Goal: Terminal-Bench smoke-5 runs through Harbor on ≥1 CLI runtime and one baseline, producing `EvidenceRecord` v0.3 + markdown report.

- [x] **P2.1** `config/manifests/terminal-bench-smoke-5.txt` (5 fixed instance ids).
- [x] **P2.2** Typed `SliceManifest` for `terminal-bench/smoke-5` + `lite-20`; benchmark contract fields in `config/benchmarks.yaml` for `terminal-bench` (native_harness=harbor, default_adapter, caveats, slices).
- [x] **P2.3** Harbor adapter: `terminal_bench_harbor.py` runs `harbor run --dataset terminal-bench@2.0 --agent <runtime> --model <model>`, parses native result, preserves raw_result/stdout/stderr/verifier logs. Adapter failure policy: preflight aborts; post-preflight writes `EvidenceRecord` with failure label.
- [x] **P2.4** Version capture: benchmark/harness (harbor)/adapter/runtime/model versions recorded on every `EvidenceRecord`.
- [x] **P2.5** Pass adapter admission gates (architecture §13.1) for `terminal-bench-harbor`; flip `adapter_status` to `manifest_available` in YAML.
- [x] **P2.6** CLI: `bencheval run --benchmark terminal-bench --slice smoke-5 --runtime claude-code --model <m> --cleanup always --output <evidence.jsonl>` (live Harbor requires doctor; adapter-smoke via injected runner in tests).

> Blocker: credentials + Docker (live blockers, see §Live blockers). Adapter-smoke with deterministic stand-in is acceptable for P2 gate if live is blocked.

## Phase 3 — Runtime comparison report

> Goal: Claude Code vs Codex CLI on Terminal-Bench smoke-5 produces a normalized comparison with caveat labels.

- [x] **P3.1** `report.py` emits runtime-comparison panel (same benchmark/slice, different runtime) with per-runtime cost/latency/pass/CI + interpretation label `runtime_comparison`.
- [x] **P3.2** `compare.py` / `evidence_compare.py` enforce comparison-validity gates (architecture §13.3): identical benchmark/slice/adapter/harness version; failed attempts reported not dropped; caveats shown.
- [x] **P3.3** Markdown + JSON report output; HTML post-MVP.

## Phase 4 — SWE-family adapter

> Goal: SWE-bench-family smoke-10 materializes instances and stores verifier artifacts, with contamination/legacy caveat.

- [x] **P4.1** `swebench` adapter (native or via `inspect-evals` `eval` extra): materialize one repo instance → patch → run test verifier → `EvidenceRecord` with `native_score`, workspace_diff_path, verifier_log_path.
- [x] **P4.2** SWE-rebench latest-window smoke slice (decontaminated catalog: `swe-rebench` benchmark + `swe-rebench-smoke-10` typed slice; harness `adapter_pending`).
- [x] **P4.3** Contamination/legacy caveat labels on every SWE-bench-Verified row; `contaminated_or_legacy` interpretation label in reports.
- [x] **P4.4** Pass adapter admission gates; flip `swe-bench-verified` to `manifest_available`.

## Phase 5 — Model-only adapter

> Goal: BFCL/LiveCodeBench/BigCodeBench smoke runs through native/API or Inspect path. Cheap model comparison.

- [x] **P5.1** BFCL V4 adapter (model-only, `native-api`/`inspect-api` runtime).
- [ ] **P5.2** LiveCodeBench or BigCodeBench adapter (latest-window / instruct subset).
- [x] **P5.3** Model-comparison report (same benchmark/slice/runtime, different model) with `model_comparison` label (`model_compare.py` + CLI `compare` auto mode).

## Phase 6 — Analytics store

> Goal: DuckDB/Parquet views for cost, latency, pass/fail, runtime failure, historical regression.

- [x] **P6.1** `export.py` Parquet tables: attempts, failures, adapter_metadata, runtime, model, task_versions (extend existing schema with v0.3 fields).
- [x] **P6.2** DuckDB views: `warehouse/views/attempt_scores.sql`, `warehouse/views/runtime_comparison.sql`, `warehouse/views/cost_latency.sql`.
- [x] **P6.3** `bencheval export <evidence.jsonl> --format parquet|duckdb --output warehouse/…` with v0.3 fields.

## Phase 7 — Defensive security adapter

> Goal: CyberSecEval / CyberGym defensive smoke only, explicit safety boundary.

- [ ] **P7.1** CyberSecEval 4 AutoPatchBench/CyberSOC defensive adapter (sandbox, no network, no live targets).
- [ ] **P7.2** CyberGym defensive slice (vulnerability reproduction against **pre-patch** code with sanitizers) — `smoke-10`; `defensive_security_only` label; never exploit deployment.
- [ ] **P7.3** Safety-review gate documented in benchmark contract (`safety_review: dual_use`); CLI refuses `--slice` resolving to offensive tasks outside Stretch without `--allow-stretch`.

## Phase 8 — Offensive-restricted Stretch + GUI (gated)

> Goal: ExploitGym / BountyBench Exploit / OSWorld behind explicit safety review and approval.

- [ ] **P8.1** ExploitGym Stretch adapter (offensive-restricted; explicit safety review + approval gate; never Core-weighted; no live targets). Blocked on S0 confirmation of source URL/license.
- [ ] **P8.2** BountyBench Detect+Patch in normal lanes (P7-equivalent); Exploit tasks Stretch-only.
- [ ] **P8.3** OSWorld GUI adapter (post-MVP; VM snapshot/replay stability required).
- [ ] **P8.4** CyberGym-E2E adapter — **wait** for public task release; registry keeps `reference_only`/`unverified` until then.

## Phase 9 — Selftest maintenance (ongoing, frozen scope)

- [x] **P9.1** Keep Core-8/Core-16 verifiers + admission green as regression for the control plane itself.
- [x] **P9.2** Re-label `config/tasks/core-8` → `config/selftest/core-8` (move, not delete); update `task_registry` paths.
- [ ] **P9.3** Freeze Core-16 expansion; no new selftest tasks unless they test a control-plane codepath.

## Hot files (v0.3)

- `docs/context/concept-hld.md` — product HLD (source of truth)
- `docs/architecture.md` — this companion (decisions)
- `config/benchmarks.yaml` (80 entries), `config/runtimes/*.yaml` (new), `config/manifests/*.txt` + `config/manifests/*.yaml` (typed wrappers)
- `src/bencheval/`: `benchmark_registry.py`, `manifest.py` (+`slice_manifest.py` new), `models.py`, `pricing.py`, `runtime_registry.py` (new), `planner.py`, `doctor.py`, `executor.py`, `backends.py`, `inspect_adapter.py`, `harbor_adapter.py`, `evidence.py`, `report.py`, `compare.py`, `evidence_compare.py`, `export.py`, `cli.py`, `lifecycle.py`, `workspace_staging.py`
- `scripts/run_provider_smoke.sh`, `scripts/verify_auth.sh`
- Tests: extend `test_evidence.py`, `test_planner.py`, `test_cli_task.py`, `test_cli_benchmark.py`; add `test_runtime_registry.py`, `test_slice_manifest.py`, `test_cli_runtime.py`, `test_harbor_adapter.py` (live-gated)

## Live blockers (2026-06-17)

| Gate | Status | Affects |
|------|--------|---------|
| Provider credentials (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, …) | Required | P2–P5 live runs |
| Docker daemon | Required | P2 Harbor / P4 SWE E1 |
| Harbor CLI install + contract stability | Required (S0.1) | P2 Terminal-Bench |
| `claude-code` / `codex-cli` noninteractive + auth | Required (S0.2) | P2 runtime comparison |
| CyberGym-E2E public task release | Pending | P8.4 |
| ExploitGym stable source URL/license | Pending | P8.1 |

Adapter-smoke with deterministic stand-ins is acceptable for admission gates while live blockers hold; reports must label such runs `adapter_smoke`, never `benchmark_native_claim`.

## Checkpoints

- After P1: tag `checkpoint-v03-control-plane-skeleton`
- After P2: tag `checkpoint-v03-first-adapter`
- After P3: tag `checkpoint-v03-runtime-comparison`
- After P4: tag `checkpoint-v03-swe-family`
- Before P7: tag `checkpoint-pre-defensive-security`
- Before P8: tag `checkpoint-pre-stretch-offensive` (safety review record required)

## Definition of Done per phase

- All touched modules pass `ruff check` + `ruff format --check` + `pytest` (affected suites green).
- Every new Pydantic model is `frozen=True, extra="forbid"`.
- Every `EvidenceRecord` write is additive; v0.2 fixtures still parse.
- Every adapter that flips to `manifest_available` passes admission gates §13.1.
- No live-credential claim without a real run; otherwise label `adapter_smoke`.
