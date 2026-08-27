# GPQA Diamond Tier-2 ledger

This ledger does **not** promote GPQA Diamond to Tier-2. It maps readiness
§A–§E against imported `private_proof_v1` objects. Status values are `proven`,
`partial`, `missing`, or `not-applicable`.

Imported complete proofs (independently verified after `bencheval proof import`):

| Kind | run_id | proof_id | Notes |
|---|---|---|---|
| Historical Tier-1 | `run-20260825-160511-036214-304c2cee` | `sha256:aa19d02b7d1457d0f43d9588b3d08c042e967a981ed8537068412e1797ff0eda` | Official Inspect log; unique 2 × epochs 4; accuracy 1.0 |
| Post-retention refresh | `run-20260826-082238-670967-54af8e96` | `sha256:90978d9e161419aba7ca9c48ceedabc1a009403a7e36deeee861b22a7c21c032` | Owned `gpqa-official-log.json`; `score_artifact_sha256` `sha256:cfe18542c44fb9493e8a918c480d3716db664e2116f1f13f09e7c602705072ca`; `verifier_log_path` is the owned copy |
| Cleanup replay | `run-20260826-103433-678152-7ace1b73` | `sha256:a8f17d90cd44dea3f6a032f7db406ec8061f878626c8b2a7615552fe4c6da2f8` | Run-owned Inspect cache under `materialized-workspace` via `XDG_CACHE_HOME`; `cleanup_result=success`; official log retained; transient absent from proof |

All are `kimi-k2.7-code` / ByteLLM / `adapter_smoke`. The refresh is the AR-16 scored-byte retention proof. The third row is cleanup-replay only.

| Item | Status | Evidence | Proof boundary | Remaining action | Portability |
| --- | --- | --- | --- | --- | --- |
| A. `execution_support=executable_adapter` | proven | `config/benchmarks.yaml` GPQA row; Tier-0 gate count=4 | Software catalog only | None | local-only |
| A. `adapter_status=manifest_available` | proven | Same catalog row | Software catalog only | None | local-only |
| A. Cyber policy layer | not-applicable | GPQA is not a dual-use benchmark | — | None | not-applicable |
| B. Native harness ≥1 instance | proven | Both imported proofs; official Inspect eval log | Aggregate smoke (2 unique × 4 epochs), not the full diamond set | None for Tier-1 | imported `private_proof_v1` |
| B. Version capture | proven | `benchmark_version` `gpqa-diamond@inspect-evals-0.8.0+eval-2-B+csv-41d1213cd7a49986` | Does not prove later Inspect pins | None | imported `private_proof_v1` |
| B. Evidence completeness | proven | Official log bytes, stdout/stderr, run-plan, history, projection, score digest; cleanup-replay row also retains the official log after transient removal | Historical rows still record cleanup `skipped` | Keep skipped cleanup visible on historical rows | imported `private_proof_v1` |
| B. Failure separation | proven | Official scores retained; wrong-solution remains representable | These smokes were all-correct | None for these runs | imported `private_proof_v1` |
| B. Cleanup replay | proven | `run-20260826-103433-678152-7ace1b73` `cleanup_result=success`; `materialized-workspace` removed; `gpqa-official-log.json` retained | Docker pruning not owned; historical rows stay `skipped` | None | imported `private_proof_v1` |
| B. Typed slice | proven | `config/slices/gpqa-diamond-smoke.yaml` | Software only | None | local-only |
| B. Dry-run envelope | proven | `bencheval run gpqa-diamond --dry-run` matches 2 planned samples | Live summary emits one aggregate evidence row | None | local-only |
| B. Caveats | proven | Registered interpretation is `adapter_smoke` | Full-suite claim still forbidden | Keep smoke labelling | imported `private_proof_v1` |
| C. Runtime admission | not-applicable | Model-only path; no runtime scaffold | — | None | not-applicable |
| D. Comparison validity | not-applicable | No model/runtime superiority claim is made from these smoke runs | A future comparison needs a qualified shared population | None unless a comparison claim is proposed | not-applicable |
| D. Failed/invalid retained | proven | Official log and owned copy remain | — | None | imported `private_proof_v1` |
| D. Interpretation label | proven | `adapter_smoke` | Not a native-claim or statistical result | None | imported `private_proof_v1` |
| E. No native claim without Phase B | proven | Tier-1 is claimed; `benchmark_native_claim` is not | Injected-runner tests stay diagnostic | None | local-only |
| E. No smoke statistical claim | proven | Two-sample smoke is not treated as significance | — | None | local-only |
| E. No calibration mix-in | not-applicable | Official GPQA Diamond smoke items only | — | None | not-applicable |

**Tier-2 decision:** not claimed. Cleanup replay is now imported; this ledger
still does not promote the row.
