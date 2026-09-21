# SEC1.2 — RED specification for the CyberMetric-500 model-only comparison lane

Status: **implemented; bounded software review ACCEPTED 2026-09-21 after three integrated-path rounds (history table below) and one cleanup pass. Not admitted (`executable: false`). Live calls to date: the authorized SEC1.3 qualification packet and the accepted full diagnostic baseline of 2026-09-21 (sections below); no admission, formal comparison or publication has happened or is authorized.**
Basis: roadmap SEC1.1, accepted 2026-09-17 after one correction round (SEC11-F001…F003 closed, N001 corrected).
This document began as the RED packet (contracts, demonstrated RED failures, a declared interface, registration points); the implementation, its review history, and SEC1.3's route qualification and diagnostic baseline are recorded below.

## Ownership boundaries

| Owner | Owns | Does not own |
|---|---|---|
| Review | Whether the pinned protocol is the right measurement, whether a result is interpretable, what a comparison may claim | Module shape, schema names, test structure |
| Implementation peer | Typed surface, pins, attempt loop, retention, refusal behaviour, registration in planner/doctor/executor/catalog | Changing the protocol, the population, the labels, or what a score means |
| Repository owner | Authorization to fetch the snapshot onto a host, to spend, to admit the row, to publish | — |

Out of scope: a generic evaluator framework, a benchmark plugin system, any new runtime or agent integration, a custom judge, a transformed or filtered population, a scorer fork, and any change to historical identities, proofs or locks.

## Frozen parameters

Inputs to this spec, not decisions it may revisit. Every value below was verified independently by both peers during SEC1.1.

| Parameter | Value |
|---|---|
| Population of record | Hugging Face `tihanyin/CyberMetric` (Norbert Tihanyi, the paper's first author) at `32759c2fa90274706219e1cf946cadff93da52e3`, file `CyberMetric-500-v1.json`, `sha256:036747c989da9f38f39a6b33fa2d5ab14147c928df0274217bbecab20be88faa` — byte-identical to upstream GitHub commit `62cc8a9` (2024-12-11) |
| Shape | 500 records × 4 options, keys A/B/C/D 125 each, no duplicate question text, no record identifier |
| License | Apache-2.0, declared by the author in that snapshot's card metadata; rights evidence for those bytes only. The card (`README.md`, `sha256:a63f0b57…`) and the Apache-2.0 text (`sha256:cfc7749b…`) are retained with every run |
| Protocol | `cybermetric-evaluator-v1`: the pinned executable upstream evaluator `CyberMetric_evaluator.py` at GitHub `294662b0…`, `sha256:d73642a3684c2a59a4fe45982e971c4043b3ae4d468334203b929ea2987d8597`, unchanged since 2024-02-15 |
| Prompt | System `You are a security expert who answers questions.`; user `Question: … / Options: A) …, B) …, C) …, D) … / Choose the correct answer (A, B, C, or D) only. Always return in this format: 'ANSWER: X' ` (trailing space retained) |
| Parser | `ANSWER:?\s*([A-D])`, case-insensitive, first match, upper-cased |
| Attempts | Up to **five**; the **first parseable letter ends the loop whether or not it is correct**; `None` after five is scored incorrect and stays in the denominator |
| Generation parameters | None sent — no `temperature`, `max_tokens`, `seed`, `response_format`, `reasoning_effort`; provider defaults apply; no output cap |
| Named deviation | A transport/HTTP failure is classified `remote_infra_failure` and **never silently retried**; upstream swallows exceptions inside the same five-attempt budget. A question the confirmed wall envelope ends — per-instance or run-total — is `runtime_budget_exceeded`, the label the aggregate harnesses stamp when their deadline fires, never an infrastructure claim against the far end |
| Outcome labels | correct → pass; wrong letter → `model_wrong_solution`; five misses → `model_output_invalid` (eligible); transport → `remote_infra_failure` (ineligible); wall envelope exhausted → `runtime_budget_exceeded` (ineligible). `runtime_output_unparseable` is never used for a model's answer |
| Wall envelopes | Both `RunPlan` walls are enforced (architecture §budget truth: wall envelopes are enforceable, dollars are estimates): `max_wall_clock_sec_per_instance` is one absolute deadline over a question's attempts, `max_wall_clock_sec` one over the run; each request is given only what remains, none is started when nothing remains, and a question the run has no room left for is a budget row with zero requests |
| Instance identity | Content-derived: `cybermetric-` + first 16 hex of sha256 over the canonical JSON of `{question, sorted answers, solution}`; never list position |
| Comparison pair (provisional) | `gpt-5.2-2025-12-11` vs `glm-5.2`, both on `bytellm`, `runtime_id`/`agent_id` refused, one `provider_config_hash` |
| Admission | Catalog row `executable: false`; first runs are explicitly diagnostic and never register `passed`; **diagnostic rows never qualify as a model comparison** |
| Cost | Unmeasured: `cost_usd=0.0` with `reported_cost_usd: unavailable`; token usage summed over every attempt and retained |

## Module surface

New, minimal, and typed: `src/bencheval/cybermetric_adapter.py`. It makes chat-completion requests itself — the first in-process model call in BenchEval — because the upstream evaluator is a 90-line script with a hard-coded model and no retained output, so shelling out to it unmodified is impossible and modifying it is a scorer fork. The request path is a stdlib JSON POST to `<base_url>/chat/completions` on the resolved `OpenAICompatibleLaunch`, with **no client-side retry**, behind an injectable `CybermetricRequestRunner` at exactly that boundary (the `GpqaProcessRunner` pattern).

| Symbol | Responsibility |
|---|---|
| `DATASET_PIN`, `ATTRIBUTION_PINS`, `EVALUATOR_SHA256`, `PROTOCOL_ID`, prompt/parser/attempt constants | Reviewed data, restated independently in the contracts so a drifted constant fails |
| `cybermetric_instance_id` | Content-derived id |
| `cybermetric_cache_dir`, `verify_cybermetric_dataset`, `verify_attribution_files` | Host-side snapshot keyed by revision under `BENCHEVAL_CYBERMETRIC_CACHE`; digest-verified before any record is read; card and license verified by digest |
| `cybermetric_benchmark_identity`, `cybermetric_harness_version` | `cybermetric-500@<rev16>+data-<sha16>` and `cybermetric-evaluator-v1@<evaluator sha16>`: captured, non-provisional axes the comparison validator accepts |
| `build_chat_request`, `parse_answer` | The pinned prompt and regex, verbatim |
| `evaluate_question` | The attempt loop under one absolute deadline — `timeout_sec` from the question's start, capped by `run_deadline` (a `time.monotonic()` instant) — handing each request only the remaining allowance, starting none when nothing remains, and retaining without scoring any response that completed after the deadline; one `CybermetricInstanceOutcome` with every `AttemptRecord`, `wall_allowance_sec` and `wall_envelope_exhausted` (`none`, `per_instance`, `run_total`) in its metadata |
| `run_cybermetric_slice` | One outcome per planned instance in plan order under `timeout_sec` per question and `run_wall_sec` for the run, counted from the call; refuses instances outside the verified dataset; retains `cybermetric/attempts/<id>.json` per question (an empty list for a question never launched) and `cybermetric/README.md` + `cybermetric/LICENSE-2.0.txt` under the run, all referenced from `artifact_paths` |
| `default_request_runner` | The real transport: one stdlib JSON POST to `<base_url>/chat/completions` with `Authorization: Bearer <credential>` from the launch environment, a body of exactly `model` and `messages`; decodes `choices[0].message.content`, the response's own `model` (never the request's echoed back) and `usage`; any failure — HTTP status, network, deadline, non-chat envelope — is one `CybermetricTransportError` after that one request, with no client-side retry and no credential in the error text; the allowance bounds the **complete exchange** (a watchdog shuts the socket down at the absolute deadline, however much progress the far end is making), and its expiry is the `CybermetricDeadlineError` subtype, so the loop can tell the envelope from the far end. Direct `http.client`: no proxy resolution and no redirect following exist on the path. Refuses to run without the credential; an injected runner needs none |

### Registration points (implemented 2026-09-18)

- `domain.py`: `HarnessKindLiteral` gains `cybermetric-native`.
- `benchmark_plan.py`: `_MODEL_ONLY_HARNESSES` and `_ADAPTER_TO_OFFICIAL_RUNNER["cybermetric"] = "cybermetric-native"`, so the planner refuses `--runtime` and `--agent` for the lane with its existing model-only wording; `cybermetric` joins the adapters whose `max_cost_usd` is an unenforced estimate.
- `doctor.py`: a `cybermetric-native` preparation recipe (`uv sync`; the lane needs no eval extra), `_BACKEND_BY_HARNESS` entry, and a `cybermetric_dataset` check that fails closed when the cache is unset, the revision directory or file is absent, or any byte of the dataset or the two attribution files drifts from the catalog row's pin; the existing `provider_credentials` check applies.
- `control_plane_executor.py`: `cybermetric` in `_DIAGNOSTIC_CAPABLE_ADAPTER_IDS` and in the model-only set; one new injection kwarg `cybermetric_request_runner`; `_execute_cybermetric` runs the doctor (real transport only), the endpoint guard, the pinned-dataset verification and the planned-membership check **before any output is reserved**, then builds rows through `_evidence_from_scored_instance` with `backend: local`, `token_usage`, no `verifier_log_path` (the verifier is a BenchEval reimplementation, never `native`), `harness_version` and `benchmark_version` captured from the adapter. The model-only agent refusal now precedes the agent-binding gate, because the adapter property, not the agent's binding state, is the reason.
- `config/benchmarks.yaml`: row `cybermetric-500`, `category: cybersecurity`, `tier: calibration`, `contamination_risk: high` (public since 2024), `adapter_id: cybermetric`, `executable: false`, `task_count: 500`, `identity` = `DATASET_PIN`, `default_slice: cybermetric-500-v1`.
- `config/slices/cybermetric-500-v1.yaml`: `fixed_instance_ids` of all 500 content ids, derived through the adapter's own verifier from the digest-verified pinned bytes (answer key 125/125/125/125), `purpose: model_comparison`, `invalid_for: [benchmark_native_claim]`, `contamination_warning: true`, 120 s per-instance wall (each question's absolute deadline over its attempts; the planner's run-total wall is 500 × 120 s), `max_total_cost_usd: 25` as a planning envelope only.
- `docs/ops/benchmarks/cybermetric-500.md` and the ops index row.
- Binding at launch (the existing CF1 guard, no new mechanism): `run_cybermetric_slice` resolves the launch for `plan.provider_id`, calls `require_snapshot_endpoint(plan.model_binding_snapshot, base_url=launch.base_url)` before any request or artifact, and sends the snapshot's `api_model`, never `plan.model_id`; the executor runs the same guard before any output is reserved and stamps `model_binding_sha256` on every row. A run that discarded the snapshot, or an endpoint override that changed after confirmation, is refused with zero requests.
- Fixture discipline, applied (the X6.3 F005 lesson, and review round 1 F002): every slice-run and executor contract plans through the unmodified `plan_control_plane` over a copied bundle whose only deltas are the synthetic dataset digest, the admission flag, and a fixture slice `cybermetric-fixture-8` naming the eight synthetic content ids under `purpose: model_comparison`. Nothing on a plan is edited afterwards except in two deliberately mutated negative cases (a foreign instance id; an agent id the planner itself refuses). Until the catalog row and the harness registration exist, these contracts fail at the bundle or the planner — RED for the registration's absence, never green by relabelling.

## Contracts (written RED first)

`tests/specs/test_cybermetric_contracts.py`, 56 cases at RED (63 after the three integrated-path review rounds below). Only the dataset is synthetic — eight questions in the pinned schema about a fictional system — the scripted runner returns fixed texts (or, stalled, only its deadline), and a loopback HTTP server on 127.0.0.1 stands at the far end of the production transport, holding each reply for a scripted delay where a contract needs one; the id rule, pins, launch resolver, binding snapshot and endpoint guard, planner, executor, evidence model, comparison validator and both attribution files are real. `SUBSTITUTE_JUSTIFICATION` is in the module docstring.

### 1. Dataset identity and content-derived ids (11)

Digest verified before records are read; schema refusals (no solution, three options, solution outside A–D, five options); duplicate question text refused; ids survive reordering and change exactly one when one option changes; cache keyed by revision; attribution verified by digest; identity strings captured, not provisional.

### 2. Protocol fidelity (11)

The request is the pinned prompt verbatim with empty parameters; the parser agrees with the upstream regex on a ten-string corpus whose expected values are hard-coded — including `The ANSWER is D → None`, `ANSWER: E → None`, and first-match-wins.

### 3. The attempt loop (8)

Correct first answer → one attempt; first parseable wrong answer ends the loop and a scripted correct third answer is never requested; five misses → eligible `model_output_invalid`, exactly five requests; transport error → ineligible `remote_infra_failure`, no further request; usage and latency summed over every attempt; every attempt resends the same parameterless request; served model retained per attempt; a correct answer that arrives after the allowance is retained in the attempt record with its usage and parse but is `runtime_budget_exceeded`, never the question's answer, never eligible (review round 2).

### 4. The transport (5)

The production `default_request_runner` against a loopback endpoint: exactly one POST to `/v1/chat/completions` carrying `Authorization: Bearer <credential>` and a JSON body of exactly `model` and `messages` (no generation parameter can hide there), the envelope decoded as sent with the served model read from the response — the server names a different model than the request so an echo is caught — and no credential in the decoded payload; then three failed exchanges (HTTP 502, a 200 that is not a chat envelope, a stalled server past a one-second deadline), each one typed `CybermetricTransportError` after exactly one request received — no hidden retry — with the credential absent from the error text; the stalled case's error is the `CybermetricDeadlineError` subtype; a close-delimited reply (no `Content-Length`) inside the allowance decodes normally — the within-budget control for the round-3 cutoff contract.

### 5. The slice run (6)

One outcome per planned instance in plan order; attempts and attribution retained under the run and referenced from every outcome; a planned instance outside the verified dataset is refused; every request carries the snapshot's `api_model` and is handed the snapshot's route (planned as `gpt-5.2-2025-12-11-FC`, the shipped row whose vendor API name `gpt-5.2-2025-12-11` differs from its logical id, so a discarded snapshot is visible); an endpoint override that changed after planning is refused by the existing guard before any request, with no artifact directory created; under a 1 s per-question wall and a 1.5 s run wall against a far end that never answers, the first question gets the whole per-question wall, the second only what the run has left, and the third is a `runtime_budget_exceeded` outcome with zero requests and an empty attempts file (review SEC12-IMPL-F001).

### 6. Registration (7, incl. one host-asset skip)

Catalog row pinned and non-executable; slice pins 500 content ids for `model_comparison`; slice ids equal the pinned dataset's ids when the snapshot is on the host (skips otherwise, the `bfcl_eval` precedent); the real planner produces the lane model-only; runtime and agent refused *because* the lane is model-only — an unknown-benchmark refusal does not satisfy it; doctor fails closed without the dataset or the credential.

### 7. Executor (13)

One scored row per question with honest labels (no `native` verifier, `diagnostic` interpretation, unmeasured cost, summed usage, captured identities, attribution in `artifact_paths`); a transport failure is ineligible and the correct answer is never requested afterwards; requests carry the confirmed API name on the confirmed route while rows carry the logical id and the binding digest; an endpoint changed after planning is refused with zero requests, no evidence file and no artifacts tree (nothing reserved); with no runner injected, every question reaches the confirmed loopback endpoint through the production transport as one bearer-authenticated POST of `model` and `messages`, rows are scored from the server's answers, the served identity is retained as the server named it, and no retained byte — evidence, frozen plan, attempts — contains the credential; through the real planner, doctor, executor and transport under a 1 s per-question wall over two questions, a loopback far end holding every reply 0.6 s and answering only on the fifth yields two ineligible `runtime_budget_exceeded` rows and no pass, every request starts inside the run's 2 s deadline and the run ends with it (review SEC12-IMPL-F001); through the same real path under a 1 s wall, a far end whose status line comes after 0.6 s and whose body follows 0.9 s later, one that trickles a valid body 16 bytes every 0.4 s, and one whose close-delimited body (no `Content-Length`, so the cutoff is a normal EOF, not an exception) follows the status line too late, are each cut off at the deadline — one request, an ineligible `runtime_budget_exceeded` row, no content retained, the run over within the wall plus 0.4 s — although every single wait was inside the wall and the answer being sent was correct (review round 2); an agent is refused; a non-diagnostic run is refused while the row is not admitted; **diagnostic rows never qualify as a model comparison**; admitted runs on one route do — proved through a copied config bundle whose only further delta is `executable: true`.

## RED status, as run

Focused module at RED: **53 failed, 2 passed, 1 skipped** (48 `NotImplementedError`, 2 missing-catalog-row, 3 wrong-reason refusals; the passes are pin guards, the skip the host-asset case, no `xfail`). Full suite over the exact tree (`sha256:87799cc2…`): 1,599 collected, the same 53 failures by name, nothing else red. JUnits at `~/BenchEval-exposure/results/sec12/r1/`.

## Discrimination, measured both ways

A disposable reference implementation (never committed) passed every contract except the twelve that need the registration points; each single-rule cheat below was caught, and none turned an honest-RED contract green:

| Wrong implementation | Contracts that catch it |
|---|---:|
| Keeps sampling after a wrong parseable answer (retry until correct) | 2 |
| Five misses labelled `runtime_output_unparseable` (silently leaves the denominator) | 1 |
| A transport error consumes an attempt and the loop goes on | 1 |
| Token usage of the final attempt only | 1 |
| The README's XML prompt instead of the evaluator's | 1 |
| Six attempts instead of five | 1 |
| Instance ids from list position | 2 |
| `max_tokens=16` sent | 1 |
| Dataset digest never checked | 1 |
| **The default transport always raises** (the reviewer's F001 probe) | 4 |
| **The slice run discards the binding snapshot** (the reviewer's F002 probe) | 2 |
| The slice run never checks the launch endpoint against the snapshot | 1 |
| The request carries `plan.model_id` instead of the snapshot's `api_model` | 1 |
| The transport retries an HTTP failure up to three times | 1 |
| The wire body carries `temperature: 0` | 1 |
| POST to `<base_url>/completions` | 1 |
| The served model is the request's model echoed back | 1 |
| The transport error text includes the `Authorization` header | 3 |

## Implementation and review history

Scope stayed as handed off: the declared adapter, the registration points above, the existing binding and evidence mechanisms, `executable: false`. Each round's repair is in the code and contracts; the numbers below come from the retained JUnits and gate logs under `~/BenchEval-exposure/results/sec12/<round>/`.

| Round | Finding | Repair | Gate (dev-box, exact tree) |
|---|---|---|---|
| RED review 1 (09-17) | F001 transport untested; F002 requests not bound to the confirmed model/endpoint | loopback contracts on the production transport; fixtures plan through the unmodified planner over `gpt-5.2-2025-12-11-FC`; endpoint drift refused with zero requests | `r1`: 1,599 collected, 53 RED by name |
| Implementation (09-18) | — | adapter, registrations, catalog row, 500-id slice, ops doc; N001 (valid delayed envelope) | `impl`, `e063bdb8…`: 1,596 passed, gate green |
| Integrated review 1 (09-18) | IMPL-F001 wall envelope unenforced; IMPL-F002 formatter rewrote 23 fixtures and the pinned card | absolute deadlines through the attempt loop, `runtime_budget_exceeded` rows; fixtures restored byte-for-byte from `HEAD` and the SEC1.1 copy, protected via `.editorconfig`, `.prettierignore` and pre-commit excludes | `r2`, `7b3b7562…`: 1,598 passed, gate green |
| Round 2 (09-20) | a socket timeout bounds each wait, not the exchange | direct `http.client` under a watchdog that shuts the socket at the deadline; late responses retained, never scored | `r3`, `b0675b39…`: 1,601 passed, gate green |
| Round 3 (09-21) | close-delimited cutoff surfaced as normal EOF and was labelled `remote_infra_failure` | watchdog expiry authoritative after the read too | `r4`, `a3ee13f9…`: 1,603 passed, gate green; module 62 passed, 1 skipped |

Not done, by scope: no live call, no fetch of the snapshot onto an execution host, no admission, no served-model interpretation.

## Open conditions carried from SEC1.1 — route qualification (2026-09-21)

The authorized SEC1.3 qualification packet (two pinned questions per model, diagnostic, `~/BenchEval-exposure/results/sec13/`) settles three of the four:

| Condition | Result |
|---|---|
| `glm-5.2` service | The configured route answers: two correct first-attempt answers, 8.6 s and 3.3 s |
| Request compatibility | Both routes accept the parameterless request and return a chat envelope with `usage`; both answered `ANSWER: X` first time. `glm-5.2` reported 478 completion tokens against gpt-5.2's 14 for equally short visible answers — consistent with reasoning accounting, but the retained attempts hold aggregate usage only, no reasoning breakdown or invoice |
| Served-model identity | Observed aliases: `ptu_495` for `gpt-5.2-2025-12-11`, `glm-5.2-bytedance` for `glm-5.2`. They disprove literal equality with `api_model` as a drift rule. The gateway's registry (read through operator access on the host) routes `gpt-5.2-2025-12-11` to the Azure deployment `azure5.2_20251211` via its responses adapter — `ptu_495` is that deployment's echoed id, ignored by the gateway's cost accounting — and `glm-5.2` to upstream `glm_5.2` (China model-hub route, reasoning model). An expected-string check per route would detect a label change, not prove identity. Retained, not enforced |
| Gateway price | Reference rates from the gateway's `config/model_pricing.yaml` (operator access): gpt-5.2 $2.5 / $15 per 1M in/out, glm-5.2 $1.40 / $4.40, reasoning tokens billed inside output. The packet's 851 reported tokens are ~$0.0030 at those rates — an estimate, not an invoice; the gateway's billing endpoints refuse the inference key. 500-question projection: ~$0.16 / ~$0.59 at one attempt each ($0.75 combined), ~$0.81 / ~$2.95 if every question took five attempts at the same per-attempt usage ($3.76 combined) — a scenario, not a ceiling: five attempts bound the request count, not output tokens. The slice's $25 is a planning envelope, not an enforced cap |

## Full diagnostic baseline (2026-09-21)

Review disposition GO, forwarded by the owner; **accepted by review the same day as a completed diagnostic baseline** (digests, population, scores and usage re-checked on the host) and preserved unchanged. The pinned population once per model on `dev-box-cpu` (gated subset `c2f95fc1…`, the pilot's tree), protocol and walls unchanged, both runs concurrent. Records: `~/BenchEval-exposure/results/sec13-baseline/` (`manifest.json`, per-model `evidence.jsonl`, `artifacts/run-plan.json`, every attempt, card and license, config bundle, tree digest).

| Outcome across the same 500 questions | `gpt-5.2-2025-12-11` route | `glm-5.2` route |
|---|---|---|
| Run | `run-20260921-045159-275967-82edd2c1` | `run-20260921-045159-236020-ea7742c6` |
| **Correct within the configured wall** | **480 / 500 — 96.0%** | **483 / 500 — 96.6%** |
| Wrong answer (`model_wrong_solution`) | 20 | 14 |
| Wall exhausted without a scored answer (`runtime_budget_exceeded`, ineligible — not relabelled, not rerun) | 0 | 3 — the 120 s per-question wall ended the exchange mid-generation; retained with empty content and empty usage |
| Eligible rows | 500 | 497 (483 / 497 = 97.2% is conditional on that population and is not the headline) |
| Attempts | 500, all parsed first time | 501: one question needed attempt 2 (bare `A`, then `ANSWER: A`) |
| Transport / final parse failures | 0 / 0 | 0 / 0 |
| Latency mean / median / max | 1.8 s / 1.4 s / 27 s; 15 min wall | 7.6 s / 3.7 s / 120 s; 63 min wall |
| Tokens prompt / completion | 51,471 / 3,500 | 53,342 / 183,618 |
| Reference-rate estimate from observed usage | $0.181 (projection $0.16) | $0.883 (projection $0.59; completion ran 367 per question against the pilot's 239 — noted, not acted on) |
| Served-model labels | the requested model served through the observed ByteLLM route; seven upstream deployment labels retained per attempt (`openai006gpt52` 229, `ptu_641` 90, `ptu_645` 71, `ptu_495` 50, `ptu_653` 43, `deployment-gpt-5.2-2025-12-11-global` 11, `ptu_642` 6) — label variation, not seven models nor proof of identical weights | `glm-5.2-bytedance` on every answered request |

Paired outcomes on the 497 questions eligible for both: both correct 468, GPT alone 9, GLM alone 15, both wrong 5; GPT answered all three GLM wall-cut questions. An exploratory exact paired test gives p ≈ 0.31 — a post-hoc descriptive check, not an admitted comparison or evidence of equivalence; no superiority claim follows. The narrow conclusion: GLM returned three more correct answers across the 500 assigned questions, while the GPT serving configuration was substantially faster and consumed far less reported output.

Cost: baseline $1.064, SEC1.3 cumulative ~$1.07 — reference-rate estimates from observed usage; timed-out usage and the billed total are unverified; inside the $25 planning envelope. Diagnostic accuracy under these two serving configurations on a public, contamination-flagged dataset — not general cybersecurity skill, not contamination-free capability, not a formal comparison; the catalog row stays `executable: false`.

## Explicit non-claims

The RED packet measured nothing; the diagnostic baseline above measures answer accuracy under two serving configurations and nothing more. Neither establishes either model's practical security skill, general capability, contamination resistance or cross-product superiority; the baseline does not admit the benchmark, make its rows comparison-eligible, authorize publication, or reopen X6.1–X6.3 or bear on X6.4. The three wall cuts stay ineligible and are not rerun.
