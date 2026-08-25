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
| Agents | none admitted; `momo` is a discoverable, non-executable scaffold |
| Providers | `bytellm`, `ollama-cloud` |
| CLI | `list`, `catalog …`, `run <benchmark>/<slice> [--runtime\|--agent] --model … [--provider] [--dry-run\|-y]` |

Runtime XOR admitted agent. Omit both for model-only (GPQA, HLE, BFCL). Unknown ids and scaffold-only agents must fail before subprocess or output reservation.

**Tiers** (definitions: [`production-readiness.md`](context/production-readiness.md)): **Tier-0 executable** = software gate — the control plane compiles, plans, and gates with no live deps. **Tier-1 live-proven** = ≥1 real instance end-to-end via the benchmark's native harness. **Tier-2 Production v1** = adapter admitted + Tier-1 live proof + full checklist. All four benchmarks above are Tier-0 executable and hold Tier-1 in the proof ledger below. No Tier-2 claim.

### Proof ledger

| Benchmark | Software | Live evidence | Tier-2 | Next evidence |
|---|---|---|---|---|
| `terminal-bench` | Tier-0 executable | Tier-1: `run-20260825-173913-754489-4f43e296` (`claude-code` 2.1.235) and `run-20260825-171829-685914-aa08dd1d` (`codex-cli` 0.148.0); both official `reward == 0.0` / `model_wrong_solution`; compare `comparison_valid` | not claimed | benchmark-specific §A–§E ledger |
| `gpqa-diamond` | Tier-0 executable | Tier-1: `run-20260825-160511-036214-304c2cee` (official Inspect log; unique 2 × epochs 4; private proof `sha256:aa19d02b7d1457d0f43d9588b3d08c042e967a981ed8537068412e1797ff0eda`) | not claimed | benchmark-specific §A–§E ledger |
| `hle` | Tier-0 executable | Tier-1: `run-20260824-092017-110245-dbbdf99e`; isolated-cache path additionally verified by `hle-isolated-cache-live-20260825T072129Z` | not claimed | benchmark-specific §A–§E ledger and portable proof bundle |
| `bfcl-v4` | Tier-0 executable | Tier-1: `run-20260824-045622-854659-a46ae44d` (with earlier non-registerable diagnostic lifecycle run) | not claimed | benchmark-specific §A–§E ledger and portable proof bundle |

`results/` and its run registry are machine-local and gitignored. Run IDs above identify operator-host proof; they are not durable publication until the portable-bundle work below is complete.

## Executable roadmap

### R0 — Decisions and source-of-truth reconciliation

- [x] Reconcile the **8 catalog / 4 executable** state and BFCL/HLE Tier-1 status across current documentation.
- [x] Close the v1 cost contract: wall-bounded and cost-estimated; no provider-enforced hard-dollar termination promise.
- [x] Keep MOMO as a discoverable scaffold rather than an admitted agent.
- [x] Select permanent local private-proof retention with no BenchEval deletion/expiry operation; defer bucket/object-store transport.
- [x] Select SWE-bench Verified diagnostic proof first and a separate later promotion decision.
- [x] Keep CyberGym and ExploitGym catalog-only for v1.
- [x] Define the HITL boundary: ordinary probes and provisioning are automated; pause only for a literal device/subscription/CAPTCHA/hardware/admin interaction or a new product decision.

**Exit:** the current architecture contains no unresolved product choice needed for the implementation tracks below.

### R1 — Deterministic correctness debt

- [x] **MOMO scaffold gate:** change the typed admission state to `scaffold`; make planner, CLI, and crafted direct-executor paths reject before output reservation, subprocess, or provider launch. Catalog list/show remains usable.
- [x] **Legacy compare validity:** compute headline/backend rates over the shared eligible intersection, retain excluded rows in details, reject asymmetric/empty eligibility, emit `comparison_valid` plus `contaminated_or_legacy`, and return nonzero when invalid.
- [x] Keep append-time live-run validation: fill-once axes, nondecreasing time, legal transitions, and raw event preservation.
- [x] **Reader and projection:** validate the entire on-disk history on read; expose a last-valid-event projection that carries latest non-null locators without modifying raw events.
- [x] **Registry concurrency:** lock read→validate→append→fsync with an adjacent mode-0600 `fcntl.flock` file.
- [x] Reconcile current docs and narrowly stale proof/substitute records after the behavior changes; add dynamic hygiene checks only where values derive from typed config.

**RED specifications:** `test_agent_scaffold_contracts.py`, `test_legacy_compare_eligibility_contracts.py`, and `test_live_run_operational_view_contracts.py` define the required behavior before implementation.

**Exit:** non-admitted axes cannot launch; comparison headlines cannot be improved by infrastructure rows; copied/corrupt registry history cannot masquerade as valid current state.

### R2 — Immutable portable private proof

- [x] Keep append-time validation of fill-once axes, nondecreasing timestamps, legal transitions, and raw-history preservation as the base event contract.
- [x] Supply the validated last-valid-event operational view consumed by proof export; implementation ownership remains R1.
- [x] Persist an anchored exclusive `run-plan.json` after run-root claim and before every first benchmark launch. Failed launches retain the plan.
- [x] Add `private_proof_v1` in a dedicated `proof_bundle.py`: canonical inventory bytes, small closed artifact roles, size/SHA-256, strict normalized paths, exactly one run ID, and complete file-set equality.
- [x] Export evidence, official results, logs, run plan, normalized history, derived projection, report, and every referenced raw/capture artifact; reject outside-root, missing, skipped, duplicate, nested, symlink, hardlink, device, FIFO, extra, or digest-mismatched content.
- [x] Add `bencheval proof export|verify|import` and `evidence list --current`. Public bundles remain redacted publication derivatives and cannot import as private proof.
- [x] Derive `proof_id` from exact inventory bytes; install atomically under `results/proofs/sha256/<digest>` and append one idempotent non-secret row to `proofs.jsonl`.
- [x] Prove export, source-checkout removal, offline verification/import into a disposable second root, archive traversal rejection, idempotent import, and preservation of a conflicting existing proof.
- [x] Retain finalized proofs permanently. Add no delete, prune, replacement, TTL, or garbage-collection path.
- [x] Classify historical BFCL/HLE material without a captured run plan as `legacy_unverifiable` / `run_plan_missing_legacy`; never reconstruct historical execution state from current config.

**RED specification:** `test_private_proof_bundle_contracts.py` covers portable private-export path completeness. `test_private_proof_v1_contracts.py` covers export, source-checkout-removed verify, import/idempotency/conflict, archive traversal, public-bundle rejection, legacy missing-plan classification, extra/missing/digest/symlink/dir-escape/unknown-classification rejects, and no `runs.jsonl` replay on import.

**Exit:** a known proof digest verifies without the originating checkout; local retention does not depend on a host-absolute path. This proves byte completeness, not creator authenticity or benchmark truth.

### R3 — Tier-1 proof for the current executable set

- [x] Add `terminal-bench/tier1-one` containing only `fix-git`, with typed one-instance budgets and no benchmark-native/statistical claim.
- [x] Parameterize `run-live-pilot-matrix.sh` for `tier1-one` (expected 1) or `smoke-5` (expected 5); reject slice/count mismatch and use the chosen slice consistently.
- [x] On the dev-box, run `tier1-one` through Harbor for `claude-code` (`run-20260825-173913-754489-4f43e296`, agent 2.1.235, private proof `sha256:afe6f655f7c3f4f940c83703a7c2f5231ae9a87fd998803fdf92ed04967b9592`) and `codex-cli` (`run-20260825-171829-685914-aa08dd1d`, agent 0.148.0, private proof `sha256:fca2295d6844e4dda99799527561985885a90b59e01c865082510eaa63d90c06`). Both are official-verifier `model_wrong_solution` (`reward == 0.0`) with qualified `passed` registration.
- [x] Compare only the eligible shared instance with constant benchmark/slice/model/harness axes (`comparison_valid=true`, `pass_rate_delta=0.0`, `contaminated_or_legacy`). Plumbing/axis proof only; not statistical superiority.
- [x] Run GPQA smoke through real Inspect Evals, retain the official eval log, prove the pinned task/package/CSV identity, qualify, register, and export the resulting private proof.

**RED specification:** `test_terminal_bench_tier1_slice_contracts.py` requires the missing typed one-instance slice.

**Dependencies:** the dev-box has previously demonstrated Docker/Harbor and provider access, but re-probe immediately before charged work. Pause only on the HITL conditions in R0.

**Exit:** all four executable benchmarks hold registered Tier-1 proof; no one-instance result is presented as a quality ranking.

### R4 — Benchmark-specific Tier-2 ledgers and retained adapter boundary

- [x] Preserve the directory-fd-anchored I/O hardening in the dormant CyberGym/ExploitGym scaffolds; this is pre-admission safety, not executable lifecycle proof.
- [x] Add `docs/context/tier2/hle.md` and `bfcl-v4.md` with every readiness §A–§E item marked `proven | partial | missing | not-applicable`, exact evidence, proof boundary, remaining action, and portability state.
- [ ] HLE: map the registered CAIS-judged run plus isolated-cache proof; export at the source host when possible. Rerun only if the existing source artifacts cannot form a coherent proof.
- [ ] BFCL: map the registered 5-category official lifecycle. Because retained rows predate the cost-basis fix, report cleanup `skipped`, and lack a run-plan artifact, perform one refreshed supported-model smoke for a clean Tier-2 source artifact unless those gaps are deliberately left partial.
- [ ] Complete portable proof and cleanup evidence before marking either ledger Tier-2.

**Exit:** each Tier-2 claim is justified by its own complete ledger; creating a ledger does not itself advance the tier.

### R5 — SWE-bench Verified diagnostic lifecycle

- [ ] **Uncharged compatibility spike:** Inspect Evals `0.8.0` loads `princeton-nlp/SWE-bench_Verified@c104f840…` and `django__django-11099` without a provider call, but the architecture pin `78f471…` is on `SWE-bench/SWE-bench_Verified` and crashes inspect-evals (`PASS_TO_PASS` already a list). Images remain tag-form, not digest. Resolve the dataset/revision pair before charging.
- [x] **Official-evaluator schema spike:** `swebench==5.0.1` `eval verified` accepted the one-row prediction. Empty patches are skipped (`empty_patch_ids`, no Docker). A non-empty dummy patch wrote both `schema_version: 2` summary JSON and per-instance `logs/run_evaluation/<run_id>/<model>/django__django-11099/report.json` with `resolved: false`. Adapter now passes unique `--run-id` and `--report-dir`.
- [ ] Add `swe-bench-verified-diagnostic-1` for `django__django-11099`; keep smoke-10 and `executable: false` unchanged.
- [ ] Pin the official evaluator, Verified revision/parquet hash, and execution-time platform image digest contract without upgrading the already admitted Inspect dependencies.
- [ ] Implement Inspect Evals + exact Inspect SWE runtime generation, export exactly one standard prediction row, then invoke the official evaluator within the remaining cumulative deadline and one run-owned root.
- [ ] Accept pass only from coherent strict-boolean official per-instance and aggregate reports. Preserve empty-patch/model failure versus infra/ambiguous/error distinctions and retain all dataset/image/generator/runtime/evaluator identities and artifacts.
- [ ] Wire SWE only as diagnostic-capable dispatch. Every row stays diagnostic/contaminated and cannot register `passed`.
- [ ] Run one real dev-box diagnostic instance, export its private proof, and independently review provenance/security. Make catalog promotion a separate explicit decision afterward.

**RED specification:** `test_swebench_official_lifecycle_v2_contracts.py` captures two-phase ordering, official JSONL/report authority, missing-prediction fail-closed, unique `--run-id`/`--report-dir`, default-runner refusal, and exhausted-budget refusal. Substitute-backed sequencing remains diagnostic; the real charged diagnostic is still required.

**Exit:** one real diagnostic proves the official generation→evaluation lifecycle. It does not prove model quality, frontier validity, admission, or Tier-1.

### R6 — Catalog-only and later work

- [x] CyberGym and ExploitGym remain catalog-only/non-executable; retained modules have pre-admission anchored I/O but no v1 lifecycle work.
- [ ] Keep catalog planning rejecting CyberGym, ExploitGym, SWE-bench Pro, and any other pending row before launch after every catalog change.
- [ ] Keep mini-SWE as a possible separately named agent scaffold rather than silently using it under an admitted runtime identity.
- [ ] Defer object/bucket storage, proof signing, dashboards, weighted portfolios, OCI/ORAS, database/service orchestration, and additional benchmark families until a demonstrated requirement earns them.

### Requirement traceability

| Architecture requirements | Roadmap proof |
|---|---|
| AR-01, AR-03, AR-06 official authority/lifecycle/native metrics | R3, R4, R5 |
| AR-02, AR-04 identity and fail-before-charge | R1, R3, R5 |
| AR-05 isolated evidence I/O | R2, R5, catalog-only pre-admission tests |
| AR-07 comparison validity | R1 legacy compare and R3 Terminal-Bench comparison |
| AR-08 budget truth | R0 decision plus evidence/report contracts |
| AR-09 proof-tier separation | proof ledger, R3, R4, R5 |
| AR-10 operator-owned environments | R3/R5 live prerequisites and HITL policy |
| AR-11 dual-use boundary | R6 |
| AR-12, AR-14 portable/permanent proof | R2 |
| AR-13 agent admission | R1 MOMO scaffold gate |
| AR-15 raw history and projection | R1 registry work |

### Hot files

- `README.md`, `docs/architecture.md`, `docs/api/internal-contracts.md`
- `config/benchmarks.yaml`, `config/runtimes/{claude-code,codex-cli}.yaml`, `config/agents/`, `config/providers/`, `config/slices/`, `config/models.yaml`
- `src/bencheval/`: `cli.py`, `benchmark_plan.py`, `control_plane_executor.py`, `doctor.py`, registries, `terminal_bench_harbor.py`, `gpqa_adapter.py`, `hle_adapter.py`, `bfcl_native_adapter.py`, `swebench_adapter.py`, `external_agent_adapter.py`, `evidence.py`, `live_run_manifest.py`, `report.py`, `evidence_compare.py`, `export.py`, `run_bundle.py`, `proof_bundle.py`
- Pilot: `scripts/run-live-pilot-matrix.sh`, `scripts/doctor-pilot.sh`
- Hygiene: `tests/regressions/test_peer_ship_hygiene.py`

### Live prerequisites and true HITL blockers

| Gate | Status |
|------|--------|
| In-repo implementation (R1/R2 and most of R3/R5) | **Not HITL-blocked.** Implement and run deterministic/local proof directly. |
| Provider credentials | Required only for charged Terminal-Bench/GPQA/SWE calls. Probe presence and a redacted health endpoint first; absent/revoked credentials require operator/admin procurement, not a code workaround. |
| Harbor / Docker on dev-box | Required for Terminal-Bench and official SWE evaluation. Probe automatically; ask only if daemon/socket authority requires unavailable administrator action. |
| Runtime authentication | The selected Inspect SWE diagnostic avoids first-party device login. Terminal-Bench runtime auth is probed noninteractively; pause only if the runtime presents device/subscription login, CAPTCHA, or hardware touch. |
| SWE promotion | Explicit later product decision after diagnostic evidence. It does not block implementation or the diagnostic run. |
| Historical BFCL/HLE plans | Historical runs have no pre-launch `run-plan.json`; classify them as legacy/partial. A rerun is required only for a complete new-format proof, not to implement the format. |

No current decision blocker remains. Ordinary missing dependencies, host provisioning, artifact transfer, evidence verification, and credential-presence checks are automatable and must be attempted before reporting a blocker.

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
