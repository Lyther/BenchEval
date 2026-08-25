# Execution Roadmap

> **Operator contract:** [`README.md`](../README.md), [`docs/architecture.md`](architecture.md), [`docs/api/internal-contracts.md`](api/internal-contracts.md).
> **Production bar:** [`production-readiness.md`](context/production-readiness.md) + `make check-production-v1`.
> **Principle:** Prefer official harnesses and evidence-bound claims. A benchmark becomes executable only after its official generation/execution and scoring phases form one identity-bound lifecycle; green software tests never substitute for live proof.

## Current roadmap

Live operator instructions. The historical ledger below is archive-only.

## Current state (2026-08-25)

### Tier-0 executable product surface

```text
benchmark  →  (runtime | agent)?  →  model via provider  →  evidence
```

| Axis | Tier-0 executable ids |
|------|-----------------------|
| Benchmarks | `terminal-bench`, `gpqa-diamond`, `hle`, `bfcl-v4` |
| Runtimes | `claude-code`, `codex-cli` |
| Agents | `momo` |
| Providers | `bytellm`, `ollama-cloud` |
| CLI | `list`, `catalog …`, `run <benchmark>/<slice> [--runtime\|--agent] --model … [--provider] [--dry-run\|-y]` |

Runtime XOR agent. Omit both for model-only (GPQA, HLE, BFCL). Unknown ids fail before subprocess.

**Tiers** (definitions: [`production-readiness.md`](context/production-readiness.md)): **Tier-0 executable** = software gate — the control plane compiles, plans, and gates with no live deps. **Tier-1 live-proven** = ≥1 real instance end-to-end via the benchmark's native harness. **Tier-2 Production v1** = adapter admitted + Tier-1 live proof + full checklist. All four benchmarks above are Tier-0 executable; `bfcl-v4` and `hle` also hold Tier-1 in the proof ledger below; `terminal-bench` and `gpqa-diamond` do not.

### Proof ledger

| Benchmark | Software | Live evidence | Tier-2 | Next evidence |
|---|---|---|---|---|
| `terminal-bench` | Tier-0 executable | not registered on the current proof ledger | not claimed | clean native `fix-git` attempt for both admitted runtimes, then shared-axis comparison |
| `gpqa-diamond` | Tier-0 executable | not registered | not claimed | real Inspect smoke bound to official eval log and captured package/dataset identity |
| `hle` | Tier-0 executable | Tier-1: `run-20260824-092017-110245-dbbdf99e`; isolated-cache path additionally verified by `hle-isolated-cache-live-20260825T072129Z` | not claimed | benchmark-specific §A–§E ledger and portable proof bundle |
| `bfcl-v4` | Tier-0 executable | Tier-1: `run-20260824-045622-854659-a46ae44d` (with earlier non-registerable diagnostic lifecycle run) | not claimed | benchmark-specific §A–§E ledger and portable proof bundle |

`results/` and its run registry are machine-local and gitignored. Run IDs above identify operator-host proof; they are not durable publication until the portable-bundle work below is complete.

## Executable roadmap

### R0 — Source-of-truth reconciliation

- [x] Reconcile the **8 catalog / 4 executable** state and BFCL/HLE Tier-1 status across architecture, readiness, runtime-invocation, and manifest-registry docs.
- [x] Assign every `src/bencheval/*.py` production module to one architecture component.
- [x] Replace universal hard-dollar language with the implemented wall-bounded / cost-estimated contract.
- [x] Record the official SWE-bench, CyberGym, and ExploitGym lifecycle research and the product decisions that precede implementation.
- [ ] Add a compact dynamic documentation-hygiene test only where it can derive facts from typed catalog data; do not duplicate whole prose sections in tests.

**Exit:** a new operator can distinguish Tier-0, Tier-1, Tier-2, diagnostic adapters, decision gates, and host prerequisites without contradictory instructions.

### R1 — Finish proof for the current executable set

- [ ] **Terminal-Bench Tier-1:** on the dev-box, run `fix-git` through Harbor for `claude-code` and `codex-cli`; require a clean harness run, native verifier result, pinned container `agent_info.version`, complete artifacts, and qualified registration. Wrong solutions remain valid attempts; infrastructure failures do not.
- [ ] **Terminal-Bench comparison:** compare only the eligible shared-instance intersection with identical benchmark/slice/model/harness axes; retain invalid/failed attempts in the report.
- [ ] **GPQA Tier-1:** run the typed smoke through real Inspect Evals, retain the official eval log, prove the pinned task/package/CSV identity, qualify, and register.
- [ ] **HLE Tier-2 ledger:** map each readiness §A–§E item to the registered run, isolated-cache proof, cleanup replay, typed slice, and bundle evidence; leave unchecked items explicit.
- [ ] **BFCL Tier-2 ledger:** map each readiness §A–§E item to the registered lifecycle, official score files, data/package pins, cleanup replay, typed slice, and bundle evidence.

**Dependencies:** provider credentials for live model calls; Docker/Harbor and noninteractive runtime auth for Terminal-Bench. These are operator-host prerequisites, not reasons to add a BenchEval Docker service.

**Exit:** all four executables have registered Tier-1 proof; any Tier-2 claim has a benchmark-specific complete ledger rather than a global checklist inference.

### R2 — Portable registered evidence

- [x] Enforce append-time validation of the architecture §18.3 event contract: fill-once identity axes, nondecreasing timestamps, explicit forward/same-status transitions, and raw history preservation.
- [ ] Expose a last-valid-event operational-view API; the current reader still returns raw append order and does not derive current state.
- [ ] Define a versioned private bundle inventory containing evidence, official results, logs, run configuration, and every referenced artifact.
- [ ] Rewrite retained references to bundle-relative paths and reject missing, duplicate, nested-bundle, symlink, or digest-mismatched entries.
- [ ] Compute an integrity digest for the inventory and add a non-secret portable index record; retain `runs.jsonl` as the machine-local operational registry.
- [ ] Prove export on one host and offline verification/import on a disposable second root; public redacted bundles remain publication derivatives, not the private proof source.

**Exit:** loss of the originating checkout does not invalidate a registered proof, and no private/secret artifact is accidentally treated as public.

### R3 — SWE-bench Verified diagnostic redesign

- [ ] Pin supported mini-SWE-agent and official SWE-bench evaluator revisions plus the Verified dataset revision.
- [ ] Replace the single-instance helper/local-verdict path with batch prediction generation for exact typed slice IDs.
- [ ] Feed the retained prediction JSONL to the official evaluator within one cumulative deadline.
- [ ] Accept only `report.json[requested_instance]["resolved"]`; reject local `verifier.json`/`result.json`, wrong-instance, duplicate, missing, and non-boolean reports.
- [ ] Capture generator/evaluator/dataset/image identities and prediction/report digests; preserve contamination/quality caveats.
- [ ] Run one real diagnostic smoke on the dev-box. Keep `executable: false` until the operator reviews that evidence and deliberately promotes the row.

**Exit:** a diagnostic run proves the official generation→evaluation lifecycle. It is not a frontier-quality claim and does not automatically admit the benchmark.

### R4 — Pending adapter integrity and catalog-only closure

- [x] Implement the existing RED contract that makes CyberGym/ExploitGym BenchEval-owned log writes directory-fd anchored and fails closed on post-launch swaps. This is pre-admission filesystem work only.
- [x] **Decision:** keep CyberGym and ExploitGym catalog-only and non-executable for v1.
- [x] Remove their official lifecycle, metric-selection, and live-run work from the v1 execution queue; retained modules are non-authoritative research scaffolding.
- [ ] Keep catalog planning rejecting both rows before launch after any later scaffolding change.

**Exit:** both rows remain non-executable, no official PoC/exploit lifecycle is part of v1, and retained scaffolding contains no known unsafe BenchEval-owned pathname writes.

### R5 — Cost semantics decision

- [ ] **Decision:** is provider-enforced dollar termination required for v1?
- [ ] If **no**, keep `max_cost_usd` explicitly estimated where metering is unavailable and preserve `cost_basis=unmeasured_*` in evidence/reports.
- [ ] If **yes**, select one provider/router with measured incremental spend plus a termination API, design charged-run reservation/reconciliation semantics, and prove over-budget termination live before claiming a hard cap.

**Exit:** documentation, plan caveats, evidence, reports, and readiness use one truthful cost contract.

### R6 — Later research candidates

- [ ] Select the next benchmark family only after R1 and the R3 diagnostic evidence are reviewed. Current recommendation: finish SWE-bench Verified lifecycle integration before adding another code-evaluation family.
- [ ] Keep SWE-bench Pro, LiveCodeBench/BigCodeBench, SWE-rebench, tool-use/τ-bench, GUI/OSWorld, and broader security benchmarks as research candidates until each has a pinned source, official scorer, typed slice, operational capacity estimate, and product role.
- [ ] Keep dashboard and user-defined weighted portfolios deferred; JSONL plus report/export remains the right-sized interface.

### Requirement traceability

| Architecture requirements | Roadmap proof |
|---|---|
| AR-01, AR-03, AR-06 official authority/lifecycle/native metrics | R1, R3, R4 |
| AR-02, AR-04 identity and fail-before-charge | R1, R3, R4 |
| AR-05 isolated evidence I/O | R2, R4 |
| AR-07 comparison validity | R1 Terminal-Bench comparison |
| AR-08 budget truth | R5 |
| AR-09 proof-tier separation | proof ledger and R1 Tier-2 ledgers |
| AR-10 operator-owned environments | every live exit criterion and blocker table |
| AR-11 dual-use boundary | R4 |
| AR-12 portable evidence | R2 |

### Hot files

- `README.md`, `docs/architecture.md`, `docs/api/internal-contracts.md`
- `config/benchmarks.yaml`, `config/runtimes/{claude-code,codex-cli}.yaml`, `config/agents/`, `config/providers/`, `config/slices/`, `config/models.yaml`
- `src/bencheval/`: `cli.py`, `benchmark_plan.py`, `control_plane_executor.py`, `doctor.py`, registries, `terminal_bench_harbor.py`, `gpqa_adapter.py`, `hle_adapter.py`, `external_agent_adapter.py`, `evidence.py`, `report.py`, `evidence_compare.py`, `export.py` (the SWE module is diagnostic and non-executable; BFCL is executable)
- Pilot: `scripts/run-live-pilot-matrix.sh`, `scripts/doctor-pilot.sh`
- Hygiene: `tests/regressions/test_peer_ship_hygiene.py`

### Live and decision blockers

| Gate | Status |
|------|--------|
| Provider credentials | Required for Terminal-Bench/GPQA live calls; probe the dev-box before calling this blocked. |
| Harbor / Docker on **dev-box** | Required for the Terminal-Bench native lane — not a BenchEval Docker plane. |
| `claude-code` / `codex-cli` noninteractive auth | Required for the Terminal-Bench runtime matrix. |
| Next benchmark selection | User decision; recommendation is the SWE-bench Verified diagnostic lifecycle first. |
| Hard dollar enforcement | User decision; current implementation is wall-bounded and cost-estimated where provider metering is absent. |

---

## Historical ledger (do not execute)

> Archive of v0.3 phase checkboxes. Names deleted modules/commands (`planner.py`, `inspect-api`, `harbor-agent`, `run --config`, Core selftest). **Not** operator instructions.

<details>
<summary>P0–P9 historical milestones (click to expand)</summary>

### Phase 0 — Validation (research spikes)

- [ ] **S0.1** Harbor CLI spike for Terminal-Bench.
- [ ] **S0.2** `claude-code` / `codex-cli` noninteractive + version capture.
- [ ] **S0.3** EvidenceRecord v0.3 additive parse of v0.2 fixtures.
- [x] **S0.4** Product catalog expanded to **8** catalog rows (later demoted to **3** Tier-0 executables: TB / GPQA / HLE; SWE/BFCL wait on official evaluate); ops manuals under `docs/ops/benchmarks/`.

### Phase 1 — MVP skeleton (historical CLI shapes)

- [x] **P1.1** Runtime registry + profiles (admitted set later pruned to `claude-code` / `codex-cli`).
- [x] **P1.2–P1.6** Catalog/list/show + dry-run planning (commands since collapsed into `catalog` / `run --dry-run`).
- [x] **P1.7** Additive `EvidenceRecord` v0.3 fields.
- [x] **P1.8–P1.9** Selftest / external-command lanes (since removed from product CLI).

### Phase 2–6 — Adapters and warehouse

- [x] **P2** Terminal-Bench Harbor adapter + smoke slice.
- [x] **P3** Runtime comparison report / compare gates.
- [x] **P4.1/P4.3/P4.4** SWE-bench Verified adapter + contamination caveats (SWE-rebench slice later removed).
- [x] **P5.1/P5.3** BFCL generation adapter + model compare (evaluate not wired).
- [ ] **P5.2** LiveCodeBench / BigCodeBench (not admitted).
- [x] **P6** Parquet/DuckDB export.

### Phase 7–9 — Deferred / removed

- [ ] **P7–P8** Defensive / offensive Stretch adapters (research only).
- [x] **P9** Core-8/16 selftest lane (removed from product surface).

</details>
