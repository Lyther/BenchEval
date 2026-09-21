# BFCL v4 Tier-2 ledger

This ledger does **not** promote BFCL to Tier-2. It maps readiness §A–§E against retained source-host evidence plus one imported `private_proof_v1`. Status values are `proven`, `partial`, `missing`, or `not-applicable`.

Diagnostic lifecycle demonstration: `run-20260824-040631-228703-4756f857` (not registerable). Registered `passed` run: `run-20260824-045622-854659-a46ae44d` (5/5 smoke categories, official `BFCL_v4_<category>_score.json`). Both predate the new-format run plan.

Refreshed complete proof (independently verified after `bencheval proof import`): `run-20260826-083403-019994-e449daac` / `sha256:8323f91621aeae863c78c53722d5ed6b0e91396ea90a7292bfdf10e25f0c38bc` (`gpt-5.2-2025-12-11`, official generate→evaluate, 1/5 pass, four `model_wrong_solution`, `cost_basis=unmeasured_no_provider_metering`, `run-plan.json` present). Cleanup replay is `not-applicable`: `results/` and `scores/` are official evidence.

**Clean-host qualified-lane registration (CF3.1, 2026-09-09, host `n37-089-091`, fresh checkout and venv, plan doctor green before launch):** `run-20260909-054622-852393-b3c7eefe` on slice `tool-order-canonical-plumbing-2` with `gpt-5.2-2025-12-11-FC`, registered `passed`. This is the row's current Tier-1 anchor and supersedes the August citations above as *most recent* live evidence; it does not widen the population scope recorded in the table.

| Item | Status | Evidence | Proof boundary | Remaining action | Portability |
| --- | --- | --- | --- | --- | --- |
| A. `execution_support=executable_adapter` | proven | `config/benchmarks.yaml` BFCL row; Tier-0 gate count=4 | Software catalog only | None | local-only |
| A. `adapter_status=manifest_available` | proven | Same catalog row | Software catalog only | None | local-only |
| A. Cyber policy layer | not-applicable | BFCL is not a dual-use benchmark | — | None | not-applicable |
| B. Native harness ≥1 instance | proven | Official generate → evaluate on all five smoke categories in the imported proof | Smoke only | None for Tier-1 | imported `private_proof_v1` |
| B. Version capture | proven | `benchmark_version` `bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b`; cost basis and run plan retained on the refresh | Does not prove later package pins | None | imported `private_proof_v1` |
| B. Evidence completeness | proven | Official score JSONL, raw generate/evaluate artifacts, run-plan, history, projection | Cleanup `skipped` is the no-transient case, not missing evidence | None | imported `private_proof_v1` |
| B. Failure separation | proven | Irrelevance 1.0; four categories native `model_wrong_solution` 0.0 | Does not prove infrastructure-failure labelling live | None for this run | imported `private_proof_v1` |
| B. Cleanup replay | not-applicable | BFCL writes official `results/` and `scores/` only; those names are excluded from `TRANSIENT_ARTIFACT_DIR_NAMES` | Cleanup `skipped` is honest: there is no named BenchEval transient to remove | None unless BFCL later grows a named transient | imported `private_proof_v1` |
| B. Typed slice | proven | `config/slices/bfcl-v4-smoke-5.yaml` | Software only | None | local-only |
| B. Dry-run envelope | proven | `bencheval run bfcl-v4/smoke-5 --dry-run` | Does not prove live spend | None | local-only |
| B. Caveats | proven | Interpretation is `adapter_smoke`; `--diagnostic` is refused | Smoke is not a full-suite claim | Keep smoke labelling | imported `private_proof_v1` |
| C. Runtime admission | not-applicable | Model-only path; no runtime scaffold | — | None | not-applicable |
| D. Comparison validity | not-applicable | No model/runtime superiority claim is made from this smoke run | A future comparison needs a qualified shared population | None unless a comparison claim is proposed | not-applicable |
| D. Failed/invalid retained | proven | Wrong-solution category rows remain | — | None | imported `private_proof_v1` |
| D. Interpretation label | proven | `adapter_smoke` | Diagnostic demonstration never registers `passed` | None | imported `private_proof_v1` |
| E. No native claim without Phase B | proven | Tier-1 is claimed; `benchmark_native_claim` is not | Injected-runner tests stay diagnostic | None | local-only |
| E. No smoke statistical claim | proven | Five-category smoke is not treated as significance | — | None | local-only |
| E. No calibration mix-in | not-applicable | Official BFCL smoke categories only | — | None | not-applicable |

## Retained non-smoke canonical populations (corrected 2026-09-15)

An earlier draft of this ledger called these runs "diagnostic-lane registrations" because the manifest records them `completed`. That was wrong, and the correction matters: **`completed` is a lifecycle status, `diagnostic` is an evidence and plan classification, and they are different axes.** `qualify_lane` rejects a row whose `interpretation_label` is `diagnostic`; it never infers that label from registration status.

Verified directly through `load_verified_proof_inputs(require_complete=True)` and the real `qualify_lane`:

| Run | Slice | Rows | Plan `diagnostic` | Label | Lane qualification |
|---|---|---:|---|---|---|
| X2.4 `run-20260905-064918-223328-f38fe8fe` | `exposure-non-live-v1` | **340** | `false` | `rough_regression` | 340/340 eligible, `ok=True` |
| X3 primary `run-20260907-044713-829381-5e5d4652` | `tool-order-canonical-v1` | 200 | `false` | `rough_regression` | 200/200 eligible, `ok=True` |
| X3 repeat `run-20260907-060237-419067-d9fb217f` | `tool-order-canonical-v1` | 200 | `false` | `rough_regression` | 200/200 eligible, `ok=True` |
| CF4.1 arm A `run-20260909-095350-269014-a37f9311` | `tool-order-canonical-v1` | 200 | `true` | `diagnostic` | rejected: `diagnostic-interpretation` |
| CF4.1 arm C `run-20260909-124738-559243-11afa080` | `tool-order-canonical-v1` | 200 | `true` | `diagnostic` | rejected: `diagnostic-interpretation` |

Only the CF4.1 arms are diagnostic. CF4.1's timeout correction is about **that** study's declared population and says nothing about the X2.4 and X3 canonical runs above.

**Qualification is root-relative, and that is not a portability limit.** `qualify_lane` resolves each row's `artifact_paths` against the supplied repo root, so the root has to match the locators the evidence actually carries:

- **Original run evidence** (`results/evidence/<run_id>.jsonl`) carries locators like `results/raw/<run_id>/…` and qualifies against the root that holds those trees — here `~/BenchEval-exposure`.
- **Portable proof evidence** (`<proof>/evidence.jsonl`) carries proof-relative locators like `artifacts/raw/…` and qualifies against the proof directory itself. All three runs above were re-qualified `ok=True` from a copied proof under `/tmp`, with that copy as the root.

Supplying the wrong root yields `missing-artifacts`. That says nothing about the run and does not require the original host.

**Tier-2 decision:** pending, not refused. Every §A–§E item is `proven` or `not-applicable`, and no contract criterion is unmet — including population, now that the non-smoke canonical evidence above is recorded accurately. What is missing is a decision about **which public claim this row should license**; that decision is the owner's, and this ledger does not pre-empt it in either direction. Cleanup replay stays `not-applicable`; do not invent a scratch directory to check a box.
