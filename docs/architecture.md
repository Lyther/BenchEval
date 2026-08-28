# Architecture & Decisions

> **Status:** ACCEPTED current system; PROPOSED remaining v1 extensions (reconciled 2026-08-26). Source concept: [`docs/context/concept-zero.md`](context/concept-zero.md); implementation tracked in [`docs/roadmap.md`](roadmap.md)
> **Supersedes:** vNext v0.2 (ACCEPTED 2026-05-29, Core-first) — preserved as `legacy_static` context only
> **Operator contract / product SoT:** root [`README.md`](../README.md), this file, and [`docs/api/internal-contracts.md`](api/internal-contracts.md). [`docs/context/concept-zero.md`](context/concept-zero.md) owns product intent and constraints. [`docs/context/concept-hld.md`](context/concept-hld.md) is a **historical design ledger**, not live CLI instructions.
> **Scope:** Defined benchmarks → (runtime XOR agent)? → model via provider → evidence.

## 0. Product Principles

1. **Simple spine.** Product path is `benchmark → (runtime|agent)? → model → evidence`. Runtime and agent are mutually exclusive axes; omit both for the executable model-only paths (GPQA/HLE/BFCL). A cataloged agent scaffold is not executable until separately admitted.
2. **Defined benchmarks only.** Live execution is limited to config-declared executable adapters.
3. **Official-first execution.** Prefer official distributions, runners, and scorers. BenchEval normalizes evidence; it does not reimplement benchmark semantics unless upstream has no usable feedback path (then label it as fallback).
4. **Config-first expansion.** New slices/runtimes/models/agents/providers on an existing adapter family are YAML/manifest work.
5. **Runtime-owned environments.** Benchmarks and selected runtimes own sandboxes/containers. BenchEval does not ship a separate Docker plane.
6. **Evidence over claims.** Reports preserve native artifacts and caveats; smoke ≠ full benchmark claim; green tests are not live proof.

### 0.1 Concept traceability

- `G-01` / `G-02` official execution and provenance drive AR-01–AR-06 and AR-16: adapters own preflight, official authority, exact-byte retention, and typed failure separation.
- `G-03` controlled comparison drives AR-07; only a shared eligible population with constant non-varied axes can produce a valid headline.
- `G-04` durable evidence and `C-06` permanent local retention drive AR-12 and AR-14: `private_proof_v1` is offline-verifiable and has no delete lifecycle.
- `G-05` SWE diagnostic-first and `N-06` no implicit promotion drive §18.1: a real diagnostic remains ineligible for `passed` until a later product decision.
- `G-06` benchmark-specific readiness drives AR-09 and the Tier-2 ledgers.
- `C-01` / `C-02` keep one Python CLI and the runtime-XOR-agent spine. `C-03` keeps credentials environment-only. `C-04` keeps substitute proof diagnostic. `C-05` defines the narrow human-intervention boundary.
- `N-01`–`N-05` exclude hard-dollar control, MOMO admission, dual-use execution, service/storage expansion, and smoke-derived superiority claims from v1.

## 1. Product Shape (v1)

BenchEval is a thin evaluation control plane:

> Given a **defined** benchmark (or slice), an optional runtime XOR agent, a provider-bound model, what happened, how expensive was it, and what evidence supports the result?

```text
benchmark/slice  →  (runtime | agent)?  →  model via provider  →  EvidenceRecord + artifacts
```

**Tier-0 executable software (gate count = 4):** `terminal-bench`, `gpqa-diamond`, `hle`, `bfcl-v4`. Catalog lists `swe-bench-verified` as non-executable: the official generation→evaluation diagnostic is implemented and remains ineligible for `passed` or auto-promotion (`bfcl-v4` was admitted 2026-08-24 on the diagnostic-labeled dev-box lifecycle demonstration `run-20260824-040631-228703-4756f857` plus the registered `passed` run `run-20260824-045622-854659-a46ae44d`), plus `swe-bench-pro`, `cybergym`, and `exploitgym` as `adapter_pending`.

**Live-proof status:** `bfcl-v4`, `hle`, `gpqa-diamond`, and `terminal-bench` hold registered Tier-1 evidence. Terminal-Bench is one native `fix-git` attempt per admitted runtime (`claude-code` `run-20260825-173913-754489-4f43e296`, `codex-cli` `run-20260825-171829-685914-aa08dd1d`), both `model_wrong_solution` with official `reward == 0.0`, plus a valid shared-axis runtime compare (`comparison_valid`, `contaminated_or_legacy`). No benchmark is called Tier-2 until its benchmark-specific checklist is complete. `swe-bench-verified` remains non-executable: official generation and evaluation are one evidence-bound diagnostic lifecycle and never auto-promote the row.

**Admitted execution profiles:** runtimes `claude-code`, `codex-cli`; providers `bytellm`, `ollama-cloud`. `momo` remains a discoverable **scaffold only**: planning or direct execution with it must fail before output reservation or provider/agent launch until a later admission decision.

## 2. Identity axes

```text
benchmark_id / slice_id  = what is being evaluated
model_id / provider_id   = model + how it is reached
runtime_id XOR agent_id  = optional scaffold (never both; both null = model-only)
adapter_id = BenchEval adapter selected by config
harness_kind = derived run-plan/evidence metadata declared by the adapter, not benchmark YAML
```

CLI: `bencheval run <bench>/<slice> --model <id> [--runtime|--agent] [--provider bytellm]`. `--dry-run` = phase 1 only; `-y` skips the continue prompt.

## 3. System Diagram

Full layered set: **[`docs/diagrams/`](diagrams/README.md)** — start at [system overview](diagrams/system-overview.md).

```mermaid
flowchart LR
    U[User CLI] --> BP[Run Planner]
    BR[Executable benchmarks] --> BP
    SM[Slice manifests] --> BP
    MR[Model registry] --> BP
    PR[Provider registry] --> BP
    RR[Runtime registry] --> BP
    AG[Agent registry] --> BP

    BP --> PF[Preflight / Doctor]
    PF --> AD[Adapter dispatcher]

    AD --> A1[TB / Harbor]
    AD --> A2[GPQA / Inspect Evals]
    AD --> A3[HLE / CAIS scripts]
    AD --> A4[BFCL / bfcl-eval]
    AD --> A5[SWE diagnostic, demoted]
    AD --> A6[External agent scaffold]

    A1 --> EN[Evidence normalizer]
    A2 --> EN
    A3 --> EN
    A4 --> EN
    A5 --> EN
    A6 --> EN
    EN --> ES[Evidence store]
    ES --> CP[Compare / Report / Export]
```

## 4. Stack Selection

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | **Python 3.12** | Already set; matches Inspect ecosystem. |
| Package manager | **`uv`** | Already set (`pyproject.toml`). |
| Build backend | **hatchling** | Already set. |
| Config format | **YAML** | Human-diffable, lintable, versioned. `config/*.yaml`. |
| Validation | **Pydantic v2** | Already in deps. Used for `BenchmarkContract`, `SliceManifest`, `RuntimeProfile`, `ModelProfile`, extended `EvidenceRecord`. `frozen=True, extra="forbid"` per repo convention. |
| CLI | **argparse** (`bencheval` entrypoint) | Already set; extend `cli.py`, don't replace. |
| Evidence store | **JSONL** (primary) + **Parquet/DuckDB** (analytics) | JSONL now; DuckDB/Parquet via existing `analytics` extra (`duckdb`, `pyarrow`) and `export.py`. **No database** — this is a CLI tool. |
| Harness adapters | **External binaries, not vendored** | Harbor = external CLI (`uv tool install harbor`) and may use Docker internally; Inspect = optional `eval` extra; native/external-command = subprocess. Core library stays dependency-light (no `eval` requirement for core). |
| Orchestration (heavy) | **Inspect AI** (optional `eval` extra) + **Harbor** (external) | Provider abstraction + sandbox; never reimplement benchmark semantics. |
| Sandbox ownership | **Runtime-owned** | BenchEval does not ship a Docker plane. Official benchmark runtimes own containers/images when they require them. |
| Terminal/verifier-heavy | **Harbor or external command profiles** | Optional E2 paths; not mandatory for all tasks. |
| Testing | **pytest** | Already set. |
| Lint | **ruff** (E/F/I/W, line 100) | Already set. Type-check via ruff; no pyright in repo. |
| Secret store | **`.env` only** | `config/models.yaml` must stay non-secret (AGENTS.md rule). |

## 5. Component Responsibilities

| Component | Responsibility | Status | Module(s) |
|---|---|---|---|
| Benchmark Registry | Catalog runnable benchmarks, adapters, source, license, native harness, metrics, caveats. | **Implemented:** `benchmark_registry.py` + `config/benchmarks.yaml` (**8** product entries, **4** executable). | `benchmark_registry.py` |
| Slice Manifest Registry | Typed `smoke`/`lite`/`full`/`custom` instance lists with budget + labels. | Product slices keep instance ids inline; `manifest.py` remains for optional large/generated external lists. | `manifest.py` (+ `slice_manifest.py`) |
| Model Registry | Model identity, provider, pricing, context limits, version capture. | **Implemented:** `config/models.yaml` + `pricing/` + model registry/types. | `model_registry.py`, `models.py`, `pricing.py` |
| Runtime Registry | Admitted runtimes (`claude-code`, `codex-cli`) + capability metadata. | `runtime_registry.py` + `config/runtimes/*.yaml`. | `runtime_registry.py` |
| Agent Registry | Catalog agent scaffolds and their admission state; only `admitted` profiles may enter a plan. MOMO is currently `scaffold`. | `agent_registry.py` + `config/agents/*.yaml`. | `agent_registry.py` |
| Provider Registry | Admitted providers (`bytellm`, `ollama-cloud`). | `provider_registry.py` + `config/providers/*.yaml`. | `provider_registry.py` |
| Run Planner | Build `RunPlan` from benchmark + slice + model + (runtime\|agent) + provider. | `benchmark_plan.py` (phase 1 of `run`). | `benchmark_plan.py` |
| Preflight / Doctor | Runtime/provider env checks before live runs (never prints secrets). | `doctor.py`. | `doctor.py` |
| Materialization Manager | Cleanup policy + adapter-owned ephemeral dirs. | `lifecycle.py` (`CleanupPolicy`); adapters own workspace layout. | `lifecycle.py` |
| Adapter Dispatcher | Route plan → adapter (runtime XOR agent XOR model-only). | `control_plane_executor.py`. | `control_plane_executor.py` |
| Adapters | Harbor TB, GPQA, HLE, BFCL; the SWE diagnostic module remains non-executable; SWE-Pro / ExploitGym / CyberGym are pending. | Tier-0 executable set in YAML. | `terminal_bench_harbor.py`, `gpqa_adapter.py`, `hle_adapter.py`, `bfcl_native_adapter.py`; the SWE diagnostic module and pending adapter modules |
| Evidence Normalizer | Convert native output → `EvidenceRecord`. | `evidence.py`. | `evidence.py` |
| Evidence Store | Evidence JSONL + optional Parquet/DuckDB export. | `evidence.py`, `export.py`. | as listed |
| Compare/Report/Export | Markdown/JSON reports + cross-run comparisons + run bundles. | `report.py`, `evidence_compare.py`, `export.py`, `run_bundle.py`. | as listed |
| Dashboard | UI over stored evidence. | **Post-MVP** (non-goal now). | — |

## 6. Execution Profiles

Live product paths use upstream-owned harnesses: Harbor/Docker for Terminal-Bench, Inspect Evals for GPQA, the CAIS scripts for HLE, and `bfcl-eval` for BFCL. Historical E0–E4 labels below are planning vocabulary only — Inspect and `bfcl-eval` are benchmark harnesses, not admitted product runtimes.

| Profile | Name | Used for | Notes |
|---------|------|----------|-------|
| E0 | Model-only / API | Official model-only benchmark harness | GPQA / HLE / BFCL |
| E1 | Runtime sandbox | Coding / repo tests under admitted runtime | Runtime-owned |
| E2 | Terminal / harness sandbox | Terminal, multi-step verifier-heavy | Harbor for TB; harness-owned |
| E3 | Calibration external | Public micro-slices | Adapter-backed; never Core-weighted |
| E4 | Stretch sandbox | Expensive official-harness runs | Explicit review; research unless admitted |

Dry-run planning reports `requires_harbor` / `requires_sandbox` when needed. Those flags are operator preflight signals, not a BenchEval-owned Docker plane. `recommended_profile` is catalog planning vocabulary: E3 does not itself imply a sandbox, while E4 does. New evidence normalizes the concrete launch to E0 (model-only), E1 (non-Harbor sandbox), or E2 (Harbor); E3/E4 remain valid when reading historical evidence.

## 7. Data Contracts

### 7.1 Benchmark Contract (`config/benchmarks.yaml`)

Existing product YAML registry is the authoritative catalog (**8** entries; **4** Tier-0 executable). Schema: `BenchmarkCatalog`/`BenchmarkEntry` in `benchmark_registry.py` (Pydantic, `frozen=True, extra="forbid"`). Fields: id, name, aliases, category, tier (`calibration`/`stretch`/`reference_only`), adapter_status (`cataloged`/`adapter_pending`/`manifest_available`/`unverified`), recommended_backend, recommended_profile, task_count, public_indexed, contamination_risk, single_mode_required, source_url, notes, `default_slice`, `adapter_id`, and `executable`. Ops manuals: `docs/ops/benchmarks/`. `harness_kind` is deliberately **not** configurable in benchmark YAML: the adapter implementation declares the official runner kind used for planning and evidence metadata. New harness families need a Python adapter + executor wiring + official score ingestion; config-only expansion applies when reusing an existing adapter family.

### 7.2 Slice Manifest (new typed layer)

```yaml
schema_version: "0.1"
slice:
  id: "swe-bench-verified-smoke-10"
  benchmark_id: "swe-bench-verified"
  purpose: "adapter_smoke"           # adapter_smoke | rough_regression | benchmark_native_claim | runtime_comparison | model_comparison
  selection_policy: "fixed_instance_ids"
  instances:
    - django__django-11099
    - sympy__sympy-18087
  valid_for: ["adapter_smoke", "rough_regression"]
  invalid_for: ["model_comparison"]
budget:
  max_instances: 10
  max_wall_clock_sec_per_instance: 900
  max_total_cost_usd: 50
labels:
  contamination_warning: true
  public_benchmark: true
```

Product slice YAML keeps small fixed instance lists inline. Large generated manifests can still use `instances_source`, but no product benchmark depends on a separate `*-smoke.txt` file.

### 7.3 Runtime Profile (`config/runtimes/<id>.yaml`)

Per HLD §6.2. Pydantic `RuntimeProfile`: id, kind, display_name, lifecycle, supported_platforms, supported_harnesses, model_binding, launch (command_template, working_dir_policy, env vars, timeout), capabilities, safety (network_default, workspace_boundary, forbidden_features), versioning (version_command, config_hash_inputs). **Admitted profiles now:** `claude-code`, `codex-cli`. Agent profiles live under `config/agents/` and carry a closed `scaffold | draft | admitted` state; MOMO is `scaffold` and non-executable. Providers live under `config/providers/` (`bytellm`, `ollama-cloud`).

### 7.4 EvidenceRecord v0.3 — additive extension (no breaking change)

`EvidenceRecord` is a **public export** (AGENTS.md fact). v0.3 **extends, does not restructure**, the v0.2 flat schema. New optional fields (default to keep v0.2 rows valid):

```python
class EvidenceRecord(BaseModel):
    # --- v0.2 (unchanged, frozen contract) ---
    run_id, task_id, model_id, execution_profile, backend
    primary_pass, partial_score, cost_usd, latency_sec
    failure_labels, artifact_paths, verifier_log_path, adapter_metadata, created_at
    # --- v0.3 additive (optional, default empty/None) ---
    benchmark_id: str | None = None
    benchmark_version: str | None = None
    slice_id: str | None = None
    adapter_id: str | None = None
    harness_kind: str | None = None
    harness_version: str | None = None
    runtime_id: str | None = None
    runtime_version: str | None = None
    runtime_kind: str | None = None
    runtime_config_hash: str | None = None
    agent_id: str | None = None
    provider_id: str | None = None
    provider_config_hash: str | None = None
    judge_model_id: str | None = None
    instance_id: str | None = None
    steps: int | None = None
    token_usage: dict[str, int] | None = None
    native_score: dict[str, JsonValue] | None = None
    normalized_score: float | None = None
    contamination_label: str | None = None
    reward_hack_risk_label: str | None = None
    verifier_integrity_label: str | None = None
    cleanup_result: str | None = None
    interpretation_label: str | None = None   # adapter_smoke | rough_regression | ...
    failure_class: str | None = None
    attempt_validity: str | None = None       # valid | invalid
    invalid_reason: str | None = None
    counts_toward_pass_at_k: bool | None = None
    physical_launch_id: str | None = None
    logical_attempt_number: int | None = None
    runtime_output_cap: int | None = None
```

Nested `run`/`model`/`runtime`/`attempt`/`artifacts`/`integrity` blocks from HLD §9.3 are **not** adopted as the on-disk shape (would break v0.2 readers); they remain a *report projection* only.

## 8. Adapter Rule

Adapters **prefer native harnesses**. Product v1 allowed shapes:

1. **Native wrapper** — call the official runner/scorer, parse its result files, and preserve raw artifacts (GPQA/HLE/BFCL today; future adapters must meet the same bar).
2. **Harbor wrapper** — Harbor-native terminal tasks (Terminal-Bench 2.1).
3. **External agent wrapper** — retained scaffold mechanics via `external_agent_adapter.py`; no agent profile is admitted in v1.

Deferred / not product: Inspect-as-runtime wrappers. Compatibility shims must be explicitly labeled `adapter_smoke`.

**Forbidden:** copying public benchmark instances into custom Core tasks and treating them as BenchEval-native.

### 8.1 Official lifecycle contract

Every adapter family has an explicit, code-owned lifecycle. Configuration selects a declared adapter; it never supplies executable code or scoring semantics.

```text
resolve typed slice and immutable identities
  → preflight and fail-before-charge checks
  → reserve run/evidence/artifact ownership
  → invoke the pinned official generator or harness
  → invoke the pinned official evaluator/judge when generation alone is not authoritative
  → bind the exact official result to the requested instance(s)
  → normalize native metrics and provenance into EvidenceRecord
  → verify retained artifact identity, clean transient state, register only qualified evidence
```

Exit status, stdout, model self-report, and adapter-invented verdict files never become scoring authority when the upstream benchmark defines an official report. Multi-phase adapters share one cumulative run envelope. A demoted adapter may run only as explicitly labeled diagnostic evidence; diagnostic evidence cannot register `passed`.

Current official authority boundaries:

| Benchmark | Generation / execution | Sole scoring authority |
|---|---|---|
| Terminal-Bench | Harbor dataset `terminal-bench/terminal-bench-2-1` | Harbor trial `verifier_result.rewards["reward"]` |
| GPQA Diamond | Inspect Evals `inspect_evals/gpqa_diamond` | successful Inspect eval log accuracy |
| HLE | official CAIS prediction then judge scripts | exact run-owned judged artifact |
| BFCL v4 | `bfcl generate` then `bfcl evaluate` | official `BFCL_v4_<category>_score.json` JSONL |
| SWE-bench Verified (demoted) | locked Inspect Evals + Inspect SWE generation, then official SWE-bench evaluator | executed instance: official `report.json` boolean `resolved`; official `empty_patch_ids` is a valid unevaluated model failure. Local `verifier.json`/`result.json` has no authority |

The authority boundary extends through retention (AR-16), not only parsing. GPQA copies the exact scored Inspect-log bytes into the owned direct-child `gpqa-official-log.json` while the scored descriptor is held, stamps `score_artifact_sha256`, and points `verifier_log_path` at that copy. A later pathname or hardlink swap of the original Inspect log must not change what private proof contains.

### 8.2 Expansion rule

The selected architecture is **explicit adapters over a shared control-plane spine**. Two alternatives were rejected:

- a generic benchmark plugin/lifecycle DSL, because the pending harnesses differ at their scoring, identity, sandbox, and cleanup trust boundaries;
- a BenchEval-owned orchestration service, database, or Docker plane, because the current operator-owned harness environments and JSONL evidence path meet the product need with fewer stateful components.

Adding a new family therefore means one narrow adapter, one executor dispatch, one official-artifact parser, typed identity/slice config, and the verification gates in §13. Shared helpers are extracted only after at least two admitted adapters demonstrate the same trust-boundary behavior.

## 9. Budget Classes

| Class | Max cost (run total) | Max wall time (per instance) | Notes |
|-------|---------:|--------------:|-------|
| B0 | $0.05 | 60s | E0 structured/tool tasks |
| B1 | $0.25 | 180s | Simple coding |
| B2 | $2.00 | 300s | Agentic / defensive Core upper bound |
| B3 | explicit | explicit | Stretch only |

Class values are classification ceilings, and the slice's own envelope is always the effective cap (bands mirror the class defaults, so a slice never classifies into a class whose ceiling it exceeds; B3's zero defaults declare no standard envelope). Per-instance wall-clock and run-total wall-clock are **separate `RunPlan` fields**: `max_wall_clock_sec_per_instance` bounds each attempt and `max_wall_clock_sec` bounds the whole run (`per-instance × instances`); adapters must never derive one from the other. Serialized schema-"0.3" plans written before the per-instance field existed derive it from the run total on load (the pre-field contract allowed one attempt to consume the whole envelope). The aggregate model-only harnesses (GPQA, HLE) execute every sample in one subprocess chain and are therefore bounded by the **run-total** envelope; per-instance wall is not enforceable inside an aggregate process and evidence records this as `per_instance_wall_enforcement=unavailable_aggregate_harness`. Observed steps are recorded retrospectively in evidence only — no max-step envelope is claimed or enforced.

**Budget truth (v1 decision):** BenchEval promises enforceable wall-clock envelopes and cost estimates; it does **not** promise provider-enforced hard-dollar termination. Provider-reported billing may be retained when available, but is informational and does not become a required stop controller. `max_cost_usd` is therefore a planning envelope, and `cost_usd=0.0` means *unmeasured*, not zero spend, whenever no measured value is returned. Reports and readiness claims must preserve that distinction. Exceeding an enforced wall envelope → failure label `budget_exceeded` (distinct from `wrong_solution`). A future provider termination controller is out of scope unless a new product decision reopens it.

## 10. Failure Taxonomy (must be distinguishable)

`harness_failure` · `runtime_launch_failure` · `runtime_auth_failure` · `runtime_permission_block` · `runtime_output_unparseable` · `runtime_context_overflow` · `runtime_tool_failure` · `runtime_config_drift` · `runtime_budget_exceeded` · `runtime_output_cap_reached` · `runtime_no_progress_stall` · `runtime_wall_clock_timeout` · `materialization_failure` · `model_wrong_solution` · `model_output_invalid` · `adapter_error` · `budget_exceeded` · `wrong_solution` · `operator_interrupted` · `interrupted_by_harness` · `config_failed` · `remote_infra_failure` · `evidence_corrupt` · `duplicate_launch`. (Canonical source: `FailureLabel` in `domain.py`.)

Preflight/infrastructure failures **abort without evidence**. Post-preflight adapter failures write `EvidenceRecord` with `primary_pass=false` and the relevant failure label. Verifier remains scoring authority when a candidate artifact exists.

External runtime launch and tool failures are separate: `runtime_launch_failure` means BenchEval could not start or materialize the runtime process; `runtime_tool_failure` means the runtime/tool process launched and returned an unsuccessful status. Output caps are recorded as `runtime_output_cap_reached`; when both output and total token counts are present, the output count is authoritative, otherwise total count is the fallback.

## 11. Scoring & Reporting

- **Preserve native metrics.** Keep the official metrics emitted by each admitted harness (for example Terminal-Bench verifier results, Inspect GPQA accuracy, and HLE judged answers). BenchEval adds an operational layer: cost, latency, token usage, runtime/harness/adapter/model/provider versions and hashes, judge identity, failure class, cleanup status, artifact paths, and caveats.
- **No universal weighted score by default.** Side-by-side only. A user-defined weighted portfolio may exist later as a labeled local-decision policy object, never as a benchmark-native score.
- **Interpretation labels** on every report: `adapter_smoke` · `rough_regression` · `benchmark_native_claim` · `runtime_comparison` · `model_comparison` · `contaminated_or_legacy` · `defensive_security_only`.

## 12. Security Boundary

- **Allowed normal lanes:** local toy patching, authorization repair, alert-triage data, regression tests, and local prompt-injection resistance without exfiltration or live-target access.
- **Catalog-only v1 boundary:** the official CyberGym and ExploitGym tasks require PoC/exploit behavior against benchmark-owned vulnerable targets. The product decision for v1 is to keep both catalog-only and non-executable; no official PoC/exploit lifecycle is planned for this release. Any post-v1 reconsideration requires a new explicit product decision, a separately labelled sandboxed lane, authoritative success semantics, and operator-host authorization and isolation prerequisites. Relabelling the official PoC lifecycle as merely “defensive” is not sufficient.
- **Forbidden:** exploit generation against live or third-party targets, real-target attack chains, credential theft, persistence, and mixing any dual-use Stretch result into Core/public weighted totals.

## 13. Verification Gates

### 13.1 Adapter Admission

A benchmark adapter cannot claim Tier-1 live proof or Tier-2 readiness unless: native harness invocation ≥1 instance; version capture (benchmark/harness/adapter/runtime/model/provider and any judge); evidence completeness (raw result, stdout/stderr, verifier logs, artifacts, run config); failure separation; cleanup replay without deleting evidence; ≥1 typed slice with instance ids; dry-run accuracy; caveat labels attached. Tier-0 `executable: true` remains a software capability claim only.

### 13.2 Runtime Admission

A runtime cannot be marked production-ready unless: noninteractive launch; version capture; workspace isolation; config isolation (no global mutation unless allowed); known/controllable network; artifact extraction; budget enforcement; failure mapping to standard classes.

### 13.3 Report Validity

A report cannot claim model/runtime superiority unless: benchmark id identical; slice id identical; adapter version identical; harness version identical or explicitly waived; runtime-config difference = intended variable; model-config difference = intended variable; failed/invalid attempts reported not dropped; caveat labels shown.

### 13.4 Stable requirements

| ID | Requirement |
|---|---|
| AR-01 | An official upstream artifact is the only pass authority when the benchmark defines one. |
| AR-02 | Benchmark, dataset, harness, adapter, model/provider, runtime/agent, slice, and judge identities are captured or the attempt is ineligible. |
| AR-03 | Multi-phase benchmark lifecycles are explicit, ordered, cumulatively bounded, and fail closed between phases. |
| AR-04 | Identity, dependency, model-support, and environment checks that can fail deterministically run before a charged launch. |
| AR-05 | Run/evidence/artifact paths are exclusively owned and post-launch writes and scored reads remain bound to pinned filesystem identities. |
| AR-06 | Native metrics and official raw artifacts are preserved; normalization never replaces them. |
| AR-07 | Comparison eligibility requires the shared-instance intersection and constant non-varied provenance axes. |
| AR-08 | Enforced budgets, estimates, and unavailable metering are distinct evidence states. |
| AR-09 | Tier-0 software, Tier-1 live evidence, and Tier-2 checklist completion are separate claims with benchmark-specific status. |
| AR-10 | Heavy harnesses, containers, corpora, and credentials remain operator-owned; BenchEval owns preflight, dispatch, evidence, and cleanup. |
| AR-11 | Dual-use benchmark execution is impossible until the product boundary and operator-host policy explicitly admit it. |
| AR-12 | Registered evidence has a portable, integrity-bound export path; machine-local registry paths are never presented as durable publication. |
| AR-13 | An agent profile marked `scaffold` remains discoverable but cannot produce a plan, reserve outputs, launch a provider, or enter evidence. |
| AR-14 | Finalized private proofs are retained in the local proof store permanently; v1 exposes no delete, prune, replacement, retention-expiry, or garbage-collection operation. |
| AR-15 | Raw live-run events remain authoritative; readers validate the complete history before deriving a non-destructive current-state projection. |
| AR-16 | Bytes used for an official verdict remain identical to the bytes later retained in private proof, or the evidence is ineligible. |

### 13.5 Quality scenarios

| ID | Scenario and required response |
|---|---|
| QS-01 | A local result file claims success while the official report is missing: record an invalid/unparseable failure; never pass. |
| QS-02 | A dataset, harness, or output path changes after preflight: fail as provenance drift or evidence corruption before accepting its bytes. |
| QS-03 | A multi-phase harness times out in phase two: terminate within the remaining cumulative wall envelope and retain phase-one evidence. |
| QS-04 | Provider spend is unavailable: record unmeasured cost and do not claim a dollar cap was enforced. |
| QS-05 | Two runtime files contain asymmetric eligible instance sets: invalidate the comparison rather than silently changing the sample. |
| QS-06 | A diagnostic run succeeds: retain labeled evidence but reject `evidence register --status passed`. |
| QS-07 | A private bundle moves to another host: included artifacts resolve within the bundle and its digest/index verifies without source-host paths. |
| QS-08 | A pending adapter's output directory is swapped after launch: no write or scored read escapes; the attempt fails `evidence_corrupt`. |
| QS-09 | An operator requests a dual-use benchmark before policy admission: planning remains non-executable and no harness launches. |
| QS-10 | A fresh supported install follows the documented dependency path: every advertised executable adapter reaches preflight without an undeclared package. |
| QS-11 | A private proof is copied after the source checkout disappears: offline verification resolves every reference beneath the proof root and matches the expected inventory digest. |
| QS-12 | An already-written live registry contains an illegal transition or identity drift: reading or projecting it fails instead of presenting a false current state. |
| QS-13 | MOMO is selected by CLI or a crafted direct plan: the request fails before any output path, subprocess, or provider call is created. |
| QS-14 | A legacy comparison contains a passing infrastructure-failure row or asymmetric eligibility: the row remains visible, is excluded from headline rates, and an invalid comparison exits nonzero. |

## 14. VETOs (unchanged where still relevant)

- Mixing Calibration/Stretch tasks into weighted public-benchmark totals without caveats.
- BenchEval-authored or ad hoc LLM-as-judge for authoritative `primary_pass`. An upstream benchmark's official judge (HLE) is allowed only when its exact model identity and native judged artifact are bound into evidence.
- Live internet in MVP tasks.
- Statistical significance claims from smoke/lite slices alone.
- Breaking the v0.2 `EvidenceRecord` flat contract (additive only).
- Reintroducing fake runtimes (e.g. `native-api`) for model-only paths — use null `runtime_id` / `agent_id`.
- Vendoring Harbor as a Python dependency (external CLI only).

## 15. Risk Assessment

| Risk | Severity | Mitigation |
|---|---|---|
| Runtime/model conflation | High | Four-axis identity §2; CLI enforces `--runtime` distinct from `--backend`. |
| EvidenceRecord break | High | Additive-only v0.3; v0.2 rows stay valid. |
| Harbor unavailable / Docker absent | High | Doctor gates; local injected-runner tests remain diagnostic only; Terminal-Bench live acceptance stays blocked until the operator host passes preflight. |
| Public benchmark contamination | High | Caveat labels; prefer fresh benchmarks for promotion; contaminated = smoke/trend only. |
| Reward-hackable verifiers | High | Preserve native result + label verifier-integrity risk; no promotion on one score. |
| Cost overrun | High | Enforced wall limits, default smoke slices, dry-run cost estimates, and explicit `unmeasured` evidence. v1 deliberately makes no provider-enforced hard-dollar termination claim. |
| Cyber scope creep | High | CyberGym/ExploitGym remain catalog-only and non-executable for v1; never target live systems or mix their results into Core. |
| CLI runtimes mutate global config | Medium | Ephemeral home/workspace; config hash capture. |
| Native harness drift | High | Pin benchmark repo version, image digest, harness version, adapter version. |
| Adapter maintenance burden | Medium | Native wrappers only; no task reimplementation. |
| Machine-local proof loss | High | Export/import implemented `private_proof_v1`; transfer or refresh operator-host Tier-1 proofs before Tier-2 and never treat a host path alone as durable evidence. |
| Scored-versus-retained byte drift | High | Copy exact scored bytes under an owned path before descriptor release, stamp the digest, and verify proof contains those bytes. GPQA exact-byte retention is implemented; remaining Tier-2 items are ledger-specific. |

## 16. Tech Debt (acknowledged)

- Plain-text manifests remain supported only for optional large/generated lists; product slices store small fixed ids inline.
- No DB: JSONL is the store of record; DuckDB/Parquet is a derived analytics export, not transactional.
- No pyright in repo; type discipline via ruff + Pydantic runtime validation.
- Historical sections under `docs/context/` deliberately preserve pre-prune design decisions and are labeled non-operational; the live product contract is README + this architecture + `docs/api/internal-contracts.md` + `docs/diagrams/`.

## 17. Module map and source-tree ownership (current)

Every production module under `src/bencheval/` has one architectural home below. This is an ownership map, not a promise that pending adapters are executable.

| Component | Production modules | Responsibility |
|---|---|---|
| Public core and types | `__init__.py`, `domain.py`, `contracts.py`, `exceptions.py`, `ids.py` | Public exports, frozen DTOs, errors, and identifiers. |
| Config location/cache | `paths.py`, `config_cache.py` | Checkout, packaged config, `BENCHEVAL_HOME`, validation, cached reads. |
| Catalogs, slices, models, budgets | `benchmark_registry.py`, `slice_manifest.py`, `manifest.py`, `model_registry.py`, `runtime_registry.py`, `agent_registry.py`, `provider_registry.py`, `models.py`, `pricing.py`, `budget_defaults.py` | Typed configuration and identity lookup; no secrets. |
| Planning and preflight | `benchmark_plan.py`, `doctor.py`, `preflight_report.py`, `redaction.py` | Phase-one plan, dependency/env checks, shareable preflight, secret/path redaction. |
| Execution, isolation, lifecycle | `control_plane_executor.py`, `lifecycle.py`, `run_isolation.py`, `path_safety.py`, `backends.py` | Dispatch, budgets/deadlines, path ownership, cleanup, backend vocabulary. |
| Executable adapters and integrations | `terminal_bench_harbor.py`, `harbor_claude_code_npm.py`, `harbor_codex_npm.py`, `anthropic_role_shim.py`, `gpqa_adapter.py`, `hle_adapter.py`, `bfcl_native_adapter.py` | Admitted official harnesses and runtime install/shim boundaries. |
| Agent scaffold mechanics | `external_agent_adapter.py`, `momo_agent_adapter.py` | Non-authoritative external-agent integration retained for future admission work; no v1 agent is executable. |
| Demoted or pending adapters | `swebench_adapter.py`, `swebench_pro_harbor.py`, `cybergym_adapter.py`, `exploitgym_adapter.py` | Research/diagnostic code only; no catalog-executable claim. |
| Evidence, identity, admission | `evidence.py`, `identity_strings.py`, `live_proof.py`, `provenance_gates.py`, `adapter_admission.py`, `live_run_manifest.py` | JSONL record, captured identities, qualification, Tier-0 assessment, append-only run registry. |
| Comparison and statistics | `evidence_compare.py`, `model_compare.py`, `runtime_compare.py`, `stats.py` | Shared-instance validity, deltas, confidence intervals, comparison CLIs. |
| Reports and exports | `report.py`, `export.py`, `run_bundle.py`, `proof_bundle.py` | Markdown/JSON reporting, Parquet/DuckDB analytics, publication bundles, and immutable `private_proof_v1`. |
| CLI | `cli.py` | `list`, `catalog`, `run`, `doctor`, report/compare/export, evidence registration. |

## 18. Remaining adapter architecture

The following are researched designs, not executable claims:

### 18.1 SWE-bench Verified diagnostic lifecycle

The retained adapter already contains injected-runner generation→official-evaluator sequencing. Local `verifier.json`/`result.json` have no authority. Official per-instance `report.json[instance_id]["resolved"]` is the pass/fail oracle when the instance was executed; official schema-v2 `empty_patch_ids` membership without that report is a valid submitted model failure. Diagnostic dispatch and schema-v2 coherence are wired. CLI `--diagnostic` injects the real process runner after run-owned parquet materialization and execution-time image-digest binding; `process_runner is None` still fail-closes. The charged diagnostic `run-20260826-095222-202465-019ab2b0` proved generation→official eval; official schema-v2 classified the instance as `error_ids` (patch apply failed), so the row is invalid-for-verdict evidence and not a promotion trigger. Three routes were compared:

| Route | Fit | Decision |
|---|---|---|
| Locked Inspect Evals + Inspect SWE runtime generation, then official SWE-bench evaluator | Reuses the installed task and exact admitted Codex/Claude binary pins, exports standard predictions, and still leaves the official evaluator as sole score authority. Inspect proxies the model route, so the result is diagnostic rather than standalone-CLI parity. | **Selected for the first diagnostic implementation.** |
| mini-SWE-agent batch generation + official SWE-bench evaluator | Upstream-simple exact-ID batch generation, but mini-SWE is a distinct agent/scaffold. Using it while claiming a selected BenchEval Codex/Claude runtime would make the runtime axis misleading. | Defer to a separately named future agent profile, if admitted. |
| Harbor SWE-bench Verified | Reuses Harbor, but Harbor documents an adapted dataset and measured parity drift rather than byte-for-byte official lifecycle parity. | Do not select as the first official diagnostic. |

The selected lifecycle is:

```text
locked Inspect Evals task + Inspect SWE solver for the selected pinned runtime binary
  → export exactly one standard prediction JSONL row
  → pinned official SWE-bench evaluator over a run-owned pinned dataset row
  → official schema-v2 aggregate plus, when executed, requested-instance
    `report.json[instance_id]["resolved"]` (empty-patch classification is a
    valid model failure and is not executed)
  → evidence with prediction bytes, schema-v2 aggregate, and per-instance
    report.json when the instance was executed
```

The official evaluation guide defines the prediction fields as `instance_id`, `model_name_or_path`, and `model_patch`; the evaluator emits the requested instance's `report.json`: [SWE-bench evaluation guide](https://github.com/SWE-bench/SWE-bench/blob/v5.0.1/docs/guides/evaluation.md), [official evaluator](https://github.com/SWE-bench/SWE-bench/blob/v5.0.1/swebench/harness/run_evaluation.py), and [CLI evaluator](https://github.com/SWE-bench/SWE-bench/blob/v5.0.1/swebench/cli/evaluate.py). Inspect Evals documents its task/export boundary in its [SWE-bench task README](https://github.com/UKGovernmentBEIS/inspect_evals/blob/main/src/inspect_evals/swe_bench/README.md), while Inspect SWE documents the [Codex solver](https://meridianlabs-ai.github.io/inspect_swe/codex_cli.html).

Inspect generation and official evaluation use separate isolated `uv` envs: inspect-evals `0.8.0` still imports `MAP_REPO_VERSION_TO_SPECS` to write `model_patch`, so generation gets `swebench==4.1.0`; the official CLI stays exact `swebench==5.0.1`. Those pins do not share a venv.

The selected versions are the already locked Inspect Evals `0.8.0` task version 3 and Inspect SWE `0.2.47`, the exact runtime binary pins already stored in runtime profiles, exact `swebench==5.0.1` (tag commit `87ab1f6ced28f75ba73ca899dc759b019310944a`), and the official Verified dataset revision `78f471bf655a3137b2e8a75af1501690ec009ec3`. The source parquet is `data/test-00000-of-00001.parquet`, 6,304,616 bytes, SHA-256 `030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25`. `swebench` belongs in an exact-pinned `swe` dependency group so its evaluator, Docker, dataset, and CLI graph does not enter core or the generic Inspect extra.

Uncharged 2026-08-26 compatibility research closed the earlier dataset ambiguity. A run-owned Hugging Face-style directory containing the selected official row loads successfully in Inspect Evals `0.8.0` when only `PASS_TO_PASS` and `FAIL_TO_PASS` are deterministically encoded as canonical JSON strings; the task decodes them to lists, selects exactly `django__django-11099`, reports task version 3, and accepts an immutable digest-form image template. This is an adapter-owned compatibility representation, not a second source snapshot. The official evaluator receives a separate run-owned row derived from the same verified source bytes. Retain the source row, both deterministic representations, a transformation manifest, and all digests.

The official CLI shape is `swebench eval <run-owned eval-input> -p <preds> -i <id> -j 1 --run-id <unique> --report-dir <dir>` (the default runner prefixes `uv run --isolated --project <BenchEval root> --group swe --`). The explicit project selects the pinned evaluator group without changing the evaluator cwd: official `logs/run_evaluation` output therefore remains under the run-owned instance directory. `eval-input` is a post-generation owned copy of the bound official row; Inspect never receives that path. Hub aliases such as `verified` are rejected on this diagnostic route. The v1 diagnostic is Codex-only. The schema-v2 aggregate is a required coherence oracle: an executed per-instance `report.json` without that summary, or with `error` / `infra_failure` / `ambiguous_failure` membership, or resolved/unresolved/empty-patch disagreement, is invalid evidence. Empty patches are valid submitted model failures and are not executed. Inspect generation binds an execution-time platform image digest. Both phases share one monotonic cumulative deadline and one run-owned artifact root.

Historical Hub-alias diagnostic `sha256:fcc766f5932607c5250571cdfdf6603e62a8bb19a995a05f81edc561939235b5` used `swebench eval verified` and stamped `provisional:swe-bench-verified/public`. Retention-bound diagnostic `run-20260826-141431-679309-31a57785` / `sha256:5f7f79ce44eb8c00d7ee826914e8d4591206de2d3b876a2524ccad508e373e52` scored the run-owned `official-dataset` directory, stamped `swe-bench-verified@78f471bf655a3137+data-030cfd7f2a704c4c` plus `swebench==5.0.1`, and retains the official row, Inspect row, transformation manifest, bound Inspect `.eval`, predictions, and schema-v2 summary. `runtime_version` is `0.148.0` from the sandbox Codex binary. Official schema-v2 classified the instance as `error_ids` (patch apply failed), so there is no executed per-instance `report.json` and the row is invalid-for-verdict, not a promotion trigger. `cleanup_result=skipped`.

Keep the benchmark non-executable and force `diagnostic` interpretation until a real smoke proves both phases. That proof triggers a separate human review; it never auto-promotes the catalog row. The contamination/quality caveat still prevents a frontier-quality claim.

### 18.2 CyberGym and ExploitGym

CyberGym's official lifecycle is data materialization, a local/private execution server, task generation, agent PoC submission, and `verify_agent_result.py`; its public data footprint is roughly 240 GB before full server data. [Official CyberGym repository](https://github.com/sunblaze-ucb/cybergym). ExploitGym's official runner accepts positional task IDs or `--tasks-file`, writes task-scoped `result.json`, and optionally adds a causal target-vulnerability scorer; the product must choose whether flag acquisition alone or flag-plus-causal-score is authoritative. [Official ExploitGym evaluation guide](https://github.com/sunblaze-ucb/exploitgym/blob/main/docs/eval.md).

Neither current adapter implements that lifecycle. The v1 product decision is to keep both benchmarks catalog-only and non-executable, so no official lifecycle or scoring-authority implementation is planned in the v1 roadmap. The retained Python modules remain non-authoritative research scaffolding; the pre-admission anchored-I/O contract is implemented so dormant code cannot preserve known unsafe pathname writes. Any post-v1 admission proposal must reopen the product decision and define a pinned upstream release/task manifest, official result authority, host-capacity runbook, operator authorization, isolation, and real one-instance proof before catalog promotion.

### 18.3 Portable live evidence

`results/manifests/runs.jsonl` is an append-only machine-local event index. `append_live_run` already enforces the append-time event contract: `model_id` is immutable; optional benchmark/slice/runtime axes may be filled once and are immutable thereafter; event timestamps do not move backward; same-status correction rows are allowed; `registered` may advance to any lifecycle state, `running` to completed/passed/failed/archived, `completed` to passed/failed/archived, and passed/failed only to themselves or archived.

The reader preserves raw append order and exposes a validated derived projection. `private_proof_v1` is the implemented portable/offline-verifiable format below. Legacy `run_bundle_v1` remains a local convenience export rather than durable proof; private legacy export must fail closed when an evidence-referenced path cannot be copied exactly, including a path beneath a skipped symlink ancestor.

#### Selected private-proof format

BenchEval implements a **`private_proof_v1` directory**, borrowing the completeness/path rules of [BagIt RFC 8493](https://www.rfc-editor.org/rfc/rfc8493.html) without claiming BagIt conformance. Full BagIt adds payload/tag conventions that do not remove the need for BenchEval run semantics. [OCI image layout](https://github.com/opencontainers/image-spec/blob/main/image-layout.md) and the [OCI distribution specification](https://github.com/opencontainers/distribution-spec/blob/main/spec.md) add registry complexity for an object-storage problem explicitly deferred from v1. Neither dependency is earned now.

```text
results/proofs/
  proofs.jsonl
  sha256/<inventory-digest>/
    inventory.json
    proof.json
    history.jsonl
    projection.json
    evidence.jsonl
    run-plan.json
    report.md
    artifacts/{raw,capture}/...
```

The canonical proof is the finalized directory; a `.tar.gz` is only a transport derivative. `proof_id` is `sha256:` plus the SHA-256 of the exact canonical `inventory.json` bytes. Each other regular file appears exactly once in the inventory with a small closed role, byte size, and SHA-256. Inventory paths are normalized relative paths beneath the proof root. Absolute paths, empty/`.`/`..` components, backslashes, NUL, symlinks, hardlinks, devices, FIFOs, nested proofs, duplicate normalized names, case-fold collisions, Unicode-normalization collisions, missing files, and extra files are rejected.

Private export is fail-closed:

- copy the exact evidence, official results, verifier logs, stdout/stderr, workspace diffs, run configuration, run history, projection, report, and every evidence-referenced raw/capture artifact;
- resolve repository-relative and absolute source references only against explicitly declared raw/capture roots, rewrite them beneath `artifacts/`, and reject anything outside those roots;
- persist the frozen `RunPlan` with an anchored exclusive write after output ownership is claimed and before the first launch; never reconstruct a historical plan from current config;
- require exactly one `run_id` across proof metadata, history, projection, and evidence (`RunPlan` has no `run_id`); a complete proof also binds shared frozen identity axes — benchmark, slice, model, runtime/agent, adapter, and planned instances — across plan, evidence, history, and projection, and rejects absent required axes or any non-null disagreement; and
- keep public/redacted bundles as publication derivatives that private-proof verify/import rejects.

`runs.jsonl` remains the raw machine-local lifecycle event log. Whole-history reader validation and the derived **last-valid-event operational-view** are implemented: immutable run/model identities, first-non-null fill-once axes, last valid status/host/notes/time, latest non-null artifact locators, event count, and first/last timestamps. Projection never compacts or overwrites raw rows. An adjacent mode-0600 `fcntl.flock` file makes read→validate→append→flush/fsync one exclusive critical section; public reads take a shared lock. This deliberately targets the supported macOS/Linux operator hosts without adding a locking dependency.

Offline verification must prove exact file-set equality, sizes, hashes, inventory digest, run-ID coherence, valid replayed history, stored-versus-derived projection equality, and containment/inventory of every retained reference. An expected proof digest or an existing local index anchors self-consistency; the digest detects corruption but does not authenticate the creator. Import verifies first, atomically installs under `sha256/<digest>`, and appends one idempotent `proof_index_v1` row to `proofs.jsonl`. Imported source lifecycle events are **not** replayed into local `runs.jsonl` because retaining a proof is not the same event as running it.

The local proof store is the v1 long-term store. Finalized proofs are retained permanently and BenchEval exposes no delete, prune, replacement, expiry, or garbage-collection operation. Filesystem backup remains operator-owned. Bucket/object-store transports, deduplication, signatures, OCI/ORAS, discovery services, and remote retention are future options, not present blockers. Historical BFCL/HLE evidence without a pre-launch `run-plan.json` is retained as `legacy_unverifiable` / `run_plan_missing_legacy`; BenchEval must not invent a historical plan from current configuration.

## 19. Product decisions

The following decisions are closed for v1:

1. **Cost:** no provider-enforced hard-dollar termination promise. BenchEval is wall-bounded and cost-estimated; measured provider billing is optional evidence, not a required controller.
2. **Agent:** MOMO is cataloged scaffold mechanics, not an admitted execution profile. It must fail before charge until a future admission decision.
3. **Private proof retention:** local store, permanent by default, and no BenchEval cleanup operation. Object/bucket storage is deferred.
4. **SWE-bench Verified:** implement and retain a real diagnostic generation→official-evaluation proof, then make a separate promotion decision. No automatic admission.
5. **Dual-use benchmarks:** CyberGym and ExploitGym remain catalog-only and non-executable. Their official PoC/exploit lifecycles and ExploitGym metric selection are outside v1.
6. **HITL:** probe and automate ordinary host, dependency, credential-presence, and service prerequisites. Pause only when a runtime literally requires device/subscription login, CAPTCHA, hardware touch, unavailable administrator action, or a new product decision.

After the current executable set, the next implementation candidate is the SWE-bench Verified diagnostic lifecycle. No later benchmark family is selected until that evidence is reviewed.
