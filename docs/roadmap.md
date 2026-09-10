# Execution Roadmap

> **Status:** ACCEPTED capability correction; config-first recovery (CF) is the current implementation priority (CF1–CF4.1 done 2026-09-09; X5.1 next). Completed first-model exposure work is retained; broader onboarding and final readiness remain incomplete.
> **Last updated:** 2026-09-09.
> **Source concept:** [`docs/context/concept-zero.md`](context/concept-zero.md).
> **Operator contract:** [`README.md`](../README.md), [`docs/architecture.md`](architecture.md), [`docs/api/internal-contracts.md`](api/internal-contracts.md).
> **Production bar:** [`production-readiness.md`](context/production-readiness.md) + `make check-production-v1`.
> **Principle:** Prefer official harnesses and evidence-bound claims. A benchmark becomes executable only after its official generation/execution and scoring phases form one identity-bound lifecycle; green software tests never substitute for live proof.
> **Implemented UI extension:** [`docs/prototypes/frontend-v1.md`](prototypes/frontend-v1.md) and architecture §20–§21. The CLI remains stable automation; the optional console is loopback-only.
> **Exposure principle:** Preserve native scores and official runners. Measure benchmark-specific dependence under declared verifier/access/freshness conditions; never infer a clean model, cheating, or a universal decontaminated score.

## Current roadmap

Live operator instructions. The historical ledger below is archive-only.

## Current state (2026-09-09)

### Tier-0 executable product surface

```text
benchmark  →  (runtime | agent)?  →  model via provider  →  evidence
```

| Axis | Verified scope / remaining limitation |
|------|-----------------------|
| Benchmarks | `terminal-bench`, `gpqa-diamond`, `hle`, `bfcl-v4` |
| Runtimes | `claude-code`, `codex-cli` |
| Agents | `terminus-2` admitted for exactly the demonstrated combination (Terminus-2 2.0.0 with `parser_name=json`, Harbor 0.17.1, Terminal-Bench 2.1 `fix-git`, `ollama-qwen3.5-397b-fc` on direct Ollama Cloud; CF2.3 diagnostic proof, first ordinary `passed` run in CF3.1); `momo` is a discoverable, non-executable scaffold; import-path agents are refused at launch |
| Providers | `bytellm` and `ollama-cloud` are admitted `openai_compatible` routes with live CLI proof (`bytellm`: the GPQA/HLE/BFCL and Claude/Codex lanes; `ollama-cloud`: the CF1.3 BFCL configured-registration diagnostics and the Terminus-2 lanes). A route is proven per registered combination, never per provider; unsupported protocols fail typed at planning. |
| CLI | `list`, `catalog …`, `run <benchmark>/<slice> [--runtime\|--agent] --model … [--provider] [--dry-run\|-y]` |

Runtime XOR admitted agent. Omit both for model-only (GPQA, HLE, BFCL). Unknown ids and scaffold-only agents must fail before subprocess or output reservation.

There are **10 catalog rows / 4 executable benchmarks / 38 model metadata entries / 2 admitted runtimes / 1 admitted native agent (one combination) / 0 admitted external CLI agents**. This is not a supported Cartesian product. The generic external CLI agent path still lacks an official verifier. Config-only onboarding is proven for one supported-protocol model/provider route and one native Harbor agent (CF1.3, CF2.3); the registries validate shape and the planner/doctor gate combinations, but a registry row is not a support claim (CF3.2 vocabulary: registered → compatible → preflight-ready → live-proven). Completion counts in the historical R/U/X work must not stand in for the user's three capability goals: easy supported-lane preparation/run, config-first onboarding, and scientifically bounded transformation evidence.

**Tiers** (definitions: [`production-readiness.md`](context/production-readiness.md)): **Tier-0 executable** = software gate — the control plane compiles, plans, and gates with no live deps. **Tier-1 live-proven** = ≥1 real instance end-to-end via the benchmark's native harness. **Tier-2 Production v1** = adapter admitted + Tier-1 live proof + full checklist. All four benchmarks above are Tier-0 executable and hold Tier-1 in the proof ledger below. No Tier-2 claim.

### Proof ledger

| Benchmark | Software | Live evidence | Tier-2 | Next evidence |
|---|---|---|---|---|
| `terminal-bench` | Tier-0 executable | Tier-1: `run-20260825-173913-754489-4f43e296` (`claude-code` 2.1.235, proof `sha256:afe6f655…7b9592`) and `run-20260825-171829-685914-aa08dd1d` (`codex-cli` 0.148.0, proof `sha256:fca2295d…d90c06`); both official `reward == 0.0` / `model_wrong_solution`. Cleanup replay: `run-20260826-104126-417176-facd93a7` (proof `sha256:cd681305…e29c7`, `cleanup_result=success`, `runtime_launch_failure`) | not claimed | no superiority claim |
| `gpqa-diamond` | Tier-0 executable | Tier-1: `run-20260825-160511-036214-304c2cee` (proof `sha256:aa19d02b…ff0eda`) plus post-retention refresh `run-20260826-082238-670967-54af8e96` (proof `sha256:90978d9e…1c032`) and cleanup replay `run-20260826-103433-678152-7ace1b73` (proof `sha256:a8f17d90…da2f8`, `cleanup_result=success`) | not claimed | no Tier-2 claim |
| `hle` | Tier-0 executable | Tier-1: `run-20260824-092017-110245-dbbdf99e`; isolated-cache `hle-isolated-cache-live-20260825T072129Z`. Post-fix identity-bound smoke `run-20260826-135512-189732-203685b9` (proof `sha256:4be3b7cd…f4b62b`, official 0/2, `cleanup_result=success`). Historical `sha256:b3260e8b…601b77` predates ambient-cache removal | not claimed | no Tier-2 claim |
| `bfcl-v4` | Tier-0 executable | Tier-1: `run-20260824-045622-854659-a46ae44d`; refresh `run-20260826-083403-019994-e449daac` (proof `sha256:8323f916…0c38bc`, official 1/5, run-plan present) | not claimed | cleanup replay `not-applicable` (`results/`/`scores/` are official evidence, not named transients) |

`results/` and its run registry are machine-local and gitignored. Run IDs above identify operator-host proof; they are not durable publication until the portable-bundle work below is complete.

### Current product priority

**First recover config-first execution, then extend the research.** X0–X3 have completed their first-model BFCL scope: the Live contrast, tool-order materializer, official runs, and bound report/lock reproduction exist. These results do not establish generalized model/agent onboarding, reduced training contamination, or a decontaminated capability score. CF below closes the configuration-to-native execution gaps without per-model Python patches. X4 final exposure integration/review and X5 research decisions remain required. U3/U4 general console hardening remains lower priority and is not a prerequisite for model-only CLI studies. BFCL Live and tool-order are distinct diagnostic catalog identities and inherit no canonical admission.

The accepted correction is architecture §23 / concept G-13–G-15. It permits only a typed, content-bound model-registration delta in a run-owned BFCL copy; installed packages and official handler/runtime/generator/scorer logic stay unchanged. No code, profile admission, or future live proof is completed by writing this plan.

## Config-first capability recovery (CF — current priority)

**Objective:** make another supported-protocol model/provider and another supported native runtime/agent profile configuration work for the user; prove the full CLI/native-scoring path instead of only registry loading or a direct handler call.

**Program exit:** config-only onboarding, one genuinely scored native-agent profile, and clean supported-host preparation have real evidence. No arbitrary protocol/agent compatibility, global Tier-2, or pollution-removal claim is implied. Keep all prior study/report/proof bytes and the existing catalog admission boundaries.

### CF1 — Model/provider binding and the first complete config-only path

- [x] `CF1.1` Specify and implement typed model/provider/native bindings *(done 2026-09-08: `model_registry.py` gains optional `api_model`, `backend_bindings.bfcl` (`upstream` | `configured` with explicit `handler`/`underscore_to_dot`) and descriptive `reference_url`/`organization`/`license`; `model_binding.py` resolves logical id, exact API name, provider protocol, public endpoint, and BFCL registry id into a digest-bound non-secret `ModelBinding`; `RunPlan.model_binding_snapshot`/`judge_binding_snapshot` are frozen before confirmation; the HLE judge launches on its own route; GPQA derives `openai/<api_model>` from the protocol; doctor reports configured registrations; `ollama-cloud` is a direct `openai_compatible` profile (`https://ollama.com/v1`, `OLLAMA_API_KEY`, optional `OLLAMA_CLOUD_BASE_URL`). Contracts: `tests/specs/test_config_model_binding_contracts.py`.)*
  - Files: `model_registry.py`, `provider_registry.py`, proposed `model_binding.py`, `domain.py`, `benchmark_plan.py`, `doctor.py`, `gpqa_adapter.py`, `hle_adapter.py`, shared application projections, existing provider/model configs; new `tests/specs/test_config_model_binding_contracts.py`.
  - Scope: begin with independent RED behavior contracts for architecture §23.3. Separate logical ID, API name, protocol, and backend registry/handler selection; snapshot non-secret bindings before confirmation. Remove ByteLLM-name-based Inspect routing. Make candidate/judge resolution explicit for HLE. Correct the direct Ollama Cloud profile without changing the local daemon. Preserve legacy config reading and effective shipped behavior; add no proxy, arbitrary request callbacks, or new native protocol.
  - Dependencies: accepted §23 design; no new HITL or package upgrade is required.
  - Acceptance evidence: real config loaders/planner/doctor use arbitrary supported route IDs rather than provider-name branches; wrong protocol/handler/API-name binding fails before launch; changed binding invalidates confirmation; core import remains optional-dependency-free. Tests exercise configuration/behavior, never document wording or checklist counts.

- [x] `CF1.2` Generate and retain BFCL registration from configuration *(done 2026-09-08: `bfcl_package.py` stages a real copy of the installed package, appends exactly one fixed-rendered `ModelConfig` entry after the pinned `constants/model_config.py` bytes (reviewed pin `registry_sha256` in `config/bfcl-v4-supported-models.yaml`), refuses existing upstream keys and unsafe values, re-verifies before generate and around evaluate, and retains `execution/bfcl-registration.json`; the tool-order variant composes on the same copy (`registered_files` in the variant manifest); rows carry `bfcl-eval@2026.3.23+registration-<sha256>` with `base_harness_version`, `model_binding_sha256`, `bfcl_registry_id`, `api_model`; proofs read the manifest inventory-bound and paired reports require one registration shared by both arms. Contracts: `tests/specs/test_bfcl_config_registration_contracts.py` (real-package staging case runs where bfcl-eval is installed).)*
  - Files: proposed `bfcl_package.py`, `bfcl_study.py`, `bfcl_native_adapter.py`, `control_plane_executor.py`, `proof_bundle.py`, `exposure_report.py`, base BFCL pin manifest, and `tests/specs/test_bfcl_config_registration_contracts.py`.
  - Scope: one shared owned package-copy/verifier path; exactly one fixed-rendered appended registration in `constants/model_config.py`; use the unchanged pinned `OpenAICompletionsHandler`. Keep native registry ID distinct from API name and reject existing-key replacement. Apply identical registration to canonical/variant/repeat, with only the candidate's declared data delta added. Retain the separate execution registration manifest/digest and effective harness identity on every row. New configured registrations come from model config, not another duplicate model allowlist.
  - Dependencies: CF1.1.
  - Acceptance evidence: uncharged actual package imports/registry lookups work for generation and evaluation; exact changed-file/prefix checks reject extra executable changes; installed bytes remain untouched; changed/absent/asymmetric registration fails at launch/report/proof boundaries. All old raw/declared/paired locks reproduce without regeneration. A direct class invocation cannot close this task's live integration boundary; CF1.3 supplies it.

- [x] `CF1.3` Prove config-only onboarding through the real CLI and official score *(done 2026-09-08 on dev-box-cpu, direct Ollama Cloud, key delivered to the process environment only. `ollama-qwen3.5-397b-fc` (`qwen3.5:397b`): canonical plumbing `run-20260908-070838-004519-ccfbce2e` 2/2 and derived plumbing `run-20260908-070915-107154-84ea6c6f` 2/2 through ordinary `bencheval run` → real `bfcl generate` → `bfcl evaluate` from the staged copy (registration `sha256:05b2da63…`, shared by both arms; `passed` registration refused; proofs `51c0c8d2…`/`75266257…`); raw-only paired report `sha256:e3cbb2cb…` (lock `e8b77668…`) reproduces byte-identically from copied proofs on the dev-box and the Mac, and all six historical locks still verify. Second config-only model `ollama-gpt-oss-120b-fc` (`gpt-oss:120b`, `config/models.yaml` only, no Python change): `run-20260908-072448-877197-21f44c90`, two official verdicts, both `model_wrong_solution` (prose instead of a call; wrong call count), proof `b030fd26…`. All three runs are diagnostic; no admission, no 600-case study.)*
  - Files: reviewed model/provider config entries and real run/evidence/proofs/reports; regression tests and factual ops documentation only as necessary. No new Python branch for the second configured model.
  - Scope: use direct Ollama Cloud with explicitly labelled `qwen3.5:397b` as the first API model. Run the existing two-case canonical and derived plumbing slices in explicit diagnostic mode through ordinary `bencheval run` → real `bfcl generate` → real `bfcl evaluate`. Add a second genuinely available, correctly identified Cloud model by config only and obtain at least one official-score case; choose from verified provider metadata, not a namespaced model's self-description. Do not use a MiniCPM/GPT alias to reach Qwen or the Gemini-labelled wrapper whose registry points to Gemma.
  - Dependencies: CF1.2 and green focused/full software gates on the content-identified execution snapshot.
  - Acceptance evidence: real official score artifacts (pass or legitimate wrong solution), correct logical/API/registry identities, no modified scorer/handler, diagnostic `passed` registration refused, complete exported/copied proofs, and raw-only report/lock reproduction without original source config or overlay. Re-prove the second config entry requires no code edit. Run independent `qa-review`; report the full gate and live proof separately.
  - Cost/HITL: registry/import probes are uncharged; real generation is small but charged. Use the existing bounded provider budget and secret env delivery. Pause only for literal auth/admin interaction, not for an ordinary package/config repair. Do not start the 600-case study in this packet.

**CF1 exit:** a supported OpenAI-compatible route is genuinely config-extensible for the demonstrated native paths. BFCL configured registration is labelled as an extension, not plain upstream support. Native Gemini/Anthropic protocols and arbitrary model/benchmark combinations remain outside this proof.

### CF2 — Config-selected runtime and genuinely scored agent profiles

- [x] `CF2.1` Replace runtime-ID branching with explicit native driver bindings *(done 2026-09-08: `config/runtimes/*.yaml` declare a closed `launch.harbor` binding (`agent`, code-owned `install_recipe` `claude_code_npm` | `codex_npm` that implies its agent, `setup_timeout_multiplier`); `terminal_bench_harbor.py` launches from that binding only, so the profile id selects nothing and a YAML-only profile naming an installed built-in agent launches by name; `verify_harbor_runtime_binding`/doctor `harbor_actor_binding` check selectors against the installed Harbor registry; the shipped Claude/Codex argv is locked byte-for-byte and re-run live on the dev-box (see CF2.3). Contracts: `tests/specs/test_native_profile_binding_contracts.py`.)*
  - Files: `runtime_registry.py`, `domain.py`, `benchmark_plan.py`, `doctor.py`, `terminal_bench_harbor.py`, existing runtime YAML, and `tests/specs/test_native_profile_binding_contracts.py`.
  - Scope: RED contracts first; implement the §23.6 closed Harbor launch binding. Migrate the two shipped runtime profiles without changing their effective agent/runtime pins, install recipes, auth separation, or argv semantics. Validate supported native selectors/options against the installed official interface; a new profile ID on that driver must not require another mapping in Python.
  - Dependencies: CF1.1 binding/schema baseline; native API details must be re-probed without a provider call before implementation.
  - Acceptance evidence: old runtime behavior is preserved; a further config-defined native selector passes real factory/preflight resolution; unsupported selectors/options fail before charge; public profile names do not select behavior. Actual runtime regression/live proof is completed in CF2.3.

- [x] `CF2.2` Route native agent profiles through the benchmark-owned verifier *(done 2026-09-08: `agent_registry.py` is a discriminated union (`external_cli` scaffold | `harbor` native with `harbor_agent` XOR `harbor_import_path`, typed non-secret `kwargs`, `version_pin`, `source`); `actor_binding.py` resolves runtime and agent profiles into a digest-bound `RunPlan.actor_binding_snapshot`, retained as `execution/actor-binding.json` and stamped as `adapter_metadata.actor_binding_sha256`; a draft native agent plans `diagnostic_only` and launches only with explicit diagnostic on planner, executor, CLI, and console (`resolve_launchable_agent`); a profile edited after planning is refused before any output reservation; the Terminal-Bench adapter launches `--agent <harbor_agent> --model <namespace>/<api_model> --agent-kwarg api_base=<confirmed endpoint>` with the provider key only in the mode-0600 `--env-file`; only the official `verifier_result` reward scores, a mismatched `agent_info` forfeits the pass, reward 0.0 is `model_wrong_solution`; model-only adapters refuse agents. Contracts: `tests/specs/test_native_agent_scoring_contracts.py`.)*
  - Files: `agent_registry.py`, `domain.py`, `benchmark_plan.py`, `control_plane_executor.py`, `terminal_bench_harbor.py`, application projections, agent config, and `tests/specs/test_native_agent_scoring_contracts.py`.
  - Scope: implement the §23.6 `kind: harbor` agent binding using the real Harbor name/import interface; no new generic agent protocol. First candidate is Terminus-2. Dispatch it through the Terminal-Bench adapter and official verifier, not the legacy host command fallback. Preserve agent identity with null runtime and retained actor binding/version. Permit explicit diagnostic execution only for known wired draft profiles; scaffold (including MOMO) still rejects before output reservation. Keep arbitrary legacy `external_cli` scoring unavailable.
  - Dependencies: CF2.1 and its uncharged native-interface evidence.
  - Acceptance evidence: CLI/direct executor/UI share draft/scaffold/unsupported gates; actor binding is confirmed and retained as `execution/actor-binding.json`; changed bindings invalidate confirmation. Missing/forged agent-authored results cannot pass; only the official result decides. Model-only paths reject agents. CF2.3 must establish real scoring before any admission or completion claim.

- [x] `CF2.3` Close the native-profile matrix with real attempts *(done 2026-09-08 on dev-box-cpu, Harbor 0.17.1 + Docker: `--agent terminus-2 --model ollama-qwen3.5-397b-fc --diagnostic` on `terminal-bench/tier1-one` (`fix-git`) → `run-20260908-150221-437459-86b913ba`, official `verifier_result.rewards.reward = 1.0`, `agent_info` `terminus-2`/`2.0.0`, launched `--agent terminus-2 --model openai/qwen3.5:397b --agent-kwarg api_base=https://ollama.com/v1 --agent-kwarg parser_name=json`, Ollama key only in the unlinked mode-0600 env file, `execution/actor-binding.json` `sha256:ff5c68e8…`, row `interpretation_label=diagnostic`; `passed` registration refused (`diagnostic-interpretation`), `completed` registered, proof `sha256:e25e2f20…` (complete) verified from a `/tmp` copy and imported. A first attempt (`…-4f0347cf`) died in Harbor environment setup because the host had exhausted Docker's address pools (`runtime_launch_failure`, identity still retained); three orphaned `fix-git__*__env_default` networks were removed. Shipped runtimes re-qualified through the unchanged pilot matrix (`docs/ops/dev-box-pilot.md` §3, role shim on, `kimi-k2.7-code`; the matrix's `qualify-lane` step counts `passed=2` and appends no canonical manifest rows, so these reruns are qualified, not re-registered): `claude-code` `run-20260908-153924-906681-a2779557` and `codex-cli` `run-20260908-154051-364397-06c4a9b8`, both official reward 0.0 = `model_wrong_solution` exactly as on 2026-08-25, `agent_info` versions 2.1.235 / 0.148.0 matching the pins, `Pilot summary: passed=2 … tb_compare=1`, argv byte-identical to the pre-migration golden. Two earlier matrix passes failed at the model call (`401` from the router: the checkout's `.env` loopback URL and a shim-less environment), which is host configuration, not adapter behavior. Independent review accepted this evidence on 2026-09-09 and `config/agents/terminus-2.yaml` is now `admitted` for exactly the demonstrated combination (Terminus-2 2.0.0 with `parser_name=json`, Harbor 0.17.1, Terminal-Bench 2.1 `fix-git`, `ollama-qwen3.5-397b-fc` on direct Ollama Cloud); admission changes neither the actor binding (`sha256:ff5c68e8…`, locked in `test_admission_preserves_the_cf23_binding_and_permits_an_ordinary_plan`) nor the argv, the retained run stays diagnostic/`completed`, and the first ordinary `passed` registration on the admitted profile is CF3.1's minimal live run. Import-path agents remain refused at launch; MOMO stays scaffold.)*
  - Files: only scoped config admission, real proof/ledger artifacts, and factual docs after verification; code changes require the normal fix/review loop.
  - Scope: re-prove affected Claude/Codex native launch behavior and one real `--agent terminus-2` Terminal-Bench attempt on the operator host. Inspect its actual model/provider/native-agent identity and official reward. If an operator-installed custom `BaseAgent` is claimed supported, exercise that actual import path separately; a factory import or a built-in agent cannot prove an arbitrary external implementation.
  - Dependencies: CF2.1–CF2.2 and green software gates.
  - Acceptance evidence: official verifier feedback, complete retained actor/model binding and proof, correct runtime-XOR-agent axes, failure/cleanup behavior, and independent review. Admit only the demonstrated profile/combination after its evidence gate; do not admit MOMO, SWE, or every Harbor agent by association.
  - If blocked: record the exact native interface/dependency/auth problem. Do not replace the agent with a fake runner or keep the legacy zero-score path while claiming agent support complete.

**CF2 exit:** config-selected native runtime/agent profiles work on the demonstrated Harbor family with real official scoring. Other agent protocols still require one explicit adapter, not silent compatibility or false admission.

### CF3 — Supported-host preparation and capability-based closeout

- [x] `CF3.1` Make preparation/preflight reproducible for supported lanes *(done 2026-09-09. Software: `doctor.run_plan_doctor(plan)` is the one preflight behind `bencheval doctor <benchmark>[/<slice>] --model … [--runtime|--agent] [--provider] [--diagnostic]` (legacy `--backend/--profile` form unchanged), `OperatorOperations.preflight` (the console plan page), and the real-runner gate of all four executable families before any output is reserved; it dispatches on the frozen plan's harness, reports the resolved selection with binding digests, the harness's `PreparationRecipe` (`uv sync --extra eval` / `uv sync --group bfcl`, execution context = a checkout at its `uv.lock`; wheel/bundle installs preflight but cannot prepare and the report says so), and the host roots; new checks `judge_provider_credentials` (HLE), `inspect_evals_import`, `inspect_openai_client` (Inspect's own floor on the installed client), `harbor_launch_identity`; `config/agents` is required in every bundle. Contracts: `tests/specs/test_supported_host_preflight_contracts.py` (21, incl. the four-family ordering case, the unrouted-model cases below, and the installed-wheel/`BENCHEVAL_HOME` cases against a real built wheel). Clean-host rehearsal on dev-box-cpu, fresh checkout `~/BenchEval-clean` + fresh CPython 3.12 venv + fresh results root: it found two real gaps — `uv sync` picked CPython 3.14 (no `faiss-cpu` wheel) until `.python-version` pinned 3.12, and the refreshed lock's `inspect-ai` 0.3.262 refuses `openai` 2.54 at launch (every release after 0.3.252 requires openai>=3.1.0, which the litellm range under `inspect-harbor<0.7.4` cannot satisfy), so `inspect-ai` is pinned to 0.3.252 (`inspect-swe` follows to 0.2.68) and the doctor now reports that floor before reservation. On the corrected tree all four doctors are green and one minimal run per family registered `passed` with complete proofs verified from `/tmp` copies: `terminal-bench/tier1-one --agent terminus-2` `run-20260909-054158-477883-0748b911` (official reward 1.0, the admitted profile's first ordinary registration, proof `sha256:af0eba76…`), `gpqa-diamond/smoke` `run-20260909-054344-074803-4eb3204f` (accuracy 1.0, `sha256:aab0d3a9…`), `bfcl-v4/tool-order-canonical-plumbing-2` `run-20260909-054622-852393-b3c7eefe` (2/2, `sha256:33d9742f…`), `hle/smoke` `run-20260909-073706-188201-02ec6d7d` with `gpt-5.2-2025-12-11` (official 0/2 `model_wrong_solution`, the documented small-slice calibration exit; a `kimi-k2.7-code` attempt `…-0eba1ca5` exceeded the pinned script's 600 s client timeout twice and is retained unregistered). Host facts recorded, not product changes: Hugging Face is reachable from the host only through its relay proxy (exported for the HLE lane), and uv 0.11's cold cache generation downloads the locked graph at ~130 KB/s there while the system uv 0.9.5 reuses the warm cache. The historical diagnostic Terminus-2 proof is unchanged. CF3.2 review round 1 (2026-09-09) rejected on one bounded defect, F001: the plan doctor checked the model's declared `provider_route` rather than the route the plan selected, so a valid registry entry without `provider_route` on `--provider`/the default passed doctor without the credential and `run` reserved its evidence file, artifacts tree, and `run-plan.json` before failing at launch. Fixed the same day: `run_plan_doctor` checks the candidate's confirmed route (model binding snapshot, else `provider_id`) and the HLE judge's resolved route (judge binding snapshot) through the launch resolver itself; the optional-route/default-provider behavior is unchanged and the legacy `--backend`/`--profile` doctors keep the model-route form. Regression: `test_unrouted_model_preflight_follows_the_selected_provider`, `test_cli_refuses_unrouted_model_run_before_reservation` (the reviewed probe), and `test_executor_refuses_unrouted_model_without_the_selected_credential` over all four families, each against a `BENCHEVAL_HOME` bundle whose only delta is the removed route.)*
  - Files: `doctor.py`, `cli.py`, shared application operations, README and `docs/ops/benchmarks/`, existing preparation scripts only where a reusable command is actually needed, and focused doctor/config-package tests; `control_plane_executor.py` only to put the plan doctor ahead of reservation on the four real execution paths, `paths.py` for the bundle rule, `.python-version` and the `inspect-ai` pin in `pyproject.toml`/`uv.lock` as the rehearsal's findings.
  - Scope: doctor uses the same resolved benchmark/slice/model/actor selections as planning. Document one short locked recipe per supported benchmark and its real external prerequisites. Rehearse core/wheel/config-bundle install separately from live checkout-owned BFCL/SWE groups; do not claim a core wheel provisions every harness. Use clean supported-host venv/data roots rather than a preloaded developer environment. Add no environment manager, Docker plane, daemon, or broad installer framework.
  - Dependencies: CF1.3, CF2.3 for their respective advertised combinations; existing four-adapter recipes remain in scope.
  - Acceptance evidence: fresh preparation and preflight for all four executable families, plus the minimal actual run required for each changed live path; exact missing dependency/route errors precede charge. Configuration reaches the installed package/config-bundle surface, not just the source checkout. No undocumented manual source edits or reused peer venv are necessary.

- [x] `CF3.2` Review the three capability claims and publish an honest support matrix *(done 2026-09-09. Independent review in two rounds: round 1 rejected on F001 (the unrouted-model credential preflight gap recorded under CF3.1, fixed the same day) and noted N001 (stale current-state prose, reconciled above); round 2 accepted with zero open findings and scoped readiness PASS. Accepted claim: configuration-driven planning and preflight for the demonstrated CF1–CF3.1 lanes on the documented Linux/CPython 3.12 setup, including rejection of a missing selected-provider credential before output reservation — not whole-project, arbitrary-combination, or research-method readiness. Reviewer evidence: dev-box exact-tree `make check-production-v1` passed (1,389 passed, 1 deselected under coverage, the separately run timing test passed, 83% coverage, Ruff/format/ShellCheck/shell-syntax/lock/catalog gates green); the four retained CF3.1 proofs reverified against their proof ids; all 12 historical study locks reproduced from retained proofs with working directory `/tmp`, nothing regenerated; working-tree secret scan and `git diff --check` clean; no new paid runs. Support matrix: the current-state table above is the matrix, read with the architecture §23.7 vocabulary — the four registered `passed` combinations of CF3.1 are live-proven, and anything else a registry row permits is at most compatible or preflight-ready until it earns its own run. Remaining unsupported: provider kinds other than `openai_compatible` (typed refusal at planning), Harbor import-path agents (refused at launch), external CLI agents (`momo` scaffold, no official verifier), SWE-bench Verified (`swebench-native`: default runner disabled, catalog and evaluator group only), and any Terminus-2 combination other than the admitted one. Operational distinction the reviewer recorded: a supported preparation path does not mean every shell is configured — in a partial environment GPQA/BFCL preflight passed while Terminus-2/HLE reported missing prerequisites, which is the doctor working, not new live evidence. U3/U4, global Tier-2, and contamination-removal claims stay open; commit/push remain a separate publication request.)*
  - Files: architecture/roadmap/README/current contracts and scoped review/readiness artifacts; no product edits during review.
  - Scope: independently review config onboarding, native runtime/agent scoring, and clean-host preparation. Distinguish registered, compatible, preflight-ready, and live-proven combinations using actual operation results; a YAML admission flag is not all four. Close only the demonstrated scope. Coordinate with X4.2/X4.3 to reuse unchanged integrity/compatibility evidence instead of duplicating a hardening program.
  - Dependencies: CF1.3, CF2.3, CF3.1.
  - Acceptance evidence: exact-tree `make check-production-v1`, relevant real native/clean-host proofs, historical lock compatibility, zero open blocking findings, and scoped `verify-readiness`. Record remaining unsupported protocols/agents. U3/U4 and global Tier-2 are not silently closed; commit/push still follow a separate publication request.

### CF4 — Resume research using the recovered capability

- [x] `CF4.1` Run the second-model fixed-cohort study after route qualification *(done 2026-09-09 on dev-box-cpu from a clean checkout of PR #13 head `ab9fdef` (tree `a072feb4…`, producer content `sha256:5d7972ea…`, CPython 3.12.12, `uv sync --group bfcl`, bfcl-eval 2026.3.23), predeclared in the machine-local `results/cf41/execution-record.json` before the first paid call. Binding constant across all three arms: `ollama-qwen3.5-397b-fc` (`qwen3.5:397b`) on direct Ollama Cloud, model binding `sha256:c3eff4a4…`, provider config `sha256:3d4a1ee8…`, registration `sha256:05b2da63…` (identical to CF1.3), harness `bfcl-eval@2026.3.23+registration-05b2da63…`. Arms, each 200/200 official verdicts, all `diagnostic`, registered `completed`: A primary canonical `run-20260909-095350-269014-a37f9311` 178/200 (proof `sha256:e77f20e0…`), B fixed tool-order variant `run-20260909-112850-658620-d221f624` 178/200 (proof `sha256:f1f5cc1e…`; derived data `sha256:c2bb8007…`, variant `sha256:65f040df…`), C independent canonical repeat, the predeclared control, `run-20260909-124738-559243-11afa080` 179/200 (proof `sha256:21c8c8ec…`); every proof complete, verified from a `/tmp` copy, imported into the canonical store. Primary declared report `sha256:601ae052…` (lock `sha256:d0bb583a…`, reproduced byte-identically by `study verify` from copied proofs with cwd `/tmp`): canonical 0.890 [0.839, 0.926] (multiple 90/100, parallel_multiple 88/100), variant 0.890 [0.839, 0.926] (92/100, 86/100); pairs 166 both-pass, 10 both-fail, 12 canonical-only, 12 variant-only; paired delta +0.000; exact binomial on 24 discordant pairs p = 1.0. Control: A-versus-C 23 discordant (11/12, delta +0.005), so the variant's discordance equals an unchanged rerun's in this serving configuration, unlike the X3.5 GPT-5.2 lane (18 versus 6). Serving-path timeouts: `bfcl generate` caught `openai.APITimeoutError` on 10/8/7 cases (A/B/C) and recorded `Error during inference: Request timed out.` in place of the answer; the official evaluator scores that string as a failure, and the adapter of the frozen tree labelled those rows `model_wrong_solution`, so they entered the declared population as eligible. **Review correction (round 1, 2026-09-10):** the native scores above are reproducible descriptive serving-path outcomes, but the report does **not** satisfy its declared `native_eligible_only` population contract — 15 of the 24 A-versus-B discordances and 16 of the 23 A-versus-C discordances involve a known timeout. The runs, proofs, report, and lock stay unchanged; nothing was removed, retried, or relaxed. The tree now classifies such a generation record as `remote_infra_failure` while retaining the official zero score and the generation record itself in the proof (contracts in `tests/specs/test_bfcl_official_score_contracts.py`), so a future population with a timeout is rejected by the report as designed. Defensible summary: on this fixed cohort and serving configuration, official pass rates were equal with no detected directional pass-rate change (exact binomial, p = 1.0); variant discordance was 24 cases versus 23 for an unchanged repeat, and inference timeouts materially contributed to both, so these observations do not establish absence of tool-order sensitivity; the timeout-excluded comparison (9 and 7 discordant pairs) is post-hoc descriptive material only. Cost: token-based estimate before launch $1.02 for three arms at standard list price; reported usage from the official result files 390,902 input + 175,921 output tokens = $0.87 at the listed Qwen prices, a reported-usage figure and not a complete metered bill (the 25 timeout records carry no usage fields, provider metering is absent from evidence, and the account ledger is the metered truth); inside the $50 allocation. No retries, no pooling, no baseline change. Next: X5.1 after the review of this record.)*
  - Predeclared execution record (drafted 2026-09-09 after the CF3.2 closeout review; not started): primary analysis is the proof-backed `bencheval study report --analysis declared` on the retained `bfcl-v4-tool-order-v1` selection and variant bindings (Wilson 95% intervals, the predeclared exact-binomial paired test; `raw_only` is the contract's smoke mode and the report labels it `plumbing_only`, so it may be produced for inspection but is never the completed study's result); the 200-case canonical-repeat arm is a separately predeclared control, never pooled with the primary canonical arm or picked afterwards as a more favorable baseline; one identical registration/handler/provider/settings binding across all three arms (`ollama-qwen3.5-397b-fc` on `ollama-cloud`, registration `sha256:05b2da63…`, captured `provider_config_hash`); the snapshot is identified by a commit or tree hash and the retained producer digest — a push is a review convenience, not what fixes identity, and a later-modified checkout is not frozen because it was pushed; $50 allocation inside the $1,000 ceiling with estimated versus measured cost recorded; interpretation is benchmark-specific dependence within the serving configuration only.
  - Files: predeclared model/provider/study execution record and immutable local runs/proofs/reports; no scorer change or outcome-driven source edits.
  - Scope: use the same 200-case cohort and fixed variant as X3, with 200 canonical + 200 variant + 200 independent canonical-repeat cases. Capture one identical registration/handler/provider/settings binding across all three arms; do not pool, retry selectively, or choose a favorable baseline after results. Run from a frozen content-identified snapshot, not a checkout peers are editing.
  - Dependencies: CF1.3 and scoped review of the changed model/registration/report path (X4.2/X4.3 as applicable). CF2 agent work, CF3's other benchmark recipes, and general U3 hardening are not dependencies of this model-only study.
  - Acceptance evidence: official scores, complete bound proofs, copied-proof/lock reproduction, native paired outcomes and variance control, uncertainty and competing explanations. Compare within each serving configuration; do not infer a bare-model ranking or contamination cause from different provider/handler paths.
  - Budget/next decision: retain the initial $50 allocation inside the $1,000 campaign ceiling; report tokens/estimated versus measured cost honestly. Then perform X5.1. A further rotation-seed study must explicitly handle the current coupling of cohort and transform seed; a second benchmark family still requires X5.2. No automatic spending to the ceiling or generic transform framework.

### Peer execution order and ownership

1. **Peer #2 starts with `dev-spec` for CF1.1–CF1.3**, then the implementation/self-critique/independent-review/fix loop. The first handoff must include the actual new-model CLI/scorer/proof path, not only a direct handler probe. Leave all new CF checkboxes open until their own evidence exists.
2. Keep one writer on `domain.py`, registries, planner, executor, CLI, and proof/report files. CF2 may begin after the CF1 binding baseline settles; do not launch concurrent writers on the shared schemas. Reuse Synapse file leases.
3. CF4 can run on a frozen operator-host snapshot after CF1 qualification while independent local CF2 work continues; never edit its producer snapshot or run roots. CF3 closes the supported installation matrix, not the whole product's research agenda.
4. Preserve the existing dirty batch and all historical reports/locks. No dependency upgrade, benchmark admission, MOMO promotion, public endpoint, or publication is implicit. Test executable behavior and real integrations; add no documentation tests.

## Executable roadmap

### R0 — Decisions and source-of-truth reconciliation

- [x] Reconcile the original catalog/executable state and BFCL/HLE Tier-1 status; later Live/tool-order diagnostics bring the current count to **10 / 4** without new admission.
- [x] Close the v1 cost contract: wall-bounded and cost-estimated; no provider-enforced hard-dollar termination promise.
- [x] Keep MOMO as a discoverable scaffold rather than an admitted agent.
- [x] Select permanent local private-proof retention with no BenchEval deletion/expiry operation; defer bucket/object-store transport.
- [x] Select SWE-bench Verified diagnostic proof first and a separate later promotion decision.
- [x] Keep CyberGym and ExploitGym catalog-only for v1.
- [x] Define the HITL boundary: ordinary probes and provisioning are automated; pause only for a literal device/subscription/CAPTCHA/hardware/admin interaction or a new product decision.

**Exit:** the current architecture contains no unresolved product choice needed for the implementation tracks below.

### R1 — Deterministic correctness debt

- [x] **MOMO scaffold gate:** change the typed admission state to `scaffold`; make planner, CLI, and crafted direct-executor paths reject before output reservation, subprocess, or provider launch. Catalog list/show remains usable.
- [x] **Legacy compare validity:** compute headline/backend rates over the shared eligible intersection, retain excluded rows in details, reject asymmetric/empty eligibility, emit `comparison_valid` plus `contaminated_or_legacy`, and return nonzero when invalid.
- [x] Keep append-time live-run validation: fill-once axes, nondecreasing time, legal transitions, and raw event preservation.
- [x] **Reader and projection:** validate the entire on-disk history on read; expose a last-valid-event projection that carries latest non-null locators without modifying raw events.
- [x] **Registry concurrency:** lock read→validate→append→fsync with an adjacent mode-0600 `fcntl.flock` file.
- [x] Reconcile current docs and narrowly stale proof/substitute records after the behavior changes; behavioral config checks remain, but documentation wording/count tests are not part of the product gate.

**RED specifications:** `test_agent_scaffold_contracts.py`, `test_legacy_compare_eligibility_contracts.py`, and `test_live_run_operational_view_contracts.py` define the required behavior before implementation.

**Exit:** non-admitted axes cannot launch; comparison headlines cannot be improved by infrastructure rows; copied/corrupt registry history cannot masquerade as valid current state.

### R2 — Immutable portable private proof

- [x] Keep append-time validation of fill-once axes, nondecreasing timestamps, legal transitions, and raw-history preservation as the base event contract.
- [x] Supply the validated last-valid-event operational view consumed by proof export; implementation ownership remains R1.
- [x] Persist an anchored exclusive `run-plan.json` after run-root claim and before every first benchmark launch. Failed launches retain the plan.
- [x] Add `private_proof_v1` in a dedicated `proof_bundle.py`: canonical inventory bytes, small closed artifact roles, size/SHA-256, strict normalized paths, exactly one run ID, and complete file-set equality.
- [x] Export evidence, official results, logs, run plan, normalized history, derived projection, report, and every referenced raw/capture artifact; reject outside-root, missing, skipped, duplicate, nested, symlink, hardlink, device, FIFO, extra, or digest-mismatched content.
- [x] Add `bencheval proof export|verify|import` and `evidence list --current`. Public bundles remain redacted publication derivatives and cannot import as private proof.
- [x] Derive `proof_id` from exact inventory bytes; install atomically under `results/proofs/sha256/<digest>` and append one idempotent non-secret row to `proofs.jsonl`.
- [x] Prove export, source-checkout removal, offline verification/import into a disposable second root, archive traversal rejection, idempotent import, and preservation of a conflicting existing proof.
- [x] Retain finalized proofs permanently. Add no delete, prune, replacement, TTL, or garbage-collection path.
- [x] Classify historical BFCL/HLE material without a captured run plan as `legacy_unverifiable` / `run_plan_missing_legacy`; never reconstruct historical execution state from current config.

**RED specification:** `test_private_proof_bundle_contracts.py` covers portable private-export path completeness. `test_private_proof_v1_contracts.py` covers export, source-checkout-removed verify, import/idempotency/conflict, archive traversal, public-bundle rejection, legacy missing-plan classification, extra/missing/digest/symlink/dir-escape/unknown-classification rejects, and no `runs.jsonl` replay on import.

**Exit:** a known proof digest verifies without the originating checkout; local retention does not depend on a host-absolute path. This proves byte completeness, not creator authenticity or benchmark truth.

### R3 — Tier-1 proof for the current executable set

- [x] Add `terminal-bench/tier1-one` containing only `fix-git`, with typed one-instance budgets and no benchmark-native/statistical claim.
- [x] Parameterize `run-live-pilot-matrix.sh` for `tier1-one` (expected 1) or `smoke-5` (expected 5); reject slice/count mismatch and use the chosen slice consistently.
- [x] On the dev-box, run `tier1-one` through Harbor for `claude-code` (`run-20260825-173913-754489-4f43e296`, agent 2.1.235, private proof `sha256:afe6f655f7c3f4f940c83703a7c2f5231ae9a87fd998803fdf92ed04967b9592`) and `codex-cli` (`run-20260825-171829-685914-aa08dd1d`, agent 0.148.0, private proof `sha256:fca2295d6844e4dda99799527561985885a90b59e01c865082510eaa63d90c06`). Both are official-verifier `model_wrong_solution` (`reward == 0.0`) with qualified `passed` registration.
- [x] Compare only the eligible shared instance with constant benchmark/slice/model/harness axes (`comparison_valid=true`, `pass_rate_delta=0.0`, `contaminated_or_legacy`). Plumbing/axis proof only; not statistical superiority.
- [x] Run GPQA smoke through real Inspect Evals, retain the official eval log, prove the pinned task/package/CSV identity, qualify, register, and export the resulting private proof.

**RED specification:** `test_terminal_bench_tier1_slice_contracts.py` requires the missing typed one-instance slice.

**Dependencies:** the dev-box has previously demonstrated Docker/Harbor and provider access, but re-probe immediately before charged work. Pause only on the HITL conditions in R0.

**Exit:** all four executable benchmarks hold registered Tier-1 proof; no one-instance result is presented as a quality ranking.

### R4 — Benchmark-specific Tier-2 ledgers and retained adapter boundary

- [x] Preserve the directory-fd-anchored I/O hardening in the dormant CyberGym/ExploitGym scaffolds; this is pre-admission safety, not executable lifecycle proof.
- [x] Add `docs/context/tier2/hle.md` and `bfcl-v4.md` with every readiness §A–§E item marked `proven | partial | missing | not-applicable`, exact evidence, proof boundary, remaining action, and portability state.
- [x] Add equivalent Terminal-Bench and GPQA ledgers. A comparison-validity item is `not-applicable` when no superiority claim is made; do not manufacture a second run merely to fill a checklist.
- [x] **GPQA scored-byte retention:** while the official Inspect log descriptor is pinned, copy exactly those bytes to an owned direct-child artifact, verify the write, stamp SHA-256, and make evidence reference the retained copy. Reject symlink/hardlink/path swaps. Live refresh `run-20260826-082238-670967-54af8e96` exported as `sha256:90978d9e161419aba7ca9c48ceedabc1a009403a7e36deeee861b22a7c21c032`.
- [x] **Legacy private bundle integrity:** private `run_bundle_v1` fails closed with no partial destination when an evidence-referenced artifact cannot be copied exactly, including a path below a skipped symlink ancestor. Do not redesign the legacy format or change public export.
- [x] HLE: post-fix identity-bound smoke `run-20260826-135512-189732-203685b9` with official CAIS judge, `run-plan.json`, `cleanup_result=success`, and imported proof `sha256:4be3b7cdfb9f06b5eef96929dface503ea68cdbd5b3652126fdaf939e9f4b62b`. Ambient-copy fallback is removed. Historical `sha256:b3260e8b…601b77` stays as a structural-only object. Aug 24 material without a run plan stays `legacy_unverifiable`.
- [x] BFCL: refreshed supported-model smoke `run-20260826-083403-019994-e449daac` with official scores, cost basis, and `run-plan.json` (proof `sha256:8323f916…0c38bc`). Cleanup is still `skipped`.
- [x] Complete cleanup-replay evidence before marking any ledger Tier-2. HLE, GPQA (`sha256:a8f17d90…da2f8`), and Terminal-Bench (`sha256:cd681305…e29c7`) have imported `cleanup_result=success` proofs. BFCL cleanup replay is `not-applicable`: generate `results/` and official `scores/` are retained evidence, not named transients (`TRANSIENT_ARTIFACT_DIR_NAMES` excludes them). No ledger is Tier-2.

**Exit:** each Tier-2 claim is justified by its own complete ledger; creating a ledger does not itself advance the tier.

### R5 — SWE-bench Verified diagnostic lifecycle

- [x] **Uncharged compatibility spike:** verify the official `SWE-bench/SWE-bench_Verified@78f471bf…` parquet (`030cfd…`) and select `django__django-11099`; prove locked Inspect Evals `0.8.0` task version 3 loads a run-owned one-row HF-style directory when only the two list fields are canonically JSON encoded and accepts a digest-bound image template. Both phases derive from this one official source snapshot.
- [x] **Official-evaluator schema spike:** `swebench==5.0.1` `eval verified` accepted the one-row prediction. Empty patches are skipped (`empty_patch_ids`, no Docker). A non-empty dummy patch wrote both `schema_version: 2` summary JSON and per-instance `logs/run_evaluation/<run_id>/<model>/django__django-11099/report.json` with `resolved: false`. Adapter now passes unique `--run-id` and `--report-dir`.
- [x] Add `swe-bench-verified-diagnostic-1` for `django__django-11099`; keep smoke-10 and `executable: false` unchanged.
- [x] Add immutable SWE identity (`SWE-bench/SWE-bench_Verified`, revision `78f471bf655a3137b2e8a75af1501690ec009ec3`, parquet SHA-256 `030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25`) and exact `swebench==5.0.1` in a separate `swe` dependency group. Do not upgrade admitted Inspect dependencies.
- [x] Materialize the source row and two deterministic run-owned representations: Inspect-compatible local HF directory and official-evaluator local row. Record transformations/digests and bind the execution-time platform image digest for Inspect generation. CLI injects the real process runner; `process_runner is None` still fail-closes.
- [x] Implement Inspect Evals + exact Inspect SWE runtime generation command, validate exactly one standard prediction row (`instance_id`, `model_name_or_path`, `model_patch`), then invoke the official evaluator under one monotonic cumulative deadline and run-owned root. The default process runner stays explicitly disabled.
- [x] Accept pass only from a coherent pair: official per-instance boolean `resolved` plus a present schema-v2 aggregate. An executed `report.json` without that summary fail-closes. Preserve empty-patch/model failure versus infra/ambiguous/error distinctions.
- [x] Wire SWE only as diagnostic-capable dispatch. Every row stays diagnostic/contaminated and cannot register `passed`.
- [x] Real dev-box diagnostic `run-20260826-095222-202465-019ab2b0` (`codex-cli` / `kimi-k2.7-code` / ByteLLM): Inspect generation exported `predictions.jsonl`, official `swebench==5.0.1` ran, schema-v2 `error_ids` / patch-apply failure, fail-closed `runtime_output_unparseable`. Retained prediction+summary proof `sha256:fcc766f5932607c5250571cdfdf6603e62a8bb19a995a05f81edc561939235b5` (registered `completed`, never `passed`). That proof is `provisional:swe-bench-verified/public`, used Hub alias `swebench eval verified`, has no per-instance `report.json`, and `cleanup_result=skipped`. Catalog stays non-executable; no auto-promotion.
- [x] Identity-bound official-eval diagnostic `run-20260826-141431-679309-31a57785` / `sha256:5f7f79ce44eb8c00d7ee826914e8d4591206de2d3b876a2524ccad508e373e52`: `swebench eval` received the run-owned official-dataset path, stamped `swe-bench-verified@78f471bf655a3137+data-030cfd7f2a704c4c`, retained official/Inspect rows, transformation manifest, and the bound Inspect `.eval`. `runtime_version=0.148.0` from the sandbox Codex binary. Schema-v2 `error_ids` so no executed per-instance `report.json`. `cleanup_result=skipped`. Registered `completed` never `passed`. Historical `sha256:1e6c0d3c…`, `sha256:5a1e24f3…`, and `sha256:fcc766f5…` remain in the store. Catalog stays `executable: false`.

**RED specifications:** `test_swebench_official_lifecycle_v2_contracts.py` preserves the existing two-phase and official-authority boundary. `test_swebench_diagnostic_v3_contracts.py` adds the immutable snapshot/dependency, diagnostic slice/dispatch, explicit generation inputs, strict prediction, aggregate-coherence, and monotonic-deadline contracts. Substitute-backed sequencing remains diagnostic; the real charged diagnostic is still required.

**Exit:** one real diagnostic proves the official generation→evaluation lifecycle. It does not prove model quality, frontier validity, admission, or Tier-1.

### R6 — Catalog-only and later work

- [x] CyberGym and ExploitGym remain catalog-only/non-executable; retained modules have pre-admission anchored I/O but no v1 lifecycle work.
- [x] Catalog planning rejects CyberGym, ExploitGym, SWE-bench Pro, and other pending rows before launch; keep the regression gate when the catalog changes.
- [x] **Not scheduled for v1:** mini-SWE may return only as a separately named agent scaffold; never run it under an admitted runtime identity.
- [x] **Still not scheduled:** object/bucket storage, proof signing, weighted portfolios, OCI/ORAS, database/service orchestration, additional benchmark families, and proof deletion/TTL/garbage collection. The earlier dashboard deferral is superseded by the 2026-09-01 local operator-console decision; remote/multi-user service scope remains excluded.

## Benchmark exposure roadmap (first-model X0–X3 complete; X4/X5 remain)

**Objective:** add the smallest evidence-bound capability that can show whether a canonical BFCL score transfers to fresher or representation-equivalent data, without changing official runtime/scorer behavior or claiming to prove training contamination.

**Program exit gate:** exact pinned BFCL Live and one balanced tool-order study have real official-score/private-proof evidence; reports validate their declared populations and access/verifier axes; smoke is labelled plumbing-only; no clean, cheating, novelty, direct-contamination, or universal adjusted-score claim is emitted. Completion of this program does not admit either diagnostic benchmark, advance Tier-2, or complete U3/U4.

X0–X3 below retain their original first-model scope and evidence. CF is not a reason to reopen completed experiments. Future configured-model studies apply architecture §23's registration-only clarification; historical unextended package/lock bytes are never rewritten.

### X0 — Decision closure and executable spikes

**Objective:** falsify the two BFCL integration assumptions and close the access/statistics contract before production modules or charged populations are built.

**Exit gate:** exact wheel/Live identity, official category loading, run-owned overlay viability, effective-access mapping, and the initial frontier population decision are proven or the dependent work is explicitly removed. No HITL is expected; pause only under the existing literal login/admin boundary.

- [x] `X0.1` Verify BFCL Live wheel identity and official category loading
  - Why now: the upstream commit has ten Live files, but BenchEval runs the PyPI `bfcl-eval==2026.3.23` wheel and must bind the bytes it actually executes.
  - Files: no production edits; retain the probe under the gitignored research/run artifacts and record final pins in `config/benchmarks.yaml` only in X2.1.
  - Scope: on dev-box, install/sync the existing `bfcl` group; compare the six question and four answer files with `gorilla@6ea57973…`; use the real package category parser/loader for every `live_*` category; verify supported-model resolution and official generate/evaluate command shapes without a provider call. Do not mutate site-packages or invent missing files.
  - Dependencies: none.
  - Acceptance evidence: exact path/size/SHA-256 ledger for ten files; captured package/upstream versions; real loader accepts six categories; any mismatch fails before identity or launch.
  - If it fails: keep BFCL Live research-only outside the product and stop X2; do not patch or fork BFCL.

- [x] `X0.2` Prove the run-scoped BFCL overlay route *(done 2026-09-07 on dev-box-cpu, uncharged: a copy of the installed pinned package under a disposable root plus `PYTHONPATH=<root>/pkg` and `PYTHONDONTWRITEBYTECODE=1` made `bfcl_eval.__file__`, `__main__`, `eval_checker.eval_runner`, `PROMPT_PATH`, and `POSSIBLE_ANSWER_PATH` resolve to the copy; `load_dataset_entry("multiple")` returned the reversed `function` order for `multiple_0`; only `data/BFCL_v4_multiple.json` differed; the installed tree stayed byte-identical. Findings that shaped X3.3: installed files are uv-cache hardlinks, so an overlay must be a fresh copy with link count 1; the loader follows symlinked directories, so the verifier walks with lstat and rejects any link.)*
  - Why now: pinned BFCL has no arbitrary dataset-path option, so tool order is viable only if an isolated data overlay can load without changing code/scorer.
  - Files: no production edits; disposable directory outside the checkout.
  - Scope: copy the exact installed package to an exclusive temporary root, change one declared `multiple` row's `function` order, invoke the real package loader from that root, and prove all Python/config/scorer bytes plus the installed package tree remain identical. Verify unchanged ground truth resolves through the official evaluator. No model/provider call.
  - Dependencies: X0.1.
  - Acceptance evidence: before/after producer/scorer digest sets match; only the declared data digest changes; loader observes the new order; installed tree digest is unchanged; symlink/hardlink/path replacement probes fail closed.
  - If it fails: stop X3 and retain only the official Live study; do not monkeypatch `PROMPT_PATH`, modify site-packages, or add a BFCL fork.

- [x] `X0.3` Prove the effective-access evidence matrix
  - Why now: `network_policy` currently means plan intent and demonstrably differs from model-visible access across adapters.
  - Files: research output only; architecture §22 remains the decision source.
  - Scope: inspect a real model-only plan, pinned Inspect SWE generated Docker config with default `allow_internet=False`, and Harbor/TB command/preflight. Establish exactly what artifact/config can support `not_applicable`, `blocked`, and `uncontrolled` without running a custom network service.
  - Dependencies: none; may run with X0.1.
  - Acceptance evidence: retained non-secret effective configs and a three-row mapping that cannot be derived from `network_policy`; Harbor is never stamped restricted; no runtime/harness bytes or behavior are changed.
  - If it fails: use `unknown` for the affected path; do not add probes that alter the model's tools or traffic.

- [x] `X0.4` Select the frontier study population and inference boundary
  - Why now: smoke cannot support statistics and old math-style benchmarks may be saturated for the actual target model pool.
  - Files: `config/studies/` drafts and a concise measurement record; no report implementation before the decision is reviewed.
  - Scope: name the initial admitted provider/model, BFCL categories, canonical/Live task counts, expected provider budget, deterministic order-permutation coverage, repeated-run variance check, and the raw/interval/test output that is allowed at smoke versus study scale. Reuse `stats.py` where sufficient; add no dependency during the spike.
  - Dependencies: X0.1; the final tool-order portion depends on X0.2.
  - Acceptance evidence: a reviewed population/precision/cost record with `plumbing_only` thresholds, inferential minimums, and explicit forbidden claims. If no affordable population has useful headroom, stop after the compatibility evidence rather than shipping a low-information feature.

### X1 — Additive evidence and study contracts

**Objective:** introduce the reusable minimum—effective-access evidence, closed study manifests, deterministic identities, and fail-closed report validation—without launching a derived benchmark.

**Exit gate:** old evidence/proofs remain valid; the new manifests and report boundary reject every unsupported interpretation and population drift; no new benchmark row can register `passed`.

- [x] `X1.1` Write discriminating RED contracts for access evidence
  - Files: `tests/specs/test_effective_access_contracts.py`, adjacent evidence/adapter tests.
  - Scope: require independent requested/effective values; model-only `not_applicable`; retained official Inspect blocked state; Harbor uncontrolled; historical null compatibility; no stamp from `network_policy`; retrieval-audit values do not change native scoring.
  - Dependencies: X0.3.
  - Acceptance evidence: tests fail on the current code for each intended reason before implementation. Any required substitute carries the repository's full justification and remains diagnostic.

- [x] `X1.2` Implement effective-access capture
  - Files: `src/bencheval/domain.py`, `evidence.py`, new `access_evidence.py`, concrete capture sites in model-only/SWE/Harbor paths, report/export projections, and tests from X1.1.
  - Scope: add the four optional closed fields in architecture §7.5; constructors accept concrete retained launch facts only; preserve all legacy parsing and `network_policy` behavior. Never add enforcement, probes, proxy policy, or secret config bytes.
  - Dependencies: X1.1.
  - Acceptance evidence: RED→GREEN; real effective configs from X0.3 serialize correctly; v0.2/v0.3 fixtures and historical proofs still verify; public exports reveal no private access/transcript data.

- [x] `X1.3` Write RED study-manifest and identity contracts
  - Files: `tests/specs/test_exposure_study_contracts.py`.
  - Scope: closed `freshness_contrast`/`representation_pair`, stable relation classes, paired/unpaired mode compatibility, safe ids, canonical digest, required constant axes, forbidden claims, exact source mapping, derived BFCL identity, and rejection of arbitrary transform/plugin/path fields.
  - Dependencies: X0.1/X0.2 decisions.
  - Acceptance evidence: malformed/ambiguous manifests, same identity on both roles, Live-as-paired, tool-order-as-unpaired, unsafe paths, and transform drift all fail for the intended reason.

- [x] `X1.4` Implement the closed study registry and identity spine
  - Files: new `src/bencheval/exposure_study.py`, `benchmark_registry.py`, `identity_strings.py`, `paths.py`, package-data entries in `pyproject.toml`, initial `config/studies/*.yaml`, and X1.3 tests.
  - Scope: load/canonicalize/hash declarative study YAML and add the single BFCL derived-data identity type. Do not add launch orchestration, generic transform entry points, Python callbacks, or candidate benchmark rows yet.
  - Dependencies: X1.3.
  - Acceptance evidence: RED→GREEN; source/build wheel contains and validates the manifests; clean core import remains dependency-light; identity changes on any source/transform/population change.

- [x] `X1.5` Establish read-only report validity and CLI shell *(software only: `study validate|report|verify`, `exposure-report-v1` JSON authority, raw-only smoke gate bound to each side's `smoke_slice_id`, exact catalog identity/provenance/one-run-per-side checks, declared analysis only when both populations equal the retained run plan of a complete proof, and `exposure-study-lock-v1` reproduction from inventory-bound proof bytes; pairing is by identical source instance id and derived candidates stay raw-only until X3.4 binds the derived mapping. X2.3 needs an exact-id canonical plumbing slice `exposure-plumbing-5`, since `smoke-5` scores whole categories)*
  - Files: new `src/bencheval/exposure_report.py`, `cli.py`, `stats.py` only if X0.4 earns a helper, and `tests/specs/test_exposure_study_contracts.py`.
  - Scope: add `bencheval study validate|report`; validate evidence, eligibility, identities, constant axes, access, verifier, and population before output. Implement deterministic JSON plus Markdown projection and raw-only smoke mode. Proof-backed report mode also writes an `exposure-study-lock-v1` manifest beside the report, binding both input proof ids, the study digest, selected evidence inputs, report contract version, and report JSON digest. Do not add `study run`, reference correction, UI, or automatic seeds.
  - Dependencies: X1.2, X1.4, X0.4.
  - Acceptance evidence: current valid evidence can be loaded; incomplete, asymmetric, drifted, infra-contaminated, or overclaiming studies exit nonzero and leave no partial output; smoke output contains no inferential language; proof-backed mode rejects either mismatched proof or any changed lock/report input and reproduces the locked report digest from copied proof objects.

- [x] `X1.6` Retain study artifacts without changing the run-proof format *(software only: every BFCL run writes canonical `study/benchmark-identity.json` and `study/effective-access.json` under the run root once, later instances verify the bytes, and every scored row references them so `private_proof_v1` retains them at `artifacts/raw/study/` with the generic `artifact` role; `study/private/` never reaches a public bundle because public bundles carry no raw tree; the two-proof lock stays outside both proofs and now carries the exact selected study definition, so `study verify` reproduces a custom study from two copied proofs plus the lock with no study YAML or checkout present. Variant/source/derived files arrive with X3.)*
  - Files: `proof_bundle.py`, run-bundle/public-redaction paths, proof tests.
  - Scope: make study/variant/source/derived/safe access files ordinary evidence-referenced artifacts beneath `artifacts/study/`; retain the existing `private_proof_v1` `artifact` role and required-role set. Do not embed the separate two-proof lock in either run proof or add a proof store/index. Private retrieval transcripts stay private; public outputs sanitize or omit them.
  - Dependencies: X1.2, X1.4.
  - Acceptance evidence: source-checkout-removed verify/import succeeds; missing, extra, symlink, hardlink, outside-root, or digest-changed study artifacts fail; historical private proofs still verify with no migration.

### X2 — BFCL Live freshness/generalization vertical slice

**Objective:** produce the first real exposure-adjacent evidence entirely through official BFCL data, code, scorer, and current provider path.

**Exit gate:** a distinct BFCL Live diagnostic identity produces official scores and private proof; the validated report is explicitly stratified/unpaired and contains no contamination estimate or admission claim.

- [x] `X2.1` Add the BFCL Live diagnostic identity and slices
  - Files: `config/benchmarks.yaml`, `config/slices/bfcl-v4-live-*.yaml`, `config/studies/bfcl-v4-live-vs-non-live.yaml`, packaging config, catalog/identity tests, docs/ops BFCL page.
  - Scope: add `bfcl-v4-live` as `executable: false`, adapter-bound and diagnostic-capable; pin exactly the six Live question and four answer files verified in X0.1; define a tiny plumbing slice and the X0.4 study population separately. Do not modify or replace the admitted `bfcl-v4` identity/status.
  - Dependencies: X0.1, X1.4.
  - Acceptance evidence: catalog/packaged-config parity; identity fails on any missing/drifted Live byte; current executable count remains four; ordinary run rejects while explicit diagnostic planning succeeds.

- [x] `X2.2` Wire official Live generation/evaluation without a second scorer
  - Files: `bfcl_native_adapter.py`, `control_plane_executor.py`, `doctor.py`, `access_evidence.py`, BFCL tests.
  - Scope: parameterize the current BFCL lifecycle by the catalog identity/category; preserve supported-model gate, cumulative deadline, run-owned results/scores, official JSONL parser, producer identity, model-only access state, and diagnostic registration veto. Do not copy or reinterpret score values in a study module.
  - Dependencies: X2.1, X1.2.
  - Acceptance evidence: official CLI command contains only verified Live categories; wrong solution remains eligible native evidence; local verdict/stdout cannot pass; injected-runner tests are diagnostic only.

- [x] `X2.3` Run and preserve the real Live plumbing slice *(done 2026-09-05 on dev-box-cpu with `gpt-5.2-2025-12-11` via ByteLLM: canonical `bfcl-v4/exposure-plumbing-5` run `run-20260905-045809-295551-693b2391` and Live `bfcl-v4-live/plumbing-6` diagnostic run `run-20260905-045921-199890-cbed984c`, both official generate→evaluate, both `complete` private proofs (`sha256:f02f7bd6…`, `sha256:d849b654…`), Live `--status passed` refused, raw-only report `plumbing_only`/unpaired with no contamination or significance claim, and `study verify` reproduced byte-identical report JSON from copied proofs plus the lock on the dev-box from `/tmp` and again on a second host. The first attempt (`…f1ac18dd`, `…368825d7`) exposed an upstream bfcl-eval 2026.3.23 defect: exact-id `evaluate` writes the official score then crashes computing leaderboard latency stdev over one sample; the adapter now accepts only that exact post-score crash shape on exact-id cases, retained per row as `post_score_summary_failure`. 1/5 and 1/6 passes are model behavior (prompting-mode AST decode failures), irrelevant to plumbing. X2.4 prep on the same slices with `gpt-5.2-2025-12-11-FC`: canonical `run-20260905-060326-458331-cd0e3aed` 5/5, Live `run-20260905-060424-633249-776d338b` 4/6 with real checker failures, proofs `sha256:60221395…`/`sha256:9198c332…` complete, report reproduced on both hosts; the FC handler is the X2.4 mode.)*
  - Files: no source edits except factual runbook/ledger updates after evidence; results/proofs remain gitignored/local.
  - Scope: on dev-box, re-probe BFCL group/provider/model support, execute the tiny explicit diagnostic, retain official score bytes and ten-file identity, export and verify/import private proof, and run the study report in raw-only mode.
  - Dependencies: X2.2, X1.5, X1.6, and green production gate.
  - Acceptance evidence: real provider + official generate→evaluate; diagnostic row cannot register `passed`; proof verifies after copy; report says `plumbing_only`, unpaired, and no contamination/significance claim.
  - Human boundary: pause only if provider/runtime presents literal device/ subscription/CAPTCHA/hardware/admin interaction. Missing packages or ordinary credentials are operational work, not automatic HITL.

- [x] `X2.4` Run the reviewed BFCL non-live/Live study population *(split: **X2.4a done 2026-09-05** — `study select` plus `exposure_selection.py` materialized `exposure-non-live-v1` (340) and `exposure-live-v1` (356) from the pinned package on dev-box-cpu; record `config/studies/bfcl-v4-live-vs-non-live.selection.json`, digest `sha256:937bd36c…`; declared reports now require the record, bind it to the study (id, digest, algorithm, seed) and to the catalog identity (question-file pins plus `populations` candidate-universe anchors in `config/benchmarks.yaml`), enforce selected = planned = observed per stratum, and retain it in the lock; raw-only report bytes are unchanged, proven by the retained pre-selection FC lock fixture. **X2.4b done 2026-09-05** on dev-box-cpu with `gpt-5.2-2025-12-11-FC` via ByteLLM: canonical `run-20260905-064918-223328-f38fe8fe` 293/340 and Live diagnostic `run-20260905-075524-372104-e932b596` 256/356, every row an official verdict, both `complete` proofs (`sha256:2d7148db…`, `sha256:853293d1…`), declared report `sha256:729d3e67…` (Wilson 0.862 [0.821, 0.894] vs 0.719 [0.670, 0.763], Newcombe difference −0.143 [−0.201, −0.083]) with the selection enforced and retained in the lock, reproduced byte-identical from copied proofs plus the lock on the dev-box and on a second host; 2 h 24 min wall clock, well inside the $20 / four-hour plan. The report states a benchmark-specific dependence caveat only; no contamination, cleanliness, or paired claim.)*
  - Files: study config/ops docs only if X0.4's reviewed population changes; immutable run/proof artifacts stay local.
  - Scope: run canonical and Live categories with the same model/provider/sampling/harness version and declared budgets; preserve every native row and exclusion; produce deterministic JSON/Markdown and copied-proof verification.
  - Dependencies: X2.3, X0.4.
  - Acceptance evidence: declared task counts/strata and constant axes validate; report gives native rates/intervals and a freshness/generalization caveat; independent review confirms it does not present a paired or contamination estimate. If the result has no useful headroom or costs exceed the plan, stop before X3 rather than forcing a variant feature.

### X3 — BFCL balanced tool-order paired study

**Objective:** add one representation-equivalent transform with exact source mapping and unchanged official scoring, then test whether it yields information beyond canonical/provider variance.

**Exit gate:** installed BFCL remains byte-identical; a run-owned derived identity produces official-score evidence and a population-valid paired report; no generic transform abstraction or canonical admission is introduced.

- [x] `X3.1` Write RED materialization and overlay contracts *(done 2026-09-07: `tests/specs/test_bfcl_study_contracts.py`, `test_bfcl_derived_run_contracts.py`, `test_exposure_pair_contracts.py`, plus pair cases in the selection contracts; substitute package trees, never the installed distribution)*
  - Files: `tests/specs/test_bfcl_study_contracts.py`, hostile filesystem tests.
  - Scope: deterministic non-identity balanced permutations for declared `multiple`/`parallel_multiple` rows; exact source-to-derived mapping; all non-`function` data and ground truth unchanged; canonical serialization; source/derived/producer/scorer digests; exclusive run-owned overlay; installed tree immutability; pre/post-launch drift and symlink/hardlink/path-swap rejects.
  - Dependencies: X0.2, X2.4 useful-result gate.
  - Acceptance evidence: each behavioral contract is RED on current code for the intended reason; no substitute claims official BFCL execution.

- [x] `X3.2` Implement the BFCL-specific materializer *(done 2026-09-07: `bfcl_study.py` — frozen `sha256_rotate_v1` offset `1 + sha256([algo, seed, id]) mod (k-1)`, per-row non-identity rotation of `function` only, strict row validation, byte-identical package copy with lstat/nlink checks, derived digests, variant manifest; two materializations are byte-identical and a changed seed changes the digest)*
  - Files: new `src/bencheval/bfcl_study.py`, `run_isolation.py` only for an earned shared primitive, and X3.1 tests.
  - Scope: read pinned canonical JSONL, validate ids/tool names, calculate the versioned balanced permutation, write source/derived/variant manifests through anchored exclusive I/O, and verify replay. No scorer, process runner, provider, generic transform callbacks, or installed-package writes.
  - Dependencies: X3.1.
  - Acceptance evidence: RED→GREEN; two independent materializations produce byte-identical output/digest; changed source/version changes identity; every outside-write/mutation probe fails closed.

- [x] `X3.3` Implement and bind the run-owned package overlay *(done 2026-09-07: derived runs resolve the catalog `bfcl-derived-ref`, materialize `overlay/pkg/bfcl_eval` once per run, launch the unchanged official CLI with `PYTHONPATH` pointing at it, re-verify overlay and installed bytes before generate and around evaluate, and retain `study/variant-manifest.json` plus both derived data files in evidence and proof; tampering yields `runtime_config_drift`)*
  - Files: `bfcl_study.py`, `bfcl_native_adapter.py`, `control_plane_executor.py`, `doctor.py`, proof/artifact retention tests.
  - Scope: copy the pinned package into the claimed run root, verify byte-identical code/config/scorer, replace only declared data files, launch the unchanged official CLI from the overlay, then reverify overlay/source/installed trees before accepting scores. Share the current BFCL score parser; do not add a study scorer.
  - Dependencies: X3.2.
  - Acceptance evidence: real uncharged overlay loader/evaluator probe from X0.2 passes through the production path; producer/scorer drift or concurrent swap yields typed invalid evidence; installed distribution remains unchanged.

- [x] `X3.4` Add the diagnostic identity, slices, and paired report mode *(done 2026-09-07: catalog row `bfcl-v4-tool-order-v1` (non-executable, `bfcl-derived-ref` to `bfcl-v4` and the study); the pair is selected once from the canonical universe and inherited by the derived side (record `sha256:a283dd3f…`, slices `tool-order-canonical-v1`/`tool-order-derived-v1` of 200 ids, plumbing-2 `multiple_19` + `parallel_multiple_125`); declared paired reports require the candidate proof's retained variant manifest plus both retained derived data files, bind the files to the manifest and identity digests and the mapped ids, and bind the manifest's derived label, source pins, study digest, seed, transform, and identical-id mapping; the lock retains it as `variant`. Review R1 fixes: derived-file binding (F001), prelaunch overlay failures preserved as `runtime_config_drift` (F002), manifest version validated (N001))*
  - Files: `config/benchmarks.yaml`, `config/slices/bfcl-v4-tool-order-*.yaml`, `config/studies/bfcl-v4-tool-order-v1.yaml`, registry/identity/report/CLI tests, BFCL ops docs.
  - Scope: add `bfcl-v4-tool-order-v1` as non-executable diagnostic; bind canonical source identity, transform/study version, derived digest, and source ids. Extend report with exact paired population, concordant/discordant counts, directional flips, paired delta, X0.4 uncertainty rule, and raw-only smoke.
  - Dependencies: X3.3, X1.5.
  - Acceptance evidence: ordinary execution and `passed` registration reject; diagnostic planning works; asymmetric/duplicate/missing/drifted pairs fail nonzero; relation remains `representation_equivalent` regardless of measured fidelity.

- [x] `X3.5` Run the real tool-order smoke and reviewed paired population *(done 2026-09-07 on dev-box-cpu with `gpt-5.2-2025-12-11-FC` via ByteLLM. Plumbing: canonical `run-20260907-044257-862718-0e80c19e` and derived `run-20260907-044320-657744-a93a90fc`, 2/2 each, overlay differing from the installed package only in the two declared files, proofs `sha256:b8e8b305…`/`sha256:de03e246…`, raw-only paired report `sha256:662195d1…` reproduced on both hosts. Predeclared study: primary canonical `run-20260907-044713-829381-5e5d4652` 167/200, derived variant `run-20260907-052429-563407-be7f87d2` 165/200, canonical repeat `run-20260907-060237-419067-d9fb217f` 171/200 (variance control, never pooled); proofs `sha256:eb2c9a84…`/`sha256:0b128d0b…`/`sha256:9a0ef59c…` complete; declared paired report `sha256:8e68e7d1…` (pairs: 157 both pass, 25 both fail, 10 canonical-only, 8 variant-only; paired delta −0.010; exact binomial on 18 discordant pairs p≈0.815) with the retained variant manifest bound and the lock reproduced from copied proofs on both hosts. Primary-versus-repeat control: 6 discordant pairs (1/5), so observed discordance was three times higher for the order variant, without a statistically clear directional shift in this study. That ratio is descriptive, not a significance test against the repeat; the caveat stays `benchmark_specific_dependence` with no contamination claim.)*
  - Files: immutable local evidence/proofs plus factual docs/ledger update after verification; no source change driven only by score preference.
  - Scope: use the same frontier model/provider/settings as canonical, first run the plumbing slice, then only the X0.4 reviewed population; export/verify private proofs and reproduce the paired report from copied proof bytes.
  - Dependencies: X3.4 and green software/security gates.
  - Acceptance evidence: official score JSONL is sole verdict; package code/scorer and installed-tree digests hold; smoke emits raw-only output; study population validates and reports directional flips/uncertainty with competing explanations and no contamination/clean/cheating claim.

### X4 — Operator integration, hardening, and scoped readiness

**Objective:** expose the proven study/report capability through existing application/UI/proof paths without expanding its claim or runtime surface.

**Exit gate:** CLI, optional console, copied private proof, docs, and security/readiness review agree on the exact diagnostic claim. This remains independent of the deferred general console U3/U4 program except for shared regressions.

- [ ] `X4.1` Add application and console projections
  - Files: `src/bencheval/application/{dto,operations}.py`, `ui/pages.py`, console tests, `docs/api/operator-console-contract.md`.
  - Scope: add study validation/report selection and result display to the existing Compare surface; show relation, native scores, access/verifier/freshness, population validity, flips, uncertainty, and explicit non-claims. Do not add automatic charged launch, model panels, transform editing, or page-local interpretation.
  - Dependencies: X2.4 and X3.5; schedule after the CF1 onboarding vertical. A CLI-only readiness claim may explicitly exclude this UI projection; it cannot call the UI feature complete.
  - Acceptance evidence: DTO exactly matches domain JSON; crafted UI state cannot bypass invalid/smoke claims; keyboard/table fallback works on the added view.

- [ ] `X4.2` Close artifact, privacy, and compatibility edges
  - Files: `proof_bundle.py`, `run_bundle.py`, `redaction.py`, exports, CLI/report error handling, regression tests, ops docs.
  - Scope: reconcile already-landed study/derived-file/retention regressions and close only remaining material artifact/privacy/compatibility gaps; include CF registration artifacts when that path is in the claim. Cover proof copy/import, public omission/redaction, exclusive outputs, legacy reads, and no partial report. Do not restart an open-ended filesystem-hardening program.
  - Dependencies: X1.6, X3.5.
  - Acceptance evidence: hostile real-filesystem battery passes; no secret/private transcript in public output; old proofs and CLI commands remain compatible; dependency and secret scans stay green.

- [ ] `X4.3` Independent review and readiness decision
  - Files: no product edits during review; durable readiness artifacts in the established local review location.
  - Scope: max-effort `qa-review` plus scoped `verify-readiness` over the exact final tree and real BFCL proofs. Review must challenge identity, access truth, official scoring, population validity, statistics, wording, proof portability, and runtime/harness non-modification.
  - Dependencies: X4.1/X4.2 as applicable.
  - Acceptance evidence: zero open red/yellow findings for the scoped exposure claim; `make check-production-v1`, focused hostile contracts, exact proof verify/import, and real report reproduction pass. A green unit suite alone is not readiness.

### X5 — Evidence-led continuation decision

**Objective:** decide whether the first study created enough user value to justify another transform family or any shared abstraction.

**Exit gate:** one explicit continue/stop decision is recorded from real evidence; no speculative framework remains on the active roadmap.

- [ ] `X5.1` Evaluate information value and operating cost
  - Files: concept/architecture/roadmap decision update only.
  - Scope: compare the Live and tool-order findings with provider/run variance, transform fidelity, operator effort, proof size, and whether a real model or benchmark decision changed. Do not choose a favorable score as the criterion.
  - Dependencies: X2.4 and, if not stopped, X3.5/X4.3.
  - Acceptance evidence: concise evidence-backed decision with observed costs, limits, and the next falsifiable question.

- [ ] `X5.2` Reopen architecture only on earned second-family demand
  - Files: `docs/context/concept-zero.md`, `docs/architecture.md`, `docs/roadmap.md`; no production implementation in the decision step.
  - Scope: if a second frontier-relevant benchmark needs the same source/relation/fidelity/materialization/report invariants, research it and decide whether to extract a narrow shared contract. Otherwise close the exposure program at the BFCL-specific implementation and keep MATH()/DyVal/training labs deferred.
  - Dependencies: X5.1.
  - Acceptance evidence: either a newly accepted concept/architecture with a real second family, or an explicit stop decision that leaves no generic transform task scheduled.

### Exposure execution packets and merge order

1. **Packet A — X0 spikes:** read-only/dev-box research; no production writer.
2. **Packet B — X1 access/study contracts:** one writer for shared domain/evidence/CLI/proof files; do not parallelize writers across these hot modules.
3. **Packet C — X2 Live:** begins after X1 identity/access foundations; owns BFCL catalog/slices/adapter delta and real Live proof.
4. **Packet D — X3 tool order:** starts only after the X2 usefulness gate; owns `bfcl_study.py`, overlay, derived identity, and paired report delta.
5. **Packet E — X4 review/integration:** UI projection follows the proven CLI; independent review remains read-only and uses the exact candidate tree.
6. **Packet F — publication of the accepted batch (held for the owner's request):** one PR from `feat/benchmark-exposure-foundations` that describes the whole batch — the benchmark-exposure foundations (X0–X3 study, selection, report, and BFCL transformation modules), CF1–CF3.2, and the included maintenance changes — not a CF-only patch; commit boundaries follow the actual dependencies.

Every implementation packet begins with `dev-spec` RED contracts, proceeds through implementation/self-critique, and receives an independent `qa-review`. Incomplete packet acceptance is a rejection: unrun real BFCL/proof/readiness exit criteria remain `BLOCKED` or `IMPLEMENTED BUT UNVERIFIED`, never silently complete.

### Exposure cross-phase gates

- [ ] `XG-01` Official-runner and declared-registration integrity
  - Evidence: installed BFCL and official handler/generator/scorer bytes remain pinned. Existing data-only runs retain full code/config equality; new CF runs additionally bind exactly the permitted registration-file delta shared across arms. No arbitrary executable changes or custom network/runtime layer.
- [ ] `XG-02` Identity and proof completeness
  - Evidence: study/source/candidate/variant/access artifacts are content-bound, evidence-referenced, copied under `artifacts/study/`, and verify offline; an `exposure-study-lock-v1` manifest binds both run proof ids, exact report inputs, and the deterministic report JSON digest.
- [ ] `XG-03` Population and interpretation validity
  - Evidence: paired/unpaired rules, constant axes, eligibility, verifier quality, smoke limits, uncertainty method, and forbidden claims are machine-checked.
- [ ] `XG-04` Backward compatibility
  - Evidence: v0.2/v0.3 evidence, existing CLI/report/compare, current private proofs, catalog executable count, and core import/package gates remain green.
- [ ] `XG-05` Real evidence boundary
  - Evidence: official BFCL Live/variant runs and copied-proof report reproduction are the acceptance oracle; substitutes are diagnostic only and cannot close a live or readiness checkbox.

## Operator console roadmap (IMPLEMENTED; hardening remains)

Implementation status on 2026-09-01: U0.1–U0.4, U1, and U2 are implemented for their bounded operator surface. U0.5 lacks the full automated/browser matrix. U3/U4 remain lower-priority hardening/release work, not blockers for CF's CLI-first onboarding or model-only studies. UI coverage does not prove backend/profile extensibility; a green deterministic suite or one-browser walkthrough does not close these broader claims.

The following phases cover the complete existing product surface. They do not admit new benchmarks, promote SWE, add remote users, or change proof retention. Each implementation slice must preserve CLI behavior and canonical files.

### U0 — Decision closure and executable spikes

**Objective:** prove the proposed framework, local trust boundary, shared application contract, and long-running-session mechanics before page breadth.

**Exit gate:** NiceGUI is either accepted with measured evidence or replaced by another single-process local route; state-changing UI has a proven local capability boundary and safe run-session cancellation/reconnect contract. No HITL is required.

- [x] `U0.1` NiceGUI optional-extra and clean-install spike
  - Files: throwaway spike outside production modules; proposed changes limited to `pyproject.toml`, `uv.lock`, and a minimal `src/bencheval/ui/` only after acceptance.
  - Scope: evaluate current NiceGUI 3.x license, transitive/build footprint, Python 3.12 compatibility, wheel/`uv tool install`, startup latency, browser open/no-open, loopback bind, core import isolation, table/download support, and real-browser test fixture. Do not add the dependency before the spike is reviewed.
  - Dependencies: none.
  - Acceptance evidence: clean disposable install; `import bencheval` without UI deps; minimal `bencheval ui --no-open` starts/stops on loopback; dependency audit and license record; measured startup and lock diff.
  - If it fails: spike NiceGUI native mode only if it preserves one process; otherwise select a minimal server-rendered Python route. Do not fall through to a split SPA without a new architecture review.

- [x] `U0.2` Local mutation-capability and hostile-browser spike
  - Files: `tests/ui/test_local_capability.py`; proposed `ui/app.py` boundary.
  - Scope: bind `127.0.0.1`, exact Host/Origin, no CORS/iframe, per-process capability exchange to strict cookie, nonce removal, invalid/replayed token, DNS-rebinding-style Host, and cross-origin mutation attempts. Read-only and mutation events must both be tested through a real browser/server.
  - Dependencies: U0.1.
  - Acceptance evidence: all hostile requests fail before application calls; valid local browser reaches one harmless dry-run action; no token appears in logs, durable files, or browser URL after exchange.
  - If it fails: first release is read-only while the mutation boundary is redesigned; never add a remote bind workaround.

- [x] `U0.3` Typed application-operation parity baseline
  - Files: proposed `src/bencheval/application/{dto,catalog_ops,run_ops,evidence_ops,analysis_ops,proof_ops,readiness_ops}.py`; `tests/application/`.
  - Scope: define and implement the contract in `docs/api/operator-console-contract.md` around existing modules. Capture golden CLI operation results before refactoring handlers. No storage schema or benchmark semantics change.
  - Dependencies: none; may run in parallel with U0.1/U0.2.
  - Acceptance evidence: CLI-before versus application-operation-after parity for catalog, plan failures/success, doctor, validated history, compare, report/export argument validation, and proof verify; Pydantic closed-schema tests and full production gate.

- [x] `U0.4` Real bounded RunSession cancellation/reconnect spike
  - Files: proposed `ui/session.py`, a disposable real subprocess harness, and `tests/ui/test_run_session.py`.
  - Scope: one active mutation, background task, page refresh/second tab, explicit cancel, timeout, browser close, process exit, output cap, and server restart reconciliation. No provider or official benchmark substitution may count as live acceptance; this spike proves session mechanics only.
  - Dependencies: U0.1 and U0.3.
  - Acceptance evidence: real local child lifecycle has no duplicate launch, bounded cancellation, no lost completed evidence, and explicit non-resumable state after server restart.
  - If it fails: ship read-only/dry-run UI first and defer live mutation.

- [ ] `U0.5` Browser accessibility harness
  - Files: `tests/ui/test_accessibility.py`, `ui/theme.py`, test configuration.
  - Scope: decide the real browser/axe route and prove keyboard, focus, labels, status announcements, non-color meaning, reduced motion, and chart table fallback on the minimal shell.
  - Dependencies: U0.1.
  - Acceptance evidence: Chromium real-browser journey and automated scan with zero critical/serious findings; manual Firefox/WebKit keyboard spot-check protocol recorded for later phases.

### U1 — Read-only production-shaped walking skeleton

**Objective:** ship the local entry point, shared read operations, shell, Overview, Catalog, Environment, and existing run detail without mutation.

**Exit gate:** a clean-box operator starts `bencheval ui`, navigates every read-only page by keyboard, and sees canonical local data with no UI dependency in core installs. Mutation remains disabled until U0.2/U0.4 pass.

- [x] `U1.1` Package the optional entry point and shell
  - Files: `pyproject.toml`, `uv.lock`, `cli.py`, `ui/{__init__,app,pages,security,session}.py`, `ui/assets/console.css`.
  - Scope: add `bencheval ui --port --no-open`, loopback only, lazy NiceGUI import, navigation, skip link, global status, display preferences, and graceful missing-extra error. Do not add host/auth/config editing.
  - Dependencies: U0.1, U0.2, U0.5.
  - Acceptance evidence: core and UI clean installs; start/stop smoke; missing-extra CLI error; real-browser shell and keyboard checks; `make check-production-v1`.

- [x] `U1.2` Catalog and Overview vertical path
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: current catalog, models, runtimes, agents, providers, action availability, Tier-0/Tier-1/Tier-2 truth, recent validated runs, proof health. No benchmark/run action may be enabled from page-local inference or a metadata admission label alone.
  - Dependencies: U0.3, U1.1.
  - Acceptance evidence: DTO-versus-registry parity; actual pending/diagnostic/scaffold rows disabled; real browser filter/paging/deep-link tests.

- [x] `U1.3` Environment/Doctor and read-only Runs & Evidence
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: config/results/proof roots, dependency/runtime/provider-variable presence, doctor execution, validated raw/current history, completed run detail, evidence/official result/artifact metadata/history. Default previews are redacted and size capped.
  - Dependencies: U1.1 and U0.3.
  - Acceptance evidence: corrupted history fails closed; credential values never enter DTO/HTML; hostile artifact content is served as text/download only; restart shows the same durable projection.

### U2 — Complete operator journeys

**Objective:** add every current mutation and analytical/export/proof operation.

**Exit gate:** all feature-coverage rows in `docs/prototypes/frontend-v1.md` pass through real application operations and a real browser. Charged/native benchmark proof remains a separate claim.

- [x] `U2.1` Run Builder dry-run and plan parity
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: Axes → Plan → Preflight → Confirm; runtime XOR agent, model/provider, budgets, network/caveats, diagnostic opt-in, paths, dry-run. No hidden defaults or output reservation during planning. Confirmation fingerprints bind normalized output selections, and preflight follows the derived official harness instead of treating every native adapter as Inspect.
  - Dependencies: U1, U0.3.
  - Acceptance evidence: canonical `RunPlan` bytes/errors match CLI across all executable, diagnostic, catalog-only, scaffold, and model-only paths.

- [x] `U2.2` Live start, monitor, cancel, and run detail
  - Files: `application/{dto,operations}.py`, `ui/{session,pages}.py`.
  - Scope: explicit cost/charge confirmation, one active launch, live lifecycle and bounded redacted log tail, explicit cancel, browser reconnect, evidence/artifact refresh, preallocated run identity, explicit evidence truncation metadata, and task outcome separate from registration. Orphan process-group descendants are terminated even when their worker leader exits first.
  - Dependencies: U0.2, U0.4, U2.1.
  - Acceptance evidence: real bounded local subprocess browser journey plus one previously admitted uncharged/dry lifecycle; charged/native run is `not run` unless credentials/harness are deliberately supplied.

- [x] `U2.3` Evidence qualification and registration
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: legal lifecycle actions, qualification reasons, fill-once axes, producer/provenance gates, notes/host/locators. Diagnostic cannot register passed; no automatic retry.
  - Dependencies: U1.3, U2.2.
  - Acceptance evidence: API/CLI/UI parity for legal and illegal transitions; direct crafted event calls revalidate; concurrent tabs produce one append.

- [x] `U2.4` Compare and reports
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: baseline/current selection, shared eligible validity, deltas/intervals, exclusions, caveats, Markdown/JSON result generation. Charts are projections with full table fallback and no universal score.
  - Dependencies: U1.3.
  - Acceptance evidence: compare DTO exactly matches canonical compare JSON; invalid comparison never shows headline; one-instance/smoke caveats visible.

- [x] `U2.5` Warehouse and run-bundle exports
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: Markdown report, Parquet, DuckDB, public redacted/private bundle, optional comparison inputs, exclusive destination, progress and download.
  - Dependencies: U2.4.
  - Acceptance evidence: real files verify against CLI-generated equivalents; public bundle secret/path negatives; conflict leaves no partial output.

- [x] `U2.6` Permanent private-proof workflows
  - Files: `application/{dto,operations}.py`, `ui/pages.py`, `proof_bundle.py`.
  - Scope: list/inspect roles, export, verify expected digest, import/store, legacy-unverifiable reasons, permanent retention. No delete/replace/TTL.
  - Dependencies: U1.3.
  - Acceptance evidence: source-checkout-removed proof verify/import through real browser; digest-idempotent import; traversal/symlink/hardlink/extra/missing rejects; no `runs.jsonl` replay and no delete control/event.

- [x] `U2.7` Readiness and complete environment surface
  - Files: `application/{dto,operations}.py`, `ui/pages.py`.
  - Scope: benchmark ledgers and links, software/live/readiness separation, blockers/unblock actions, optional-group and harness/runtime presence, doctor rerun. Do not parse prose into a Tier-2 claim or expose secret values.
  - Dependencies: U1.2/U1.3 and U2.3/U2.6.
  - Acceptance evidence: current four Tier-1 benchmarks and no Tier-2 claim match canonical ledger/proof evidence; stale or missing ledgers are explicit.

### U3 — Hardening and launch readiness

**Objective:** make the complete local console secure, responsive, accessible, recoverable, and installable for its actual single-user threat model.

**Exit gate:** scoped `verify-readiness` passes for the local console claim. This does not advance benchmark tiers or prove every external harness.

- [ ] `U3.1` Hostile local-web and artifact suite
  - Files: `tests/ui/security/`, shared redaction/path tests.
  - Scope: Host/Origin/rebinding/iframe/cross-site mutation, capability replay, malformed event payloads, path traversal, symlink/hardlink/FIFO, hostile Markdown/HTML, oversized logs/artifacts, secret names/values, crafted disabled actions.
  - Dependencies: U2 complete.
  - Acceptance evidence: real server/browser attacks fail before side effects; no secret in HTML, logs, downloads, screenshots, or browser storage.

- [ ] `U3.2` Performance and bounded-data proof
  - Files: bounded readers/cursor implementations and `tests/ui/performance/`.
  - Scope: measure startup, Overview, 10k/100k manifest/evidence rows, proof list, artifact metadata, log tail, and concurrent read-only tabs. No database until measurements breach an agreed local threshold.
  - Dependencies: U2.
  - Acceptance evidence: explicit baseline and thresholds in `qa-measure` output; no unbounded DOM/list/file read; performance regression gate for chosen scale.

- [ ] `U3.3` Accessibility and browser matrix
  - Files: all pages/components and `tests/ui/accessibility/`.
  - Scope: complete keyboard journeys, focus/dialog behavior, status messages, zoom/reflow, contrast, reduced motion, chart tables, Chromium/Firefox/WebKit.
  - Dependencies: U2.
  - Acceptance evidence: zero critical/serious automated findings; manual WCAG 2.2 AA checklist for complete flows; screenshots at desktop and tablet.

- [ ] `U3.4` Packaging, upgrade, and failure rehearsal
  - Files: package metadata, README/ops docs, release CI.
  - Scope: clean source/wheel/tool installs, missing extra, occupied port, interrupted process, console restart, canonical corruption, optional harness absence, downgrade/rollback. Core package remains dependency-light.
  - Dependencies: U3.1–U3.3.
  - Acceptance evidence: clean-box install/uninstall; rollback to CLI-only build; full production gate, dependency audit, gitleaks, and scoped readiness PASS.

### U4 — Documentation, distribution, and handoff

**Objective:** make the local console usable without tribal knowledge and keep generated visual/design assets distinct from real screenshots.

**Exit gate:** documented install/use/recovery journeys match shipped bits and a fresh operator completes them. No HITL unless a selected benchmark/runtime itself requires a literal human-only action.

- [ ] `U4.1` Operator and contributor documentation
  - Files: README, `docs/ops/operator-console.md`, architecture, roadmap, contracts, screenshots, optional-extra setup, security/recovery notes.
  - Dependencies: U3.
  - Acceptance evidence: docs commands execute on a clean install; prototype images remain labelled design references and shipped screenshots are captured from the real UI.

- [ ] `U4.2` Release and handoff gate
  - Files: CI/release metadata and final evidence report.
  - Dependencies: U4.1.
  - Acceptance evidence: `make check-production-v1`, UI browser suite, package build/install, dependency/secret scans, local-console `verify-readiness` PASS, and one full uncharged operator journey. External benchmark live proof is reported separately as passed/failed/not run.

### UI later / not now

- Remote or multi-user service, accounts, RBAC, TLS termination, and deployment behind a proxy — reopen concept/architecture first.
- Parallel run scheduling, durable queue, resume-after-process-restart, and notifications — revisit after measured single-run operator demand.
- Database/search index — revisit only after U3.2 shows bounded file readers do not meet real local data volume.
- Config or credential editing, proof deletion/TTL, remote proof store/signing, mobile run launch, weighted portfolios, and new benchmark admission — remain explicit non-goals or separate product decisions.

### Requirement traceability

| Architecture requirements | Roadmap proof |
|---|---|
| AR-01, AR-03, AR-06 official authority/lifecycle/native metrics | R3, R4, R5 |
| AR-02, AR-04 identity and fail-before-charge | R1, R3, R5 |
| AR-05 isolated evidence I/O | R2, R5, catalog-only pre-admission tests |
| AR-07 comparison validity | R1 legacy compare and R3 Terminal-Bench comparison |
| AR-08 budget truth | R0 decision plus evidence/report contracts |
| AR-09 proof-tier separation | proof ledger, R3, R4, R5 |
| AR-10 operator-owned environments | R3/R5 live prerequisites and HITL policy |
| AR-11 dual-use boundary | R6 |
| AR-12, AR-14 portable/permanent proof | R2, R4 transfers |
| AR-13 agent admission | R1 MOMO scaffold gate |
| AR-15 raw history and projection | R1 registry work |
| AR-16 scored-byte retention | R4 GPQA and R5 SWE retained artifacts |
| AR-17, AR-19, AR-21 shared operations/non-authoritative DTOs | U0.3, U1, U2 |
| AR-18 loopback capability boundary | U0.2, U3.1 |
| AR-20 single RunSession/no retry | U0.4, U2.2 |
| AR-22 accessible complete journeys | U0.5, U3.3 |
| AR-23 complete feature coverage | U1–U2, U4.2 |
| AR-24–AR-25 effective access truth | X0.3, X1.1–X1.2, X2.2, X4.3 |
| AR-26–AR-28 relation/identity/official-runner integrity | X0.1–X0.2, X1.3–X1.4, X2.1–X2.2, X3.1–X3.3 |
| AR-29–AR-30 population/report/smoke limits | X0.4, X1.5, X2.3–X2.4, X3.4–X3.5 |
| AR-31 bounded BFCL-first scope | X2, X3, X5 |
| AR-32 study proof portability | X1.6, X2.3–X2.4, X3.5, X4.2–X4.3 |
| AR-33–AR-34 config-first/native model binding | CF1.1–CF1.3, CF2.1 |
| AR-28 registration-only clarification | CF1.2–CF1.3, CF4.1, XG-01 |
| AR-35 genuine agent scoring | CF2.2–CF2.3 |
| AR-36 supported-host preparation | CF3.1–CF3.2 |

### Hot files

- `README.md`, `docs/architecture.md`, `docs/api/internal-contracts.md`
- `config/benchmarks.yaml`, `config/runtimes/{claude-code,codex-cli}.yaml`, `config/agents/`, `config/providers/`, `config/slices/`, `config/models.yaml`
- `src/bencheval/`: `cli.py`, `benchmark_plan.py`, `control_plane_executor.py`, `doctor.py`, registries, `terminal_bench_harbor.py`, `gpqa_adapter.py`, `hle_adapter.py`, `bfcl_native_adapter.py`, `swebench_adapter.py`, `external_agent_adapter.py`, `evidence.py`, `live_run_manifest.py`, `report.py`, `evidence_compare.py`, `export.py`, `run_bundle.py`, `proof_bundle.py`
- Exposure (existing): `access_evidence.py`, `exposure_study.py`, `exposure_selection.py`, `bfcl_study.py`, `exposure_report.py`, `config/studies/`, BFCL Live/derived slices and identity entries
- Config recovery (proposed): `model_binding.py`, `bfcl_package.py`, model/provider/runtime/agent schemas, native launch consumers, and proof/report binding readers
- Pilot: `scripts/run-live-pilot-matrix.sh`, `scripts/doctor-pilot.sh`
- Hygiene: `tests/regressions/test_peer_ship_hygiene.py`

### Live prerequisites and true HITL blockers

| Gate | Status |
|------|--------|
| In-repo implementation (R1/R2 and most of R3/R5) | **Not HITL-blocked.** Implement and run deterministic/local proof directly. |
| Provider credentials | Required for the chosen real inference/judge calls, including BFCL/HLE. Direct Ollama access has been probed; refresh before use and never print keys. Missing/revoked credentials need procurement, while ordinary binding/config repairs are implementation work. |
| Harbor / Docker on dev-box | Required for Terminal-Bench and official SWE evaluation. Probe automatically; ask only if daemon/socket authority requires unavailable administrator action. |
| Runtime authentication | The selected Inspect SWE diagnostic avoids first-party device login. Terminal-Bench runtime auth is probed noninteractively; pause only if the runtime presents device/subscription login, CAPTCHA, or hardware touch. |
| SWE promotion | Explicit later product decision after diagnostic evidence. It does not block implementation or the diagnostic run. |
| Historical BFCL/HLE plans | Historical runs have no pre-launch `run-plan.json`; classify them as legacy/partial. A rerun is required only for a complete new-format proof, not to implement the format. |
| BFCL Live exact wheel data | Required by X0.1 before any Live identity. Verify automatically on dev-box against `gorilla@6ea57973…`; a mismatch stops the route but needs no human action. |
| BFCL exposure provider spend | X2.3/X2.4/X3.5 use the existing admitted provider/model path and explicit run budgets. Probe credentials and model support automatically; only literal device/subscription/CAPTCHA/admin interaction is HITL. |
| Configured BFCL models | CF1 must bridge both native CLI registry lookups and retain the registration identity. The architecture decision is closed; handler-only success is not acceptance, and a key cannot substitute for missing software. |
| Native agent scoring | CF2 implements the selected Harbor interface and official verifier path. MOMO remains scaffold; unknown raw CLI output is not a fallback scorer. Native interface failure requires a bounded spike/result, not false admission. |
| Effective access evidence | No new firewall/proxy service is required. Capture official Inspect config, model-only non-applicability, and Harbor uncontrolled state; unknown remains valid evidence and is not a human blocker. |

No current decision blocker remains. Ordinary missing dependencies, host provisioning, artifact transfer, evidence verification, and credential-presence checks are automatable and must be attempted before reporting a blocker.

---
