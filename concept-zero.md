# BenchEval: LLM Benchmark Evaluation Tracker

## Concept-Zero HLD

**Author:** Catherine Li
**Date:** 2026-04-15
**Status:** Revised draft

---

## Decision Log (Answered as of 2026-04-15)

| OQ | Answer | Required action |
|----|--------|-----------------|
| 1. CyBench subset definition | Use the current native `inspect_evals/cybench` task as the canonical baseline: 39 of 40 tasks, with `motp` excluded for GPL reasons [S4]. Do not use the ambiguous label `CyBench-35`. | Commit the exact task manifest as `config/manifests/cybench-39.txt` and hash it in every result row. |
| 2. Claude Code OAuth token rotation | This is not part of the primary BenchEval execution path. In `inspect_swe`, the agent runs in the sample sandbox but model API calls are proxied back to Inspect [S1]. Current Inspect Anthropic provider docs only document `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL` [S2]. | Remove `ANTHROPIC_OAUTH_TOKEN` from the baseline design. Treat local Claude Code login state or gateway auth as experimental until a reproduction proves it affects Inspect-driven runs. |
| 3. Codex CLI auth model | Same correction. Because `inspect_swe` proxies model calls back to Inspect [S1], the safest current design assumption is that baseline auth should remain with the Inspect model provider, not local Codex CLI ChatGPT-account sign-in. Standalone Codex CLI can authenticate with either a ChatGPT account or an API key [S7], but that is a separate path. | Remove `OPENAI_OAUTH_TOKEN` planning from the baseline design. Keep standalone Codex CLI auth isolated from baseline metrics until proven equivalent. |
| 4. Thinking effort parameterization | Use Inspect first-class reasoning controls: `--reasoning-effort` and `--reasoning-tokens`, or the corresponding `GenerateConfig` fields [S3]. Do not model this as `-M thinking_budget`. Use `-M` only for provider-specific extras such as Anthropic `betas` or `streaming` [S2]. | Change the experiment matrix, CLI examples, and summary schema to use reasoning settings as first-class fields. |
| 5. Cost attribution | API-key runs can use provider-reported usage and cost from Inspect logs. Subscription-backed or gateway-backed runs cannot be treated as true measured spend. | Store `estimated_api_equivalent_usd` from a versioned price sheet for experimental runs, and never mix that with `actual_cost_usd`. |
| 6. SWE-bench Pro private subset | Use the public Harbor dataset for internal trend tracking only. As of 2026-04-15, Harbor exposes `scale-ai/swe-bench-pro@2` with 731 public tasks [S5]. Hidden or commercial access is only needed if the goal becomes external leaderboard-quality claims. | Treat SWE-bench Pro public as useful but not externally conclusive. Record Harbor dataset revision in every run. |
| 7. Cursor CLI baseline eligibility | **Decided — experimental only.** Cursor CLI auth is Cursor-platform auth (`-a/--api-key` or browser flow) [S11]; agent usage is metered through Cursor plans and even BYOK requests traverse Cursor's backend for final prompt assembly [S12] [S13]. This is not baseline-equivalent to direct Inspect provider execution. | Cursor CLI is **experimental-lane only**; never add as a baseline row. Phase 0 smoke confirms headless operation before any run writes a row, and every row records `auth_lane: experimental_cursor` (or similar) so delta analysis refuses cross-lane merges. |
| 8. Cursor CLI `-m` model selection scope | **Decided — bounded to Cursor's supported catalog.** `cursor-agent -m <model>` selects from the models Cursor has integrated, including BYOK against a supported-provider set; it is not arbitrary OpenAI-compatible endpoint routing [S10] [S13] [S14]. | Constrain the "model delta within Cursor harness" axis (§2.4) to Cursor's published supported-model list captured during Phase 0. Open-weight / custom-endpoint evaluation stays out of this axis unless Cursor explicitly adds them to the catalog. |
| 9. Composer-family base-model attribution | **Decided narrowly for Composer 2; other Composer versions remain open.** The Composer 2 technical report (2026-04-15) explicitly names **Kimi K2.5** as the base model, followed by continued pretraining and asynchronous RL [S15]. The report does not publish the pre-RL (post-continued-pretraining) checkpoint. | Unblock the `Composer 2 vs Kimi K2.5` **training-stack-delta** row in §2.4 with [S15] as the source. Do **not** relabel it as an RL-only delta; the RL-only-delta row stays blocked until Cursor publishes the intermediate checkpoint or ablation numbers. Any claim about a Composer version other than v2 requires its own citable source. |

---

## 1. Goals

Build a reproducible, version-controlled evaluation tracker that:

- Measures deltas across model snapshots, reasoning settings, and scaffold choices.
- Produces versioned raw logs plus compact summary artifacts for longitudinal comparison.
- Uses provider-authenticated API-key runs as the default comparable baseline.
- Keeps subscription-backed or gateway-backed runs in a clearly separated experimental lane.
- Focuses on a small set of high-signal agentic coding and cybersecurity benchmarks.

**Non-goals:**

- Building a new evaluation framework.
- Mixing unsupported auth hacks into baseline results.
- Chasing saturated general benchmarks.
- Publishing a public leaderboard before hidden-set access exists.

**Design principles:**

- Every run must record dataset revision, task manifest hash, model snapshot, scaffold version, auth lane, and reasoning settings.
- Prefer fewer benchmarks with clean history over many poorly controlled runs.
- Keep grounded claims in the baseline plan and move speculative extensions into an experimental lane.

---

## 2. Evaluation Stack

### 2.1 Framework Layer

| Component | Role | Notes |
|-----------|------|-------|
| **Inspect AI** | Orchestration, scoring, logs, provider abstraction | Core execution layer |
| **inspect-evals** | Native benchmark task definitions | Includes CyBench, CyberGym, and other Inspect-native tasks [S4] |
| **inspect-harbor** | Interface for running Harbor tasks through Inspect | Use for Harbor datasets such as SWE-bench Pro and Terminal-Bench 2 [S4] |
| **Harbor** | Registry and runtime for Harbor-native datasets | Current public dataset revisions and task counts come from the Harbor registry [S5] |
| **inspect-swe** | Claude Code and Codex CLI style agents as Inspect solvers | Agents run inside the sandbox, but model calls are proxied back to Inspect [S1] [S8] [S9]. **Cursor CLI is not a published `inspect-swe` solver as of 2026-04-15** — the public adapter set is limited to Claude Code and Codex CLI. |
| **Cursor CLI (installed-agent)** | Cursor's `cursor-agent` binary run headless inside a Harbor container as a separate installed-agent path — **not** an `inspect-swe` solver | Auth terminates at the Cursor platform (`-a/--api-key` or browser flow [S11]); usage is metered through Cursor plans and BYOK still passes through Cursor's backend with a bounded supported-model list [S12] [S13] [S14]. Experimental lane only; see Decision Log OQ 7–9. |

### 2.2 Execution Model

- Native tasks run directly inside Inspect via `inspect-evals`.
- Harbor tasks run inside Inspect via `inspect-harbor`, with Harbor providing dataset definitions and revisions [S4] [S5].
- `inspect_swe` agents run inside the sample sandbox, but their model API calls are proxied back to Inspect [S1].
- BenchEval should therefore treat provider auth, usage accounting, and logging as determined by the Inspect model-provider configuration rather than the local CLI login. This is an inference from the documented proxy architecture, not a separately documented billing guarantee.

```text
Inspect AI
├── inspect-evals
│   ├── SWE-bench Verified
│   ├── CyBench
│   └── CyberGym
├── inspect-harbor
│   └── Harbor registry datasets
│       ├── SWE-bench Pro (public)
│       └── Terminal-Bench 2
├── inspect-swe
│   └── sandbox agents
│       ├── Claude Code style solver        [S8]
│       └── Codex CLI style solver          [S9]
│            └── model API calls proxied back to Inspect providers [S1]
│                ├── anthropic/*
│                ├── openai/*
│                └── local compatible backends
└── Cursor CLI installed-agent (separate path; experimental lane)
    └── cursor-agent -p --output-format stream-json   [S10]
         └── auth terminates at Cursor platform       [S11] [S12] [S13]
             └── bounded supported-model catalog      [S14]
```

### 2.3 Benchmark Suite (As of 2026-04-15)

**Primary baseline suite:**

| Benchmark | Current size | Path | Why it belongs in the first baseline |
|-----------|--------------|------|--------------------------------------|
| SWE-bench Verified | 500 | Native Inspect [S4]; Harbor also lists a 500-task dataset [S5] | Stable public software engineering baseline |
| CyBench | 39 | Native Inspect [S4] | Current cyber benchmark with exact task membership pinned |

**Secondary suite:**

| Benchmark | Current size | Path | Notes |
|-----------|--------------|------|-------|
| SWE-bench Pro (public) | 731 | Inspect -> Harbor [S5] | Useful for internal trend tracking; not equivalent to hidden/private evaluation |
| Terminal-Bench 2 | 89 | Inspect -> Harbor [S5] | Terminal-heavy agent benchmark |
| CyberGym | 1,507 | Native Inspect [S4] | Large-scale vulnerability analysis benchmark |

**Deferred until the baseline lane is stable:**

- GAIA
- LiveCodeBench

These are fine future additions, but they do not belong in the first clean baseline until integration, scoring, and contamination policy are pinned.

### 2.4 Scaffold × Model Cross-Evaluation

Scaffold choice is a first-class experiment dimension: the same underlying model can score differently depending on the agentic harness it runs in. BenchEval treats scaffold as a held-constant variable (§4.4) **unless** a run is explicitly part of the cross-evaluation matrix below.

Planned comparisons (all gated on Phase 0 smoke + an equivalence note):

| Axis | Held constant | Varied | Notes |
|------|---------------|--------|-------|
| Scaffold delta | Claude Sonnet 4.5 (each scaffold in whichever lane it supports) | `inspect_swe.claude_code` vs Cursor CLI installed-agent vs bare ReAct reference solver | Cross-lane comparison: Cursor rows stay experimental (not baseline-comparable) per OQ 7. Record `auth_lane` on every row; never merge Cursor and Inspect-provider rows into a single headline number without an equivalence note. |
| Model delta (within Cursor harness) | Cursor CLI installed-agent | Cursor Composer 2 vs Claude Sonnet 4.5 vs GPT-5.4 — **constrained to Cursor's supported-model catalog** [S14] | Arbitrary OpenAI-compatible endpoints are out of scope for this axis per OQ 8. |
| Training-stack delta (Composer 2 vs Kimi K2.5) | Same primary-suite benchmark + task manifest; same evaluation harness when possible | Composer 2 (Cursor CLI; experimental lane) vs Kimi K2.5 base (Moonshot API; baseline lane) | **Unblocked narrowly** by the Composer 2 technical report [S15], which states Composer 2 = Kimi K2.5 + continued pretraining + async RL. This is a **full training-stack delta**, not an RL-only delta. |
| RL-only delta | — | — | **Still blocked.** The pre-RL (post-continued-pretraining) checkpoint is not publicly exposed, so the RL contribution cannot be isolated from [S15] alone. Do not generate this row until Cursor publishes the intermediate checkpoint or equivalent ablation numbers. |

Rule: scaffold cross-evaluation never mixes auth lanes inside a single comparison. Every row records `solver`, `solver_version`, and `auth_lane` per the architecture §6 schema.

### 2.5 Subset Policy

- No ambiguous labels such as `CyBench-35`.
- Every subset must have a committed manifest file and a content hash.
- Smoke suites must use explicit names such as `cybench-smoke-5` and `swebench-verified-smoke-10`.
- Reports must always record both the benchmark family and the exact task manifest.

---

## 3. Authentication and Reasoning Controls

### 3.1 Evaluation Lanes

| Lane | Auth path | Default use | Comparability |
|------|-----------|-------------|---------------|
| **Baseline** | Inspect provider auth such as `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or compatible provider credentials [S2] | All official baselines | Comparable |
| **Experimental** | Standalone CLI or gateway-backed auth such as Claude Code `ANTHROPIC_AUTH_TOKEN` / `apiKeyHelper` [S6], Codex ChatGPT sign-in [S7], or Cursor CLI subscription (`CURSOR_API_KEY`, obtained from the Cursor dashboard) | Exploratory runs only | Not comparable by default; rate-limit behavior for Cursor headless usage is undocumented (see Risk Register) |

### 3.2 Correct Auth Model

- Current Inspect Anthropic provider docs document `ANTHROPIC_API_KEY` and `ANTHROPIC_BASE_URL`, not `ANTHROPIC_OAUTH_TOKEN` [S2].
- Standalone Claude Code supports gateway-style bearer auth with `ANTHROPIC_AUTH_TOKEN`, plus rotating credentials through `apiKeyHelper` and `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` [S6].
- Standalone Codex CLI prompts for either ChatGPT sign-in or API key auth [S7].
- Because `inspect_swe` proxies model calls back to Inspect [S1], BenchEval should not assume local CLI login state is the auth or billing source for baseline evals unless that behavior is reproduced explicitly.

### 3.3 Reasoning Controls

- Use Inspect `--reasoning-effort` and `--reasoning-tokens`, or the equivalent `GenerateConfig` fields [S3].
- Use `-M` only for provider-specific extras such as Anthropic `betas` or `streaming` [S2].
- Record reasoning settings as first-class summary fields, not opaque free-form JSON blobs.

```bash
inspect eval ... --model anthropic/claude-sonnet-4-6 \
  --reasoning-effort medium \
  --reasoning-tokens 4096

inspect eval ... --model openai/gpt-5.4 \
  --reasoning-effort medium
```

### 3.4 Cost Attribution

- API-key lane: use provider-reported usage and cost from Inspect logs when available.
- Experimental lane: store token usage, wall-clock time, and `estimated_api_equivalent_usd` computed from a versioned price sheet.
- Never compare `actual_cost_usd` from API-key runs to `estimated_api_equivalent_usd` from subscription-backed or gateway-backed runs without labeling the difference.

---

## 4. Results and Historical Tracking

### 4.1 Required Metadata Per Run

- Benchmark family
- Benchmark revision or Harbor dataset revision
- Task manifest hash
- Model name and snapshot
- Solver or scaffold version
- Auth lane
- Reasoning settings
- Token usage, wall time, and task metrics
- Actual cost or estimate provenance

### 4.2 Repository Structure

```text
bencheval/
├── config/
│   ├── manifests/
│   │   ├── cybench-39.txt
│   │   ├── swebench-verified-500.txt
│   │   ├── swebench-verified-smoke-10.txt
│   │   └── swe-bench-pro-public-r2.txt
│   ├── benchmarks.yaml
│   ├── models.yaml
│   ├── experiments.yaml
│   └── pricing/
│       └── 2026-04-15.yaml
├── results/
│   ├── raw/                     # Large .eval files, not committed
│   ├── summary/                 # Committed JSONL summaries
│   └── reports/                 # Generated markdown reports
├── scripts/
│   ├── run_eval.sh
│   ├── extract_summary.py
│   ├── compare.py
│   └── verify_auth.sh
├── Makefile
└── .env.example
```

### 4.3 Summary Schema (JSONL)

Canonical definition and nullability rules live in [`docs/architecture.md`](docs/architecture.md) §6. This illustrative row must stay in lockstep with that file — update both, or neither.

```json
{
  "timestamp": "2026-04-15T14:30:00Z",
  "benchmark": "swebench-verified",
  "benchmark_revision": "inspect-evals==0.8.0",
  "task_manifest_hash": "a...(sha256 hex, 64 chars)...",
  "model": "anthropic/claude-sonnet-4-6",
  "model_snapshot": "provider-specific-snapshot-id",
  "model_family": "anthropic",
  "solver": "inspect_swe.claude_code",
  "solver_version": "0.2.47",
  "auth_lane": "baseline_api",
  "reasoning_effort_requested": "medium",
  "reasoning_tokens_requested": 4096,
  "reasoning_effort_honored": "medium",
  "reasoning_tokens_honored": 4096,
  "provider_model_args": {},
  "n_samples": 500,
  "resolved": 312,
  "resolved_rate": 0.624,
  "total_tokens": 4823901,
  "wall_time_s": 7200,
  "actual_cost_usd": "41.82",
  "estimated_api_equivalent_usd": null,
  "inspect_version": "0.3.205",
  "inspect_swe_version": "0.2.47",
  "log_file": "raw/2026-04-15_swebench-verified_claude-sonnet-4-6/logs.eval"
}
```

Key invariants (from `docs/architecture.md` §6): exactly one of the two `*_cost_usd` fields is non-null; `reasoning_*_honored` may be null when the family does not support the knob, the knob was not requested, or the realized value is not observable; `resolved ≤ n_samples` and `resolved_rate == resolved / n_samples`; `model_family` is drawn from a closed vocabulary.

### 4.4 Delta Analysis

Canonical rule set lives in [`docs/architecture.md`](docs/architecture.md) §7. Summary:

Compare only when these are held constant:

- `task_manifest_hash`
- `benchmark_revision`
- `auth_lane`
- `solver` **and** `solver_version`
- `model_family` / `model_snapshot` policy

Reasoning-control comparisons are additionally restricted to rows within a single `model_family` whose `reasoning_*_honored` fields are non-null and comparable.

Primary comparisons:

- Model snapshot deltas (within a family)
- Reasoning setting deltas (within a family; honored fields only)
- Solver deltas where the routing is actually comparable and auth lanes agree
- Training-stack deltas like Composer 2 vs Kimi K2.5 (see §2.4) — cross-lane, must carry an equivalence note
- Temporal drift on the same pinned configuration

Report uncertainty using bootstrap or Wilson intervals. Do not hard-code "delta < 2%" as a universal reproducibility rule.

---

## 5. Automation and Environment

### 5.1 Triggers

| Trigger | Action |
|---------|--------|
| Manual dispatch | Run a specific benchmark x model x config |
| Weekly cron | Re-run the last pinned baseline to detect provider-side drift |
| New model release detected | Queue the primary baseline suite after manual confirmation |
| Quarterly | Run the full primary suite plus selected secondary benchmarks |

### 5.2 Execution Environment

- Use local Docker for native Inspect evals.
- Use Harbor-backed remote execution only when a benchmark benefits from scale-out.
- Budget for **100 GB free disk**, not 65 GB, because Inspect Evals recommends roughly 35 GB base plus up to 65 GB extra for Docker-backed evals [S4].
- Prefer a dedicated machine or isolated cloud worker for multi-hour runs.

### 5.3 Test Gates

- Run committed smoke manifests before every full run.
- Re-run the same pinned config on the same auth lane when validating reproducibility.
- Verify provider credentials before launching long jobs.
- Refuse to write summary rows if task manifest hash, dataset revision, or scaffold version is missing.

---

## 6. Phased Plan

### Phase 0 - Bootstrap

- Install Inspect AI, inspect-evals, inspect-harbor, and inspect-swe.
- Commit canonical manifests for SWE-bench Verified 500, CyBench 39, and smoke subsets.
- Run API-key smoke baselines on `swebench-verified-smoke-10` and `cybench-smoke-5`.
- Confirm `.eval` logs parse into summary rows.
- Freeze a price sheet snapshot under `config/pricing/`.
- **Cursor CLI headless smoke** (experimental lane, no summary rows written): verify `cursor-agent -p --output-format stream-json` runs inside a Harbor installed-agent container with `CURSOR_API_KEY`. Record the exact CLI version, supported `-m` values, and any `--print` hang / trust-prompt issues encountered (OQ 7–8, Risk Register row).

### Phase 1 - Baseline Collection

- Run full SWE-bench Verified 500 and CyBench 39 on current Anthropic and OpenAI API-key models.
- Build `extract_summary.py`.
- Commit summary rows and the first delta report.

### Phase 2 - Reasoning Experiments

- Sweep `reasoning_effort` and `reasoning_tokens` using Inspect flags.
- Keep the scaffold version fixed for the full experiment matrix.
- Report performance, wall-clock time, token usage, and uncertainty intervals.

### Phase 3 - Harbor Expansion

- Add Harbor public datasets `scale-ai/swe-bench-pro@2` and `terminal-bench/terminal-bench-2@1`.
- Record Harbor dataset revision in every run.
- Decide whether private or commercial benchmark access is worth pursuing based on actual project value.
- **Kimi K2.5 baseline collection** (Moonshot API key, baseline lane): run the primary suite against Kimi K2.5 so the Composer 2 training-stack delta has a comparable reference. Rows use `model_family: moonshot`. This is the only §2.4 cross-eval prep work that fits in Phase 3 — everything involving Cursor waits for Phase 4.

### Phase 4 - Experimental Auth Lane (gate for all Cursor / Composer work)

- Only after the API-key baseline lane is stable, introduce the experimental results namespace (`auth_lane: experimental_*`) and plumb Claude Code gateway [S6] + standalone Codex CLI [S7] auth.
- Integrate the Cursor CLI installed-agent path (per OQ 7–8): Cursor platform auth (`-a/--api-key` / browser flow [S11]), pinned `cursor-agent` version, and the captured supported-model catalog [S14].
- **Scaffold × model cross-evaluation** (per §2.4) lands here, not in Phase 3, because every variant it touches — scaffold delta, Cursor-harness model delta, Composer 2 vs Kimi training-stack delta — emits at least one row that must be in the experimental lane.
- Require an equivalence note per experimental run before any baseline comparison. Never merge experimental and baseline rows into a single headline number.
- Keep any credential-refresh helper outside the baseline result path.
- **RL-only delta** remains blocked (OQ 9); do not generate that row until Cursor publishes the pre-RL checkpoint or ablation numbers.

### Phase 5 - Automation

- Build `run_eval.sh` and `verify_auth.sh`.
- Add weekly regression reruns.
- Add model-release detection and quarterly reports after the manual baseline flow is stable.

---

## 7. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Unsupported subscription auth in the Inspect baseline path | High | High | Keep subscription or gateway auth in a separate experimental lane; do not block baseline on it |
| Dataset drift or ambiguous subsets | High | High | Commit manifests, hash them, and record Harbor dataset revisions |
| Scaffold or provider behavior changes between runs | Medium | High | Pin versions and record model snapshot plus solver version |
| Disk exhaustion during Docker-heavy evals | Medium | High | Require 100 GB free space and add preflight disk checks |
| Reasoning controls are misconfigured | Medium | Medium | Use first-class Inspect flags and reject unknown knobs |
| Public-only SWE-bench Pro overstates hidden-set generalization | Medium | High | Use the public set for internal tracking only and label the external validity limit |
| Cost comparisons mix actual spend and estimates | High | Medium | Separate `actual_cost_usd` from `estimated_api_equivalent_usd` |
| Cursor CLI beta instability (known hangs in `--print`, workspace-trust prompts, undocumented rate limits) | High | Medium | Pin `cursor-agent` version per run; wrap in timeout + bounded retry; on repeated failure, fall back to Claude Code scaffold and mark the row `scaffold_fallback: true` |

---

## ChangeLog

### What changed

- Replaced the original open questions with concrete decisions or clearly bounded experimental-lane rules.
- Fixed the incorrect assumption that Claude Code or Codex CLI subscription auth is the primary auth path when used through `inspect_swe`.
- Corrected benchmark sizes and revisions: SWE-bench Verified 500, CyBench 39, CyberGym 1,507, Terminal-Bench 2 public 89, and SWE-bench Pro public Harbor revision 2 with 731 tasks.
- Replaced `thinking_budget` / `-M` framing with Inspect's current `reasoning_effort` and `reasoning_tokens` controls.
- Raised the storage recommendation from 65 GB to 100 GB and added manifest hashing, dataset revision tracking, and auth-lane separation.

### Why

- The previous draft mixed unsupported auth assumptions with the baseline path, which would have produced misleading comparisons.
- The revised draft makes the primary lane reproducible and keeps speculative auth experiments from contaminating longitudinal results.

### Grounded now

- `inspect_swe` proxy behavior
- Current Inspect Anthropic provider env vars and reasoning controls
- Current public benchmark sizes and Harbor dataset revisions
- Claude Code gateway auth helpers
- Codex CLI standalone auth options

### Still speculative

- Whether a subscription-backed experimental lane can be made operationally equivalent to API-key baselines
- Whether private or commercial SWE-bench Pro access is worth the effort for this project

---

## Sources (as of 2026-04-15)

- **[S1] Inspect SWE**
  URL: <https://meridianlabs-ai.github.io/inspect_swe/>
  Publication/update date: 2026-03-16 (`Last-Modified`)
  Relevance: Documents that Inspect SWE agents run in the sample sandbox and proxy model API calls back to Inspect.

- **[S2] Inspect AI - Model Providers**
  URL: <https://inspect.aisi.org.uk/providers.html>
  Publication/update date: 2026-04-10 (`Last-Modified`)
  Relevance: Current Anthropic provider env vars and the meaning of provider-specific `-M` model args.

- **[S3] Inspect AI - Reasoning**
  URL: <https://inspect.aisi.org.uk/reasoning.html>
  Publication/update date: 2026-04-10 (`Last-Modified`)
  Relevance: Current `reasoning_effort` and `reasoning_tokens` controls in CLI and `GenerateConfig`.

- **[S4] Inspect Evals repository / README**
  URL: <https://github.com/UKGovernmentBEIS/inspect_evals>
  Publication/update date: Accessed 2026-04-15
  Relevance: Current CyBench 39/40 task note, CyberGym 1,507 instances, Harbor integration note, and disk guidance.

- **[S5] Harbor Registry**
  URL: <https://registry.harborframework.com/>
  Publication/update date: Live registry accessed 2026-04-15; page data includes `terminal-bench-2@1` published 2026-03-20, `swe-bench-verified@1` published 2026-03-24, and `scale-ai/swe-bench-pro@2` published 2026-04-15
  Relevance: Current public task counts and dataset revisions for Harbor-backed benchmarks.

- **[S6] Claude Code docs - LLM gateway configuration**
  URL: <https://code.claude.com/docs/en/llm-gateway>
  Publication/update date: Accessed 2026-04-15
  Relevance: Documents `ANTHROPIC_AUTH_TOKEN`, `apiKeyHelper`, and TTL-based credential rotation for standalone Claude Code gateway usage.

- **[S7] Codex CLI docs**
  URL: <https://developers.openai.com/codex/cli>
  Publication/update date: 2026-04-15 (`Last-Modified`)
  Relevance: Documents that standalone Codex CLI prompts for ChatGPT sign-in or API key auth.

- **[S8] Inspect SWE — Claude Code agent**
  URL: <https://meridianlabs-ai.github.io/inspect_swe/claude_code.html>
  Publication/update date: Accessed 2026-04-15
  Relevance: Confirms Claude Code is a published `inspect-swe` solver.

- **[S9] Inspect SWE — Codex CLI agent**
  URL: <https://meridianlabs-ai.github.io/inspect_swe/codex_cli.html>
  Publication/update date: Accessed 2026-04-15
  Relevance: Confirms Codex CLI is a published `inspect-swe` solver. The adapter set is limited to Claude Code and Codex CLI as of this date; there is no published Cursor CLI adapter.

- **[S10] Cursor CLI — Parameters**
  URL: <https://docs.cursor.com/en/cli/reference/parameters>
  Publication/update date: Accessed 2026-04-15
  Relevance: Documents `-p/--print`, `--output-format`, `-m/--model`, and `-a/--api-key` flags for `cursor-agent`.

- **[S11] Cursor CLI — Authentication**
  URL: <https://docs.cursor.com/en/cli/reference/authentication>
  Publication/update date: Accessed 2026-04-15
  Relevance: Cursor CLI auth uses Cursor-platform credentials (`-a/--api-key` or browser flow), not direct provider credentials.

- **[S12] Cursor — Plans, usage, and pricing**
  URL: <https://docs.cursor.com/get-started/usage>
  Publication/update date: Accessed 2026-04-15
  Relevance: Agent usage, including CLI agent usage, is metered through Cursor plans; not equivalent to direct provider billing.

- **[S13] Cursor — API keys (BYOK)**
  URL: <https://docs.cursor.com/advanced/api-keys>
  Publication/update date: Accessed 2026-04-15
  Relevance: BYOK requests are still routed through Cursor's backend; custom API keys are limited to supported standard chat models.

- **[S14] Cursor — Models**
  URL: <https://docs.cursor.com/models>
  Publication/update date: Accessed 2026-04-15
  Relevance: Bounded supported-model catalog; there is no documented support for arbitrary OpenAI-compatible endpoints.

- **[S15] Cursor — Composer 2 Technical Report**
  URL: <https://cursor.com/resources/Composer2.pdf>
  Publication/update date: 2026-04-15
  Relevance: Names Kimi K2.5 as Composer 2's base model, followed by continued pretraining and asynchronous RL. Supports the §2.4 "training-stack delta" framing. Does **not** publish a pre-RL checkpoint, so an RL-only delta remains unevaluable from this source alone.
