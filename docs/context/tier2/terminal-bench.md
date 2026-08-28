# Terminal-Bench Tier-2 ledger

This ledger does **not** promote Terminal-Bench to Tier-2. It maps readiness
§A–§E against imported `private_proof_v1` objects. Status values are `proven`,
`partial`, `missing`, or `not-applicable`.

Imported complete proofs (independently verified after `bencheval proof import`):

| Runtime | run_id | proof_id | Official verdict |
|---|---|---|---|
| `codex-cli` 0.148.0 | `run-20260825-171829-685914-aa08dd1d` | `sha256:fca2295d6844e4dda99799527561985885a90b59e01c865082510eaa63d90c06` | `reward == 0.0` / `model_wrong_solution` |
| `claude-code` 2.1.235 | `run-20260825-173913-754489-4f43e296` | `sha256:afe6f655f7c3f4f940c83703a7c2f5231ae9a87fd998803fdf92ed04967b9592` | `reward == 0.0` / `model_wrong_solution` |
| `claude-code` 2.1.235 cleanup replay | `run-20260826-104126-417176-facd93a7` | `sha256:cd681305651cb985feccacb5e99f38edc8ac210b6e52c20dce3462a99f6e29c7` | Harbor wrote official `reward == 0.0`; evidence is `runtime_launch_failure` / registered `completed`; `cleanup_result=success` |

The first two are Harbor `tier1-one` / `fix-git` on `kimi-k2.7-code` via ByteLLM. Cleanup on those rows is `skipped`. The third row is cleanup-replay only and does not replace Tier-1.

| Item | Status | Evidence | Proof boundary | Remaining action | Portability |
| --- | --- | --- | --- | --- | --- |
| A. `execution_support=executable_adapter` | proven | `config/benchmarks.yaml` Terminal-Bench row; Tier-0 gate count=4 | Software catalog only | None | local-only |
| A. `adapter_status=manifest_available` | proven | Same catalog row | Software catalog only | None | local-only |
| A. Cyber policy layer | not-applicable | Terminal-Bench is not a dual-use benchmark | — | None | not-applicable |
| B. Native harness ≥1 instance | proven | Both imported proofs; official Harbor `result.json` / `verifier_result.rewards["reward"]` | One `fix-git` instance per runtime, not `smoke-5` | None for Tier-1 | imported `private_proof_v1` |
| B. Version capture | proven | `benchmark_version` `terminal-bench@2.1`; Harbor `0.17.1`; runtime versions above; provider hash present | Does not prove later Harbor/agent pins | None | imported `private_proof_v1` |
| B. Evidence completeness | proven | Official result, stdout/stderr, run-plan, history, projection; cleanup-replay retains `harbor-official-result.json` after `harbor-package` removal | Historical rows still record cleanup `skipped`; compare artifact not in this proof store | Keep skipped cleanup visible on historical rows | imported `private_proof_v1` |
| B. Failure separation | proven | Official `model_wrong_solution` retained and qualified; cleanup-replay separately retained `runtime_launch_failure` | Does not prove every failure class live | None for these runs | imported `private_proof_v1` |
| B. Cleanup replay | proven | `run-20260826-104126-417176-facd93a7` `cleanup_result=success`; `harbor-package` absent from proof; `harbor-official-result.json` retained | That run is `runtime_launch_failure`, not a replacement Tier-1; Docker pruning not owned | None | imported `private_proof_v1` |
| B. Typed slice | proven | `config/slices/terminal-bench-tier1-one.yaml` | Software only | None | local-only |
| B. Dry-run envelope | proven | `bencheval run terminal-bench/tier1-one --dry-run` matches one instance | Does not prove live spend | None | local-only |
| B. Caveats | proven | Registered interpretation is `adapter_smoke` | Not a native-claim or statistical result | Keep smoke labelling | imported `private_proof_v1` |
| C. Runtime admission | proven | Both admitted Harbor runtimes launched noninteractively with pinned agent versions | Does not prove other runtimes | None for these two | imported `private_proof_v1` |
| D. Comparison validity | not-applicable | No superiority claim is made in this ledger. A prior source-host compare of these two runs was recorded `comparison_valid` on one shared `fix-git` instance | The compare artifact was not imported here | None unless a comparison claim is proposed | local-only |
| D. Failed/invalid retained | proven | Wrong-solution rows remain | — | None | imported `private_proof_v1` |
| D. Interpretation label | proven | `adapter_smoke` | Not a native-claim or statistical result | None | imported `private_proof_v1` |
| E. No native claim without Phase B | proven | Tier-1 is claimed; `benchmark_native_claim` is not | Injected-runner tests stay diagnostic | None | local-only |
| E. No smoke statistical claim | proven | One-instance `fix-git` is not treated as significance | — | None | local-only |
| E. No calibration mix-in | not-applicable | Official Harbor `fix-git` only | — | None | not-applicable |

**Tier-2 decision:** not claimed. Cleanup replay is now imported; this ledger
makes no superiority claim and does not promote the row.
