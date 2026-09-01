# BenchEval Concept Zero

Status: ACCEPTED CLI concept and implemented local operator-console extension.
Implementation and live-evidence status remain tracked in
[`../roadmap.md`](../roadmap.md).

Last updated: 2026-09-01

## Executive decision

BenchEval is a local-first, operator-run Python control plane for producing
comparable, auditable benchmark evidence from official or native benchmark
harnesses. The existing CLI remains the stable automation surface; a proposed
loopback-only browser console makes every current operator journey visible and
actionable without creating a second scoring, planning, or persistence path.
Its primary user is an engineer who needs to distinguish model, runtime,
harness, and infrastructure effects without turning a smoke run into a quality
claim. The production path is one checkout, one Python process, operator-
provisioned harnesses and credentials, append-only evidence, and permanent local
content-addressed proof bundles that verify offline. BenchEval deliberately does
not become a hosted service, multi-user scheduler, billing system, benchmark
reimplementation, general agent platform, or offensive execution platform.

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

## Users and stakeholders

| Actor | Need | Constraint | Success signal |
|---|---|---|---|
| Benchmark operator | Run a small official lifecycle and retain everything needed to audit it. | External harnesses, images, credentials, and disk remain operator-provisioned. | A qualified evidence set and an offline-verifiable private proof. |
| Model/runtime engineer | Compare one controlled axis without infrastructure rows improving the headline. | Smoke samples are not statistical rankings. | Comparison uses the shared eligible intersection and names contamination. |
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
| N-01 | non-goal | Provider-enforced hard-dollar termination. Cost may be measured or estimated; wall limits remain enforceable. | User decision |
| N-02 | non-goal | MOMO admission in v1. | User decision |
| N-03 | non-goal | CyberGym, ExploitGym, or other official exploit/PoC execution in v1. | User decision |
| N-04 | non-goal | Hosted or multi-user service, database, durable queue, object-store transport, signing PKI, deletion, TTL, or garbage collection. The earlier dashboard exclusion is superseded by G-07; the console remains local-only. | User decision and proportionality |
| N-05 | non-goal | Statistical or superiority claims from smoke slices. | Evidence policy |
| N-06 | non-goal | SWE promotion as part of the diagnostic implementation. | User decision |
| C-01 | constraint | Python 3.12+, `uv`, repository-owned typed configuration, stable CLI automation, and an optional Python-authored local browser console. | Live repository and user decision |
| C-02 | constraint | Runtime XOR admitted agent; omit both for model-only harnesses. | Product spine |
| C-03 | constraint | Secrets remain environment-provided and absent from config, argv, public artifacts, and durable summaries. | Project policy |
| C-04 | constraint | Test substitutes are diagnostic only and require explicit justification. | Repository policy |
| C-05 | constraint | Human intervention is reserved for literal device/subscription/CAPTCHA/hardware/admin actions or a new product decision. | User decision |
| C-06 | constraint | Finalized private proofs are kept locally and permanently; BenchEval provides no delete path. | User decision |
| C-07 | constraint | The console binds to loopback only and exposes no remote-bind mode until an explicit authentication/authorization product decision exists. | Local-first trust boundary |
| C-08 | constraint | UI state and view DTOs are projections, never systems of record; no browser storage may hold credentials, evidence authority, run lifecycle state, or proof identity. | One-source-of-truth rule |

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

## Research landscape and selected concept

### Selected: local control plane with CLI and optional operator console

Adopt official/native harnesses for benchmark semantics; build only the narrow
control plane, evidence normalization, qualification, comparison, proof
integrity, and operator presentation that upstream harnesses do not provide.
The CLI remains the stable automation boundary. The proposed console is a
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

## Production path and remaining uncertainty

The credible production path is incremental: keep the four admitted adapters at
Tier-1, close proof-retention gaps, create benchmark-specific Tier-2 ledgers and
portable proofs, then implement and run one SWE diagnostic. The codebase has no
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

Reopen the selected local/single-user concept only if operators need multi-host
coordination, remote or concurrent users, shared proof discovery, creator
authenticity, automated retention/deletion, a new admitted agent, a dual-use
execution lane, or statistical benchmark claims.
