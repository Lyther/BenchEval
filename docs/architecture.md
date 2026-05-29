# Architecture & Decisions

> **Status:** ACCEPTED (vNext v0.2, 2026-05-29)
> **Source:** [`docs/context/concept-zero.md`](context/concept-zero.md)
> **Scope:** Private-first, evidence-based model evaluation for coding, tool use, agentic coding, terminal execution, and defensive security.

## 1. Current Architecture (vNext)

BenchEval owns the **canonical task contract** (schema v0.2). Inspect AI, Docker, and Harbor are **execution targets**, not the source of truth for task semantics.

```text
BenchEval Task Contract (YAML)
  -> Task linter / registry
  -> Run planner (dry-run)
  -> E0 Inspect Stateless
  -> E1 Inspect + Docker
  -> E2 Harbor adapter (optional, category-specific)
  -> E3 Calibration (appendix-only, never weighted in Core)
  -> E4 Stretch (quarterly / manual)
  -> Verifier (deterministic primary)
  -> JSONL evidence store
  -> Markdown evidence report
  -> DuckDB/Parquet export (`bencheval export`)
  -> Cross-run evidence compare (`bencheval compare`)
```

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Task contract | **YAML v0.2 under `config/tasks/`** | Human-diffable, lintable, versioned; SPDX + source hash required. |
| Orchestration | **Inspect AI** | Provider abstraction, logging, tools; E0/E1 profiles. |
| Local sandbox | **Docker** | Default for E1 coding and defensive tasks. |
| Terminal / verifier-heavy | **Harbor (optional E2)** | P1.5 POC only; not mandatory for all tasks. |
| Evidence store (MVP) | **JSONL + artifacts** | `EvidenceRecord` rows with `backend` + `adapter_metadata`; query via `bencheval export`. |
| Live execution | **Inspect (E0/E1) + Harbor POC (S4 packaging)** | `local/harness` default offline path; `mockllm/model` E0 stand-in (no `inspect_ai`); real providers via `scripts/run_provider_smoke.sh` (credential-gated). |
| Reports | **Generated Markdown** | `bencheval report`; directional regression panels; no significance claims from Core-8/16. |
| Language | **Python 3.12 + uv** | Matches Inspect ecosystem; core library has no eval extra requirement. |
| CLI | **`bencheval` argparse entrypoint** | `task lint\|validate\|audit`,`run`,`doctor`,`report`,`export`,`compare`. |

## 2. Execution Profiles

| Profile | Name | Used for | Runtime |
|---------|------|----------|---------|
| E0 | Inspect Stateless | Structured output, single tool calls | Inspect only |
| E1 | Inspect Local Sandbox | Coding, repo tests, local defensive tasks | Inspect + Docker |
| E2 | Harbor Sandbox | Terminal, multi-step verifier-heavy | Harbor adapter |
| E3 | Calibration External | Public micro-slices | Separate harness; **never Core-weighted** |
| E4 | Stretch Sandbox | Expensive quarterly checks | Harbor/cloud optional |

Dry-run planner sets `requires_harbor=true` when any selected task profile includes E2; `requires_sandbox=true` when E1 or E2 is present.

## 3. Evaluation Suites

| Suite | Size | Weighted in Core | Notes |
|-------|-----:|------------------|-------|
| Core-8 Smoke | 8 | Yes | MVP; two tasks per category; **8/8 admitted** (2026-05-29) |
| Core-16 | 16 | Yes | Planned in `docs/context/core-16-expansion-plan.md`; not yet implemented |
| Calibration Pack | Variable | **No** | Appendix-only diagnostics |
| Stretch Pack | Variable | **No** | Separate safety review |

Suite membership: `config/suites.yaml`. Task definitions: `config/tasks/core-8/*.yaml`.

## 4. Budget Classes

| Class | Max cost | Max wall time | Max steps | Notes |
|-------|---------:|--------------:|----------:|-------|
| B0 | $0.05 | 60s | 4 | E0 structured/tool tasks |
| B1 | $0.25 | 180s | 10 | Simple coding |
| B2 | $2.00 | 300s | 20 | Agentic / defensive Core upper bound |
| B3 | explicit | explicit | explicit | Stretch only |

Exceeding envelope → failure label `budget_exceeded` (distinct from `wrong_solution`).

## 5. Scoring & Evidence

Primary fields per attempt (`EvidenceRecord`):

- `primary_pass` — deterministic binary gate
- `partial_score` — 0.0–1.0 sub-assertion aggregate
- `cost_usd`, `latency_sec`, `failure_labels`, artifact paths, verifier log path

Adapter failure policy: preflight/infrastructure failures abort without evidence. Post-preflight adapter failures write `EvidenceRecord` rows with `primary_pass=false` and `failure_labels` of `adapter_error` or `model_output_invalid`. Verifier remains scoring authority when a candidate artifact exists.

Inspect E0 `mockllm/model` is a deterministic reference stand-in: skips Inspect doctor, does not import or call `inspect_ai`, and is **not** proof of live provider success.

Provider smoke orchestrator (`scripts/run_provider_smoke.sh`): runs `doctor` per model, skips only known blockers (missing credentials, Docker unavailable, Inspect dependency unavailable), treats unknown doctor failures as errors, validates backend/profile before output dirs are created.

Agentic and defensive tasks **must** declare non-empty `verification.partial_metrics` in the task contract.

Core-8/Core-16 pass rates are **directional regression signals**, not statistical significance.

## 6. Security Boundary (Core)

Allowed: local toy patching, authorization repair, alert triage JSON, regression tests, local prompt-injection resistance (no network, no exfiltration).

Forbidden in Core: exploit generation, real-target testing, live attack chains, offensive CyberGym-style PoC reproduction as weighted tasks.

## 7. Internal Contracts & Diagrams

- Task contract schema: concept-zero §11; implementation `src/bencheval/task_contract.py`
- Registry/linter: `src/bencheval/task_registry.py`
- Dry-run planner: `src/bencheval/planner.py`
- Evidence JSONL: `src/bencheval/evidence.py`
- Report generator: `src/bencheval/report.py`
- Export (Parquet/DuckDB): `src/bencheval/export.py`
- Evidence compare: `src/bencheval/evidence_compare.py`
- Executor / adapters: `src/bencheval/executor.py`, `inspect_adapter.py`, `harbor_adapter.py`, `doctor.py`
- Legacy summary pipeline (Inspect `.eval` → `SummaryRow`): `src/bencheval/summary.py` — preserved; not comparable to Core evidence without migration note.

Diagrams (legacy tracker + vNext overlay): [`docs/diagrams/system-overview.md`](diagrams/system-overview.md)

## 8. Legacy Benchmark Tracker (2026-04-15)

The previous architecture (Inspect + Harbor as primary benchmark lanes, SWE-bench Verified, CyBench-39, JSONL `SummaryRow` rollups) remains in the codebase for historical runs and guarded comparison reports. **New feature work follows vNext phases in [`docs/roadmap.md`](roadmap.md).** Do not block vNext P0–P2 on credential-gated Inspect/Harbor smoke from the old roadmap.

Legacy artifacts are labeled `legacy_static` / `legacy_judged` when displayed alongside vNext evidence (concept-zero §18).

## 9. VETOs (unchanged where still relevant)

- Mixing Calibration/Stretch tasks into weighted Core totals.
- LLM-as-judge for authoritative `primary_pass`.
- Live internet in Core MVP tasks.
- Statistical significance claims from Core-8/Core-16 alone.
