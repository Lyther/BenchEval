# Architecture & Decisions

> Status: ACCEPTED
> Source: `concept-zero.md` (2026-04-15, Catherine Li)
> Scope: Reproducible LLM benchmark tracker. Not a new eval framework.

## 1. Stack Selection

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Orchestration | **Inspect AI** | Provider abstraction, scoring, `.eval` logs, first-class reasoning controls [S2][S3]. |
| Native tasks | **inspect-evals** | Ships CyBench (39/40; `motp` excluded GPL) and CyberGym (1,507) [S4]. |
| Harbor tasks | **inspect-harbor + Harbor registry** | Source of SWE-bench Pro public @2 (731) and Terminal-Bench 2 (89) [S5]. |
| Agent scaffolds | **inspect-swe** | Claude Code / Codex CLI style solvers. Sandbox runs, but model calls proxy back to Inspect [S1]. |
| Language | **Python 3.12 + uv** | Matches Inspect ecosystem. Currently lower-bounded in `pyproject.toml`; exact versions pinned after Phase 0 spikes (see roadmap). `uv.lock` is the reproducibility source of truth. |
| Config format | **YAML manifests + committed hashes** | Human-diffable, hashable, reproducible. |
| Summary store | **JSONL in `results/summary/`** | Append-only, greppable, git-friendly. Raw `.eval` files gitignored. |
| Reports | **Generated Markdown in `results/reports/`** | No DB; derive from JSONL. |
| Pricing | **Versioned `config/pricing/YYYY-MM-DD.yaml`** | Freeze estimate provenance per run. |
| Runtime | **Local Docker**, Harbor remote only when scale-out helps | ≥100 GB free disk required **for local Docker-backed runs** [S4]; no disk requirement for Harbor remote. |
| Secrets | **`.env` + provider env vars** | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_BASE_URL` [S2]; `MOONSHOT_API_KEY` + `MOONSHOT_BASE_URL` for the Kimi K2.5 baseline row (Moonshot exposes an OpenAI-compatible endpoint; route via Inspect's OpenAI-compatible provider — confirm exact `moonshot/` model id during Phase 3 prep). |

## 2. Platform Strategy

- **Primary target**: **CLI** (developer workstation + CI worker). No web/desktop/mobile.
- **Build artifact**: Python package + shell scripts under `scripts/`.
- **Shared logic**: Pure Python summary/compare modules; thin shell wrappers around `inspect eval`.

## 3. Evaluation Lanes (Auth Model)

| Lane | Auth | Comparability | Cost field |
|------|------|---------------|------------|
| **Baseline** | Inspect provider env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` [S2], or `MOONSHOT_API_KEY` (+ `MOONSHOT_BASE_URL`, OpenAI-compatible) for the Kimi K2.5 row | Comparable across time | `actual_cost_usd` from provider usage |
| **Experimental** | Claude Code gateway (`ANTHROPIC_AUTH_TOKEN`, `apiKeyHelper`) [S6], standalone Codex CLI [S7], or Cursor CLI (separate **installed-agent path** — not an `inspect-swe` solver; auth terminates at the Cursor platform per `-a/--api-key` or browser flow, and BYOK still routes through Cursor's backend) | Not comparable by default | `estimated_api_equivalent_usd` from pinned price sheet |

Hard rule: never mix `actual_cost_usd` and `estimated_api_equivalent_usd` in a single comparison without an equivalence note.

## 4. Reasoning Controls

- First-class Inspect flags only: `--reasoning-effort`, `--reasoning-tokens` [S3].
- `-M` reserved for provider extras (Anthropic `betas`, `streaming`) [S2].
- Recorded as typed summary fields, not opaque JSON.
- `thinking_budget` terminology is **banned** — dropped from concept-zero revision.
- **Cross-family comparability**: `reasoning_effort` and `reasoning_tokens` are not uniformly supported across providers (Anthropic, OpenAI, local backends differ on which knobs are meaningful, and their token accounting is not equivalent). Experiment matrices must be **split per model family**; a single Cartesian grid across all models is invalid. Summary rows must record which reasoning fields the run actually honored.

## 5. Benchmark Suite

| Tier | Benchmark | Size | Path |
|------|-----------|------|------|
| Primary | SWE-bench Verified | 500 | Native Inspect |
| Primary | CyBench | 39 | Native Inspect (manifest `cybench-39.txt`) |
| Secondary | SWE-bench Pro (public) | 731 | Harbor `scale-ai/swe-bench-pro@2` |
| Secondary | Terminal-Bench 2 | 89 | Harbor `terminal-bench/terminal-bench-2@1` |
| Secondary | CyberGym | 1,507 | Native Inspect |
| Deferred | GAIA, LiveCodeBench | — | Not in first baseline |

**Subset policy**: every subset requires a committed manifest file + sha256 hash recorded in every summary row. Banned label: `CyBench-35`. Smoke manifests: `cybench-smoke-5`, `swebench-verified-smoke-10`.

## 6. Summary Row (Canonical Schema)

Required fields per run (enforced by writer; missing required fields → refuse to write). Optional fields may be `null` per the nullability rules below.

`timestamp, benchmark, benchmark_revision, task_manifest_hash, model, model_snapshot, model_family, solver, solver_version, auth_lane, reasoning_effort_requested, reasoning_tokens_requested, reasoning_effort_honored, reasoning_tokens_honored, provider_model_args, n_samples, resolved, resolved_rate, total_tokens, wall_time_s, actual_cost_usd, estimated_api_equivalent_usd, inspect_version, inspect_swe_version, log_file`.

`resolved_rate` is intentionally stored as a first-class field (greppable JSONL) even though it equals `resolved / n_samples` when `n_samples > 0`; `SummaryRow` validators enforce that equality.

**Nullability rules** (enforced by writer):

- `reasoning_*_requested`: `null` iff the run did not set that knob.
- `reasoning_*_honored`: `null` in any of the following cases — (a) the model family does not support that knob (per the Phase 0 support matrix), (b) the knob was not requested, or (c) the provider response does not expose the realized value. Non-null value may differ from `_requested` if the provider clamped or ignored it; such a difference must be logged. Delta analysis (§7) ignores rows where either side's `_honored` is `null`.
- Exactly one of `actual_cost_usd` / `estimated_api_equivalent_usd` is non-null; the other must be `null`. Never both populated.
- `model_family` is always non-null and drawn from a closed vocabulary (`anthropic`, `openai`, `moonshot`, `local`, …) — used as the join key for per-family reasoning comparisons. `moonshot` is required to represent Kimi base-model rows for the Composer 2 training-stack delta (concept-zero §2.4).
- `solver_version` is always non-null. For `inspect_swe` scaffolds it duplicates `inspect_swe_version`; for other solvers it is a `repo@sha` or `package==version` identifier captured by the run wrapper.
- `inspect_swe_version`: `null` iff the run did **not** use an `inspect_swe` scaffold (solver name does not start with `inspect_swe`). When the solver uses `inspect_swe`, populate from installed package metadata (see provenance table). **Schema-enforced:** non-null iff `solver.startswith("inspect_swe")`.

**Provenance sources** (extraction rules — must exist before strictness is enforced):

| Field | Source |
|-------|--------|
| `model`, `model_snapshot` | `.eval` log header (`eval.model`, `eval.model_base_url` or the resolved snapshot string) |
| `model_family` | run wrapper, derived from the `provider/` prefix of `model` (closed vocabulary) |
| `solver` | `eval.solver` / scaffold name from the task definition |
| `solver_version` | `inspect_swe_version` for `inspect_swe` scaffolds; otherwise the run wrapper stamps a `repo@sha` or `package==version` identifier before the run |
| `inspect_version` | installed `inspect-ai` metadata at run time (`importlib.metadata.version`) |
| `inspect_swe_version` | `importlib.metadata.version("inspect_swe")` when the solver is `inspect_swe`; otherwise `null` |
| `reasoning_effort_requested`, `reasoning_tokens_requested` | `eval.config` generate-config fields as submitted |
| `reasoning_effort_honored`, `reasoning_tokens_honored` | per-family support matrix (Phase 0 spike) crossed with the provider's response payload; `null` when the family does not support the knob, the knob was not requested, or the realized value is not observable in the response |
| `provider_model_args` | `eval.model_args` (after redacting secrets) |
| `task_manifest_hash` | computed by BenchEval from the committed manifest file before the run; stamped into the run environment |
| `benchmark_revision` | native: `inspect_evals` package version + task id; Harbor: `harbor` dataset revision tag |
| `auth_lane` | BenchEval run wrapper (set explicitly per invocation; never inferred) |
| `actual_cost_usd` vs `estimated_api_equivalent_usd` | `actual` only when `auth_lane == baseline_*` and provider usage is present; otherwise compute from `config/pricing/*.yaml` and leave `actual` null |

## 7. Delta Analysis Rules

Comparisons are valid only when `task_manifest_hash`, `benchmark_revision`, `auth_lane`, `solver` + `solver_version`, and `model_family` / `model_snapshot` policy are held constant. Reasoning-control comparisons are valid only within a single `model_family` and only across rows whose `reasoning_*_honored` fields are non-null and comparable. Report uncertainty via bootstrap or Wilson intervals. **No hard-coded "<2% = reproducible" rule.**

## 8. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Subscription auth contaminates baseline | High | High | Isolated experimental lane; separate results namespace |
| Dataset drift / ambiguous subsets | High | High | Committed manifests + sha256 + Harbor revision in every row |
| Scaffold / provider behavior shift | Medium | High | Pin `inspect-*` versions; record snapshots |
| Docker disk exhaustion | Medium | High | Preflight ≥100 GB free **only for local Docker-backed runs**; skip check for Harbor remote execution |
| Reasoning flags misconfigured | Medium | Medium | Reject unknown knobs; first-class typed fields |
| SWE-bench Pro public overstates hidden-set | Medium | High | Internal tracking only; label external validity limit |
| Cost mixing (actual vs estimate) | High | Medium | Schema-enforced separation |
| Cursor CLI beta instability (`--print` hangs, workspace-trust prompts, undocumented rate limits) | High | Medium | Pin `cursor-agent` version; timeout + bounded retry; fall back to Claude Code scaffold and mark row `scaffold_fallback: true`. Experimental lane only; Cursor CLI is a **separate installed-agent path**, not an `inspect-swe` solver (see concept-zero OQ 7–8). |
| Composer 2 training-stack delta misread as RL-only | Medium | Medium | §2.4 row in concept-zero is labeled "training-stack delta (Composer 2 vs Kimi K2.5)"; the RL-only row stays blocked until a pre-RL checkpoint or ablation is published (concept-zero OQ 9). |

## 9. Acknowledged Tech Debt

- No database; JSONL aggregation scans O(N). Acceptable until >50k rows; revisit with DuckDB or SQLite.
- No web UI; reports are static Markdown. Revisit only after baseline lane is stable.
- Experimental auth lane parity with baseline is **unproven**. Do not promote without an equivalence note.
- Hidden / commercial SWE-bench Pro access is out of scope unless external leaderboard claims become a goal.

## 10. VETOs (from concept-zero revision)

- `ANTHROPIC_OAUTH_TOKEN` in baseline path — not in current Inspect provider docs [S2].
- Assuming `inspect_swe` uses CLI subscription billing — model calls proxy back to Inspect [S1].
- `-M thinking_budget` — superseded by `--reasoning-effort` / `--reasoning-tokens` [S3].
- `CyBench-35` label — ambiguous; use the 39-task manifest.
- Disk budget of 65 GB — raised to 100 GB per inspect-evals guidance [S4].

## 11. Contracts & diagrams

- **Internal boundaries (protocols + DTOs):** [`docs/api/internal-contracts.md`](api/internal-contracts.md)
- **Mermaid:** [`docs/diagrams/system-overview.md`](diagrams/system-overview.md), [`docs/diagrams/summary-pipeline-sequence.md`](diagrams/summary-pipeline-sequence.md)
- **Implementations** (adapters) must live under `src/bencheval/` and satisfy the protocols in `src/bencheval/contracts.py` without changing `SummaryRow` semantics.

## Sources

See `concept-zero.md` §Sources for full citations.

[S1]: https://meridianlabs-ai.github.io/inspect_swe/
[S2]: https://inspect.aisi.org.uk/providers.html
[S3]: https://inspect.aisi.org.uk/reasoning.html
[S4]: https://github.com/UKGovernmentBEIS/inspect_evals
[S5]: https://registry.harborframework.com/
[S6]: https://code.claude.com/docs/en/llm-gateway
[S7]: https://developers.openai.com/codex/cli
