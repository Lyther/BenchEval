# BFCL v4 Tier-2 ledger

This ledger does **not** promote BFCL to Tier-2. It maps readiness §A–§E against
retained source-host evidence plus one imported `private_proof_v1`. Status values
are `proven`, `partial`, `missing`, or `not-applicable`.

Diagnostic lifecycle demonstration: `run-20260824-040631-228703-4756f857` (not registerable).
Registered `passed` run: `run-20260824-045622-854659-a46ae44d` (5/5 smoke categories, official `BFCL_v4_<category>_score.json`). Both predate the new-format run plan.

Refreshed complete proof (independently verified after `bencheval proof import`):
`run-20260826-083403-019994-e449daac` /
`sha256:8323f91621aeae863c78c53722d5ed6b0e91396ea90a7292bfdf10e25f0c38bc`
(`gpt-5.2-2025-12-11`, official generate→evaluate, 1/5 pass, four `model_wrong_solution`,
`cost_basis=unmeasured_no_provider_metering`, `run-plan.json` present). Cleanup
replay is `not-applicable`: `results/` and `scores/` are official evidence.

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

**Tier-2 decision:** not claimed. Cleanup replay is `not-applicable`; do not invent a scratch directory to check a box.
