# Execution Roadmap

> **Status:** ACCEPTED current control-plane/UI work; PROPOSED benchmark-exposure program is the current product priority.
> **Last updated:** 2026-09-03.
> **Source concept:** [`docs/context/concept-zero.md`](context/concept-zero.md).
> **Operator contract:** [`README.md`](../README.md), [`docs/architecture.md`](architecture.md), [`docs/api/internal-contracts.md`](api/internal-contracts.md).
> **Production bar:** [`production-readiness.md`](context/production-readiness.md) + `make check-production-v1`.
> **Principle:** Prefer official harnesses and evidence-bound claims. A benchmark becomes executable only after its official generation/execution and scoring phases form one identity-bound lifecycle; green software tests never substitute for live proof.
> **Implemented UI extension:** [`docs/prototypes/frontend-v1.md`](prototypes/frontend-v1.md) and architecture §20–§21. The CLI remains stable automation; the optional console is loopback-only.
> **Exposure principle:** Preserve native scores and official runners. Measure benchmark-specific dependence under declared verifier/access/freshness conditions; never infer a clean model, cheating, or a universal decontaminated score.

## Current roadmap

Live operator instructions. The historical ledger below is archive-only.

## Current state (2026-09-03)

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
| `terminal-bench` | Tier-0 executable | Tier-1: `run-20260825-173913-754489-4f43e296` (`claude-code` 2.1.235, proof `sha256:afe6f655…7b9592`) and `run-20260825-171829-685914-aa08dd1d` (`codex-cli` 0.148.0, proof `sha256:fca2295d…d90c06`); both official `reward == 0.0` / `model_wrong_solution`. Cleanup replay: `run-20260826-104126-417176-facd93a7` (proof `sha256:cd681305…e29c7`, `cleanup_result=success`, `runtime_launch_failure`) | not claimed | no superiority claim |
| `gpqa-diamond` | Tier-0 executable | Tier-1: `run-20260825-160511-036214-304c2cee` (proof `sha256:aa19d02b…ff0eda`) plus post-retention refresh `run-20260826-082238-670967-54af8e96` (proof `sha256:90978d9e…1c032`) and cleanup replay `run-20260826-103433-678152-7ace1b73` (proof `sha256:a8f17d90…da2f8`, `cleanup_result=success`) | not claimed | no Tier-2 claim |
| `hle` | Tier-0 executable | Tier-1: `run-20260824-092017-110245-dbbdf99e`; isolated-cache `hle-isolated-cache-live-20260825T072129Z`. Post-fix identity-bound smoke `run-20260826-135512-189732-203685b9` (proof `sha256:4be3b7cd…f4b62b`, official 0/2, `cleanup_result=success`). Historical `sha256:b3260e8b…601b77` predates ambient-cache removal | not claimed | no Tier-2 claim |
| `bfcl-v4` | Tier-0 executable | Tier-1: `run-20260824-045622-854659-a46ae44d`; refresh `run-20260826-083403-019994-e449daac` (proof `sha256:8323f916…0c38bc`, official 1/5, run-plan present) | not claimed | cleanup replay `not-applicable` (`results/`/`scores/` are official evidence, not named transients) |

`results/` and its run registry are machine-local and gitignored. Run IDs above identify operator-host proof; they are not durable publication until the portable-bundle work below is complete.

### Current product priority

The current control plane, private proof, and local console are sufficient to start the product's differentiating exposure work. Execute the new `X0–X5` program after the completed `R` tracks. `U3`/`U4` console hardening remains valid but is not a dependency for CLI-first exposure studies and is not the current priority. BFCL Live and tool-order identities remain diagnostic and do not change the **8 catalog / 4 executable** current-state claim until their own roadmap step explicitly adds demoted catalog rows.

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
- [x] Add equivalent Terminal-Bench and GPQA ledgers. A comparison-validity item is `not-applicable` when no superiority claim is made; do not manufacture a second run merely to fill a checklist.
- [x] **GPQA scored-byte retention:** while the official Inspect log descriptor is pinned, copy exactly those bytes to an owned direct-child artifact, verify the write, stamp SHA-256, and make evidence reference the retained copy. Reject symlink/hardlink/path swaps. Live refresh `run-20260826-082238-670967-54af8e96` exported as `sha256:90978d9e161419aba7ca9c48ceedabc1a009403a7e36deeee861b22a7c21c032`.
- [x] **Legacy private bundle integrity:** private `run_bundle_v1` fails closed with no partial destination when an evidence-referenced artifact cannot be copied exactly, including a path below a skipped symlink ancestor. Do not redesign the legacy format or change public export.
- [x] HLE: post-fix identity-bound smoke `run-20260826-135512-189732-203685b9` with official CAIS judge, `run-plan.json`, `cleanup_result=success`, and imported proof `sha256:4be3b7cdfb9f06b5eef96929dface503ea68cdbd5b3652126fdaf939e9f4b62b`. Ambient-copy fallback is removed. Historical `sha256:b3260e8b…601b77` stays as a structural-only object. Aug 24 material without a run plan stays `legacy_unverifiable`.
- [x] BFCL: refreshed supported-model smoke `run-20260826-083403-019994-e449daac` with official scores, cost basis, and `run-plan.json` (proof `sha256:8323f916…0c38bc`). Cleanup is still `skipped`.
- [x] Complete cleanup-replay evidence before marking any ledger Tier-2. HLE, GPQA (`sha256:a8f17d90…da2f8`), and Terminal-Bench (`sha256:cd681305…e29c7`) have imported `cleanup_result=success` proofs. BFCL cleanup replay is `not-applicable`: generate `results/` and official `scores/` are retained evidence, not named transients (`TRANSIENT_ARTIFACT_DIR_NAMES` excludes them). No ledger is Tier-2.

**Exit:** each Tier-2 claim is justified by its own complete ledger; creating a ledger does not itself advance the tier.

### R5 — SWE-bench Verified diagnostic lifecycle

- [x] **Uncharged compatibility spike:** verify the official `SWE-bench/SWE-bench_Verified@78f471bf…` parquet (`030cfd…`) and select `django__django-11099`; prove locked Inspect Evals `0.8.0` task version 3 loads a run-owned one-row HF-style directory when only the two list fields are canonically JSON encoded and accepts a digest-bound image template. Both phases derive from this one official source snapshot.
- [x] **Official-evaluator schema spike:** `swebench==5.0.1` `eval verified` accepted the one-row prediction. Empty patches are skipped (`empty_patch_ids`, no Docker). A non-empty dummy patch wrote both `schema_version: 2` summary JSON and per-instance `logs/run_evaluation/<run_id>/<model>/django__django-11099/report.json` with `resolved: false`. Adapter now passes unique `--run-id` and `--report-dir`.
- [x] Add `swe-bench-verified-diagnostic-1` for `django__django-11099`; keep smoke-10 and `executable: false` unchanged.
- [x] Add immutable SWE identity (`SWE-bench/SWE-bench_Verified`, revision `78f471bf655a3137b2e8a75af1501690ec009ec3`, parquet SHA-256 `030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25`) and exact `swebench==5.0.1` in a separate `swe` dependency group. Do not upgrade admitted Inspect dependencies.
- [x] Materialize the source row and two deterministic run-owned representations: Inspect-compatible local HF directory and official-evaluator local row. Record transformations/digests and bind the execution-time platform image digest for Inspect generation. CLI injects the real process runner; `process_runner is None` still fail-closes.
- [x] Implement Inspect Evals + exact Inspect SWE runtime generation command, validate exactly one standard prediction row (`instance_id`, `model_name_or_path`, `model_patch`), then invoke the official evaluator under one monotonic cumulative deadline and run-owned root. The default process runner stays explicitly disabled.
- [x] Accept pass only from a coherent pair: official per-instance boolean `resolved` plus a present schema-v2 aggregate. An executed `report.json` without that summary fail-closes. Preserve empty-patch/model failure versus infra/ambiguous/error distinctions.
- [x] Wire SWE only as diagnostic-capable dispatch. Every row stays diagnostic/contaminated and cannot register `passed`.
- [x] Real dev-box diagnostic `run-20260826-095222-202465-019ab2b0` (`codex-cli` / `kimi-k2.7-code` / ByteLLM): Inspect generation exported `predictions.jsonl`, official `swebench==5.0.1` ran, schema-v2 `error_ids` / patch-apply failure, fail-closed `runtime_output_unparseable`. Retained prediction+summary proof `sha256:fcc766f5932607c5250571cdfdf6603e62a8bb19a995a05f81edc561939235b5` (registered `completed`, never `passed`). That proof is `provisional:swe-bench-verified/public`, used Hub alias `swebench eval verified`, has no per-instance `report.json`, and `cleanup_result=skipped`. Catalog stays non-executable; no auto-promotion.
- [x] Identity-bound official-eval diagnostic `run-20260826-141431-679309-31a57785` / `sha256:5f7f79ce44eb8c00d7ee826914e8d4591206de2d3b876a2524ccad508e373e52`: `swebench eval` received the run-owned official-dataset path, stamped `swe-bench-verified@78f471bf655a3137+data-030cfd7f2a704c4c`, retained official/Inspect rows, transformation manifest, and the bound Inspect `.eval`. `runtime_version=0.148.0` from the sandbox Codex binary. Schema-v2 `error_ids` so no executed per-instance `report.json`. `cleanup_result=skipped`. Registered `completed` never `passed`. Historical `sha256:1e6c0d3c…`, `sha256:5a1e24f3…`, and `sha256:fcc766f5…` remain in the store. Catalog stays `executable: false`.

**RED specifications:** `test_swebench_official_lifecycle_v2_contracts.py` preserves the existing two-phase and official-authority boundary. `test_swebench_diagnostic_v3_contracts.py` adds the immutable snapshot/dependency, diagnostic slice/dispatch, explicit generation inputs, strict prediction, aggregate-coherence, and monotonic-deadline contracts. Substitute-backed sequencing remains diagnostic; the real charged diagnostic is still required.

**Exit:** one real diagnostic proves the official generation→evaluation lifecycle. It does not prove model quality, frontier validity, admission, or Tier-1.

### R6 — Catalog-only and later work

- [x] CyberGym and ExploitGym remain catalog-only/non-executable; retained modules have pre-admission anchored I/O but no v1 lifecycle work.
- [x] Catalog planning rejects CyberGym, ExploitGym, SWE-bench Pro, and other pending rows before launch; keep the regression gate when the catalog changes.
- [x] **Not scheduled for v1:** mini-SWE may return only as a separately named agent scaffold; never run it under an admitted runtime identity.
- [x] **Still not scheduled:** object/bucket storage, proof signing, weighted portfolios, OCI/ORAS, database/service orchestration, additional benchmark families, and proof deletion/TTL/garbage collection. The earlier dashboard deferral is superseded by the 2026-09-01 local operator-console decision; remote/multi-user service scope remains excluded.

### R7 — One-batch assignment plan

The remaining in-repository development is intentionally split by ownership so the three packets can run concurrently without editing the same production module:

1. **Peer A — proof-integrity debt:** implement the GPQA exact-byte retention contract in `gpqa_adapter.py` and the narrow private legacy-bundle fail-closed contract in `run_bundle.py`; preserve public export and `private_proof_v1`.
2. **Peer B — SWE diagnostic:** own `swebench_adapter.py`, SWE identity/slice, executor diagnostic dispatch, the exact `swe` dependency group/lock, and the SWE ops docs. Keep `executable: false`; do not run a charged model until the uncharged materialization and evaluator checks pass.
3. **Peer C — proof operations:** transfer and verify existing Terminal-Bench and GPQA proofs, create their Tier-2 ledgers, export or refresh HLE/BFCL proof as the existing ledgers require, and run the real SWE diagnostic only after Peer B lands. Never advance a ledger from narration or test results.

Merge order: Peer A and Peer B are independent; Peer C may transfer existing proofs immediately but must rebase before final ledger decisions and waits for the relevant adapter fix before GPQA/SWE reruns. Each software packet receives an independent `/qa-review`; live proof remains a separate evidence stream.

## Benchmark exposure roadmap (PROPOSED; current priority)

**Objective:** add the smallest evidence-bound capability that can show whether a canonical BFCL score transfers to fresher or representation-equivalent data, without changing official runtime/scorer behavior or claiming to prove training contamination.

**Program exit gate:** exact pinned BFCL Live and one balanced tool-order study have real official-score/private-proof evidence; reports validate their declared populations and access/verifier axes; smoke is labelled plumbing-only; no clean, cheating, novelty, direct-contamination, or universal adjusted-score claim is emitted. Completion of this program does not admit either diagnostic benchmark, advance Tier-2, or complete U3/U4.

### X0 — Decision closure and executable spikes

**Objective:** falsify the two BFCL integration assumptions and close the access/statistics contract before production modules or charged populations are built.

**Exit gate:** exact wheel/Live identity, official category loading, run-owned overlay viability, effective-access mapping, and the initial frontier population decision are proven or the dependent work is explicitly removed. No HITL is expected; pause only under the existing literal login/admin boundary.

- [ ] `X0.1` Verify BFCL Live wheel identity and official category loading
  - Why now: the upstream commit has ten Live files, but BenchEval runs the PyPI `bfcl-eval==2026.3.23` wheel and must bind the bytes it actually executes.
  - Files: no production edits; retain the probe under the gitignored research/run artifacts and record final pins in `config/benchmarks.yaml` only in X2.1.
  - Scope: on dev-box, install/sync the existing `bfcl` group; compare the six question and four answer files with `gorilla@6ea57973…`; use the real package category parser/loader for every `live_*` category; verify supported-model resolution and official generate/evaluate command shapes without a provider call. Do not mutate site-packages or invent missing files.
  - Dependencies: none.
  - Acceptance evidence: exact path/size/SHA-256 ledger for ten files; captured package/upstream versions; real loader accepts six categories; any mismatch fails before identity or launch.
  - If it fails: keep BFCL Live research-only outside the product and stop X2; do not patch or fork BFCL.

- [ ] `X0.2` Prove the run-scoped BFCL overlay route
  - Why now: pinned BFCL has no arbitrary dataset-path option, so tool order is viable only if an isolated data overlay can load without changing code/scorer.
  - Files: no production edits; disposable directory outside the checkout.
  - Scope: copy the exact installed package to an exclusive temporary root, change one declared `multiple` row's `function` order, invoke the real package loader from that root, and prove all Python/config/scorer bytes plus the installed package tree remain identical. Verify unchanged ground truth resolves through the official evaluator. No model/provider call.
  - Dependencies: X0.1.
  - Acceptance evidence: before/after producer/scorer digest sets match; only the declared data digest changes; loader observes the new order; installed tree digest is unchanged; symlink/hardlink/path replacement probes fail closed.
  - If it fails: stop X3 and retain only the official Live study; do not monkeypatch `PROMPT_PATH`, modify site-packages, or add a BFCL fork.

- [ ] `X0.3` Prove the effective-access evidence matrix
  - Why now: `network_policy` currently means plan intent and demonstrably differs from model-visible access across adapters.
  - Files: research output only; architecture §22 remains the decision source.
  - Scope: inspect a real model-only plan, pinned Inspect SWE generated Docker config with default `allow_internet=False`, and Harbor/TB command/preflight. Establish exactly what artifact/config can support `not_applicable`, `blocked`, and `uncontrolled` without running a custom network service.
  - Dependencies: none; may run with X0.1.
  - Acceptance evidence: retained non-secret effective configs and a three-row mapping that cannot be derived from `network_policy`; Harbor is never stamped restricted; no runtime/harness bytes or behavior are changed.
  - If it fails: use `unknown` for the affected path; do not add probes that alter the model's tools or traffic.

- [ ] `X0.4` Select the frontier study population and inference boundary
  - Why now: smoke cannot support statistics and old math-style benchmarks may be saturated for the actual target model pool.
  - Files: `config/studies/` drafts and a concise measurement record; no report implementation before the decision is reviewed.
  - Scope: name the initial admitted provider/model, BFCL categories, canonical/Live task counts, expected provider budget, deterministic order-permutation coverage, repeated-run variance check, and the raw/interval/test output that is allowed at smoke versus study scale. Reuse `stats.py` where sufficient; add no dependency during the spike.
  - Dependencies: X0.1; the final tool-order portion depends on X0.2.
  - Acceptance evidence: a reviewed population/precision/cost record with `plumbing_only` thresholds, inferential minimums, and explicit forbidden claims. If no affordable population has useful headroom, stop after the compatibility evidence rather than shipping a low-information feature.

### X1 — Additive evidence and study contracts

**Objective:** introduce the reusable minimum—effective-access evidence, closed study manifests, deterministic identities, and fail-closed report validation—without launching a derived benchmark.

**Exit gate:** old evidence/proofs remain valid; the new manifests and report boundary reject every unsupported interpretation and population drift; no new benchmark row can register `passed`.

- [ ] `X1.1` Write discriminating RED contracts for access evidence
  - Files: `tests/specs/test_effective_access_contracts.py`, adjacent evidence/adapter tests.
  - Scope: require independent requested/effective values; model-only `not_applicable`; retained official Inspect blocked state; Harbor uncontrolled; historical null compatibility; no stamp from `network_policy`; retrieval-audit values do not change native scoring.
  - Dependencies: X0.3.
  - Acceptance evidence: tests fail on the current code for each intended reason before implementation. Any required substitute carries the repository's full justification and remains diagnostic.

- [ ] `X1.2` Implement effective-access capture
  - Files: `src/bencheval/domain.py`, `evidence.py`, new `access_evidence.py`, concrete capture sites in model-only/SWE/Harbor paths, report/export projections, and tests from X1.1.
  - Scope: add the four optional closed fields in architecture §7.5; constructors accept concrete retained launch facts only; preserve all legacy parsing and `network_policy` behavior. Never add enforcement, probes, proxy policy, or secret config bytes.
  - Dependencies: X1.1.
  - Acceptance evidence: RED→GREEN; real effective configs from X0.3 serialize correctly; v0.2/v0.3 fixtures and historical proofs still verify; public exports reveal no private access/transcript data.

- [ ] `X1.3` Write RED study-manifest and identity contracts
  - Files: `tests/specs/test_exposure_study_contracts.py`.
  - Scope: closed `freshness_contrast`/`representation_pair`, stable relation classes, paired/unpaired mode compatibility, safe ids, canonical digest, required constant axes, forbidden claims, exact source mapping, derived BFCL identity, and rejection of arbitrary transform/plugin/path fields.
  - Dependencies: X0.1/X0.2 decisions.
  - Acceptance evidence: malformed/ambiguous manifests, same identity on both roles, Live-as-paired, tool-order-as-unpaired, unsafe paths, and transform drift all fail for the intended reason.

- [ ] `X1.4` Implement the closed study registry and identity spine
  - Files: new `src/bencheval/exposure_study.py`, `benchmark_registry.py`, `identity_strings.py`, `paths.py`, package-data entries in `pyproject.toml`, initial `config/studies/*.yaml`, and X1.3 tests.
  - Scope: load/canonicalize/hash declarative study YAML and add the single BFCL derived-data identity type. Do not add launch orchestration, generic transform entry points, Python callbacks, or candidate benchmark rows yet.
  - Dependencies: X1.3.
  - Acceptance evidence: RED→GREEN; source/build wheel contains and validates the manifests; clean core import remains dependency-light; identity changes on any source/transform/population change.

- [ ] `X1.5` Establish read-only report validity and CLI shell
  - Files: new `src/bencheval/exposure_report.py`, `cli.py`, `stats.py` only if X0.4 earns a helper, and `tests/specs/test_exposure_study_contracts.py`.
  - Scope: add `bencheval study validate|report`; validate evidence, eligibility, identities, constant axes, access, verifier, and population before output. Implement deterministic JSON plus Markdown projection and raw-only smoke mode. Proof-backed report mode also writes an `exposure-study-lock-v1` manifest beside the report, binding both input proof ids, the study digest, selected evidence inputs, report contract version, and report JSON digest. Do not add `study run`, reference correction, UI, or automatic seeds.
  - Dependencies: X1.2, X1.4, X0.4.
  - Acceptance evidence: current valid evidence can be loaded; incomplete, asymmetric, drifted, infra-contaminated, or overclaiming studies exit nonzero and leave no partial output; smoke output contains no inferential language; proof-backed mode rejects either mismatched proof or any changed lock/report input and reproduces the locked report digest from copied proof objects.

- [ ] `X1.6` Retain study artifacts without changing the run-proof format
  - Files: `proof_bundle.py`, run-bundle/public-redaction paths, proof tests.
  - Scope: make study/variant/source/derived/safe access files ordinary evidence-referenced artifacts beneath `artifacts/study/`; retain the existing `private_proof_v1` `artifact` role and required-role set. Do not embed the separate two-proof lock in either run proof or add a proof store/index. Private retrieval transcripts stay private; public outputs sanitize or omit them.
  - Dependencies: X1.2, X1.4.
  - Acceptance evidence: source-checkout-removed verify/import succeeds; missing, extra, symlink, hardlink, outside-root, or digest-changed study artifacts fail; historical private proofs still verify with no migration.

### X2 — BFCL Live freshness/generalization vertical slice

**Objective:** produce the first real exposure-adjacent evidence entirely through official BFCL data, code, scorer, and current provider path.

**Exit gate:** a distinct BFCL Live diagnostic identity produces official scores and private proof; the validated report is explicitly stratified/unpaired and contains no contamination estimate or admission claim.

- [ ] `X2.1` Add the BFCL Live diagnostic identity and slices
  - Files: `config/benchmarks.yaml`, `config/slices/bfcl-v4-live-*.yaml`, `config/studies/bfcl-v4-live-vs-non-live.yaml`, packaging config, catalog/identity tests, docs/ops BFCL page.
  - Scope: add `bfcl-v4-live` as `executable: false`, adapter-bound and diagnostic-capable; pin exactly the six Live question and four answer files verified in X0.1; define a tiny plumbing slice and the X0.4 study population separately. Do not modify or replace the admitted `bfcl-v4` identity/status.
  - Dependencies: X0.1, X1.4.
  - Acceptance evidence: catalog/packaged-config parity; identity fails on any missing/drifted Live byte; current executable count remains four; ordinary run rejects while explicit diagnostic planning succeeds.

- [ ] `X2.2` Wire official Live generation/evaluation without a second scorer
  - Files: `bfcl_native_adapter.py`, `control_plane_executor.py`, `doctor.py`, `access_evidence.py`, BFCL tests.
  - Scope: parameterize the current BFCL lifecycle by the catalog identity/category; preserve supported-model gate, cumulative deadline, run-owned results/scores, official JSONL parser, producer identity, model-only access state, and diagnostic registration veto. Do not copy or reinterpret score values in a study module.
  - Dependencies: X2.1, X1.2.
  - Acceptance evidence: official CLI command contains only verified Live categories; wrong solution remains eligible native evidence; local verdict/stdout cannot pass; injected-runner tests are diagnostic only.

- [ ] `X2.3` Run and preserve the real Live plumbing slice
  - Files: no source edits except factual runbook/ledger updates after evidence; results/proofs remain gitignored/local.
  - Scope: on dev-box, re-probe BFCL group/provider/model support, execute the tiny explicit diagnostic, retain official score bytes and ten-file identity, export and verify/import private proof, and run the study report in raw-only mode.
  - Dependencies: X2.2, X1.5, X1.6, and green production gate.
  - Acceptance evidence: real provider + official generate→evaluate; diagnostic row cannot register `passed`; proof verifies after copy; report says `plumbing_only`, unpaired, and no contamination/significance claim.
  - Human boundary: pause only if provider/runtime presents literal device/ subscription/CAPTCHA/hardware/admin interaction. Missing packages or ordinary credentials are operational work, not automatic HITL.

- [ ] `X2.4` Run the reviewed BFCL non-live/Live study population
  - Files: study config/ops docs only if X0.4's reviewed population changes; immutable run/proof artifacts stay local.
  - Scope: run canonical and Live categories with the same model/provider/sampling/harness version and declared budgets; preserve every native row and exclusion; produce deterministic JSON/Markdown and copied-proof verification.
  - Dependencies: X2.3, X0.4.
  - Acceptance evidence: declared task counts/strata and constant axes validate; report gives native rates/intervals and a freshness/generalization caveat; independent review confirms it does not present a paired or contamination estimate. If the result has no useful headroom or costs exceed the plan, stop before X3 rather than forcing a variant feature.

### X3 — BFCL balanced tool-order paired study

**Objective:** add one representation-equivalent transform with exact source mapping and unchanged official scoring, then test whether it yields information beyond canonical/provider variance.

**Exit gate:** installed BFCL remains byte-identical; a run-owned derived identity produces official-score evidence and a population-valid paired report; no generic transform abstraction or canonical admission is introduced.

- [ ] `X3.1` Write RED materialization and overlay contracts
  - Files: `tests/specs/test_bfcl_study_contracts.py`, hostile filesystem tests.
  - Scope: deterministic non-identity balanced permutations for declared `multiple`/`parallel_multiple` rows; exact source-to-derived mapping; all non-`function` data and ground truth unchanged; canonical serialization; source/derived/producer/scorer digests; exclusive run-owned overlay; installed tree immutability; pre/post-launch drift and symlink/hardlink/path-swap rejects.
  - Dependencies: X0.2, X2.4 useful-result gate.
  - Acceptance evidence: each behavioral contract is RED on current code for the intended reason; no substitute claims official BFCL execution.

- [ ] `X3.2` Implement the BFCL-specific materializer
  - Files: new `src/bencheval/bfcl_study.py`, `run_isolation.py` only for an earned shared primitive, and X3.1 tests.
  - Scope: read pinned canonical JSONL, validate ids/tool names, calculate the versioned balanced permutation, write source/derived/variant manifests through anchored exclusive I/O, and verify replay. No scorer, process runner, provider, generic transform callbacks, or installed-package writes.
  - Dependencies: X3.1.
  - Acceptance evidence: RED→GREEN; two independent materializations produce byte-identical output/digest; changed source/version changes identity; every outside-write/mutation probe fails closed.

- [ ] `X3.3` Implement and bind the run-owned package overlay
  - Files: `bfcl_study.py`, `bfcl_native_adapter.py`, `control_plane_executor.py`, `doctor.py`, proof/artifact retention tests.
  - Scope: copy the pinned package into the claimed run root, verify byte-identical code/config/scorer, replace only declared data files, launch the unchanged official CLI from the overlay, then reverify overlay/source/installed trees before accepting scores. Share the current BFCL score parser; do not add a study scorer.
  - Dependencies: X3.2.
  - Acceptance evidence: real uncharged overlay loader/evaluator probe from X0.2 passes through the production path; producer/scorer drift or concurrent swap yields typed invalid evidence; installed distribution remains unchanged.

- [ ] `X3.4` Add the diagnostic identity, slices, and paired report mode
  - Files: `config/benchmarks.yaml`, `config/slices/bfcl-v4-tool-order-*.yaml`, `config/studies/bfcl-v4-tool-order-v1.yaml`, registry/identity/report/CLI tests, BFCL ops docs.
  - Scope: add `bfcl-v4-tool-order-v1` as non-executable diagnostic; bind canonical source identity, transform/study version, derived digest, and source ids. Extend report with exact paired population, concordant/discordant counts, directional flips, paired delta, X0.4 uncertainty rule, and raw-only smoke.
  - Dependencies: X3.3, X1.5.
  - Acceptance evidence: ordinary execution and `passed` registration reject; diagnostic planning works; asymmetric/duplicate/missing/drifted pairs fail nonzero; relation remains `representation_equivalent` regardless of measured fidelity.

- [ ] `X3.5` Run the real tool-order smoke and reviewed paired population
  - Files: immutable local evidence/proofs plus factual docs/ledger update after verification; no source change driven only by score preference.
  - Scope: use the same frontier model/provider/settings as canonical, first run the plumbing slice, then only the X0.4 reviewed population; export/verify private proofs and reproduce the paired report from copied proof bytes.
  - Dependencies: X3.4 and green software/security gates.
  - Acceptance evidence: official score JSONL is sole verdict; package code/scorer and installed-tree digests hold; smoke emits raw-only output; study population validates and reports directional flips/uncertainty with competing explanations and no contamination/clean/cheating claim.

### X4 — Operator integration, hardening, and scoped readiness

**Objective:** expose the proven study/report capability through existing application/UI/proof paths without expanding its claim or runtime surface.

**Exit gate:** CLI, optional console, copied private proof, docs, and security/readiness review agree on the exact diagnostic claim. This remains independent of the deferred general console U3/U4 program except for shared regressions.

- [ ] `X4.1` Add application and console projections
  - Files: `src/bencheval/application/{dto,operations}.py`, `ui/pages.py`, console tests, `docs/api/operator-console-contract.md`.
  - Scope: add study validation/report selection and result display to the existing Compare surface; show relation, native scores, access/verifier/freshness, population validity, flips, uncertainty, and explicit non-claims. Do not add automatic charged launch, model panels, transform editing, or page-local interpretation.
  - Dependencies: X2.4 and X3.5; may be skipped if X3 stops for low information.
  - Acceptance evidence: DTO exactly matches domain JSON; crafted UI state cannot bypass invalid/smoke claims; keyboard/table fallback works on the added view.

- [ ] `X4.2` Close artifact, privacy, and compatibility edges
  - Files: `proof_bundle.py`, `run_bundle.py`, `redaction.py`, exports, CLI/report error handling, regression tests, ops docs.
  - Scope: hostile study manifests/derived files, symlink/hardlink/FIFO/oversize, proof copy/import, public transcript omission/redaction, exclusive outputs, legacy evidence/proof reads, and no partial report on failure.
  - Dependencies: X1.6, X3.5.
  - Acceptance evidence: hostile real-filesystem battery passes; no secret/private transcript in public output; old proofs and CLI commands remain compatible; dependency and secret scans stay green.

- [ ] `X4.3` Independent review and readiness decision
  - Files: no product edits during review; durable readiness artifacts in the established local review location.
  - Scope: max-effort `qa-review` plus scoped `verify-readiness` over the exact final tree and real BFCL proofs. Review must challenge identity, access truth, official scoring, population validity, statistics, wording, proof portability, and runtime/harness non-modification.
  - Dependencies: X4.1/X4.2 as applicable.
  - Acceptance evidence: zero open red/yellow findings for the scoped exposure claim; `make check-production-v1`, focused hostile contracts, exact proof verify/import, and real report reproduction pass. A green unit suite alone is not readiness.

### X5 — Evidence-led continuation decision

**Objective:** decide whether the first study created enough user value to justify another transform family or any shared abstraction.

**Exit gate:** one explicit continue/stop decision is recorded from real evidence; no speculative framework remains on the active roadmap.

- [ ] `X5.1` Evaluate information value and operating cost
  - Files: concept/architecture/roadmap decision update only.
  - Scope: compare the Live and tool-order findings with provider/run variance, transform fidelity, operator effort, proof size, and whether a real model or benchmark decision changed. Do not choose a favorable score as the criterion.
  - Dependencies: X2.4 and, if not stopped, X3.5/X4.3.
  - Acceptance evidence: concise evidence-backed decision with observed costs, limits, and the next falsifiable question.

- [ ] `X5.2` Reopen architecture only on earned second-family demand
  - Files: `docs/context/concept-zero.md`, `docs/architecture.md`, `docs/roadmap.md`; no production implementation in the decision step.
  - Scope: if a second frontier-relevant benchmark needs the same source/relation/fidelity/materialization/report invariants, research it and decide whether to extract a narrow shared contract. Otherwise close the exposure program at the BFCL-specific implementation and keep MATH()/DyVal/training labs deferred.
  - Dependencies: X5.1.
  - Acceptance evidence: either a newly accepted concept/architecture with a real second family, or an explicit stop decision that leaves no generic transform task scheduled.

### Exposure execution packets and merge order

1. **Packet A — X0 spikes:** read-only/dev-box research; no production writer.
2. **Packet B — X1 access/study contracts:** one writer for shared domain/evidence/CLI/proof files; do not parallelize writers across these hot modules.
3. **Packet C — X2 Live:** begins after X1 identity/access foundations; owns BFCL catalog/slices/adapter delta and real Live proof.
4. **Packet D — X3 tool order:** starts only after the X2 usefulness gate; owns `bfcl_study.py`, overlay, derived identity, and paired report delta.
5. **Packet E — X4 review/integration:** UI projection follows the proven CLI; independent review remains read-only and uses the exact candidate tree.

Every implementation packet begins with `dev-spec` RED contracts, proceeds through implementation/self-critique, and receives an independent `qa-review`. Incomplete packet acceptance is a rejection: unrun real BFCL/proof/readiness exit criteria remain `BLOCKED` or `IMPLEMENTED BUT UNVERIFIED`, never silently complete.

### Exposure cross-phase gates

- [ ] `XG-01` Official-runner immutability
  - Evidence: exact BFCL code/config/scorer digests before and after every derived run; installed package unchanged; no custom network/runtime layer.
- [ ] `XG-02` Identity and proof completeness
  - Evidence: study/source/candidate/variant/access artifacts are content-bound, evidence-referenced, copied under `artifacts/study/`, and verify offline; an `exposure-study-lock-v1` manifest binds both run proof ids, exact report inputs, and the deterministic report JSON digest.
- [ ] `XG-03` Population and interpretation validity
  - Evidence: paired/unpaired rules, constant axes, eligibility, verifier quality, smoke limits, uncertainty method, and forbidden claims are machine-checked.
- [ ] `XG-04` Backward compatibility
  - Evidence: v0.2/v0.3 evidence, existing CLI/report/compare, current private proofs, catalog executable count, and core import/package gates remain green.
- [ ] `XG-05` Real evidence boundary
  - Evidence: official BFCL Live/variant runs and copied-proof report reproduction are the acceptance oracle; substitutes are diagnostic only and cannot close a live or readiness checkbox.

## Operator console roadmap (IMPLEMENTED; hardening remains)

Implementation status on 2026-09-01: U0.1–U0.4, U1, and U2 are implemented. U0.5 is partially proven by a real Chromium DOM/keyboard journey but lacks the automated axe and Firefox/WebKit matrix. U3 remains the active hardening lane; U4 release certification follows it. A green deterministic suite or one-browser walkthrough does not by itself close U3/U4.

The following phases cover the complete existing product surface. They do not admit new benchmarks, promote SWE, add remote users, or change proof retention. Each implementation slice must preserve CLI behavior and canonical files.

### U0 — Decision closure and executable spikes

**Objective:** prove the proposed framework, local trust boundary, shared application contract, and long-running-session mechanics before page breadth.

**Exit gate:** NiceGUI is either accepted with measured evidence or replaced by another single-process local route; state-changing UI has a proven local capability boundary and safe run-session cancellation/reconnect contract. No HITL is required.

- [x] `U0.1` NiceGUI optional-extra and clean-install spike
  - Files: throwaway spike outside production modules; proposed changes limited to `pyproject.toml`, `uv.lock`, and a minimal `src/bencheval/ui/` only after acceptance.
  - Scope: evaluate current NiceGUI 3.x license, transitive/build footprint, Python 3.12 compatibility, wheel/`uv tool install`, startup latency, browser open/no-open, loopback bind, core import isolation, table/download support, and real-browser test fixture. Do not add the dependency before the spike is reviewed.
  - Dependencies: none.
  - Acceptance evidence: clean disposable install; `import bencheval` without UI deps; minimal `bencheval ui --no-open` starts/stops on loopback; dependency audit and license record; measured startup and lock diff.
  - If it fails: spike NiceGUI native mode only if it preserves one process; otherwise select a minimal server-rendered Python route. Do not fall through to a split SPA without a new architecture review.

- [x] `U0.2` Local mutation-capability and hostile-browser spike
  - Files: `tests/ui/test_local_capability.py`; proposed `ui/app.py` boundary.
  - Scope: bind `127.0.0.1`, exact Host/Origin, no CORS/iframe, per-process capability exchange to strict cookie, nonce removal, invalid/replayed token, DNS-rebinding-style Host, and cross-origin mutation attempts. Read-only and mutation events must both be tested through a real browser/server.
  - Dependencies: U0.1.
  - Acceptance evidence: all hostile requests fail before application calls; valid local browser reaches one harmless dry-run action; no token appears in logs, durable files, or browser URL after exchange.
  - If it fails: first release is read-only while the mutation boundary is redesigned; never add a remote bind workaround.

- [x] `U0.3` Typed application-operation parity baseline
  - Files: proposed `src/bencheval/application/{dto,catalog_ops,run_ops,evidence_ops,analysis_ops,proof_ops,readiness_ops}.py`; `tests/application/`.
  - Scope: define and implement the contract in `docs/api/operator-console-contract.md` around existing modules. Capture golden CLI operation results before refactoring handlers. No storage schema or benchmark semantics change.
  - Dependencies: none; may run in parallel with U0.1/U0.2.
  - Acceptance evidence: CLI-before versus application-operation-after parity for catalog, plan failures/success, doctor, validated history, compare, report/export argument validation, and proof verify; Pydantic closed-schema tests and full production gate.

- [x] `U0.4` Real bounded RunSession cancellation/reconnect spike
  - Files: proposed `ui/session.py`, a disposable real subprocess harness, and `tests/ui/test_run_session.py`.
  - Scope: one active mutation, background task, page refresh/second tab, explicit cancel, timeout, browser close, process exit, output cap, and server restart reconciliation. No provider or official benchmark substitution may count as live acceptance; this spike proves session mechanics only.
  - Dependencies: U0.1 and U0.3.
  - Acceptance evidence: real local child lifecycle has no duplicate launch, bounded cancellation, no lost completed evidence, and explicit non-resumable state after server restart.
  - If it fails: ship read-only/dry-run UI first and defer live mutation.

- [ ] `U0.5` Browser accessibility harness
  - Files: `tests/ui/test_accessibility.py`, `ui/theme.py`, test configuration.
  - Scope: decide the real browser/axe route and prove keyboard, focus, labels, status announcements, non-color meaning, reduced motion, and chart table fallback on the minimal shell.
  - Dependencies: U0.1.
  - Acceptance evidence: Chromium real-browser journey and automated scan with zero critical/serious findings; manual Firefox/WebKit keyboard spot-check protocol recorded for later phases.

### U1 — Read-only production-shaped walking skeleton

**Objective:** ship the local entry point, shared read operations, shell, Overview, Catalog, Environment, and existing run detail without mutation.

**Exit gate:** a clean-box operator starts `bencheval ui`, navigates every read-only page by keyboard, and sees canonical local data with no UI dependency in core installs. Mutation remains disabled until U0.2/U0.4 pass.

- [x] `U1.1` Package the optional entry point and shell
  - Files: `pyproject.toml`, `uv.lock`, `cli.py`, `ui/{__init__,app,pages,security,session}.py`, `ui/assets/console.css`.
  - Scope: add `bencheval ui --port --no-open`, loopback only, lazy NiceGUI import, navigation, skip link, global status, display preferences, and graceful missing-extra error. Do not add host/auth/config editing.
  - Dependencies: U0.1, U0.2, U0.5.
  - Acceptance evidence: core and UI clean installs; start/stop smoke; missing-extra CLI error; real-browser shell and keyboard checks; `make check-production-v1`.

- [x] `U1.2` Catalog and Overview vertical path
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: actual 8/4 catalog, models, runtimes, agents, providers, action availability, Tier-0/Tier-1/Tier-2 truth, recent validated runs, proof health. No benchmark/run action may be enabled from page-local inference.
  - Dependencies: U0.3, U1.1.
  - Acceptance evidence: DTO-versus-registry parity; actual pending/diagnostic/scaffold rows disabled; real browser filter/paging/deep-link tests.

- [x] `U1.3` Environment/Doctor and read-only Runs & Evidence
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: config/results/proof roots, dependency/runtime/provider-variable presence, doctor execution, validated raw/current history, completed run detail, evidence/official result/artifact metadata/history. Default previews are redacted and size capped.
  - Dependencies: U1.1 and U0.3.
  - Acceptance evidence: corrupted history fails closed; credential values never enter DTO/HTML; hostile artifact content is served as text/download only; restart shows the same durable projection.

### U2 — Complete operator journeys

**Objective:** add every current mutation and analytical/export/proof operation.

**Exit gate:** all feature-coverage rows in `docs/prototypes/frontend-v1.md` pass through real application operations and a real browser. Charged/native benchmark proof remains a separate claim.

- [x] `U2.1` Run Builder dry-run and plan parity
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: Axes → Plan → Preflight → Confirm; runtime XOR agent, model/provider, budgets, network/caveats, diagnostic opt-in, paths, dry-run. No hidden defaults or output reservation during planning. Confirmation fingerprints bind normalized output selections, and preflight follows the derived official harness instead of treating every native adapter as Inspect.
  - Dependencies: U1, U0.3.
  - Acceptance evidence: canonical `RunPlan` bytes/errors match CLI across all executable, diagnostic, catalog-only, scaffold, and model-only paths.

- [x] `U2.2` Live start, monitor, cancel, and run detail
  - Files: `application/{dto,operations}.py`, `ui/{session,pages}.py`.
  - Scope: explicit cost/charge confirmation, one active launch, live lifecycle and bounded redacted log tail, explicit cancel, browser reconnect, evidence/artifact refresh, preallocated run identity, explicit evidence truncation metadata, and task outcome separate from registration. Orphan process-group descendants are terminated even when their worker leader exits first.
  - Dependencies: U0.2, U0.4, U2.1.
  - Acceptance evidence: real bounded local subprocess browser journey plus one previously admitted uncharged/dry lifecycle; charged/native run is `not run` unless credentials/harness are deliberately supplied.

- [x] `U2.3` Evidence qualification and registration
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: legal lifecycle actions, qualification reasons, fill-once axes, producer/provenance gates, notes/host/locators. Diagnostic cannot register passed; no automatic retry.
  - Dependencies: U1.3, U2.2.
  - Acceptance evidence: API/CLI/UI parity for legal and illegal transitions; direct crafted event calls revalidate; concurrent tabs produce one append.

- [x] `U2.4` Compare and reports
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: baseline/current selection, shared eligible validity, deltas/intervals, exclusions, caveats, Markdown/JSON result generation. Charts are projections with full table fallback and no universal score.
  - Dependencies: U1.3.
  - Acceptance evidence: compare DTO exactly matches canonical compare JSON; invalid comparison never shows headline; one-instance/smoke caveats visible.

- [x] `U2.5` Warehouse and run-bundle exports
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: Markdown report, Parquet, DuckDB, public redacted/private bundle, optional comparison inputs, exclusive destination, progress and download.
  - Dependencies: U2.4.
  - Acceptance evidence: real files verify against CLI-generated equivalents; public bundle secret/path negatives; conflict leaves no partial output.

- [x] `U2.6` Permanent private-proof workflows
  - Files: `application/{dto,operations}.py`, `ui/pages.py`, `proof_bundle.py`.
  - Scope: list/inspect roles, export, verify expected digest, import/store, legacy-unverifiable reasons, permanent retention. No delete/replace/TTL.
  - Dependencies: U1.3.
  - Acceptance evidence: source-checkout-removed proof verify/import through real browser; digest-idempotent import; traversal/symlink/hardlink/extra/missing rejects; no `runs.jsonl` replay and no delete control/event.

- [x] `U2.7` Readiness and complete environment surface
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: benchmark ledgers and links, software/live/readiness separation, blockers/unblock actions, optional-group and harness/runtime presence, doctor rerun. Do not parse prose into a Tier-2 claim or expose secret values.
  - Dependencies: U1.2/U1.3 and U2.3/U2.6.
  - Acceptance evidence: current four Tier-1 benchmarks and no Tier-2 claim match canonical ledger/proof evidence; stale or missing ledgers are explicit.

### U3 — Hardening and launch readiness

**Objective:** make the complete local console secure, responsive, accessible, recoverable, and installable for its actual single-user threat model.

**Exit gate:** scoped `verify-readiness` passes for the local console claim. This does not advance benchmark tiers or prove every external harness.

- [ ] `U3.1` Hostile local-web and artifact suite
  - Files: `tests/ui/security/`, shared redaction/path tests.
  - Scope: Host/Origin/rebinding/iframe/cross-site mutation, capability replay, malformed event payloads, path traversal, symlink/hardlink/FIFO, hostile Markdown/HTML, oversized logs/artifacts, secret names/values, crafted disabled actions.
  - Dependencies: U2 complete.
  - Acceptance evidence: real server/browser attacks fail before side effects; no secret in HTML, logs, downloads, screenshots, or browser storage.

- [ ] `U3.2` Performance and bounded-data proof
  - Files: bounded readers/cursor implementations and `tests/ui/performance/`.
  - Scope: measure startup, Overview, 10k/100k manifest/evidence rows, proof list, artifact metadata, log tail, and concurrent read-only tabs. No database until measurements breach an agreed local threshold.
  - Dependencies: U2.
  - Acceptance evidence: explicit baseline and thresholds in `qa-measure` output; no unbounded DOM/list/file read; performance regression gate for chosen scale.

- [ ] `U3.3` Accessibility and browser matrix
  - Files: all pages/components and `tests/ui/accessibility/`.
  - Scope: complete keyboard journeys, focus/dialog behavior, status messages, zoom/reflow, contrast, reduced motion, chart tables, Chromium/Firefox/WebKit.
  - Dependencies: U2.
  - Acceptance evidence: zero critical/serious automated findings; manual WCAG 2.2 AA checklist for complete flows; screenshots at desktop and tablet.

- [ ] `U3.4` Packaging, upgrade, and failure rehearsal
  - Files: package metadata, README/ops docs, release CI.
  - Scope: clean source/wheel/tool installs, missing extra, occupied port, interrupted process, console restart, canonical corruption, optional harness absence, downgrade/rollback. Core package remains dependency-light.
  - Dependencies: U3.1–U3.3.
  - Acceptance evidence: clean-box install/uninstall; rollback to CLI-only build; full production gate, dependency audit, gitleaks, and scoped readiness PASS.

### U4 — Documentation, distribution, and handoff

**Objective:** make the local console usable without tribal knowledge and keep generated visual/design assets distinct from real screenshots.

**Exit gate:** documented install/use/recovery journeys match shipped bits and a fresh operator completes them. No HITL unless a selected benchmark/runtime itself requires a literal human-only action.

- [ ] `U4.1` Operator and contributor documentation
  - Files: README, `docs/ops/operator-console.md`, architecture, roadmap, contracts, screenshots, optional-extra setup, security/recovery notes.
  - Dependencies: U3.
  - Acceptance evidence: docs commands execute on a clean install; prototype images remain labelled design references and shipped screenshots are captured from the real UI.

- [ ] `U4.2` Release and handoff gate
  - Files: CI/release metadata and final evidence report.
  - Dependencies: U4.1.
  - Acceptance evidence: `make check-production-v1`, UI browser suite, package build/install, dependency/secret scans, local-console `verify-readiness` PASS, and one full uncharged operator journey. External benchmark live proof is reported separately as passed/failed/not run.

### UI later / not now

- Remote or multi-user service, accounts, RBAC, TLS termination, and deployment behind a proxy — reopen concept/architecture first.
- Parallel run scheduling, durable queue, resume-after-process-restart, and notifications — revisit after measured single-run operator demand.
- Database/search index — revisit only after U3.2 shows bounded file readers do not meet real local data volume.
- Config or credential editing, proof deletion/TTL, remote proof store/signing, mobile run launch, weighted portfolios, and new benchmark admission — remain explicit non-goals or separate product decisions.

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
| AR-12, AR-14 portable/permanent proof | R2, R4 transfers |
| AR-13 agent admission | R1 MOMO scaffold gate |
| AR-15 raw history and projection | R1 registry work |
| AR-16 scored-byte retention | R4 GPQA and R5 SWE retained artifacts |
| AR-17, AR-19, AR-21 shared operations/non-authoritative DTOs | U0.3, U1, U2 |
| AR-18 loopback capability boundary | U0.2, U3.1 |
| AR-20 single RunSession/no retry | U0.4, U2.2 |
| AR-22 accessible complete journeys | U0.5, U3.3 |
| AR-23 complete feature coverage | U1–U2, U4.2 |
| AR-24–AR-25 effective access truth | X0.3, X1.1–X1.2, X2.2, X4.3 |
| AR-26–AR-28 relation/identity/official-runner integrity | X0.1–X0.2, X1.3–X1.4, X2.1–X2.2, X3.1–X3.3 |
| AR-29–AR-30 population/report/smoke limits | X0.4, X1.5, X2.3–X2.4, X3.4–X3.5 |
| AR-31 bounded BFCL-first scope | X2, X3, X5 |
| AR-32 study proof portability | X1.6, X2.3–X2.4, X3.5, X4.2–X4.3 |

### Hot files

- `README.md`, `docs/architecture.md`, `docs/api/internal-contracts.md`
- `config/benchmarks.yaml`, `config/runtimes/{claude-code,codex-cli}.yaml`, `config/agents/`, `config/providers/`, `config/slices/`, `config/models.yaml`
- `src/bencheval/`: `cli.py`, `benchmark_plan.py`, `control_plane_executor.py`, `doctor.py`, registries, `terminal_bench_harbor.py`, `gpqa_adapter.py`, `hle_adapter.py`, `bfcl_native_adapter.py`, `swebench_adapter.py`, `external_agent_adapter.py`, `evidence.py`, `live_run_manifest.py`, `report.py`, `evidence_compare.py`, `export.py`, `run_bundle.py`, `proof_bundle.py`
- Exposure (proposed): `access_evidence.py`, `exposure_study.py`, `bfcl_study.py`, `exposure_report.py`, `config/studies/`, BFCL Live/derived slices and identity entries
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
| BFCL Live exact wheel data | Required by X0.1 before any Live identity. Verify automatically on dev-box against `gorilla@6ea57973…`; a mismatch stops the route but needs no human action. |
| BFCL exposure provider spend | X2.3/X2.4/X3.5 use the existing admitted provider/model path and explicit run budgets. Probe credentials and model support automatically; only literal device/subscription/CAPTCHA/admin interaction is HITL. |
| Effective access evidence | No new firewall/proxy service is required. Capture official Inspect config, model-only non-applicability, and Harbor uncontrolled state; unknown remains valid evidence and is not a human blocker. |

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
