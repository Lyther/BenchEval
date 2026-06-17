# Core-16 Expansion Plan

> **Status (2026-05-29):** Planning only. Core-8 remains 8/8 admitted and unchanged.
> **Source:** [`concept-zero.md`](concept-zero.md) §9.

Core-16 adds the remaining two tasks per category. Canonical task IDs follow Core-8 naming under `config/tasks/core-16/`.

## Summary

| Task ID | Category | Profile | Budget | Output type | Core-8 analogue |
|---|---|---|---|---|---|
| `be-core-c3-backward-compatible-config-migration` | coding | E1 | B1 | patch + config | C1/C2 |
| `be-core-c4-minimal-refactor-under-invariants` | coding | E1 | B1 | patch | C1 |
| `be-core-t3-tool-necessity-gate` | tool_usage | E0 | B0 | json | T1 |
| `be-core-t4-stateful-policy-workflow` | tool_usage | E0 | B0 | json + audit log | T2 |
| `be-core-a3-dependency-api-bump` | agentic_coding | E1 | B2 | patch + lockfile | A1/A2 |
| `be-core-a4-feature-with-invariants` | agentic_coding | E1 | B2 | patch | A1 |
| `be-core-s2-authorization-matrix-regression` | defensive_security | E1 | B2 | patch | S1 |
| `be-core-s3-alert-triage-evidence-json` | defensive_security | E0 | B0 | json | S4 |

Layout per task:

```text
config/tasks/core-16/<slug>.yaml
config/tasks/core-16/workspaces/<task-id>/
  prompt.json
  reference.<ext>
  negative.<ext>
  verify.py
  (+ category-specific fixtures)
docs/context/core-16-admission.yaml   # automated gates only; human sign-off pending
```

`config/suites.yaml` `core-16` lists all 16 tasks (Core-8 plus expansion). This admission file covers the eight expansion tasks only; `bencheval task audit core-16` audits Core-8 via `core-8-admission.yaml` and expansion via this file. Human sign-off remains pending for expansion tasks until maintainer review.

---

## C3 — Backward-Compatible Config Migration

**Intent:** Add a new optional config field while preserving old-schema compatibility.

| Field | Value |
|---|---|
| Profile | E1 (offline verifier/local-harness path uses the Core-8 E1 pattern without extra Docker assumptions; live Inspect E1 remains Docker-gated) |
| Output | JSON patch or unified diff against `config/settings.py` + schema snapshot |
| Verifier | Hidden fixture matrix: old configs must still parse; new configs unlock feature flag; lint/typecheck on touched module |
| Negative control | Breaks backward compatibility (removes default, renames key, or drops old path) |
| Hidden checks | Matrix of 6–8 YAML/JSON fixtures not shown in prompt; snapshot hash of normalized config output |
| Internet | false |
| LLM judge | none for primary |

---

## C4 — Minimal Refactor Under Invariants

**Intent:** Restructure internals without API, error-type, or complexity-regression violations.

| Field | Value |
|---|---|
| Profile | E1 |
| Output | patch against small Python package (2–3 modules) |
| Verifier | Public API import surface unchanged; unit tests + invariant script (`max_cyclomatic` or line-count ceiling on changed files); hidden integration test |
| Negative control | Changes public signature, raises unrelated exception type, or exceeds diff locality budget |
| Hidden checks | Extra property test file run only in verifier; diff must stay within declared file set |
| Internet | false |
| LLM judge | none for primary |

---

## T3 — Tool Necessity Gate

**Intent:** Decide whether a mock tool call is required or direct JSON answer suffices.

| Field | Value |
|---|---|
| Profile | E0 |
| Output | JSON: `{ "use_tool": bool, "tool_call"?: {...}, "answer"?: ... }` |
| Verifier | Precision/recall vs gold label set across 4–6 prompt variants in hidden file; schema validation |
| Negative control | Calls tool when unnecessary, skips tool when required, or wrong tool |
| Hidden checks | Held-out prompt IDs with inverted necessity; argument match when tool required |
| Internet | false |
| LLM judge | none for primary |

---

## T4 — Stateful Policy Workflow

**Intent:** Execute CRUD on in-memory policy store under role constraints; emit audit log.

| Field | Value |
|---|---|
| Profile | E0 |
| Output | JSON final state + ordered audit entries |
| Verifier | Final state diff vs gold; audit log sequence match (normalized timestamps); forbidden action absent |
| Negative control | Policy violation (delete without role), missing audit entry, wrong final entity |
| Hidden checks | Alternate starting state in verifier-only fixture; replay determinism on audit ordering |
| Internet | false |
| LLM judge | none for primary |

---

## A3 — Dependency API Bump

**Intent:** Adapt application code to a minor breaking change in a vendored stub dependency.

| Field | Value |
|---|---|
| Profile | E1 |
| Output | patch + updated lockfile stub (`requirements.txt` or `pyproject` fragment) |
| Verifier | Compatibility fixtures import and run; lockfile diff contains expected pin; hidden integration tests pass |
| Negative control | Leaves old API call, bumps wrong package, or breaks unrelated module |
| Hidden checks | Secondary consumer module tested only in verifier; API shim not mentioned in prompt |
| Internet | false (dependency tarball vendored in workspace) |
| LLM judge | none for primary |

---

## A4 — Feature with Invariants

**Intent:** Implement small feature flag while preserving existing behavioral invariants.

| Field | Value |
|---|---|
| Profile | E1 |
| Output | patch across 2–4 files in mini-repo |
| Verifier | New functional tests pass; invariant/property tests on legacy behavior still pass; diff sanity (no test tampering) |
| Negative control | Feature incomplete, breaks invariant, or edits tests |
| Hidden checks | Property-based or table-driven invariant file not in prompt |
| Internet | false |
| LLM judge | none for primary |

---

## S2 — Authorization Matrix Regression

**Intent:** Repair role/permission checks in a local toy auth module.

| Field | Value |
|---|---|
| Profile | E1 |
| Output | patch |
| Verifier | Role matrix exact-match: each `(role, action, resource)` tuple; valid paths pass, forbidden paths fail |
| Negative control | Opens privilege escalation or breaks legitimate access |
| Hidden checks | Expanded matrix rows not listed in prompt; regression tests for prior roles |
| Internet | false |
| LLM judge | none for primary |

---

## S3 — Alert Triage Evidence JSON

**Intent:** Classify static-analysis alerts and cite local evidence IDs (concept-zero §9.4 / §11 example).

| Field | Value |
|---|---|
| Profile | E0 |
| Output | JSON verdict list with normalized evidence IDs |
| Verifier | JSON schema + ID normalization map; no free-text fuzzy match on alert titles |
| Negative control | Wrong severity, hallucinated evidence ID, or missing required field |
| Hidden checks | Extra alerts in verifier-only report; alias ID map |
| Internet | false |
| LLM judge | none for primary (scanner may set `review_required` metadata only) |

---

## Implementation order (recommended)

1. **T3, S3** — E0 JSON tasks; fastest to scaffold; extend Inspect mockllm path patterns from T1/S4.
2. **T4** — E0 stateful; builds on T2 mock-tool patterns.
3. **C3, C4** — E1 coding; mirror C1/C2 workspace layout.
4. **S2** — E1 security patch; mirror S1.
5. **A3, A4** — E1 agentic; largest fixtures; do last.

Per-task gates before admission entry:

- reference passes verifier
- negative fails verifier
- replay deterministic (2 runs)
- `bencheval task lint` clean
- audit automated gates pass; `human_sign_off` left pending

## Out of scope for this plan

- Changing Core-8 contracts, workspaces, or admission records
- Live Inspect/Harbor proof (blocked on credentials, Docker, Harbor CLI)
- Calibration pack (P6) or weighted_total interaction
- Human sign-off (record only after maintainer review)

## Next implementation step

Land **T3** first as a vertical slice: contract YAML, workspace, verifier unit tests, admission stub without human sign-off, then a single incremental entry in the `core-16` suite after automated gates pass.
