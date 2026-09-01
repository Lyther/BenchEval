# BenchEval operator-console prototype

Status: **IMPLEMENTED visual reference; generated boards are not screenshots**

Last updated: 2026-09-01

Source concept: [`../context/concept-zero.md`](../context/concept-zero.md)

## Visual prototypes

- [`frontend-dashboard-v2.png`](frontend-dashboard-v2.png) — primary overview,
  catalog/proof health, recent runs, readiness, and the global live-run strip.
- [`frontend-workflows-v1.png`](frontend-workflows-v1.png) — Run Builder, Live
  Run Detail, Catalog, Compare, Proofs, and Reports/Exports/Readiness.

The images are interaction and visual-design references. They are not screenshots
of implemented behavior and do not establish any readiness claim. Exact values in
the eventual UI must come from typed application DTOs, never from image text.

## Product stance

The console is an optional, loopback-only browser entry point for the existing
local BenchEval control plane. It does not replace the CLI, expose a public HTTP
API, add a database, or reinterpret benchmark evidence. CLI and UI call the same
typed application operations; YAML, JSONL, run artifacts, reports, and the local
proof store remain authoritative.

## Information architecture

### Overview

- Tier-0 software, Tier-1 live proof, and Tier-2 readiness are separate cards.
- Catalog counts distinguish executable, diagnostic-only, and catalog-only
  benchmarks; MOMO appears separately as an agent scaffold.
- Recent runs separate registration state from task outcome and interpretation.
- Environment health reports capability or credential *presence*, never values.
- The global live-run strip provides one place to return to an active session.

### Catalog

- Tabs: Benchmarks, Models, Runtimes, Agents, Providers.
- Benchmark states: executable, diagnostic-only, catalog-only.
- Runtime/provider admission and agent scaffold/admission are explicit text.
- Catalog-only rows have no run control. Diagnostic launch requires a deliberate
  diagnostic opt-in and permanently ineligible interpretation.

### Run Builder

1. **Axes:** benchmark/slice, model/provider, runtime XOR agent when applicable.
2. **Plan:** canonical plan preview, official harness, identity, budgets, paths,
   cost basis, network policy, diagnostic/caveat labels.
3. **Preflight:** doctor checks and fail-before-charge blockers.
4. **Confirm:** dry run or explicit launch confirmation; never silently retry.

Unknown IDs, unsupported axes, scaffold agents, non-executable benchmarks, and
provider-route mismatch fail through the same domain validators as the CLI.

### Runs & Evidence

- Searchable validated current-state projection over append-only run history.
- Run detail: lifecycle timeline, live logs, plan, evidence, official result,
  artifacts, registration history, cost/latency/tokens, failure and validity.
- Registration actions expose only legal transitions. `passed` is enabled only
  after the canonical qualification and producer/provenance gates pass.
- Browser refresh never launches again. A process restart reconstructs durable
  state but does not claim to resume an in-memory active process.

### Compare

- Select baseline and current evidence/run objects.
- Show comparison validity before any headline metric.
- Show shared eligible intersection, excluded rows, constant/drifting axes,
  deltas, intervals when meaningful, and all caveats.
- Smoke and one-instance comparisons are explicitly not superiority claims.

### Reports & Exports

- Markdown evidence report.
- Markdown or JSON comparison output.
- Parquet or DuckDB analytical export.
- Public redacted or private run bundle, including optional comparison material.
- Exclusive output destinations and typed errors; no browser-side content rewrite.

### Proofs

- List local content-addressed proofs and inventory roles.
- Export `private_proof_v1` from a run, verify a directory/archive, import into
  `sha256/<digest>`, and inspect verification or legacy-unverifiable reasons.
- Verification means inventory/content integrity, **not creator signature**.
- Permanent local retention: there is no delete, replace, TTL, prune, or garbage-
  collection control.

### Readiness

- Benchmark-specific Tier-2 ledgers with proven/partial/missing/not-applicable.
- Registered Tier-1 proof references and software-gate status.
- Doctor/preflight summaries and concrete unblock actions.
- Diagnostic results and wrong solutions remain distinguishable from
  infrastructure failure and readiness blockers.

### Environment

- Active config root, results/proof roots, installed optional groups, Docker/
  Harbor/Inspect/runtime availability, and provider-variable presence.
- No credential values, `.env` editor, arbitrary shell, or remote-bind setting.
- Accessibility controls: dark/light/system, density, reduced motion, and
  keyboard-shortcut reference; preferences are non-authoritative session state.

## Feature-coverage contract

| Canonical operation | Console surface | Mutation and retry rule |
|---|---|---|
| `list`, `benchmark list/show`, `catalog … list/show` | Overview and Catalog | Read-only; refreshable. |
| `run … --dry-run` | Run Builder plan preview | Pure; safe to repeat. |
| `doctor` | Preflight and Environment | Read-only probe; explicit rerun. |
| `run … -y` / diagnostic run | Confirm and Live Run Detail | New run ID and exclusive output claim; never automatic retry. |
| `evidence list --current` | Runs & Evidence | Read-only validated projection over raw history. |
| `evidence register` | Run detail registration action | Legal append-only transition; no blind retry. |
| `report` | Reports & Exports and Run Detail | Exclusive output; result linked after success. |
| `compare` | Compare | Read-only analysis plus optional exclusive output. |
| `export` | Reports & Exports | Exclusive Parquet/DuckDB destination. |
| `export-run` | Reports & Exports | Explicit public/private visibility; exclusive destination. |
| `proof export` | Run Detail and Proofs | Canonical inventory; no partial destination. |
| `proof verify` | Proofs | Read-only integrity check. |
| `proof import` | Proofs | Verify first; digest-idempotent install; no manifest replay. |

## Visual system

- Desktop-first 16:9 workspace; responsive tablet support, no mobile run launch in
  the first implementation slice.
- Graphite/navy shell, warm neutral content surfaces, restrained teal/blue/amber/
  coral semantics. Every status also has text and an icon.
- Data-dense tables use sticky labelled headers, optional density, and monospaced
  IDs/digests. Full values are copyable and never hidden only in tooltips.
- Keyboard-visible focus, skip navigation, labelled controls, focus return from
  dialogs, non-obscured focus, polite live status, reduced motion, and no color-
  only meaning follow the applicable WCAG 2.2 requirements.

## Image-generation brief

Built-in image generation was used in `ui-mockup` mode. The final prompts required
a shippable local technical operations UI, the exact navigation and truth states,
actual BenchEval benchmark/catalog labels, distinct registration/outcome/tier
semantics, permanent unsigned proof inventory, no secrets, no offensive execution
controls, and no delete action. Generated drafts were inspected and corrected when
they invented benchmark names or confused wrong-solution, diagnostic, registration,
and readiness states.
