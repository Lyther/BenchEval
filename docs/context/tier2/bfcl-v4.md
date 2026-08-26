# BFCL v4 Tier-2 ledger

This ledger does **not** promote BFCL to Tier-2. It maps readiness §A–§E against retained source-host evidence. Status values are `proven`, `partial`, `missing`, or `not-applicable`.

Diagnostic lifecycle demonstration: `run-20260824-040631-228703-4756f857` (not registerable). Registered `passed` run: `run-20260824-045622-854659-a46ae44d` (5/5 smoke categories, official `BFCL_v4_<category>_score.json`). Both predate the cost-basis evidence fix, report cleanup `skipped`, and lack a pre-launch `run-plan.json`.

| Item | Status | Evidence | Proof boundary | Remaining action | Portability |
| --- | --- | --- | --- | --- | --- |
| A. `execution_support=executable_adapter` | proven | `config/benchmarks.yaml` BFCL row; Tier-0 gate count=4 | Software catalog only | None | local-only |
| A. `adapter_status=manifest_available` | proven | Same catalog row | Software catalog only | None | local-only |
| A. Cyber policy layer | not-applicable | BFCL is not a dual-use benchmark | — | None | not-applicable |
| B. Native harness ≥1 instance | proven | Official generate → evaluate on all five smoke categories | Source-host `results/`; diagnostic run is not registerable | Refresh one supported-model smoke for a clean Tier-2 source artifact | local-only |
| B. Version capture | partial | `benchmark_version` `bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b`; package/data pins captured | Cost-basis metadata and run plan were not retained on the registered run | Rerun after the cost-basis fix with `run-plan.json` | local-only |
| B. Evidence completeness | partial | Official score JSONL and raw generate/evaluate artifacts | Cleanup recorded `skipped`; no frozen run plan; no private-proof inventory | Export `private_proof_v1` only after a complete new-format run, or mark historical material `legacy_unverifiable` | local-only |
| B. Failure separation | proven | Irrelevance 1.0; four categories native `model_wrong_solution` 0.0 | Does not prove infrastructure-failure labelling live | None for this run | local-only |
| B. Cleanup replay | missing | Registered run reports cleanup `skipped` | Cannot treat skipped cleanup as replay proof | Rerun with `--cleanup always` and inspect the artifact tree | local-only |
| B. Typed slice | proven | `config/slices/bfcl-v4-smoke-5.yaml` | Software only | None | local-only |
| B. Dry-run envelope | proven | `bencheval run bfcl-v4/smoke-5 --dry-run` | Does not prove live spend | None | local-only |
| B. Caveats | proven | Registered interpretation is `adapter_smoke`; `--diagnostic` is refused | Smoke is not a full-suite claim | Keep smoke labelling | local-only |
| C. Runtime admission | not-applicable | Model-only path; no runtime scaffold | — | None | not-applicable |
| D. Comparison validity | missing | No second BFCL run with constant axes | Cannot claim model superiority | Only compare after a second qualified native run | local-only |
| D. Failed/invalid retained | proven | Wrong-solution category rows remain | — | None | local-only |
| D. Interpretation label | proven | Registered evidence is `adapter_smoke` | Diagnostic demonstration never registers `passed` | None | local-only |
| E. No native claim without Phase B | proven | Tier-1 is claimed; `benchmark_native_claim` is not | Injected-runner tests stay diagnostic | None | local-only |
| E. No smoke statistical claim | proven | Five-category smoke is not treated as significance | — | None | local-only |
| E. No calibration mix-in | not-applicable | Official BFCL smoke categories only | — | None | not-applicable |

**Tier-2 decision:** not claimed. Remaining blockers are a refreshed supported-model smoke with cost-basis metadata, cleanup replay, `run-plan.json`, and portable private-proof export.
