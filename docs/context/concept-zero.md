# BenchEval Concept Zero

Status: ACCEPTED current control plane and local operator console; PROPOSED
benchmark-exposure extension. Implementation and live-evidence status remain
tracked in [`../roadmap.md`](../roadmap.md).

Last updated: 2026-09-03

## Executive decision

BenchEval is a local-first, operator-run Python control plane for producing
comparable, auditable benchmark evidence from official or native benchmark
harnesses. Its next differentiating capability is not another benchmark launcher:
it is a narrow evidence layer that measures how strongly a canonical score
depends on benchmark-specific information by comparing it with source-bound
fresh or representation-equivalent populations under an explicitly captured
access regime and verifier-quality boundary. The existing CLI remains stable
automation; the implemented loopback-only browser console projects the same
typed operations. The production path remains one checkout, one Python process,
operator-provisioned official harnesses and credentials, append-only evidence,
and permanent local content-addressed proof bundles. BenchEval does not claim to
prove a model clean, compute a universal "decontaminated score," fork runtimes or
official scorers, maintain a custom egress allow-list, train contaminated model
pairs, or become a hosted service, scheduler, billing system, general agent
platform, or offensive execution platform.

## Problem and evidence

| ID | Claim | Evidence | Confidence | Impact |
|---|---|---|---|---|
| E-01 | Benchmark scores are not comparable unless the benchmark, slice, model, runtime/agent, harness, and provenance axes are explicit. | Current typed plans, evidence records, qualification gates, and comparison logic | high | The product spine remains `benchmark -> (runtime \| agent)? -> model -> evidence`. |
| E-02 | A native attempt may legitimately score zero or fail the task while still proving the lifecycle. | Registered Terminal-Bench, HLE, and BFCL Tier-1 runs retain official wrong-solution outcomes | high | Admission and proof must separate task failure from infrastructure or evidence failure. |
| E-03 | Green local tests prove software contracts, not the external harness or provider path. | Production-readiness tiers and retained Tier-1 run ledger | high | Software, live, and Tier-2 claims remain distinct. |
| E-04 | A proof that depends on the originating checkout or mutable host paths is not portable evidence. | `private_proof_v1` export, verify, import, and content-addressed local store | high | Private proof is the durable internal evidence unit. |
| E-05 | The official SWE-bench evaluator consumes standard prediction JSONL and emits per-instance plus schema-v2 aggregate reports. | [SWE-bench evaluation guide](https://github.com/SWE-bench/SWE-bench/blob/v5.0.1/docs/guides/evaluation.md), [evaluator source](https://github.com/SWE-bench/SWE-bench/blob/v5.0.1/swebench/harness/run_evaluation.py), [reporting source](https://github.com/SWE-bench/SWE-bench/blob/v5.0.1/swebench/harness/reporting.py) | high | SWE generation and official evaluation must be one evidence-bound lifecycle; local verdict files are never authority. |
| E-06 | The pinned official SWE-bench Verified snapshot is one 500-row parquet, and the selected diagnostic instance exists in it. | [official revision `78f471bf...`](https://huggingface.co/datasets/SWE-bench/SWE-bench_Verified/commit/78f471bf655a3137b2e8a75af1501690ec009ec3), parquet SHA-256 `030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25`; local uncharged load probe | high | Both SWE phases derive from one pinned source row; no second dataset identity is introduced. |
| E-07 | Locked Inspect Evals `0.8.0` can load a run-owned one-row HF-style directory when the two test-list fields are canonically JSON encoded, and it accepts a digest-bound image template. | Local no-provider compatibility probe: one selected sample, task version 3, immutable image digest | high | Adapt the pinned official row for Inspect locally; do not upgrade admitted Inspect dependencies for this lane. |
| E-08 | `swebench==5.0.1` is a real, heavy evaluator dependency with Docker and dataset transitive dependencies. | [PyPI 5.0.1 metadata](https://pypi.org/project/swebench/5.0.1/) and locked dependency inspection | high | Put it in a separate exact-pinned `swe` dependency group, not the core or generic eval install. |
| E-09 | The current CLI already owns every product operation needed by a complete local console: catalog, plan/run, doctor, evidence lifecycle, report/compare, warehouse/public export, and private-proof export/verify/import. | `bencheval --help`, nested command help, and `src/bencheval/cli.py` on `main` | high | The UI must reuse application services beneath CLI handlers rather than shelling out or reimplementing behavior. |
| E-10 | NiceGUI is a maintained MIT-licensed Python browser UI with a backend-first model, long-running-task support, tables, downloads, and real-browser testing. | [official documentation](https://nicegui.io/documentation), [official repository](https://github.com/zauberzeug/nicegui), [PyPI `3.16.0`](https://pypi.org/project/nicegui/3.16.0/) on 2026-09-01 | high | It is the smallest credible route to one local Python deployable unit and is selected for a bounded implementation spike. |
| E-11 | Accessible status-heavy interfaces require keyboard operation, visible focus, non-color-only status, labelled controls, and announced status changes. | [WCAG 2.2 Recommendation](https://www.w3.org/TR/WCAG22/) | high | Accessibility is a functional acceptance gate, not visual polish. |
| E-12 | Public benchmark scores can contain a benchmark-specific advantage from training-time item/solution exposure, task-format training, or runtime retrieval; these causes are not observationally interchangeable. | [OpenAI SWE-bench Verified audit](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/), [Training on the Test Task](https://arxiv.org/abs/2407.07890) | high | The product measures dependence and records causes/evidence separately; it does not emit a binary clean/contaminated verdict. |
| E-13 | Historical public-repository agent benchmarks can leak known fixes through the public web or retained future Git history, and restricting those channels can materially change scores. | [Cursor runtime-leakage study, 2026-06-25](https://cursor.com/blog/reward-hacking-coding-benchmarks) | high | Runtime retrieval conditions are evidence axes, distinct from training contamination and from the requested `network_policy`. |
| E-14 | Semantics/scorer-preserving edits can still change clean-model behavior, while stronger edits trade fidelity for contamination resistance; no tested strategy dominates across benchmarks. | [ICML 2025 mitigation study](https://arxiv.org/abs/2503.16402), [option-position bias](https://arxiv.org/abs/2309.03882) | high | Relation class and measured behavioral fidelity are separate; no transform tier bypasses calibration. |
| E-15 | Simple perturbations preserve the original solution pattern, while hard counterfactual perturbations expose additional solution-template dependence and require new answers/stronger validation. | [MATH-Perturb](https://arxiv.org/abs/2502.06453) | high | Representation variants and counterfactual same-construct tasks are separate study kinds and cannot share one interpretation. |
| E-16 | Paraphrase, translation, and synthetic-data propagation can preserve benchmark exposure while evading string-based overlap tests. | [Rethinking Benchmark and Contamination](https://arxiv.org/abs/2311.04850) | high | A variant may reduce canonical surface overlap but can never be called unrecognizable or fresh without separate evidence. |
| E-17 | Verifier defects interact with exposure: models that know the canonical patch can pass underspecified tests using information unavailable to a genuinely novel solver. | [OpenAI SWE-bench Verified audit](https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/), [SWE-Bench Pro audit and recommendation retraction](https://openai.com/index/separating-signal-from-noise-coding-evaluations/) | high | Verifier/task integrity gates precede access and exposure interpretation. |
| E-18 | Fresh parallel and functional benchmarks can reveal generalization gaps, but public release shortens freshness and benchmark/domain difficulty can confound the raw gap. | [GSM1k](https://arxiv.org/abs/2405.00332), [Functional Benchmarks / MATH()](https://arxiv.org/abs/2402.19450), [SWE-rebench V2](https://arxiv.org/abs/2602.23866) | high | Freshness contrasts are valuable evidence, not direct contamination estimates; saturated math tasks are not the first frontier-model pilot. |
| E-19 | BFCL V2 Live was created from fresh user-contributed functions/queries to reduce contamination and improve real-world generalization, but differs from non-live data in difficulty and composition. | [BFCL V2 Live](https://gorilla.cs.berkeley.edu/blogs/12_bfcl_v2_live.html) | high | BFCL non-live versus Live is the first low-cost freshness/generalization study, not a paired contamination score. |
| E-20 | Current `network_policy` values encode plan/runtime intent rather than proven model-visible access: model-only paths need provider egress, Inspect SWE defaults to a network-disabled sandbox, and Harbor cannot enforce `deny`. | `domain.py`, `benchmark_plan.py`, pinned Inspect Evals `0.8.0`, `terminal_bench_harbor.py` | high | Preserve historical `network_policy` semantics and add separately captured effective-access evidence. |
| E-21 | The pinned BFCL commit contains six Live question files and four answer files, while the admitted identity covers only nine non-live files; the official CLI resolves category data from package `data/` and exposes no arbitrary question-file argument. | [`gorilla@6ea57973`](https://github.com/ShishirPatil/gorilla/tree/6ea57973c7a6097fd7c5915698c54c17c5b1b6c8/berkeley-function-call-leaderboard/bfcl_eval), local source inspection | high | Live needs a distinct identity. A derived tool-order study needs a run-scoped package-data overlay rather than mutating the installed distribution. |
| E-22 | Locked Inspect Evals GPQA already shuffles answer choices by default. | `inspect_evals 0.8.0` `gpqa.get_gpqa_diamond_dataset(shuffle_choices=True)` | high | GPQA choice permutation is not a new first implementation candidate. |

## Users and stakeholders

| Actor | Need | Constraint | Success signal |
|---|---|---|---|
| Benchmark operator | Run a small official lifecycle and retain everything needed to audit it. | External harnesses, images, credentials, and disk remain operator-provisioned. | A qualified evidence set and an offline-verifiable private proof. |
| Model/runtime engineer | Compare one controlled axis without infrastructure rows improving the headline. | Smoke samples are not statistical rankings and closed-model training data is unavailable. | Comparison uses the shared eligible intersection and states verifier, access, freshness, and interpretation limits. |
| Benchmark/exposure researcher | Test whether a public canonical score transfers to fresh or representation-equivalent tasks. | A gap has several possible causes and cannot prove provider intent or clean training data. | A source-bound study reports native scores, population, fidelity, directional flips, uncertainty, and explicit non-claims. |
| Reviewer | Reproduce identity, scoring authority, and artifact completeness without trusting narration. | The source checkout or original host may be unavailable. | Proof digest verifies from copied bytes alone. |
| Maintainer | Add or admit adapters without weakening existing claims. | Catalog presence is not execution admission. | Typed gates fail before charge and admission is backed by a live official attempt. |
| Interactive operator | Discover capabilities, plan and monitor runs, inspect evidence, and manage proofs without reconstructing CLI arguments. | Local machine only; credentials remain environment-owned; long-running harnesses may outlive a browser page. | Every UI action maps to the same validated operation and produces the same durable files as the CLI. |

MOMO users, offensive benchmark operators, hosted-service tenants, and external
proof consumers are not v1 user groups. MOMO remains a discoverable scaffold;
CyberGym and ExploitGym remain catalog-only.

## Goals, non-goals, and constraints

| ID | Type | Statement | Evidence |
|---|---|---|---|
| G-01 | goal | Run admitted benchmarks through their official/native generation and scoring paths. | User intent and current four executable adapters |
| G-02 | goal | Preserve exact provenance, native outcomes, failure classes, budgets, and official artifacts. | Evidence and qualification contracts |
| G-03 | goal | Compare only a controlled shared eligible population. | Current comparison contract |
| G-04 | goal | Export, verify, and import permanent local private proofs without the source checkout. | `private_proof_v1` |
| G-05 | goal | Add one honest SWE-bench Verified diagnostic lifecycle before any promotion decision. | User decision |
| G-06 | goal | Make Tier-2 a benchmark-specific evidence ledger, not a global test-suite label. | Production-readiness policy |
| G-07 | goal | Provide feature-complete local browser coverage for catalog, planning, execution, doctor, run/evidence history, reports, comparisons, exports, proofs, and readiness. | User decision, 2026-09-01 |
| G-08 | goal | Keep UI, CLI, and library outcomes identical by sharing typed application operations and view DTOs. | Evidence-integrity requirement |
| G-09 | goal | Measure benchmark-specific dependence by comparing a canonical population with a source-bound fresh or representation-equivalent population while preserving both native results. | User decision, 2026-09-03; E-12–E-19 |
| G-10 | goal | Capture the effective model-visible access and repository-history conditions separately from requested network policy, plus optional retrieval-audit evidence. | E-13 and E-20 |
| G-11 | goal | Establish one frontier-relevant freshness contrast with official BFCL non-live versus Live data, followed by one paired BFCL tool-order study only if the Live spike is viable. | User decision and E-19–E-21 |
| G-12 | goal | Make exposure reports state what the evidence can and cannot support instead of producing a clean/contaminated verdict or adjusted universal score. | E-12–E-18 |
| N-01 | non-goal | Provider-enforced hard-dollar termination. Cost may be measured or estimated; wall limits remain enforceable. | User decision |
| N-02 | non-goal | MOMO admission in v1. | User decision |
| N-03 | non-goal | CyberGym, ExploitGym, or other official exploit/PoC execution in v1. | User decision |
| N-04 | non-goal | Hosted or multi-user service, database, durable queue, object-store transport, signing PKI, deletion, TTL, or garbage collection. The earlier dashboard exclusion is superseded by G-07; the console remains local-only. | User decision and proportionality |
| N-05 | non-goal | Statistical or superiority claims from smoke slices. | Evidence policy |
| N-06 | non-goal | SWE promotion as part of the diagnostic implementation. | User decision |
| N-07 | non-goal | Proving that a closed model is uncontaminated, attributing intent or cheating, or certifying that a transformation is unrecognizable to a model. | Closed-model observability limits; E-12 and E-16 |
| N-08 | non-goal | A generic transform DSL/plugin platform, benchmark-wide automatic rewrite service, reference-panel-corrected score, or controlled-contamination training laboratory in the first exposure release. | Proportionality and E-14–E-18 |
| N-09 | non-goal | A BenchEval-maintained egress allow-list, patched agent runtime, forked official harness/scorer, or hidden tool/prompt modification. | User decision and official-runner boundary |
| N-10 | non-goal | Treating BFCL Live/non-live or any unpaired distribution shift as a direct contamination estimate. | E-19 |
| C-01 | constraint | Python 3.12+, `uv`, repository-owned typed configuration, stable CLI automation, and an optional Python-authored local browser console. | Live repository and user decision |
| C-02 | constraint | Runtime XOR admitted agent; omit both for model-only harnesses. | Product spine |
| C-03 | constraint | Secrets remain environment-provided and absent from config, argv, public artifacts, and durable summaries. | Project policy |
| C-04 | constraint | Test substitutes are diagnostic only and require explicit justification. | Repository policy |
| C-05 | constraint | Human intervention is reserved for literal device/subscription/CAPTCHA/hardware/admin actions or a new product decision. | User decision |
| C-06 | constraint | Finalized private proofs are kept locally and permanently; BenchEval provides no delete path. | User decision |
| C-07 | constraint | The console binds to loopback only and exposes no remote-bind mode until an explicit authentication/authorization product decision exists. | Local-first trust boundary |
| C-08 | constraint | UI state and view DTOs are projections, never systems of record; no browser storage may hold credentials, evidence authority, run lifecycle state, or proof identity. | One-source-of-truth rule |
| C-09 | constraint | `network_policy` remains the plan-time intent/runtime-requirement field for backward compatibility; effective egress/history evidence is additive and cannot be inferred from it. | E-20 |
| C-10 | constraint | Official benchmark code and scorer bytes remain pinned and unchanged. Official access knobs may be selected and recorded; derived benchmark data receives a distinct identity and stays diagnostic until separately admitted. | User decision and E-13/E-21 |
| C-11 | constraint | Relation class, behavioral fidelity, task freshness, verifier integrity, access conditions, and retrieval audit remain orthogonal evidence; no field silently upgrades another. | E-12–E-20 |
| C-12 | constraint | The primary study population is newly released frontier API models already reachable through admitted providers; a benchmark must retain headroom for that population before integration. | User brief and current model/provider scope |
| C-13 | constraint | Smoke runs prove plumbing only. Inferential claims require a declared population, comparable settings, uncertainty, and an effective sample large enough for the chosen analysis. | N-05 and E-14/E-19 |

## Unacceptable outcomes

| Outcome | Why it matters | Prevention or detection |
|---|---|---|
| A local or stale file can claim an official pass. | It invalidates the product's core evidence claim. | Official artifact is sole authority; strict schema, identity, and coherence gates; fail closed. |
| The scored bytes differ from the bytes later exported as proof. | Reviewers audit a different result than the adapter scored. | Retain the exact scored bytes under an owned path and bind a digest before descriptor release. |
| Infrastructure failures improve comparison rates. | It creates misleading runtime/model conclusions. | Shared eligible intersection and nonzero exit for invalid comparisons. |
| A charged phase starts after identity or budget failure. | It wastes spend and creates unverifiable evidence. | Validate immutable inputs and claim run-owned output before launch; use one cumulative deadline. |
| A proof import mutates outside its store or accepts self-declared omissions. | It breaks local evidence integrity. | No-follow/single-link filesystem checks, required roles, canonical inventory, verify-before-install. |
| A diagnostic is promoted implicitly. | It turns lifecycle evidence into an unsupported readiness claim. | Diagnostic interpretation is permanently ineligible for `passed`; promotion is a later explicit decision. |
| Secrets enter process arguments or a public proof. | It exposes provider access. | Environment-only credentials, redaction, denylisted private files, and public sanitizer. |
| The UI shows a pass, readiness tier, comparison headline, or cost guarantee that the canonical domain gate would reject. | A polished interface could amplify a false claim. | UI receives typed domain projections; it never derives scoring, eligibility, readiness, or cost semantics in page code. |
| Refreshing or closing the browser interrupts, duplicates, or silently retries a charged run. | It can waste spend and corrupt lifecycle history. | One in-process run-session owner, exclusive run IDs/paths, explicit cancel, no automatic mutation retry, durable manifest/evidence projection after reconnect. |
| Status is encoded only by color or inaccessible live updates. | Operators can miss blockers or destructive consequences. | Text labels and icons, keyboard paths, focus management, and polite status announcements aligned with WCAG 2.2. |
| A requested `network_policy` is reported as proof of effective sandbox access. | Planning intent can disagree with the launched harness, creating a false runtime-leakage claim. | Capture effective egress/history controls from the concrete official launch; use `unknown` or `uncontrolled` when they cannot be proven. |
| A canonical/variant gap is reported as proof of training contamination or provider cheating. | Position bias, task-format training, transform artifacts, difficulty, and verifier defects can produce the same observation. | Report benchmark-specific dependence with competing explanations and evidence strength; never emit a binary clean verdict. |
| A derived BFCL input mutates the installed package or is registered as ordinary `bfcl-v4`. | It can corrupt concurrent/canonical runs and falsely inherit official benchmark identity. | Use a run-scoped verified overlay, distinct derived identity, diagnostic interpretation, and no ordinary `passed` registration. |
| An unpaired BFCL non-live/Live gap is presented as a paired or decontaminated score. | The populations differ in composition and difficulty. | Report a stratified freshness/generalization contrast with native scores, counts, and caveats. |
| A transform is called equivalent because the scorer still runs, without fidelity evidence. | Mechanical correctness does not establish construct or behavioral fidelity. | Keep relation proof and measured fidelity separate; smoke cannot close the calibration gate. |

## Glossary

| Term | Meaning |
|---|---|
| Tier-0 | In-repository software and deterministic contract gate for an executable adapter. |
| Tier-1 | At least one qualified real attempt through the native/official lifecycle; outcome may be wrong solution. |
| Tier-2 | Benchmark-specific production-v1 ledger with every required item proven or explicitly not applicable. |
| Diagnostic | Real or local lifecycle evidence that is deliberately ineligible for passed registration. |
| Official authority | The upstream-owned result artifact or judge that alone determines the native verdict. |
| Private proof | Content-addressed, offline-verifiable internal bundle containing the run plan, evidence, history, report, official results, and referenced artifacts. |
| Captured identity | Version or digest verified against the actual bytes used for the attempt, rather than a configured claim. |
| Operator console | Optional loopback-only browser UI over the same local application operations and stores as the CLI. |
| Run session | Ephemeral in-process ownership of one launched command, its cancellation signal, and live presentation buffer; durable truth remains the run plan, manifest, evidence, and artifacts. |
| View DTO | Read-only, secret-free projection for a UI page; never a serialized storage entity or scoring authority. |
| Benchmark-specific advantage | Performance attributable to benchmark-specific items, solutions, formats, verifier quirks, or answer-bearing runtime sources rather than demonstrated transfer to an independent population. It names an observed dependence, not provider intent. |
| Training contamination | Evaluation item, answer, solution, or close semantic equivalent entered model training. It is one possible cause of benchmark-specific advantage and is usually not directly observable for closed models. |
| Runtime retrieval leakage | The evaluated agent obtains a known benchmark answer, patch, hidden test, or equivalent task-specific information during execution. It is distinct from training contamination. |
| Access condition | Effective model-visible egress and repository-history state captured from the concrete launch. It is not the requested `network_policy`. |
| Retrieval audit | Optional transcript/artifact analysis recorded as `not_run`, `no_retrieval_observed`, or `retrieval_observed`; absence of an observation is not proof of absence. |
| Relation class | Stable relation between source and candidate tasks: `representation_equivalent`, `semantic_equivalent`, `counterfactual_same_construct`, `fresh_parallel`, or `unrelated_control`. |
| Behavioral fidelity | Measured agreement or performance stability attributable to the transformation on a declared calibration population; separate from relation class. |
| Exposure study | A source-bound comparison that preserves both native result sets and reports dependence, uncertainty, access, verifier, freshness, and non-claims. |

## Critical journeys

| Journey | Current pain | Selected experience | Evidence needed |
|---|---|---|---|
| Plan and run | Catalog/config drift can otherwise reach a charged harness. | Resolve typed benchmark/slice/runtime/model/provider, validate identities, claim run files, persist the plan, then launch. | Dry-run plus native attempt. |
| Qualify and register | Exit zero or any result file can be mistaken for proof. | Qualify exact expected population, provenance, official authority, and failure class before append-only registration. | Qualified evidence and manifest history. |
| Compare | Two sides can have different eligible populations or axes. | Intersect eligible instance IDs and reject asymmetric, empty, or drifting axes. | Comparison validity reasons plus shared IDs. |
| Preserve | Host paths and mutable artifacts are not durable. | Export a canonical private proof, verify it offline, import to `sha256/<digest>`, retain permanently. | Source-removed verification/import rehearsal. |
| Add SWE diagnostic | Existing partial adapter can sequence commands but lacks immutable dataset/image binding and official aggregate coherence. | Derive both phase inputs from one pinned official row, run locked Inspect generation, then `swebench==5.0.1` evaluation under one deadline. | Uncharged materialization/schema proof, then one charged dev-box diagnostic. |
| Explore current state | Operators otherwise traverse YAML, JSONL, proof directories, and several reports manually. | Dashboard and searchable catalog/run/proof/readiness views preserve admission, tier, diagnostic, and caveat labels verbatim. | Cross-check every view against canonical readers on a real local store. |
| Plan and execute in browser | CLI argument reconstruction makes axis and diagnostic constraints easy to misunderstand. | Guided axis selection, dry-run preview, doctor results, explicit charge confirmation, one active run, live lifecycle/log view, and typed failure recovery. | Browser journey produces the same `RunPlan`, evidence, and manifest events as the CLI. |
| Analyze and preserve | Reports, comparisons, exports, registrations, and proofs are separate commands. | Run detail exposes report/compare/export/register/proof actions only when their canonical preconditions pass; generated files remain operator-selected and local. | Golden CLI-versus-UI operation parity tests plus real browser export/import rehearsal. |
| Qualify access evidence | `network_policy` does not reveal whether an agent could reach the public web or future repository history. | The adapter records the official access-control source, effective egress state, repository-history state, and optional retrieval audit without changing the runtime. | Real Inspect/Harbor/model-only probes and retained effective configuration. |
| Contrast BFCL freshness | The admitted BFCL identity covers only non-live data, so a canonical score cannot show whether it transfers to fresher functions and queries. | Verify the exact pinned Live bytes, run official generation/evaluation under a distinct research identity, and report a stratified non-live/Live contrast. | Wheel-versus-upstream digest proof, official score artifacts, declared counts, and no contamination claim. |
| Measure tool-order dependence | Canonical BFCL tool ordering may reward positional familiarity or bias. | Materialize one balanced, deterministic order permutation in a run-scoped data overlay, run the unchanged official code/scorer, and compare the same source instances pairwise. | Source/derived manifests, unchanged producer digest, native scores, directional flips, fidelity/caveats, and diagnostic-only registration state. |
| Review an exposure report | A scalar gap hides task quality, access, population mismatch, and alternative explanations. | Show native canonical/candidate scores, population relationship, uncertainty, verifier stratum, access evidence, retrieval audit, and explicit unsupported claims. | Report-schema contracts plus independent review against retained private proofs. |

## Quality scenarios

| ID | Scenario | Measure | Architecture gate |
|---|---|---|---|
| Q-01 | An adapter emits a wrong solution under a healthy official harness. | Row is eligible, `primary_pass=false`, and failure is `model_wrong_solution`. | Native Tier-1 probe and qualification. |
| Q-02 | A file, directory, symlink, hardlink, FIFO, or inode changes across a scoring boundary. | No forged pass or outside write; outcome is a typed integrity failure. | Hostile real-filesystem contracts. |
| Q-03 | One phase consumes most of a run budget. | The next phase receives only monotonic remaining time or is not launched. | Cumulative-deadline regression. |
| Q-04 | A source checkout is deleted after proof export. | The same proof digest verifies and imports from the copied artifact. | Cross-root offline verification. |
| Q-05 | A later manifest event omits fill-once axes. | Projection retains earlier values; a different non-null value is rejected. | Raw-history and projection contract. |
| Q-06 | SWE Inspect and official evaluator inputs are derived. | Both trace to the same pinned parquet row, deterministic transformation manifest, and execution-time image digest. | Uncharged compatibility/materialization test plus retained live artifacts. |
| Q-07 | The same selections are planned through CLI and UI. | Canonical serialized `RunPlan` bytes and validation failures match; the UI adds no hidden defaults. | Application-service parity contract. |
| Q-08 | A browser reconnects during an active run. | No second launch occurs; the page reattaches to the sole in-memory session or falls back to durable current-state projection. | Real-browser reconnect test with a real bounded local subprocess. |
| Q-09 | The console process restarts after a completed or failed run. | Catalog, manifest projection, evidence, reports, artifacts, and proofs reappear from canonical files; no database recovery exists or is needed. | Restart/reload browser test over a disposable real results root. |
| Q-10 | An operator navigates and starts a dry run without a pointer. | All controls, focus order, validation, dialogs, and status messages are usable and visible by keyboard. | Playwright/NiceGUI browser accessibility journey plus automated axe scan. |
| Q-11 | A catalog item is pending, diagnostic-only, scaffold, or ineligible. | Its non-executable state is textual, cannot be bypassed by crafted UI state, and no launch/output reservation occurs. | Direct application-service negative contracts and browser disabled-state test. |
| Q-12 | A RunPlan requests `benchmark_required`, but the official task disables sandbox egress. | Evidence records the requested policy and effective blocked egress separately; neither overwrites the other. | Pinned Inspect SWE launch/config probe and evidence contract. |
| Q-13 | Harbor cannot prove container egress restriction. | The attempt remains valid for its official native result but records effective egress as `uncontrolled` or `unknown`; no retrieval-hardened claim appears. | Real Harbor plan/launch evidence and report negative assertion. |
| Q-14 | A retrieval auditor finds a known patch or answer in a transcript. | Native pass/fail is preserved, `retrieval_observed` is retained, and stronger novelty/exposure interpretations are disallowed. | Retained transcript/audit artifact with a discriminating report test; auditor result is never scoring authority. |
| Q-15 | BFCL Live files in the wheel differ from the pinned upstream commit or are incomplete. | No Live study launch occurs and no identity is emitted. | Exact ten-file digest and category-command compatibility spike. |
| Q-16 | A BFCL tool-order variant is materialized. | Installed package bytes remain untouched; run-scoped code/scorer bytes match the pin; only declared data bytes differ and every derived row maps to one source row. | Real filesystem/package-overlay proof plus manifest replay. |
| Q-17 | Canonical and tool-order evidence have missing, duplicate, asymmetric, or differently configured instances. | The paired exposure report is invalid and exits nonzero; no headline gap is shown. | Hostile paired-population contracts and exact-axis checks. |
| Q-18 | A smoke or unpaired Live contrast completes successfully. | The report says plumbing or freshness/generalization only and emits no significance, clean-model, cheating, or contamination estimate. | Report golden/negative contracts and reviewer inspection. |

## Research landscape and selected concept

| Capability | Existing route | Decision | Reason / limit |
|---|---|---|---|
| Runtime-leakage control | Official benchmark/runtime knobs and captured effective config | adopt when available | Preserves the official runner. BenchEval does not build a network allow-list; unsupported controls remain `unknown`/`uncontrolled`. |
| Runtime retrieval detection | Transcript/artifact audit, optionally assisted by a versioned LLM judge | adapt as diagnostic evidence | A positive observation is useful; a negative observation cannot prove absence and never changes the native score. |
| Freshness contrast | BFCL Live versus pinned non-live categories | adopt for first spike | Relevant to frontier tool-use models and official scorer; populations are unpaired and distribution-shifted. |
| Representation-equivalent variant | Balanced BFCL tool-declaration order permutation | build one narrow adapter-owned materializer after the Live spike | No output inverse mapping or scorer change; still needs a distinct identity, run-scoped data overlay, and fidelity/position-balance evidence. |
| General transformation platform | Generic DSL/plugins/inverse mappings across benchmarks | reject now | No second proven transform family; it would add abstraction before evidence demonstrates value. |
| Functional/dynamic math | MATH(), DyVal, GSM-Symbolic/GSM1k | defer as diagnostic research | Useful prior art but uncertain frontier-model headroom and outside the admitted official-harness set. |
| Controlled contamination laboratory | Fine-tuned clean/contaminated open-model pairs | defer | Requires training infrastructure and does not directly establish transfer to closed frontier pretraining. |
| Provider-side governance | private held-out sets, canaries, training-data attestations | consume as external evidence | Useful but curator/provider-controlled and not independently enforceable by BenchEval. |

### Selected base: local control plane with CLI and optional operator console

Adopt official/native harnesses for benchmark semantics; build only the narrow
control plane, evidence normalization, qualification, comparison, proof
integrity, and operator presentation that upstream harnesses do not provide.
The CLI remains the stable automation boundary. The implemented console is a
loopback-only NiceGUI surface inside the same Python process and calls shared
typed application operations directly. This keeps one deployable unit, one
permanent local proof store, no public API, and no database while making the
full product navigable. Scoring authority remains outside BenchEval.

For SWE, adapt the already locked Inspect Evals `0.8.0` + Inspect SWE `0.2.47`
generation path so it runs the selected exact Codex or Claude Code binary, then
score only with exact-pinned `swebench==5.0.1`. Both phases receive deterministic
run-owned inputs derived from the same official Verified parquet row. The Inspect
representation canonically JSON-encodes the two list fields required by the old
task loader; the official-evaluator representation preserves the official row
shape and binds the resolved platform image digest. A transformation record and
hashes make the adaptation auditable.

### Front-end route decision

- **NiceGUI, selected for spike/adoption:** Python-native and backend-first,
  runs in a browser or native window, supports long-running async work, tables,
  downloads, and real-browser tests. It preserves the single-process local
  shape and lets domain DTOs stay in Python.
- **Reflex, rejected for this slice:** maintained and Apache-2.0, but its
  [documented self-hosted topology](https://reflex.dev/docs/hosting/self-hosting/)
  separates frontend and backend with an API URL. That is a credible future
  route if frontend independence becomes a goal, but it adds a runtime boundary
  BenchEval does not currently need.
- **React/Vite plus FastAPI, rejected now:** strongest independent frontend
  ecosystem, but requires a Node build, a stable HTTP API, duplicated contract
  generation, and two runtime units before a multi-user or remote requirement
  exists.
- **Textual TUI, rejected for the requested prototype:** useful for terminal-
  only operation, but it does not satisfy the requested browser-grade visual
  dashboard and artifact/report workflows.

### Rejected alternatives

- **Hosted service or orchestration plane:** adds auth, database, scheduling,
  retention, and operational ownership without a current user need.
- **BenchEval-authored scoring:** duplicates upstream semantics and weakens the
  official-authority boundary.
- **mini-SWE under a runtime label:** mini-SWE is a distinct scaffold; using it
  while claiming the selected Codex/Claude runtime would make the axis false.
- **Harbor as the first SWE official proof:** useful for a later adapted-runtime
  comparison, but not identical to the direct official evaluator lifecycle.
- **Two separately sourced SWE snapshots:** creates avoidable identity drift;
  the compatibility probe proved both inputs can be derived from one official
  pinned parquet.
- **Remote proof store or signatures now:** local content integrity and offline
  portability satisfy v1. Creator authenticity and shared discovery are separate
  future requirements, not present blockers.
- **UI shelling out to `bencheval`:** would make stdout parsing and process
  arguments a second internal API. Extract and share typed application
  operations instead.

### Exposure extension candidates

#### Candidate A: labels and research notes only

Keep running canonical benchmarks and add caveat prose. This has almost no
engineering cost, but cannot reproduce a source/candidate population, enforce
identity or population symmetry, retain effective access evidence, or compute a
reviewable gap. It does not deliver the requested product value and is rejected.

#### Candidate B: narrow evidence-bound studies over official runners — selected

Keep every canonical run and official scorer unchanged. Add a small study
contract that binds source/candidate identities, relation class, population,
access evidence, and permitted interpretation. First consume official BFCL Live
as an unpaired freshness contrast; then materialize exactly one run-scoped,
balanced BFCL tool-order variant and score it with byte-identical official code.
Runs remain ordinary evidence/proofs; a read-only study report validates and
compares them. This adds no service, scheduler, database, runtime fork, custom
network plane, universal score, or general transform framework.

#### Candidate C: generic benchmark morphism platform

Define a transform DSL, plugin registry, inverse-output mappings, automatic
multi-seed orchestration, reference-panel correction, and adapters for several
benchmarks. This could become useful after two independent transform families
prove the same abstraction, but it is premature and creates exactly the hidden
benchmark reimplementation boundary the product currently avoids. Rejected for
the first release; revisit only on measured second-family demand.

#### Candidate D: controlled runtime/training laboratory

Patch or wrap runtimes to restrict tools/network and fine-tune controlled model
pairs on canonical/variant data. This offers stronger causal research but changes
the evaluated runtime, requires new training/compute operations, and does not
match the current closed-frontier model pool. Rejected as a BenchEval product
responsibility; external studies may be retained as supporting evidence.

### Adversarial review of the selected extension

| Challenge | Revision to the concept |
|---|---|
| A transform can preserve the scorer while changing model difficulty. | Separate stable relation class from measured behavioral fidelity; no tier bypasses calibration. |
| A public task can still be memorized after network/history controls. | Access evidence never creates a `novel_problem_solving` claim by itself; freshness/exposure relation remains independent. |
| A retrieval-audit judge can miss or hallucinate retrieval. | Treat it as one-way diagnostic evidence; preserve auditor identity/artifact and never change native scoring. |
| `network_policy` already exists and could be overloaded. | Preserve it as plan intent; capture effective access separately because current adapters demonstrably disagree with the requested value. |
| BFCL Live is harder and differently distributed. | Report only a stratified freshness/generalization contrast; do not call it paired or decontaminated. |
| Random order seeds can create seed lottery and provider cost. | Use one deterministic balanced permutation first; add seeds only if measured variance earns them. |
| BFCL CLI has no custom question-file flag. | Use a verified run-owned package-data overlay, never mutate the installed package or patch official code/scorer. |
| Frontier models may saturate old math variants. | Select the current frontier API pool first and start with BFCL; keep MATH()/DyVal diagnostic and deferred. |
| A small successful slice invites a contamination headline. | Smoke is plumbing-only by contract; inferential output requires declared population, uncertainty, and non-claims. |

## Production path and remaining uncertainty

The current control-plane path is established: four executable benchmarks hold
Tier-1 evidence, portable private proof exists, the local console is implemented,
and SWE has a retained demoted diagnostic. No benchmark is claimed Tier-2. The
next product path is the selected exposure extension: prove effective-access
capture, run the BFCL Live freshness contrast, then decide whether the BFCL
tool-order study earns a production-shaped implementation. The codebase has no
current product-decision blocker and no standing HITL blocker. Host provisioning,
artifact transfer, dependency installation, credential-presence checks, and
uncharged probes are automatable. Pause only if a runtime presents a literal
human-only action covered by C-05.

Open evidence and console work is intentionally narrow:

1. GPQA exact-byte retention and legacy private-bundle fail-closed export are
   implemented; historical Aug 25 GPQA remains a valid Tier-1 object.
2. Proof transfer is implemented; imported `private_proof_v1` objects verify
   structurally. HLE post-fix smoke `sha256:4be3b7cd…f4b62b` stamps
   `hle@5a81a4c7271a2a2a+data-6d0ee0602e8aea6b` after ambient-copy removal.
3. SWE remains demoted. Retention-bound diagnostic `sha256:5f7f79ce…373e52`
   scores the run-owned official-dataset row, stamps the verified identity,
   retains source/transform/Inspect-log bytes, and stamps
   `runtime_version=0.148.0`. Schema-v2 `error_ids` means no executed
   `report.json`; `cleanup_result=skipped`.
4. Complete benchmark-specific Tier-2 ledgers without claiming Tier-2. BFCL
   cleanup replay is `not-applicable`: `results/` and `scores/` are retained
   official evidence, not named transients.
5. Maintain the console as the `ui` optional extra. Its complete operation
   surface shares canonical domain functions with the CLI; the core import stays
   NiceGUI-free. Cross-browser accessibility, bounded-scale measurement, and a
   charged console launch remain hardening evidence rather than implied readiness.

### Selected exposure HLD

The extension remains inside the current single-process control plane. Canonical,
Live, and derived BFCL executions use the same provider route and official BFCL
code/scorer. An additive evidence projection records effective access separately
from `network_policy`. A small versioned study manifest binds the expected
source/candidate populations and relation class. A BFCL-owned materializer may
create a run-scoped data overlay, but no generic transform runtime exists. A
read-only report validates both evidence sets before calculating native-score
contrasts, directional flips, uncertainty, and explicit interpretation limits.
Private proof retains the study manifest and exact source/derived bytes; it does
not authenticate provider training data or transform a diagnostic into native
benchmark admission.

### First production slice

1. Verify the exact `bfcl-eval==2026.3.23` wheel against the ten pinned Live
   files from upstream commit `6ea57973…`; prove official generate/evaluate can
   score a tiny Live sample. This is a compatibility/plumbing spike only.
2. Capture effective access evidence for one model-only run, pinned Inspect SWE,
   and Harbor without changing any runtime or launch profile. The three paths
   must respectively demonstrate `not_applicable`, official network-disabled,
   and uncontrolled/unknown agent egress rather than inheriting `network_policy`.
3. Run an unregistered BFCL Live research population with a distinct identity
   and produce a stratified non-live/Live report. It may claim freshness and
   generalization evidence, never a contamination estimate.
4. If the Live path and report are useful, materialize one balanced BFCL
   `multiple`/`parallel_multiple` tool-order variant in a run-owned overlay,
   preserve the official code/scorer digest, run the same frontier model/settings,
   and produce a paired diagnostic report. Smoke proves plumbing; a declared
   larger population is required before inferential language.

### Open questions and spikes

| Question | Why it matters | Resolution |
|---|---|---|
| Does the PyPI wheel contain byte-identical pinned Live data and accept the required categories? | Without this, a Live identity or launch would be invented. | Dev-box compatibility spike; no HITL unless provider/runtime presents a literal human action. |
| Can a run-scoped BFCL package overlay preserve every official code/scorer byte while loading only the derived data? | This is the minimum no-fork route for tool-order variants. | Uncharged package-overlay spike with before/after digests and official CLI invocation. |
| What full or stratified population retains headroom for the current frontier model pool within a reasonable budget? | Smoke is statistically meaningless; an unnecessarily saturated or huge run wastes spend. | Use official category counts plus a small unregistered pilot, then record a power/precision target before the charged study. |
| Does one balanced order variant produce interpretable directional flips beyond ordinary provider variance? | A generic framework is unjustified if the first transform adds no information. | Repeat only enough canonical attempts to estimate run variance; compare against the paired variant before any abstraction. |
| Is an LLM-assisted retrieval audit useful enough to retain? | It can add positive evidence but may be costly and unreliable. | Defer until a real transcript corpus exists; version the auditor and keep it diagnostic if adopted. |

### Handoff to architecture and roadmap

`arch-roadmap` must preserve the single-process/local proof architecture, the
official-runner and no-custom-egress decisions, additive evidence compatibility,
relation/fidelity separation, diagnostic-only derived identities, and the
Live-before-variant order. It must define source ownership for the study contract,
effective-access capture, BFCL materializer/overlay, report validation, CLI/UI
projection, private-proof roles, and discriminating real-run gates without
creating a generic transform plugin system.

Reopen the selected local/single-user concept only if operators need multi-host
coordination, remote or concurrent users, shared proof discovery, creator
authenticity, automated retention/deletion, a new admitted agent, a dual-use
execution lane, a second proven transform family, or a new class of statistical
benchmark claim.
