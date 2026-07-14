# Architecture & Decisions

> **Status:** ACCEPTED (vNext v0.3, revised 2026-07-14 for product-spine prune); implementation tracked in [`docs/roadmap.md`](roadmap.md)
> **Supersedes:** vNext v0.2 (ACCEPTED 2026-05-29, Core-first) — preserved as `legacy_static` context only
> **Operator contract / product SoT:** root [`README.md`](../README.md), this file, and [`docs/api/internal-contracts.md`](api/internal-contracts.md). [`docs/context/concept-hld.md`](context/concept-hld.md) is a **historical design ledger**, not live CLI instructions.
> **Scope:** Defined benchmarks → (runtime XOR agent)? → model via provider → evidence.

## 0. Product Principles

1. **Simple spine.** Product path is `benchmark → (runtime|agent)? → model → evidence`. Runtime and agent are mutually exclusive scaffolds; omit both for model-only (BFCL).
2. **Defined benchmarks only.** Live execution is limited to config-declared executable adapters.
3. **Official-first execution.** Prefer official distributions, runners, and scorers. BenchEval normalizes evidence; it does not reimplement benchmark semantics unless upstream has no usable feedback path (then label it as fallback).
4. **Config-first expansion.** New slices/runtimes/models/agents/providers on an existing adapter family are YAML/manifest work.
5. **Runtime-owned environments.** Benchmarks and selected runtimes own sandboxes/containers. BenchEval does not ship a separate Docker plane.
6. **Evidence over claims.** Reports preserve native artifacts and caveats; smoke ≠ full benchmark claim; green tests are not live proof.

## 1. Product Shape (v0.3)

BenchEval is a thin evaluation control plane:

> Given a **defined** benchmark (or slice), an optional runtime XOR agent, a provider-bound model, what happened, how expensive was it, and what evidence supports the result?

```text
benchmark/slice  →  (runtime | agent)?  →  model via provider  →  EvidenceRecord + artifacts
```

**Runnable today (Production v1):** `terminal-bench`, `swe-bench-verified`, `bfcl-v4`.

**Admitted scaffolds:** runtimes `claude-code`, `codex-cli`; agent `momo`; providers `bytellm`, `ollama-cloud`.

## 2. Identity axes

```text
benchmark_id / slice_id  = what is being evaluated
model_id / provider_id   = model + how it is reached
runtime_id XOR agent_id  = optional scaffold (never both; both null = model-only)
harness_kind / adapter_id = how BenchEval joins official harness ↔ evidence
```

CLI: `bencheval run <bench>/<slice> --model <id> [--runtime|--agent] [--provider bytellm]`.
`--dry-run` = phase 1 only; `-y` skips the continue prompt.

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
    AD --> A2[SWE native]
    AD --> A3[BFCL native]
    AD --> A4[MOMO agent]

    A1 --> EN[Evidence normalizer]
    A2 --> EN
    A3 --> EN
    A4 --> EN
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
| Benchmark Registry | Catalog runnable benchmarks, adapters, source, license, native harness, metrics, caveats. | **Extend** existing `benchmark_registry.py` (catalog -> executable contract) + `config/benchmarks.yaml` (**3** product entries). | `benchmark_registry.py` |
| Slice Manifest Registry | Typed `smoke`/`lite`/`full`/`custom` instance lists with budget + labels. | **New typed layer** over existing `manifest.py` + `config/manifests/*.txt`. | `manifest.py` (+ new `slice_manifest.py`) |
| Model Registry | Model identity, provider, pricing, context limits, version capture. | **Promote** existing `config/models.yaml` + `pricing/` + `models.py` (`ModelFamily`, `RunStamp`). | `models.py`, `pricing.py` |
| Runtime Registry | Admitted runtimes (`claude-code`, `codex-cli`) + capability metadata. | `runtime_registry.py` + `config/runtimes/*.yaml`. | `runtime_registry.py` |
| Agent Registry | Admitted agents (`momo`); XOR with runtime on the plan. | `agent_registry.py` + `config/agents/*.yaml`. | `agent_registry.py` |
| Provider Registry | Admitted providers (`bytellm`, `ollama-cloud`). | `provider_registry.py` + `config/providers/*.yaml`. | `provider_registry.py` |
| Run Planner | Build `RunPlan` from benchmark + slice + model + (runtime\|agent) + provider. | `benchmark_plan.py` (phase 1 of `run`). | `benchmark_plan.py` |
| Preflight / Doctor | Runtime/provider env checks before live runs (never prints secrets). | `doctor.py`. | `doctor.py` |
| Materialization Manager | Cleanup policy + adapter-owned ephemeral dirs. | `lifecycle.py` (`CleanupPolicy`); adapters own workspace layout. | `lifecycle.py` |
| Adapter Dispatcher | Route plan → adapter (runtime XOR agent XOR model-only). | `control_plane_executor.py`. | `control_plane_executor.py` |
| Adapters | Terminal-Bench Harbor, SWE-bench, BFCL native, external agent. | Product v1 only. | `terminal_bench_harbor.py`, `swebench_adapter.py`, `bfcl_native_adapter.py`, `external_agent_adapter.py` |
| Evidence Normalizer | Convert native output → `EvidenceRecord`. | `evidence.py`. | `evidence.py` |
| Evidence Store | Evidence JSONL + optional Parquet/DuckDB export. | `evidence.py`, `export.py`. | as listed |
| Compare/Report/Export | Markdown/JSON reports + cross-run comparisons + run bundles. | `report.py`, `evidence_compare.py`, `export.py`, `run_bundle.py`. | as listed |
| Dashboard | UI over stored evidence. | **Post-MVP** (non-goal now). | — |

## 6. Execution Profiles

Live product paths use harness-owned sandboxes (Harbor for Terminal-Bench, native SWE/BFCL runners). Historical E0–E4 labels below are planning vocabulary only — Inspect/`inspect-api` is **not** an admitted product runtime.

| Profile | Name | Used for | Notes |
|---------|------|----------|-------|
| E0 | Model-only / API | Structured output, tool-call generation | BFCL generation smoke today |
| E1 | Runtime sandbox | Coding / repo tests under admitted runtime | Runtime-owned |
| E2 | Terminal / harness sandbox | Terminal, multi-step verifier-heavy | Harbor for TB; harness-owned |
| E3 | Calibration external | Public micro-slices | Adapter-backed; never Core-weighted |
| E4 | Stretch sandbox | Expensive / safety-gated | Explicit review; research unless admitted |

Dry-run planning reports `requires_harbor` / `requires_sandbox` when needed. Those flags are operator preflight signals, not a BenchEval-owned Docker plane.

## 7. Data Contracts

### 7.1 Benchmark Contract (`config/benchmarks.yaml`)

Existing product YAML registry is the authoritative executable catalog (**3** entries). Schema: `BenchmarkCatalog`/`BenchmarkEntry` in `benchmark_registry.py` (Pydantic, `frozen=True, extra="forbid"`). Fields: id, name, aliases, category, tier (`calibration`/`stretch`/`reference_only`), adapter_status (`cataloged`/`adapter_pending`/`manifest_available`/`unverified`), recommended_backend, recommended_profile, task_count, public_indexed, contamination_risk, single_mode_required, safety_review (`standard`/`dual_use`/`offensive_restricted`), source_url, notes.

### 7.2 Slice Manifest (new typed layer)

```yaml
schema_version: "0.1"
slice:
  id: "swe-bench-verified-smoke-10"
  benchmark_id: "swe-bench-verified"
  purpose: "adapter_smoke"           # adapter_smoke | rough_regression | benchmark_native_claim | runtime_comparison | model_comparison
  selection_policy: "fixed_instance_ids"
  instances_source: "config/manifests/swebench-verified-smoke-10.txt"  # plain-text id list (existing)
  valid_for: ["adapter_validation", "rough_regression"]
  invalid_for: ["frontier_model_promotion"]
budget:
  max_instances: 10
  max_wall_clock_sec_per_instance: 900
  max_total_cost_usd: 50
labels:
  contamination_warning: true
  public_benchmark: true
```

Plain-text manifests in `config/manifests/*.txt` remain the instance source; the typed YAML wraps them with budget + labels.

### 7.3 Runtime Profile (`config/runtimes/<id>.yaml`)

Per HLD §6.2. Pydantic `RuntimeProfile`: id, kind, display_name, lifecycle, supported_platforms, supported_harnesses, model_binding, launch (command_template, working_dir_policy, env vars, timeout), capabilities, safety (network_default, workspace_boundary, forbidden_features), versioning (version_command, config_hash_inputs). **Admitted profiles now:** `claude-code`, `codex-cli`. Agents live under `config/agents/` (`momo`); providers under `config/providers/` (`bytellm`, `ollama-cloud`).

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
    steps: int | None = None
    token_usage: dict[str, int] | None = None
    native_score: dict[str, JsonValue] | None = None
    contamination_label: str | None = None
    reward_hack_risk_label: str | None = None
    verifier_integrity_label: str | None = None
    cleanup_result: str | None = None
    interpretation_label: str | None = None   # adapter_smoke | rough_regression | ...
```

Nested `run`/`model`/`runtime`/`attempt`/`artifacts`/`integrity` blocks from HLD §9.3 are **not** adopted as the on-disk shape (would break v0.2 readers); they remain a *report projection* only.

## 8. Adapter Rule

Adapters **prefer native harnesses**. Product v1 allowed shapes:

1. **Native wrapper** — call official runner, parse native result files, preserve raw artifacts (SWE-bench, BFCL generate).
2. **Harbor wrapper** — Harbor-native terminal tasks (Terminal-Bench 2.0).
3. **External agent wrapper** — admitted agent profiles (`momo`) via `external_agent_adapter.py`.

Deferred / not product: Inspect-as-runtime wrappers. Compatibility shims must be explicitly labeled `adapter_smoke`.

**Forbidden:** copying public benchmark instances into custom Core tasks and treating them as BenchEval-native.

## 9. Budget Classes

| Class | Max cost | Max wall time | Max steps | Notes |
|-------|---------:|--------------:|----------:|-------|
| B0 | $0.05 | 60s | 4 | E0 structured/tool tasks |
| B1 | $0.25 | 180s | 10 | Simple coding |
| B2 | $2.00 | 300s | 20 | Agentic / defensive Core upper bound |
| B3 | explicit | explicit | explicit | Stretch only |

Exceeding envelope → failure label `budget_exceeded` (distinct from `wrong_solution`).

## 10. Failure Taxonomy (must be distinguishable)

`harness_failure` · `runtime_launch_failure` · `runtime_auth_failure` · `runtime_permission_block` · `runtime_output_unparseable` · `runtime_context_overflow` · `runtime_tool_failure` · `runtime_config_drift` · `runtime_budget_exceeded` · `materialization_failure` · `model_wrong_solution` · `adapter_error` · `model_output_invalid` · `budget_exceeded`.

Preflight/infrastructure failures **abort without evidence**. Post-preflight adapter failures write `EvidenceRecord` with `primary_pass=false` and the relevant failure label. Verifier remains scoring authority when a candidate artifact exists.

External runtime launch and tool failures are separate: `runtime_launch_failure` means BenchEval could not start or materialize the runtime process; `runtime_tool_failure` means the runtime/tool process launched and returned an unsuccessful status. Output caps are recorded as `runtime_output_cap_reached`; when both output and total token counts are present, the output count is authoritative, otherwise total count is the fallback.

## 11. Scoring & Reporting

- **Preserve native metrics.** If Terminal-Bench reports pass rate + CI, keep it. If SWE-bench reports resolved instances, keep it. BenchEval adds an operational layer: cost, latency, token usage, runtime/harness/adapter/model versions, failure class, cleanup status, artifact paths, caveats.
- **No universal weighted score by default.** Side-by-side only. A user-defined weighted portfolio may exist later as a labeled local-decision policy object, never as a benchmark-native score.
- **Interpretation labels** on every report: `adapter_smoke` · `rough_regression` · `benchmark_native_claim` · `runtime_comparison` · `model_comparison` · `contaminated_or_legacy` · `defensive_security_only` · `offensive_restricted`.

## 12. Security Boundary

- **Allowed (Core/defensive):** local toy patching, authorization repair, alert triage JSON, regression tests, local prompt-injection resistance (no network, no exfiltration), vulnerability *reproduction* against **pre-patch** code in a sandbox with sanitizers (CyberGym defensive slice).
- **Stretch (offensive-restricted, explicit safety review, never Core-weighted, no live targets):** ExploitGym full exploit generation, BountyBench Exploit tasks, CyberGym PoC generation against unpatched code.
- **Forbidden:** exploit generation against live targets, real-target attack chains, offensive CyberGym-style PoC reproduction as weighted tasks.

## 13. Verification Gates

### 13.1 Adapter Admission

A benchmark adapter cannot be marked `manifest_available`/runnable unless: native harness invocation ≥1 instance; version capture (benchmark/harness/adapter/runtime/model); evidence completeness (raw result, stdout/stderr, verifier logs, artifacts, run config); failure separation; cleanup replay without deleting evidence; ≥1 smoke manifest; dry-run accuracy; caveat labels attached.

### 13.2 Runtime Admission

A runtime cannot be marked production-ready unless: noninteractive launch; version capture; workspace isolation; config isolation (no global mutation unless allowed); known/controllable network; artifact extraction; budget enforcement; failure mapping to standard classes.

### 13.3 Report Validity

A report cannot claim model/runtime superiority unless: benchmark id identical; slice id identical; adapter version identical; harness version identical or explicitly waived; runtime-config difference = intended variable; model-config difference = intended variable; failed/invalid attempts reported not dropped; caveat labels shown.

## 14. VETOs (unchanged where still relevant)

- Mixing Calibration/Stretch tasks into weighted public-benchmark totals without caveats.
- LLM-as-judge for authoritative `primary_pass`.
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
| Harbor unavailable / Docker absent | High | Doctor gates; mockllm-style deterministic stand-in for adapter-smoke; never claim live success. |
| Public benchmark contamination | High | Caveat labels; prefer fresh benchmarks for promotion; contaminated = smoke/trend only. |
| Reward-hackable verifiers | High | Preserve native result + label verifier-integrity risk; no promotion on one score. |
| Cost overrun | High | Default smoke slices; dry-run budgets; per-run + per-instance hard caps. |
| Cyber scope creep | High | Defensive-only in normal lanes; offensive behind Stretch + safety review. |
| CLI runtimes mutate global config | Medium | Ephemeral home/workspace; config hash capture. |
| Native harness drift | High | Pin benchmark repo version, image digest, harness version, adapter version. |
| Adapter maintenance burden | Medium | Native wrappers only; no task reimplementation. |

## 16. Tech Debt (acknowledged)

- Plain-text manifests (`config/manifests/*.txt`) coexist with typed `SliceManifest` YAML wrappers until all slices migrate.
- No DB: JSONL is the store of record; DuckDB/Parquet is a derived analytics export, not transactional.
- No pyright in repo; type discipline via ruff + Pydantic runtime validation.
- Broader `docs/context/*` / roadmap still describe pre-prune catalog size and deleted lanes; product face is README + this architecture + `docs/diagrams/`.

## 17. Module map (current)

| Concern | Module | Notes |
|---|---|---|
| Benchmark catalog | `benchmark_registry.py`, `config/benchmarks.yaml` | **3** executable entries only. |
| Slices / manifests | `manifest.py`, `config/slices/`, `config/manifests/` | Typed slice wrappers + instance lists. |
| Models / pricing | `models.py`, `pricing.py`, `config/models.yaml` | Non-secret model routes. |
| Runtime / agent / provider | `runtime_registry.py`, `agent_registry.py`, `provider_registry.py` | Admitted YAML under `config/{runtimes,agents,providers}/`. |
| Plan (phase 1) | `benchmark_plan.py` | `RunPlan`; runtime XOR agent; provider default `bytellm`. |
| Doctor | `doctor.py` | Preflight; never prints secrets. |
| Execute (phase 2) | `control_plane_executor.py` | Dispatches to product adapters. |
| Adapters | `terminal_bench_harbor.py`, `swebench_adapter.py`, `bfcl_native_adapter.py`, `external_agent_adapter.py` | Product v1 only. |
| Evidence | `evidence.py` | Additive `agent_id` / `provider_id`. |
| Report / compare / export | `report.py`, `evidence_compare.py`, `export.py`, `run_bundle.py` | `export-run --redaction public\|private`. |
| CLI | `cli.py` | `list`, `run`, `catalog`, `doctor`, evidence surface. |
