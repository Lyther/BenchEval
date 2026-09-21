# X6.2 — RED specification for the qualified BFCL repeat protocol

Status: **ACCEPTED by independent review on 2026-09-16 as a RED specification. X6.3 has since implemented it — see §X6.3 at the end; the RED record below is retained exactly as reviewed and was not edited to match the implementation. Nothing is frozen for a charged run and nothing is authorized to spend.**
Date: 2026-09-15. Method and parameters: [`bfcl-repeat-protocol.md`](bfcl-repeat-protocol.md), §X6.1 accepted by independent review on 2026-09-15.
This packet delivers executable contracts, their demonstrated RED failures, declared interfaces carrying no behaviour, and ownership boundaries. Production implementation is X6.3; a reviewed execution record and paid execution are separate boundaries after it.

## Ownership boundaries

| Owner | Owns | Does not own |
|---|---|---|
| Design/review | The method, design parameters, effect target, failure policy, and whether a result is interpretable | Module shape, schema names, test structure |
| Implementation peer | Typed surface, identity and binding mechanics, RED contracts, refusal behaviour | Changing any design parameter, relaxing a target, deciding what a p-value means |
| Repository owner | Authorization to spend, to publish, and to create the new 400-case identity | — |

Out of scope for X6.2 and for X6.3: a scheduler, a generic transform framework, a second route, a report engine, a new evidence store, a copied validation implementation, silent extension of a legacy schema, documentation or checkbox tests, and any change to historical identities, proofs or locks.

## Frozen design parameters

These are inputs to the spec, not decisions it may revisit.

| Parameter | Value |
|---|---|
| Population | 400 cases, the full two-category source population (200 `multiple` + 200 `parallel_multiple`) |
| Blocking | 40 blocks of 10, hash-rank partition under a blocking seed distinct from the cohort/treatment seed |
| Rounds | 1 |
| Arms per block | 3 — **A** canonical anchor, **B** fixed treatment, **C** canonical repeat |
| Runs | 120 ordinary runs, 1,200 logical case attempts, one proof per run |
| Planning effect | **+8 percentage points**; the original +5-point target is **recorded as unmet** |
| Alpha | 0.05, two-sided, no second primary |
| Failure policy | Existing strict infrastructure-failure invalidation, unchanged |
| Route | `gpt-5.2-2025-12-11-FC` on `bytellm`, fixed-treatment boundary unchanged |
| Identity | A separately versioned 400-case selection/slice/study identity; historical identities and locks untouched |

Precision wording that must appear verbatim in any report this path produces: five points is a **median planning half-width in the evaluated scenarios**, not a promise about the interval produced. An imprecise or nonsignificant result is reportable and inconclusive, and never authorizes replacement attempts.

## Module surface

New, minimal, and typed. No module below may import a second provider, spawn a scheduler, or write outside its own run-owned tree.

| Module | Responsibility |
|---|---|
| `exposure_protocol.py` | Protocol and schedule identity: cohort binding, block partition, balanced assignment draw, frozen protocol record, refusal of post-hoc edits |
| `exposure_repeat.py` | Analysis semantics: three-arm estimand, constrained randomization test over the actual assignment space, observable interval |
| `stats.py` | Reused unchanged for existing interval/test helpers; no fork, no reimplementation |
| `cli.py` | `bencheval study protocol <protocol-id> --blocking-seed <seed> --output <path>` and `bencheval study protocol-verify --lock <path> --proofs <dir> [--output <path>]`, under the existing `study` group; no new top-level group |
| `proof_bundle.py`, `run_isolation.py`, `identity_strings.py` | Reused for inventory-bound proof reads, no-follow regular-file reads, and identity strings |

### Typed records

```text
ProtocolManifest   protocol_id, study_id, selection_sha256, source_population_sha256,
                   blocking_seed, blocks, per_block, rounds, alpha,
                   planning_effect_points, unmet_effect_points, failure_policy,
                   route_identity, partition_sha256, schedule_sha256
BlockPartition     block_id, ordered instance_ids, stratum counts, partition_sha256
SlotAssignment     block_id, round_index, arm -> chronological slot, z (+1 when B is slot 2)
ProtocolSchedule   ordered slots, assignment draw seed, allocation_space_size, schedule_sha256
ArmRunRef          block_id, round_index, arm, run_id, proof_id, evidence_sha256,
                   failure_label (None unless the run itself failed)
RepeatEstimand     v_count, r_count, mean_d, outcome_table (all eight A/B/C cells)
ProtocolReport     payload, to_json(), sha256
RandomizationResult statistic, reference_method ("exact-counting"), allocation_space_size,
                   at_or_beyond, p_value
BlockInterval      centre_points, half_width_points, block_count, degenerate
```

A new lock schema **`exposure-protocol-lock-v1`** binds the protocol manifest, the partition, the schedule, all 120 `ArmRunRef` entries, and the exact report bytes. The existing two-proof `exposure-study-lock-v1` is **not extended, not versioned up, and not touched**; historical locks must continue to verify byte-identically through the existing reader.

### The reference distribution is counted, not sampled and not enumerated

Round 1 of review was right that 137,846,528,820 allocations do not have to be visited, and that sampling is therefore not forced. For balanced `z`,

```text
T(z) = sum_j z_j e_j = 2 * sum(selected e_j) - sum(all e_j)
```

so the whole distribution follows from the number of `B/2`-element subsets producing each subset sum. A dynamic program over `(selected so far, running sum)` retains **every allocation's multiplicity** in integers. Measured on this machine: a forty-block distribution takes **0.7–14 ms**, it reproduces exhaustive enumeration on 100 random cases with zero mismatches, and it returns exactly `2/137,846,528,820` on the forty-block extreme. Two rounds, if ever adopted, are the convolution of two counted distributions and reproduce the 36-assignment product space exactly.

Consequences the implementation must honour: `reference_method` has the single permitted value `"exact-counting"`; the p-value is the plain fraction with no `+1` correction; and there is **no reference-draw count and no reference seed** anywhere in the production path. The seed for the actual experimental assignment is a different thing and remains required. Only the selected one-round design is built; no second sampled implementation is written for a hypothetical future shape.

## Contracts and their intended RED failures

Every contract is a behavioural test against real code paths. Substitutes remain diagnostic only and require a `SUBSTITUTE_JUSTIFICATION` block. Two spec modules: `tests/specs/test_exposure_protocol_contracts.py` (P, E and CLI series) and `tests/specs/test_exposure_repeat_analysis_contracts.py` (A and O series).

### 1. Protocol and schedule identity

| ID | Contract | Intended RED failure today |
|---|---|---|
| P-01 | The partition of 400 ids into 40 blocks of 10 is exact, disjoint, stratum-balanced, and reproducible from the blocking seed alone | declared interface raises `NotImplementedError` |
| P-02 | The blocking seed is distinct from the cohort/treatment seed, and blocking never selects, drops, reorders within a case, or transforms a question | declared interface raises `NotImplementedError` |
| P-03 | The balanced assignment is drawn once, recorded with its seed and space size, and a redraw after any outcome is refused | declared interface raises `NotImplementedError` |
| P-04 | Editing the retained schedule — reordering slots, swapping an arm, changing a block's ids — is refused with an identity mismatch, not silently accepted | declared interface raises `NotImplementedError` |
| P-05 | Each of the 120 slots resolves to a distinct run id and a distinct proof id; A and C sharing a proof id is refused | declared interface raises `NotImplementedError` |
| P-06 | A protocol manifest naming a stale study, selection, route binding, or source-population digest is refused before any run is planned | declared interface raises `NotImplementedError` |
| P-07 | The manifest records the planning effect as 8 points and the 5-point target as unmet; neither is derived from observed data | declared interface raises `NotImplementedError` |

### 2. Analysis semantics

| ID | Contract | Intended RED failure today |
|---|---|---|
| A-01 | `D_i = V_i − R_i` with `V_i = 1[A_i ≠ B_i]`, `R_i = 1[A_i ≠ C_i]`, computed against the **shared** anchor; substituting a per-arm anchor changes the answer and is refused | declared interface raises `NotImplementedError` |
| A-02 | The full eight-cell A/B/C table is reported alongside `mean(D_i)`; a report omitting either is refused | declared interface raises `NotImplementedError` |
| A-03 | The randomization unit is the block. A case-level permutation, or a test treating 1,200 attempts as 1,200 independent questions, is refused | declared interface raises `NotImplementedError` |
| A-04 | The reference set is the balanced allocation space of the **actual** block count, computed **exactly by counting**. At 40 blocks that space is 137,846,528,820 and `allocation_space_size` must equal it | declared interface raises `NotImplementedError` |
| A-05 | `reference_method` is `"exact-counting"` — the only permitted value. No sampled distribution may be produced, and none may be described as enumerated | declared interface raises `NotImplementedError` |
| A-06 | The p-value is the plain fraction `at_or_beyond / allocation_space_size`; no conservative `(hits+1)/(draws+1)` correction, no reference-draw count, no reference seed | declared interface raises `NotImplementedError` |
| A-07 | The interval is **frozen**, not left open: inputs are the observable slot differences `e_j` returned to the assigned frame, normalized as `b_j = z_j · e_j / (per_block · rounds)`; the centre is `mean(b_j)`; the spread is the sample standard deviation with `ddof = 1`; the half-width is `t(0.975, B−1) · sd / sqrt(B)`; both are reported in percentage points; a zero-variance cohort yields a degenerate interval of half-width zero, flagged rather than raised. A latent per-block quantity the analyst cannot see is never an input | declared interface raises `NotImplementedError` |
| A-08 | The report separates the **tested null** (sharp: no order effect on any case) from the **estimated quantity** (the cohort average effect), and states that exactness for the first is not validity for the second | declared interface raises `NotImplementedError` |
| A-09 | Interval output carries the median-planning-half-width wording, not a precision promise | declared interface raises `NotImplementedError` |

### 3. Evidence integrity

| ID | Contract | Intended RED failure today |
|---|---|---|
| E-01 | The population is exact: a missing, duplicate, or foreign instance id anywhere in the 120 runs invalidates the primary population | exists per run, absent across a 120-run population |
| E-02 | Any inference failure, provider or harness error, binding drift, or missing proof invalidates the primary population and stops further scheduling; none of it may be scored as model behaviour | exists per run, absent across a 120-run population |
| E-03 | `exposure-protocol-lock-v1` binds the manifest, partition, schedule, all 120 proof references, and the **retained report payload** beside its digest, so lock plus copied proofs reproduce the report after the working tree is gone; a lock missing any slot is refused | declared interface raises `NotImplementedError` |
| E-04 | Round trip: build the report, lock it, copy the 120 proofs, verify, and require a file to be written whose digest equals the locked `report_sha256`. Tampering with one byte of one proof is a refusal | declared interface raises `NotImplementedError` |
| E-05 | Concatenating per-run artifacts into a fabricated aggregate run proof is refused; each slot keeps its own `private_proof_v1` object | declared interface raises `NotImplementedError` |
| E-06 | Every retained `exposure-study-lock-v1` file still verifies byte-identically through the unchanged existing reader, and its bytes are unchanged before and after | **expected green** — regression guard for the new schema |
| E-07 | A diagnostic or availability record can explain an invalidated population but may never carry a successful research headline or register `passed` | declared interface raises `NotImplementedError` |

### 4. Numerical oracle families

Four families, one per defect that every other check in X6.1 passed. Each is a fault-discriminating test, not a test of this document.

| ID | Oracle | Asserts |
|---|---|---|
| O-01 | **Assignment space.** Counted distribution against exhaustive enumeration on four ten-block cohorts; the degenerate and extreme cases; and the two-round convolution | Counting reproduces enumeration exactly, cell for cell. Zero counts give p = 1; a uniform per-block excess gives p = 2/252 at ten blocks and 2/137,846,528,820 at forty. Convolving two counted per-round distributions equals the exhaustively enumerated 36-assignment product space at **p = 1/18**, and stays distinguishable from the pooled **p = 1/3** that the round-1 probes computed |
| O-02 | **Observable versus latent interval.** `z = (+1,+1,−1,−1)`, latent `D = (3,1,−2,0)`, slot drift `(2,0,0,0)`, so observed `e = (5,1,2,0)` | The observable interval is centre **10.0** points, half-width **46.8443412303**; the latent one is centre **5.0**, half-width **33.1239513442**. Both are computed in the test from exact fractions and a fixed `t(0.975,3) = 3.1824463052837078`. Returning the latent pair is a failing implementation, not a variant |
| O-03 | **Cohort mean and probability constraints.** Any generated or supplied cohort | Every probability lies in [0,1] with `p_plus + p_minus = q_i ≤ 1` and `abs(d_i) ≤ q_i`; every cohort's mean effect equals its declared target. No silent rescaling of `q_i` to admit an effect. This constrains the numerical qualification only — it never requires an observed study result to equal the planning effect |
| O-04 | **Heterogeneous discordance.** The three exact cohorts of 200 cases: 16/16/168 at `(¾,±¾)`/`(0,0)`; 80 at `(.30,.20)` plus 120 at `(0,0)`; 140/60 at `(.20,±.20)` | Effect sd is **30.00**, **9.80** and **18.33** points respectively, with mean discordance `.12`, `.12`, `.20`; the bound is `Var(d_i) ≤ mean(q_i²) − δ²`, which the first cohort attains and which a constant-`q` bound `sqrt(q²−δ²)` understates. Nominal baseline `q`, achieved mean `q_i`, and per-case `q` are reported as distinct fields |

## RED status, as run

The contracts are executable and collected. Declared interfaces exist so that failures are behavioural, not import errors:

- `src/bencheval/exposure_protocol.py` — types plus functions that raise `NotImplementedError`
- `src/bencheval/exposure_repeat.py` — the same
- `tests/specs/test_exposure_protocol_contracts.py` — P, E and CLI contracts
- `tests/specs/test_exposure_repeat_analysis_contracts.py` — A and O contracts

```text
uv run --no-sync pytest -q tests/specs/test_exposure_protocol_contracts.py \
                          tests/specs/test_exposure_repeat_analysis_contracts.py \
                          --junitxml=focused.xml
54 failed, 3 passed
```

Failure identities are retained in the JUnit report: 27 failures in the protocol module and 27 in the analysis module, of which 52 are `NotImplementedError` from the two declared interfaces and 2 are `SystemExit: 2` because `study protocol` and `study protocol-verify` are not yet CLI subcommands. The three passes are deliberate guards over real retained bytes: the CF1.3 two-proof lock still reproduces byte-identically, the old reader still refuses `exposure-protocol-lock-v1`, and the slot fixtures are real `private_proof_v1` objects. There is no reason to manufacture a failure for an unchanged regression.

### Every contract starts from an accepted baseline built from real proof objects

Review round 2 was right that the first draft could be satisfied by a validator that noticed nothing but an empty reference list, and demanded success from inputs that named no proofs at all. Review round 3 was right about something worse: the accepted baseline's "proofs" were two invented files per slot, so the production reader rejected all 120 and the declared evidence digests were digests of labels, not of evidence bytes. A correct implementation reusing the inventory-bound reader would have had to **fail** the positive round trip.

Both are repaired. Every contract now builds one **valid** protocol — 40 blocks, one round, 120 distinct run and proof ids — where each slot is a real `private_proof_v1` object produced by the production `export_private_proof` path, read back through the unchanged `load_verified_proof_inputs` with `require_complete=True` **before** the protocol API sees it. The reference's `proof_id` and `evidence_sha256` are the values that reader returns; the three-arm outcomes behind the report are read off those same verified evidence rows, so the report the lock binds describes exactly the bytes the proofs carry. Negative contracts then mutate exactly one condition, on a copy; the verified population is never edited in place.

No second proof format and no alternate reader were introduced. One guard — `test_slot_proof_fixtures_are_real_private_proof_objects` — checks the inputs without touching the protocol API, so it keeps holding the proof boundary green while the rest of the module is red, and the tamper contract now covers `run-plan.json` and `proof.json` as well as `evidence.jsonl`, which only an inventory-bound read can catch.

### Discrimination, measured both ways

A disposable reference implementation of the declared interface (not `src/`, never committed) answers the two questions that matter about a contract set.

Its verifier reads every slot through `load_verified_proof_inputs` and **recomputes** the report from those verified evidence rows rather than copying the lock's payload, so acceptance means the contracts accept a correct implementation of the agreed proof boundary — not agreement with a substitute format.

**Do the contracts accept correct work?** With every function honestly implemented: **57 passed, 0 failed.** The contracts are satisfiable and do not over-specify.

**Do they reject incorrect work?** Each row swaps in exactly one wrong implementation, everywhere that implementation is reached, leaving the rest honest:

| Cheating implementation | Contracts that catch it |
|---|---:|
| Verifier re-hashes `evidence.jsonl` and copies the report from the lock, never reading the objects through the production proof reader | 3 |
| `verify_protocol_lock` returns `{"ok": True}` and writes nothing | 7 |
| CLI returns `0` without doing anything | 3 |
| Population validator only notices an empty reference list | 9 |
| Estimand always returns `mean_d = 0` with only the observed cells | 4 |
| Randomization test samples 20,000 draws but labels itself exact | 8 |
| Interval drops the assignment and reads `e_j` raw | 3 |

The first row is round 3's finding turned into a permanent contract: it is caught by the two new tamper cases and by the aggregate-proof refusal, none of which the earlier invented-format fixtures could have caught.

A contract that passes on first implementation without ever having failed is not evidence; each red contract must stay red until X6.3 turns it green.

**Branch discipline.** This packet stays off `main`. The repository suite is red while it exists, which is acceptable on a development branch and is not a quality bar to be frozen at any particular number — the RED count changes whenever a contract is added or repaired, and a stale expected count would itself become a way to hide a regression. No `skip` or `xfail` is used to make the suite look green.

**Full suite, with identities retained.** The earlier full-suite claim in this section rested on totals arithmetic against a baseline, which review round 3 correctly refused: totals cannot identify failures, and one unexpected pass paired with one regression leaves them unchanged. The run was repeated with `--junitxml` after the repair:

```text
uv run --no-sync pytest -q --junitxml=full.xml
54 failed, 1473 passed, 1 skipped in 867.53s (0:14:27)
```

Read out of that report rather than inferred: 1,528 cases collected, 0 errors; **all 54 failures are in the two X6.2 modules** (27 and 27), and the failing set is byte-identical to the focused run's. Outside those two modules, 1,471 cases collected, **1,470 passed, 1 skipped, 0 failed** — so nothing else regressed, established by identity and not by totals. The single skip is the browser module where Selenium is absent locally. Every future full gate for this work captures JUnit or an untruncated log; a totals-only record is not acceptable evidence.

## X6.3: the contracts are green against a real implementation

Added 2026-09-16, after this specification was accepted. The RED record above is retained exactly as reviewed; nothing in it was edited to match the implementation.

`exposure_protocol.py` and `exposure_repeat.py` carry behaviour, `cli.py` exposes the two frozen commands, and every contract passes unchanged — **72 passed, 0 failed** (45 protocol, 27 analysis). No contract was relaxed, renamed, skipped or marked `xfail`; the fifteen added since the first submission are qualification boundaries the first submission did not draw — twelve refusals it failed to make, and three cases over evidence it wrongly refused.

### A complete proof is not an eligible one

That distinction is what round 1 of review got right and this implementation had wrong. A complete `private_proof_v1` establishes file integrity and consistency with its own run plan; it says nothing about whether the run belongs in *this* study. Four qualification boundaries were missing, all of them now applied from the two-proof study path's own implementation rather than a second copy:

| Was accepted | Now |
|---|---|
| A complete proof carrying a `remote_infra_failure` row, scored as an ordinary wrong answer, reported `population_valid: true` | The canonical pass-at-k eligibility rule runs on every inventory-bound row; one infrastructure row invalidates the whole primary population |
| Proofs of `kimi-k2.7-code` satisfied a protocol declaring `gpt-5.2-2025-12-11-FC`; a canonical proof substituted into a treatment slot verified | Each arm is bound to its declared benchmark, slice, adapter, harness, benchmark version and native verifier, to the retained plan's population, to the declared route model, and to the study's constant serving axes across all 120 runs |
| Zero retained variant manifests, and the derived resolver only ever offered a 200-id mapping | A treatment slot must retain the variant manifest bound to the measured derived bytes, all 40 must share one, and the mapping must cover all 400 declared cases |
| A lock could assert its own source pins and study digest and still verify | The retained study is checked against its own digest and the retained selection against the **installed catalog's** pinned question files and population anchors |
| A hand-swapped schedule verified on a self-consistent digest, moving the p-value from 3.047e-10 to 5.078e-10 with no new observations | The partition and schedule are replayed from their declared blocking and draw seeds, and the draw seed must be the protocol's |
| A legitimate ten-case block run was refused as a foreign slice, because the arm was matched on the **whole-cohort slice name** | The arm is bound to the population its own retained block plan names: `planned = block = observed`, with the benchmark, serving identity, eligibility and variant checks unchanged |

The last row was a genuine integration defect, not a hardening gap: the protocol consumes **40 ten-case block runs**, each planned through an ordinary BenchEval slice, so a per-block slice id is the normal case and a cohort slice id would never appear on a real run. Matching on the label rejected valid evidence. The binding that replaces it is the population itself — the retained plan's instances must be the block's frozen membership, and the eligible rows must be that same set — which is stronger than a name, because the membership comes from the catalog-bound selection and the label does not. Two regressions hold it: a slot built from an **unmodified `plan_control_plane` result** over a real, distinctly named block slice must verify and reproduce the same report bytes, on both the canonical and the derived side; and an equally real planner result for the *wrong* block, whose plan and evidence agree with each other, must still be refused.

The **400-case mapping** exists without disturbing anything historical. `resolve_derived_source` takes an optional study override, checked exactly as the catalog's own study is, and the protocol study **shares the tool-order treatment seed** — the transform is seeded from it — so the derived bytes are byte-identical to the historical ones (`sha256:c2bb8007…` under both studies, the same digest X6.1 recorded) while the mapping covers 400 rather than 200 cases. The historical derived label `…@derived-703a44fc…` is unchanged; the protocol's is `…@derived-d452135d…`.

### The identity, and what makes it portable

`config/studies/bfcl-tool-order-repeat-400-v1.yaml` plus the record and two exact-id slices that `bencheval study select` materialized from the pinned installed package data through the unchanged selection path. It holds the whole two-category source population (200 `multiple` + 200 `parallel_multiple`), so the `sha256_rank_v1` rank only fixes an order and nothing is dropped. Digests: study `sha256:0017d809…`, selection `sha256:293b7188…`, source population `sha256:d12c0591…`.

The lock retains that study and selection and re-binds both on the way back in, so **portability is not self-assertion**. Demonstrated by deleting the protocol's study manifest, its selection record and both slice files from a copied config bundle, pointing `BENCHEVAL_HOME` at it, and verifying from outside the checkout: `ok`, 120 runs, same report digest.

### Uncharged production-CLI journey

End to end through the console script over 120 real `private_proof_v1` objects built from synthetic outcomes (`SUBSTITUTE_JUSTIFICATION` in the disposable script; it is contract data and never research evidence):

| Step | Result |
|---|---|
| `study protocol … --blocking-seed … --output` | 40 blocks, 40 assignments, manifest `sha256:a90f30db…`; a second write to the same path is refused |
| Library rebuild of the same partition and schedule | identical, to the manifest digest |
| 120 exported proofs | 120 distinct proof ids, each accepted by the unchanged reader |
| Analysis | `v=159`, `r=100`, `mean_d=0.1475`, `p=5.08e-10`, space `137,846,528,820`, `exact-counting`, interval `14.75 ± 3.16` points |
| Proofs copied elsewhere, originals deleted, `study protocol-verify` | `ok`; the written bytes' digest equals the locked `report_sha256` and the built report byte for byte |

Ten refusals, each one mutation from that accepted journey, all nonzero exit: tampered `evidence.jsonl`, `run-plan.json` and `proof.json`; a concatenated aggregate directory; a missing slot proof; a post-hoc schedule edit; a **re-digested** manifest claiming a 3-point planning effect, two rounds, or another route; and a lock carrying the 200-case study's selection record.

### The new guards are proved to discriminate

A disposable probe swaps exactly one rule at a time and measures which contracts notice. Honest implementation: **45 passed, 0 failed**.

| Rule swapped | Contracts that catch it |
|---|---:|
| The reviewed slot loader restored — proof digests and instance ids only | 7 |
| The route, constant-axis and variant binding removed | 4 |
| The retained study and selection re-bound to nothing | 2 |
| The partition and schedule accepted on their digests alone | 3 |
| The whole-cohort slice-name requirement restored — over-refusal, not under-refusal | 2 |

Full gate, round 2: **1,539 passed, 1 skipped, 0 failed** in 14m43s, identities retained in JUnit — 1,540 collected, 0 errors, all 69 contracts green inside it. The skip is the browser module where Selenium is absent locally.

### The exact-tree production gate

Three attempts on the authoring laptop returned three *different* sets of wall-clock failures — 4, then 1, then 8 — while every X6 contract stayed green and run time went from 14m43s to 35m26s. The host was saturated (load average 20–51, an endpoint scanner holding ~520% CPU), and each failure was a deadline assertion: a `p50 < 15ms` plan latency measured at 18.8ms, a 1.0s subprocess timeout, race windows that never landed. That is not evidence of anything, in either direction, so the gate was moved rather than repeated.

The gate was run once on `dev-box-cpu` — 16 cores, load average ~1.0 — over the **exact tree**: 454 source files, `tree_sha256 f88cb4fd…`, computed identically on both hosts and byte-identical, on branch `docs/prospective-repeat-protocol-20260915` at `b42d6b2` with the same 18 dirty entries. `scripts/check-production-v1.sh` ran unchanged.

```text
make check-production-v1
  1541 passed, 1 skipped, 1 deselected in 483.89s (0:08:03)
  coverage TOTAL 14888 statements, 2339 missed, 84% (gate floor 80%)
  ruff check / ruff format --check / shellcheck / bash -n / uv lock --check: passed
  executable_adapter benchmark count = 4; unknown-benchmark run refused before execute
check-production-v1: passed
```

The single deselection is the plan-latency assertion, which `check-domain-coverage.sh` excludes by design so a timing threshold is never measured under coverage instrumentation. It was then measured on its own terms: a separate untouched full run on the same quiet host, JUnit retained, gives **1,542 passed, 1 skipped, 0 failed** — 1,543 collected, 0 errors, all 72 contracts green, and the plan-latency, harness-recapture and no-follow-FIFO tests all pass. The one skip is the browser module where Selenium is absent.

One provisioning fact is worth recording rather than rediscovering: `bfcl-eval==2026.3.23` and `swebench==5.0.1` live in repository-owned **dependency groups**, not extras, so `uv sync --all-extras` leaves them out and `bfcl` identity capture then fails on a missing distribution instead of on the behaviour under test. A correctly provisioned runner needs `uv sync --all-extras --all-groups`.

Still true and unchanged: no paid execution, no freeze of a charged run, no publication, and no historical identity, proof or lock touched.

## Explicit non-claims

This specification does not promise that the study will detect anything, does not establish weak-null or average-effect validity, does not authorize a paid run, does not create the 400-case identity, and does not reopen R5, X4, or any historical study. A no-go result from X6.3 is a completed investigation, not grounds to relax a target or hide an infrastructure failure.
