# HLE Tier-2 ledger

This ledger does **not** promote HLE to Tier-2. It maps readiness §A–§E against retained source-host evidence. Status values are `proven`, `partial`, `missing`, or `not-applicable`.

Registered native run: `run-20260824-092017-110245-dbbdf99e` (dev-box-cpu, official CAIS judge, 0/2 `model_wrong_solution` for `gpt-5.4-2026-03-05`). Isolated-cache proof: `hle-isolated-cache-live-20260825T072129Z`. Neither artifact includes a pre-launch `run-plan.json`.

| Item | Status | Evidence | Proof boundary | Remaining action | Portability |
| --- | --- | --- | --- | --- | --- |
| A. `execution_support=executable_adapter` | proven | `config/benchmarks.yaml` HLE row; Tier-0 gate count=4 | Software catalog only | None | local-only |
| A. `adapter_status=manifest_available` | proven | Same catalog row | Software catalog only | None | local-only |
| A. Cyber policy layer | not-applicable | HLE is not a dual-use benchmark | — | None | not-applicable |
| B. Native harness ≥1 instance | proven | Registered run + official judged JSON | Source-host `results/`; no portable proof | Export `private_proof_v1` from the source host | local-only |
| B. Version capture | proven | Evidence `benchmark_version` `hle@5a81a4c7271a2a2a+data-6d0ee0602e8aea6b`; harness/adapter/model/judge/provider hashes | Does not include a frozen `run-plan.json` | Classify existing material `legacy_unverifiable` / `run_plan_missing_legacy` until a new-format rerun | local-only |
| B. Evidence completeness | partial | Official judged artifact, stdout/stderr, isolated-cache byte manifest | Missing pre-launch run plan; public/private proof inventory not exported | Export coherent private proof or rerun | local-only |
| B. Failure separation | proven | Native 0/2 `model_wrong_solution` retained and qualified | Does not prove other failure classes live | None for this run | local-only |
| B. Cleanup replay | proven | Isolated-cache run: default cleanup removed `hle-datasets-cache` and kept evidence | Docker pruning not owned | None | local-only |
| B. Typed slice | proven | `config/slices/hle-smoke.yaml` | Software only | None | local-only |
| B. Dry-run envelope | proven | `bencheval run hle --dry-run` matches smoke instance count | Does not prove live spend | None | local-only |
| B. Caveats | proven | Smoke remains `adapter_smoke`; no `benchmark_native_claim` | Full-suite claim still forbidden | Keep smoke labelling | local-only |
| C. Runtime admission | not-applicable | Model-only path; no runtime scaffold | — | None | not-applicable |
| D. Comparison validity | missing | No second HLE run with constant axes | Cannot claim model superiority | Only compare after a second qualified native run | local-only |
| D. Failed/invalid retained | proven | Wrong-solution rows remain in evidence | — | None | local-only |
| D. Interpretation label | proven | Registered evidence is `adapter_smoke` | Not a native-claim or statistical result | None | local-only |
| E. No native claim without Phase B | proven | Tier-1 is claimed; `benchmark_native_claim` is not | Isolated-cache/injected tests stay diagnostic | None | local-only |
| E. No smoke statistical claim | proven | Two-sample smoke is not treated as significance | — | None | local-only |
| E. No calibration mix-in | not-applicable | HLE smoke is official CAIS items only | — | None | not-applicable |

**Tier-2 decision:** not claimed. Remaining blockers are portable private-proof export (or an honest `legacy_unverifiable` classification) and the missing historical run plan.
