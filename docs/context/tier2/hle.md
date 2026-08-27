# HLE Tier-2 ledger

This ledger does **not** promote HLE to Tier-2. It maps readiness §A–§E against
retained source-host evidence plus imported `private_proof_v1` objects. Status
values are `proven`, `partial`, `missing`, or `not-applicable`.

Registered native run: `run-20260824-092017-110245-dbbdf99e` (dev-box-cpu, official
CAIS judge, 0/2 `model_wrong_solution` for `gpt-5.4-2026-03-05`). Isolated-cache
proof: `hle-isolated-cache-live-20260825T072129Z`. Both predate the new-format
run plan and stay `legacy_unverifiable` / `run_plan_missing_legacy`.

Earlier same-day refresh `run-20260826-090309-188566-06a37606` /
`sha256:b3260e8b17d46ec4da9a848270df2aa69bcf0d59ef94f8cedd81b6dc48601b77`
is structurally imported but predates ambient-cache removal, so it cannot bind
consumed dataset bytes to the verified parquet.

Post-fix identity-bound proof (independently verified after `bencheval proof
import`): `run-20260826-135512-189732-203685b9` /
`sha256:4be3b7cdfb9f06b5eef96929dface503ea68cdbd5b3652126fdaf939e9f4b62b`
(`gpt-5.4-2026-03-05`, official CAIS judge 0/2 `model_wrong_solution`,
`known_post_artifact_small_slice_calibration_failure` after artifacts,
`cleanup_result=success`, `run-plan.json` present, `benchmark_version=
hle@5a81a4c7271a2a2a+data-6d0ee0602e8aea6b`, registered `passed`). Ambient-copy
fallback is absent; pre-warm fail-closes unless `load_dataset` materializes the
pinned revision into a fresh run-owned cache. Remote producer git identity is
`unknown` because that checkout has no `.git`.

| Item | Status | Evidence | Proof boundary | Remaining action | Portability |
| --- | --- | --- | --- | --- | --- |
| A. `execution_support=executable_adapter` | proven | `config/benchmarks.yaml` HLE row; Tier-0 gate count=4 | Software catalog only | None | local-only |
| A. `adapter_status=manifest_available` | proven | Same catalog row | Software catalog only | None | local-only |
| A. Cyber policy layer | not-applicable | HLE is not a dual-use benchmark | — | None | not-applicable |
| B. Native harness ≥1 instance | proven | Official CAIS predict→judge on both smoke samples in `4be3b7cd…` | Smoke only | None for Tier-1 | imported `private_proof_v1` |
| B. Version capture | proven | `hle@5a81a4c7271a2a2a+data-6d0ee0602e8aea6b`; ambient-copy fallback removed; consumed cache is the run-owned pre-warm of the pinned revision | Remote producer git is `unknown` (rsync checkout has no `.git`) | None for dataset identity | imported `private_proof_v1` |
| B. Evidence completeness | proven | Official judged artifact, stdout/stderr, run-plan, history, projection | Predictions file is referenced by the judge command but not an evidence artifact path | None for this refresh | imported `private_proof_v1` |
| B. Failure separation | proven | Native 0/2 `model_wrong_solution`; judge `IndexError` after artifacts is typed as `known_post_artifact_small_slice_calibration_failure` | Does not prove other failure classes live | None for this run | imported `private_proof_v1` |
| B. Cleanup replay | proven | Isolated-cache run plus this refresh `cleanup_result=success` | Docker pruning not owned | None | imported `private_proof_v1` |
| B. Typed slice | proven | `config/slices/hle-smoke.yaml` | Software only | None | local-only |
| B. Dry-run envelope | proven | `bencheval run hle --dry-run` matches smoke instance count | Does not prove live spend | None | local-only |
| B. Caveats | proven | Smoke remains `adapter_smoke`; no `benchmark_native_claim` | Full-suite claim still forbidden | Keep smoke labelling | imported `private_proof_v1` |
| C. Runtime admission | not-applicable | Model-only path; no runtime scaffold | — | None | not-applicable |
| D. Comparison validity | not-applicable | No model/runtime superiority claim is made from this one smoke run | A future comparison needs a qualified shared population | None unless a comparison claim is proposed | not-applicable |
| D. Failed/invalid retained | proven | Wrong-solution rows remain in evidence | — | None | imported `private_proof_v1` |
| D. Interpretation label | proven | Registered evidence is `adapter_smoke` | Not a native-claim or statistical result | None | imported `private_proof_v1` |
| E. No native claim without Phase B | proven | Tier-1 is claimed; `benchmark_native_claim` is not | Isolated-cache/injected tests stay diagnostic | None | local-only |
| E. No smoke statistical claim | proven | Two-sample smoke is not treated as significance | — | None | local-only |
| E. No calibration mix-in | not-applicable | HLE smoke is official CAIS items only | — | None | not-applicable |

**Tier-2 decision:** not claimed. The post-fix proof replaces `b3260e8b…` as the
current identity-bound smoke; this ledger still does not promote the row.
