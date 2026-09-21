# Prospective BFCL tool-order repeat protocol

Status: **PROPOSED; offline design qualification first, not a frozen paid experiment.**
Date: 2026-09-15. Software baseline: merged PR #15, `b42d6b264f5378fa20178eb1cb55e6cd4b5993b1`.
Owners: design/review owns the method; the implementation peer owns the bounded X6.1 investigation, then RED contracts if the design earns implementation. This protocol does not reopen R5/X4, promote a benchmark, or authorize publication or provider calls.

## Decision and question

On a fixed BFCL cohort and one confirmed serving configuration, does a fixed tool-order treatment produce **excess case-level disagreement over an unchanged-repeat control**? A useful positive result would justify retaining a repeat-adjusted sensitivity view and a separately designed replication; it would not justify model ranking, a corrected benchmark score, or a contamination claim. A negative or imprecise result does not demonstrate equivalence or cleanliness.

The next work is method and feasibility qualification, not another automatic 200-case study. The existing two-arm report measures directional pass changes, not the difference between two disagreement rates sharing an anchor. Shared observations must remain paired; McNemar's binary-pair test and its independence assumptions are documented by [NIST](https://itl.nist.gov/div898/software/dataplot/refman1/auxillar/mcnemar.htm). Because treatment order will be assigned by execution block, the primary test below uses that block as its randomization unit instead of treating every case as independently randomized.

## Inputs and identity boundary

The first candidate reuses the existing 200-case cohort and exact treatment bytes, not historical outcomes as a new control. These anchors were checked locally through the real selection validator and inventory-bound proof loader on 2026-09-15:

- Study `bfcl-v4-tool-order-v1`: `sha256:36903ca7afb4a1d94f0bb7c2fecbd174d6ff6c9aa5b353516dad0cbbea25724b`.
- Selection: `sha256:a283dd3fe058006816a5719de601d285976f5c1b1fdd4ce2744e9635d41821c2`, 100 `multiple` and 100 `parallel_multiple` ids, replayed against catalog source-population anchors.
- Combined derived-data identity: `sha256:c2bb8007d09ed5d956dc6f57d11bdcd5545bcb74bead72a530fb7bdab374b0fa`; retained X3 variant manifest file `sha256:33a1b8f84dbac69fee28dac8f424d3d5e6c6dd86581dc4b438b9b68bb3f9193d` in run `run-20260907-052429-563407-be7f87d2`.
- Exact derived files: `BFCL_v4_multiple.json` → `sha256:83d830558e2fa2562177ed1a355983814b07fa384242a60229ecfd07ba0f9bfe`; `BFCL_v4_parallel_multiple.json` → `sha256:922f2585c0ce534e5db5d04aec9b61a4ac4f07051396d56af044f85683f3f71f`.

The candidate serving configuration is the previously exercised `gpt-5.2-2025-12-11-FC` on `bytellm`, with its exact API name, endpoint, registration, provider hash, settings, and current producer digest re-resolved before a future freeze. This is not a claim of current route availability. Do not silently substitute another model or route. Qwen/Ollama is not a second primary in this packet.

**Separate frozen inputs, not a claim of independent legacy seeds.** Cohort selection and treatment are separately referenced content objects. Their v1 provenance still uses the same seed, `bencheval-bfcl-tool-order-v1`; this protocol neither erases that fact nor implements independent rotation-seed generation. It asks about this fixed treatment. A new seed or a 400-case population needs a separately versioned, reviewed identity route; do not edit the current study, catalog reference, selection, derived mapping, or old locks to obtain it. New blocking and order-assignment randomness must not select or transform questions.

## Candidate execution design

*The next two paragraphs state the drafted 200-case shape; the selected parameters are below.* Partition each stratum's selected ids into groups by a retained hash-ranking rule with a distinct blocking seed, and combine equal-index groups into blocks. Every block has the same ordered ids in three fresh logical arms: **A**, canonical anchor; **B**, fixed treatment; **C**, independent canonical repeat. All runs use ordinary BenchEval planning, doctor, generation, official evaluation, and private proof. A and C are distinct runs, not copied results or two names for one proof.

Run A first within each block. Assign B then C or C then B uniformly over the balanced allocations, half the blocks in each order; draw once at freeze, retain the assignment index and full schedule, and never redraw based on outcomes. Blocking reduces time/order confounding; it cannot eliminate hidden provider state or interference. [NIST's block-design guidance](https://www.itl.nist.gov/div898/handbook/pri/section3/pri332.htm) motivates controlling execution conditions and randomizing the remaining treatment order.

The frozen record must include block ids and exact instances, slot order, distinct run ids, slice/plan digests, model/provider/registration/producer identities, generation settings and concurrency, native retry behavior, chronological execution records, and budget basis. Existing per-run proofs remain study-agnostic. Block slices belong to an exclusive prepared work/config tree; never add them to the historical frozen checkout. An uncharged real-planner/installed-package check must establish that block subsets preserve the full pinned treatment identity before implementation is called viable.

**Design selected 2026-09-15 after X6.1 and its review.** The 200-case ten-block shape above is the *drafted* candidate and is not the selected one. The adopted alternative is the **400-case two-category source population, 40 ten-case blocks, one round**, three fresh arms per block — **120 ordinary runs, 1,200 logical case attempts** — with a separately versioned 400-case identity and every historical identity and lock untouched. The repeated-round alternative is not selected; X6.1 found no statistical reason to prefer or forbid it, and one round is the operationally cheaper choice. Repeated cases would not be new independent questions in any case; any future round must preserve the source-id and block/round dependence and draw a fresh balanced assignment per round. No scheduler, generic transform framework, new provider, or runtime/scorer fork is selected.

## Estimand, test, and precision gate

For a valid triple, let `V_i = 1[A_i != B_i]`, `R_i = 1[A_i != C_i]`, and `D_i = V_i - R_i`. Report both disagreement counts, the full eight-cell A/B/C outcome table, and `mean(D_i)`; native pass rates and directional flips remain secondary. No ratio such as historical 18/6 is itself a significance test.

Let `e_j` be the count of anchor disagreements in chronological slot 2 minus slot 3. With `z_j = +1` when B is slot 2 and `-1` otherwise, the observed numerator is `sum(z_j * e_j)`. The reference set is the **actual balanced allocation space**, including the observed one; the two-sided p-value is the fraction with absolute numerator at least the observed absolute value. Integer counts avoid float tie ambiguity.

**How that space is computed is frozen, not left to the implementation — and it is computed exactly.** A ten-block pass has 252 allocations. The selected 40-block design has C(40,20) = 137,846,528,820, which cannot be enumerated but does not need to be: for balanced `z`, `T(z) = 2·sum(selected e_j) − sum(all e_j)`, so counting the `B/2`-element subsets by subset sum retains every allocation's multiplicity in a few milliseconds. The production path therefore uses **exact counting** — no sampling, no Monte Carlo error, no reference-draw count and no reference seed, and the p-value is the plain fraction with no `+1` correction. The seed for the actual experimental assignment is a separate thing and remains required. The sampled allocation matrices in the planning table above are simulation shortcuts, not the analysis. See [`bfcl-repeat-spec.md`](bfcl-repeat-spec.md) for the contract. Do not permute individual cases or substitute the old A/B directional test. With multiple rounds, use the declared within-round assignment space and keep repeated identities clustered; never pretend that the number of runs is the number of independent questions. General paired permutation principles and the need to preserve the assignment scheme are described in the [SciPy reference](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html); this does not add SciPy as a product dependency or claim its default permutation mode implements the constrained design.

The null is treatment/control exchangeability at the assigned slots under the recorded conditions. Interference, route drift, or adaptive scheduling can defeat that interpretation and must be reported, not hidden by a low p-value. Primary two-sided alpha is **0.05**, with no second model/seed/endpoint primary.

**Effect target, settled by X6.1.** The originally proposed smallest useful effect of **+5 percentage points is recorded as unmet** and is not the planning effect: no affordable shape reaches 80% planning power for it. The planning effect is **+8 percentage points**, which the selected design clears at .902 or better in every cell of the declared active-share family. That qualification is scenario-specific, not a universal guarantee, and it does not establish validity for a zero-average-effect null with heterogeneous effects — the test is exact for the sharp null, which is a different statement ([Wu and Ding](https://arxiv.org/abs/1809.07419)).

**Precision wording.** Five points is a **median planning half-width in the evaluated scenarios**, not a promise about the interval this study will produce. The selected design's worst evaluated median is 4.75 points. An imprecise or nonsignificant result is reportable and inconclusive; it never authorizes replacement attempts.

**The interval is settled as of X6.2 and frozen in the spec:** a two-sided 95% t-interval over `b_j = z_j · e_j / (per_block · rounds)`, the observable slot differences returned to the assigned frame, with centre `mean(b_j)`, sample standard deviation at `ddof = 1`, half-width `t(0.975, B−1) · sd / sqrt(B)`, reported in percentage points, and a flagged degenerate interval of half-width zero when the block estimates are identical. Its interpretation stays scenario-qualified: the [NIST t-interval](https://itl.nist.gov/div898/handbook/eda/section3/eda352.htm) requires distributional assumptions, and a few blocks or repeated source cases can make a naive interval misleading. X6.1 must check coverage, within-case/block dependence, discrete/zero-variance cases, and the scope of the population claim. A nonsignificant result or failure to meet precision remains inconclusive, never evidence that the model is insensitive.

## Planning evidence already obtained — not benchmark results

An uncharged calculation on 2026-09-15 modeled independent signed differences with `P(D=+1)=(q+delta)/2`, `P(D=-1)=(q-delta)/2`, otherwise zero. `q` is discordance between V and R, not the provider-error rate. These hypothetical distributions are planning sensitivity cases, not measured LLM behavior or software acceptance evidence.

| Candidate | Planning replicates / allocation calculation | Rejection at delta=0 | Power at +5 points | Power at +10 points |
|---|---|---|---|---|
| 200 cases, 10 blocks, q=.12 | 1,000; all 252 allocations | 2.2% | 32.8% | 95.8% |
| 200 cases, 10 blocks, q=.20 | 1,000; all 252 allocations | 2.6% | 20.6% | 73.4% |
| 400 cases, 20 blocks, q=.12 | 2,000; 1,999 sampled balanced allocations, conservative plus-one p | 3.0% | 74.7% | 100.0% |
| 400 cases, 20 blocks, q=.20 | 2,000; 1,999 sampled balanced allocations, conservative plus-one p | 3.6% | 51.7% | 98.3% |

The first calculation used Python `random.Random(20260915)` reset per scenario; the second used NumPy `default_rng(20260915)`, a shared sampled allocation matrix, and a reset outcome stream per scenario. Maximum Monte Carlo standard errors for these fractions are about 1.6 and 1.1 points respectively; the second calculation also approximates the randomization distribution. The real 20-block test has 184,756 assignments, not 1,999. A zero-count oracle gives p=1 and the most extreme ten-block contrast gives p=2/252. These calculations justify **not freezing either one-pass design at a five-point target**. They do not prove power under provider drift, clustered outcomes, or missing inference; the peer must independently reproduce and extend them in X6.1.

## Failures, retention, and spend

Keep `native_eligible_only` strict. Any inference timeout, provider/harness error, missing or duplicate planned case, binding drift, or missing proof invalidates the primary population. Stop scheduling further block runs after the first completed run revealing such a defect; retain all completed/failed runs and identify unexecuted slots. Do not drop triples, replace them, score infrastructure as model behavior, or retry until a publishable population appears. Native handler-internal retries remain unchanged and recorded; there is at most one BenchEval invocation per declared slot. A plumbing attempt, if later authorized, is separate from the frozen research population and is never pooled into it.

A diagnostic completion/availability record may explain why no inferential report exists; it must not contain a successful research headline. Quantify this operating risk before freeze: under an illustrative independent per-attempt error probability p, a complete M-attempt population has probability `(1-p)^M`. For p=.001, this is about .55 at 600 attempts and .09 at 2,400. Those are not measured route probabilities; a small clean probe cannot establish a rare-error guarantee. Report endpoint stability, latency and all available historical failure evidence, without filtering inconvenient failures or making a paid probe part of the unpaid task.

The prospective study lock must bind the full protocol and schedule, every block/arm/round proof id, retained selection and treatment bytes, and exact report bytes. Verification must work from copied inputs outside the checkout. Reuse inventory-bound readers and `private_proof_v1`; do not concatenate files into a fabricated run proof, embed circular proof ids, weaken the old two-proof lock, or create another store. Original X2/X3/CF1/CF4 reports and locks stay byte-identical.

A **proposed $50 allocation** may be considered within the user's $1,000 campaign ceiling only after the design/review gates; remaining account budget and the current price basis must be checked, not assumed. This document spends nothing and schedules no paid run. Record estimates, returned usage, unknown usage, and provider-metered spend separately. No hard-dollar termination guarantee, automatic expansion, second route, retry campaign, cleanup, or Tier-2 promotion is implied.

## Peer packet and exit

**GO now: X6.1, unpaid investigation only.** Independently reproduce the planning arithmetic; challenge the repeated-round and 400-case alternatives, confidence-interval assumptions, and complete-population operating risk; exercise real planning and installed BFCL loading for block subsets without inference; return one recommendation with frozen-shape candidate counts, expected cost/host effort, exact remaining implementation files, and go/no-go evidence. Do not add source modules, new study identities, or a report engine merely to make a speculative design look implemented. No further acknowledgement-only approval is needed for this investigation.

If that packet passes, X6.2 is `dev-spec` for the minimal typed protocol, exact assignment/analysis, and multi-proof binding; X6.3 implements and verifies those contracts, including unchanged historical reproduction. Statistical code requires independent numerical oracles and fault-discriminating checks, not tests of this document. A reviewed execution record is a separate boundary before any paid X6.4 run. A no-go result is a completed investigation, not authority to relax the target, hide infrastructure failures, or launch a different experiment.

## X6.1 qualification result (implementation peer, 2026-09-15)

**Recommendation: conditional go — but not for either design as written, and not at a five-point target.** Everything below is planning simulation under stated hypothetical models plus real read-only probes; none of it is benchmark evidence about tool-order sensitivity. Artifacts: `power.py`, `power2.py`, `power3.py`, `mde.py`, `blocks.py`, `loader.py` with their JSON outputs, retained beside this record; round 2 adds `power4.py`, `mde2.py`, `usage.py`, `blocks2.py` and round 3 adds `power5.py` and round 4 `power6.py`, with theirs.

### Corrections after review (rounds 2 and 3, 2026-09-15)

Independent review rejected the round-1 method qualification on four calculation and evidence defects, and then rejected the round-2 correction on a fifth. All five reproduce. What was asserted and what replaces it:

| Defect | Withdrawn | Replaced by |
|---|---|---|
| F001 assignment space | The repeated-round comparison, and the conclusion that extra rounds saturate | Fresh balanced assignment per round, product reference space; the comparison is rerun below and its conclusion reversed |
| F002 interval | "The t-interval covered 94–96%" computed from latent counts, and the blanket claim that 400 cases meet the five-point half-width | The estimator the analyst can actually compute, with coverage measured under drift, and half-widths reported per scenario |
| F003 effect target | "Set the smallest useful effect at eight points" | Eight points qualifies only at 2,400 attempts; at 1,200 the qualified target is ten points |
| F004 cost basis | "The retained evidence rows carry no token usage, so the $50 allocation has no measured basis" | The official generation records carry usage for every attempt; the basis is recovered below |
| F005 cohort target (round 3) | Finding 3a's round-driven false positives, the two-round cap, the ten-point target, and "no one-round design meets the five-point half-width" | Effects bounded by each case's own headroom with the cohort mean forced to the target exactly; rejection at a zero cohort mean is flat in rounds and eight points requalifies |
| F006 admissibility bound (round 4) | The `sqrt(q² − δ²)` ceiling, the `q_i >= δ` floor, `share="max"` as the maximum, and every "admissible range" claim | The heterogeneous bound `Var(d_i) <= mean(q_i²) − δ²`, three exact counterexamples as oracles, and results scoped to one named scenario family with nominal, achieved and per-case `q` reported separately |

**F001 is a design substitution, not a rounding error.** `power2.py`, `power3.py` and `mde.py` summed rounds and then drew one assignment, simulating a study that reuses one assignment in every round. `power4.py:counterexample` is an exact, hand-checkable instance: four blocks, two rounds, latent block scores `[[3,1,0,0],[0,2,-1,3]]`, observed statistic 8 either way. The declared per-round design enumerates 36 assignments and reaches 8 twice, **p = 1/18**; the pooled design enumerates 6 and reaches 8 twice, **p = 1/3**. Single-round numbers are unaffected, so the reproduction table above still stands.

The round-1 risk wording was also wrong in three ways, corrected below: 66.3% completion is a **Jeffreys predictive forecast, not measured reliability**; "no design reaches even 50% joint probability" was contradicted by a 50.10% cell in round 1's own table; and "the most likely outcome is an operational invalidation" does not follow from a completion probability above one half.

### The arithmetic reproduces

Independent reimplementation, 4,000 replicates per cell against the 1,000/2,000 above, enumerating all 252 allocations at ten blocks and 184,756 at twenty:

| Design | null q=.12 | null q=.20 | +5pt q=.12 | +5pt q=.20 | +10pt q=.12 | +10pt q=.20 |
|---|---|---|---|---|---|---|
| 200, 10×20 — drafted | 2.6 vs 2.2 | 3.2 vs 2.6 | **31.9 vs 32.8** | **20.7 vs 20.6** | 95.3 vs 95.8 | 73.5 vs 73.4 |
| 400, 20×20 — drafted | 3.3 vs 3.0 | 4.0 vs 3.6 | **74.8 vs 74.7** | **51.2 vs 51.7** | 100.0 vs 100.0 | 99.0 vs 98.3 |

Every cell agrees within Monte Carlo error. The conclusion stands: neither drafted one-pass design reaches 80% at five points. Two numerical oracles hold exactly — a zero-count result gives p=1, and a uniform per-block excess gives p=2/252 for every balanced observed allocation, scale-invariant and antisymmetric.

### Findings that change the design (two retracted across rounds 2 and 3)

**1. Power is set by the number of blocks, not the number of cases.** The randomization unit is the block, so ten blocks means a 252-point reference distribution however many cases sit inside them. Re-cutting the *same* 200 cases as twenty blocks of ten lifts five-point power from 31.9% to 40.7% (q=.12) and 20.7% to 25.9% (q=.20) at identical spend. Use ten-case blocks.

**2. Randomization survives the nuisances; power does not.** At the sharp null — no order effect on any case — rejection stays between 2.5% and 4.6% across all 28 design/nuisance cells, with and without a two-point later-slot drift and block clustering. The test is valid, as blocking intends. Drift still costs real power: at five points and q=.12, 34.1% with drift against 40.7% without at twenty blocks.

**3. Repeated rounds do not saturate — that round-1 finding was an artifact of F001 and is withdrawn.** With the declared per-round assignment space, extra rounds buy very nearly what their attempt count implies. At five points, q=.12, drift and clustering present:

| Design | attempts | esd=0 | esd=10 | esd=20 | esd=30 |
|---|---:|---|---|---|---|
| 200 ×1 (20×10) | 600 | .341 | .304 | .243 | .194 |
| 200 ×2 | 1,200 | .682 | .622 | .505 | .431 |
| 200 ×4 | 2,400 | .951 | .900 | .779 | .672 |
| 400 ×1 (40×10) | 1,200 | .684 | .632 | .511 | .397 |
| 400 ×2 (40×10) | 2,400 | .955 | .915 | .822 | .704 |

At equal attempts the two routes are within a few points of each other at every heterogeneity level, sometimes favouring the repeat. **Round 1's headline comparison — 200 ×4 at .427 losing to 400 ×1 at .438 on half the attempts — was produced by the wrong assignment space and is retracted.** Information gain alone therefore does not justify the 400-case identity change.

The `esd` columns above carry round 2's defective parameterization and its inflated discordance; read them only as an ordering, not as levels. Regenerated with valid probabilities and exact cohort means (finding 3a), the same comparison at a five-point cohort mean gives 200 ×2 at .668 against 400 ×1 at .679 on 1,200 attempts, and 200 ×4 at .952 against 400 ×2 at .956 on 2,400 — the same near-tie, now at valid probabilities.

**3a. Withdrawn in round 3. There is no round-driven false-positive effect, and the two-round cap it produced is withdrawn with it.** Round 2 reported rejection climbing to .151 at four rounds "at a zero mean effect". Review found that the generator never produced one, and the audit is worse than that. Drawing per-case effects from an unbounded Gaussian and then raising `q_i` to `|d_i|` to keep the probabilities nominally legal meant that, in the cell that produced .151:

| Round-2 cell, q=.12, nominal effect sd 30 points | Measured |
|---|---|
| Cohorts with an exactly zero mean effect | **0 of 1,000** |
| Spread of cohort mean effects | sd 2.11 points, central 95% −4.27 to +4.15 |
| Cases whose `q` was silently raised by the clip | **138,816 of 200,000** |
| Mean `q` actually simulated, against the declared .12 | **.264** |
| Probabilities still outside [0,1] | 174 |

So that cell was neither zero-mean nor q=.12. The model's own constraint is `|d_i| <= q_i <= 1`.

**Round 4 correction to the bound round 3 drew from it.** Round 3 wrote the ceiling as `sqrt(q² − δ²)` — 12.0 points at q=.12 — and concluded that 20- or 30-point heterogeneity was unattainable there. That bound holds only when every case shares the same `q`, or when `q` is a uniform upper bound on `q_i`. The simulator draws heterogeneous `q_i`, where the applicable bound is `Var(d_i) <= mean(q_i²) − δ²`, which is far larger. Three exact counterexamples supplied by review, verified here in rational arithmetic:

| Cohort of 200 cases | mean `q` | mean effect | effect sd | probabilities |
|---|---|---|---|---|
| 16 at `(q,d)=(¾,+¾)`, 16 at `(¾,−¾)`, 168 at `(0,0)` | **3/25 = .12** | 0 | **30.00 pt** | all valid |
| 80 at `(.30,+.20)`, 120 at `(0,0)` | **.12** | **.08** | 9.80 pt | all valid |
| 140 at `(.20,+.20)`, 60 at `(.20,−.20)` | .20 | **.08** | **18.33 pt** | all valid |

The first attains the heterogeneous bound exactly and exceeds round 3's by a factor of 2.5, so **"30-point heterogeneity is impossible at q=.12" is false** when `.12` is the cohort's mean discordance. The second carries an eight-point mean effect with 60% of its cases at zero discordance, so **round 3's floor `q_i >= |δ|` was a modelling choice, not a requirement**. The third shows round 3's `share="max"` was not the maximum: at constant `q=.20` and `δ=.08` it produced **11.57 points** against the 18.33 that is attainable, because centre-and-shrink only reaches `d_i` in `[2δ − q_i, q_i]`.

Two reporting gaps followed from the same confusion and are now separated in the retained output: **nominal baseline `q`**, **achieved mean `q_i`**, and **constant per-case `q`** are distinct. Round 3's eight-point q=.12 cell achieved a mean `q_i` of **.1355**, not .12, because of the floor.

Regenerated with effects bounded by each case's own headroom and every cohort mean forced to the target exactly — verified to 2.1e-17 across every cell, with zero invalid probabilities — the rejection rate at an **exactly zero cohort mean** is flat in rounds and never exceeds α:

| Design | attempts | homogeneous | half headroom | round-3 `share="max"` |
|---|---:|---|---|---|
| 200 ×1 (20×10) | 600 | .031 | .033 | .027 |
| 200 ×2 | 1,200 | .034 | .033 | .032 |
| 200 ×4 | 2,400 | .043 | .035 | .031 |
| 400 ×1 (40×10) | 1,200 | .034 | .035 | .031 |
| 400 ×2 (40×10) | 2,400 | .034 | .035 | .029 |

Across all 30 zero-mean cells at both discordance rates, rejection runs .024–.043 and if anything *falls* as heterogeneity rises, which is what the randomization reference should do when it is wider than the observed statistic's own spread. **Rounds do not manufacture false positives on a fixed cohort whose mean effect is zero.** The choice between one and two rounds is therefore operational — runs, proofs and schedule — not statistical.

Round 4 re-ran this under the wider **active-share family** (below), where heterogeneity reaches 44.8 points rather than round 3's 15: rejection at an exactly zero cohort mean stays between **.000 and .043** in all 48 cells and still does not climb with rounds. The withdrawal holds under the corrected bound.

**4. The completeness rule and the power target fight each other.** Measured from the retained raw trees this turn: the proposed route (`gpt-5.2-2025-12-11-FC` on `bytellm`) recorded **zero inference failures in 940 attempts** across X2.4 (340), X3 primary, X3 repeat and X3 variant (200 each). The same detector finds CF4.1's known 10/8/7 timeouts on the Qwen route, so it detects real failures.

A fifth retained run on the same route adds 356 live-category attempts, also with zero inference failures and no missing attempts, so the observed base is **0 failures in 1,296 attempts**; 940 is the conservative subset. Completing with no infrastructure failure is a **predictive forecast, not measured reliability**, and the prior does visible work. Zero failures in N attempts does not pin the failure rate, and two conventional priors disagree widely about what it implies:

| Observed base | Prior | 600 | 1,200 | 2,400 |
|---|---|---|---|---|
| 0/940 | Jeffreys | .781 | .663 | .531 |
| 0/940 | uniform | .611 | .440 | .282 |
| 0/1,296 | Jeffreys | .827 | .721 | .592 |
| 0/1,296 | uniform | .684 | .519 | .351 |

The CF4.1 Qwen route forecasts essentially zero completion at every one of these sizes under either prior, which is what a 25-failure base should do.

Under "any failure invalidates the primary population", the decision-relevant quantity is completion × power. Corrected power, with drift and clustering present, at the best and worst declared nuisance scenarios (q=.12 with effect sd 10 points, and q=.20 with effect sd 30 points), against the conservative 0/940 forecasts:

| Design | attempts | comp J | comp U | @8pt best | **joint J** | @8pt worst | **joint J** |
|---|---:|---|---|---|---|---|---|
| 200 ×1 (20×10) | 600 | .781 | .611 | .695 | .543 | .424 | .331 |
| 200 ×2 | 1,200 | .663 | .440 | .958 | .635 | .732 | .485 |
| 200 ×4 | 2,400 | .531 | .282 | .998 | .530 | .926 | .491 |
| 400 ×1 (40×10) | 1,200 | .663 | .440 | .965 | **.640** | .757 | .502 |
| 400 ×2 (40×10) | 2,400 | .531 | .282 | 1.000 | .530 | .962 | .510 |

The shape of round 1's conclusion survives: joint probability peaks near 1,200 attempts and then falls, because added attempts buy power the design already has while spending completion probability it cannot spare. Its wording does not. **Several cells exceed one half**, including round 1's own `.501`, so "no design reaches even 50%" is withdrawn; and at 1,200 attempts the Jeffreys forecast puts completion at .663, so an operational invalidation is not the most likely single outcome. The uniform prior puts it at .440 and so reverses that reading. The gap between .440 and .663 is the honest width of this estimate, and it is a forecast under either prior. Treating attempts as independently failing is conservative where outages cluster and optimistic where a route degrades.

### Interval behaviour, now computed from what the analyst can see

Round 1 computed the interval from latent per-block scores that exclude the slot drift the observed statistic contains, so it was not the proposed estimator. Corrected to the observable slot differences returned to the assigned frame, the two calculations differ across the 154 cells carrying drift in **84.3–96.7% of replicates by centre and 95.7–99.9% by width**, and the observable interval is the wider of the two — at the sharp null with drift, 3.79 against the latent 3.47 points at 400 ×1, and 5.89 against 5.33 at the drafted 200 ×1.

Coverage of the **observable** interval is .941–.961 in all 280 scenario cells, including drift, clustering and heterogeneous effects, so the t-interval over block means is now evaluated rather than assumed.

Round 3 re-checks it against the right target. Review was correct that round 2 compared the interval to the global `delta` rather than to each generated cohort's own mean effect; with the corrected generator those coincide by construction, and coverage of **each cohort's realized mean effect** is .944–.980 across all 70 cells of that generator, and .944–1.000 across the wider round-4 family, drifting conservative as heterogeneity concentrates.

Round 2's claim that no one-round design meets the five-point half-width target is **withdrawn** — it rested on the same infeasible cells. Median half-width across the active-share family, spanning 0 to 44.8 points of per-case effect heterogeneity at a fixed mean discordance:

| Design | attempts | q=.12 | q=.20 |
|---|---:|---|---|
| 200 ×1 (20×10) | 600 | 5.32–5.53 | 6.72–6.87 |
| 400 ×1 (40×10) | 1,200 | 3.69–3.82 | 4.64–4.75 |
| 400 ×2 (40×10) | 2,400 | 2.61–3.67 | 3.30–4.64 |

**Within this family** the 400-case one-round design meets the five-point half-width target throughout, at 4.75 points in its worst cell; 200 cases in one round do not, at 6.9. Where disagreement is rare (q=.02) the test remains valid and powerless — a null there means nothing.

One property of the corrected family deserves recording rather than burying: as heterogeneity concentrates into fewer, more extreme cases, both the test and the interval become markedly **conservative** rather than anti-conservative. At a zero cohort mean with 34.7-point heterogeneity, rejection falls to .000 and interval coverage rises to 1.000. The nominal 5% and 95% are attained only near the homogeneous end; elsewhere they are one-sided guarantees. Power is unaffected, because it is driven by the cohort mean.

### Eight points, requalified under one declared scenario family

Round 1 selected an eight-point target from one favourable scenario, and review was right to reject that. Round 2 then rejected eight points on the strength of a single .757 cell — which was one of the inadmissible cells, simulating neither q=.20 nor the heterogeneity it claimed. **Round 2's ten-point recommendation is therefore withdrawn as well.** Neither round had grounds for the number it named.

Regenerated with valid probabilities and exact cohort means, at a target cohort mean of eight points with drift and clustering:

| Design | attempts | q=.12 homogeneous | q=.12 max | q=.20 homogeneous | q=.20 max |
|---|---:|---|---|---|---|
| 200 ×1 (20×10) | 600 | .747 | .744 | .572 | .570 |
| 200 ×2 | 1,200 | .979 | .978 | .900 | .904 |
| 400 ×1 (40×10) | 1,200 | .981 | .982 | .898 | .904 |
| 400 ×2 (40×10) | 2,400 | 1.000 | 1.000 | .998 | .998 |

**Round 4 restates the scope of that result.** Those cells used round 3's floored generator, whose achieved mean discordance was .1355 rather than .12, and "every admissible cell" claimed more than the evidence supports. Rerun under an explicitly declared family instead — the **active-share family**: a fraction π of cases are active with per-case discordance `q_a = q/π` so the cohort's *mean* discordance is exactly the nominal `q`; the remaining cases are inert at `q_i = 0`, no case is required to reach δ, and active effects are ±ν·`q_a` with the cohort mean forced to δ exactly. π = 1 is the constant-per-case case, and π = q drives `q_a` to 1, which attains the heterogeneous bound. This family reproduces all three review counterexamples, including the 18.33-point cell exactly.

Power for the candidate at an eight-point cohort mean, 1,200 attempts, across π ∈ {1, .5, .25, q} and ν from its minimum to 1 — that is, per-case effect heterogeneity from 0 to 44.1 points:

| Design | attempts | q=.12 | q=.20 |
|---|---:|---|---|
| 200 ×1 (20×10) | 600 | .788–.934 | .573–.678 |
| 400 ×1 (40×10) | 1,200 | .989–1.000 | **.902–.999** |
| 400 ×2 (40×10) | 2,400 | 1.000 | .997–1.000 |

**Within this family the 400-case one-round design clears 80% everywhere, worst case .902**, and 600 attempts do not at q=.20. Achieved mean `q_i` equals the nominal baseline exactly in every one of these cells, and no simulated probability leaves [0,1]. Five points remains a no-go, and 600 attempts remain short at eight points.

Three limits travel with that number. It is a statement about **this family**, not about all cohorts with the same mean discordance. The floor is gone, but π is still a declared choice. And passing these simulations does **not** establish weak-null or average-effect validity: the randomization test is exact for the sharp null, which is a different statement ([Wu and Ding](https://arxiv.org/abs/1809.07419)) — the observed behaviour here is conservative rather than exact once heterogeneity concentrates, and nothing here proves that holds generally. Interference is not modelled at all.

One structural constraint remains: the source population is 400 cases (200 `multiple` + 200 `parallel_multiple`), so a one-round design cannot exceed 1,200 attempts.

### Feasibility, proven with no provider call

- Twenty ten-case block slices were built from the retained 200-id cohort by hash rank under a distinct blocking seed; the partition is exact and disjoint, and the blocking randomness only groups already-selected ids.
- All twenty planned through the real planner with **exact ids, zero failures**, resolving the ByteLLM route and model binding `sha256:9f1fa60a…`.
- Installed pinned `bfcl-eval 2026.3.23` contains **every block id** (200 `multiple` + 200 `parallel_multiple`, which is where the 400-case population comes from).
- The retained treatment overlay's derived files still hash to `83d83055…` and `922f2585…`. The overlay replaces whole category files and the adapter already executes one instance per official invocation, so **a block subset cannot alter the treatment identity**.
- The plan doctor passes `bfcl_harness` and `bfcl_package_data` and fails only `provider_credentials`, with no key loaded — the correct shape for an unpaid probe.

**Round 2 adds the derived arm, which round 1 left canonical-only.** The same partition now carries twenty derived block slices on `bfcl-v4-tool-order-v1` beside the twenty canonical ones; all **40 plan through the real planner with exact ids and zero failures**, the derived ones labelled `diagnostic: true` as that benchmark's `manifest_only` support requires, both arms resolving the same ByteLLM binding. The treatment overlay was then materialized twice through `prepare_tool_order_run`, the production function the executor calls: it reproduces `83d83055…`, `922f2585…`, the combined derived identity `c2bb8007…`, and the retained variant manifest digest `33a1b8f8…`, deterministically. That function takes a study and a pinned package and **no slice at all**, which is the structural reason a block subset cannot alter the treatment bytes — round 1 argued this from retained overlay copies; it is now demonstrated on the path itself. Block fingerprint `sha256:54782159…`.

### Effort and the recovered cost basis

Round 1's statement that this route has no measured cost basis is **withdrawn**. The BenchEval evidence rows do carry `cost_basis=unmeasured_no_provider_metering`, but the official BFCL generation records keep `input_token_count` and `output_token_count` for every attempt, and they are retained:

| Panel | attempts | inference failures | input tokens | output tokens |
|---|---:|---:|---:|---:|
| Tool-order panel (X3 primary/repeat/variant) | 600 | 0 | 210,618 | 44,032 |
| X2.4 non-live | 340 | 0 | 75,590 | 27,897 |
| **Route base** | **940** | **0** | **286,208** | **71,929** |
| Live exposure, same route | 356 | 0 | 161,277 | 29,358 |
| CF4.1 Qwen control | 600 | 25 (10/8/7) | — | — |

No attempt is missing in any panel. The directly relevant 600-attempt panel gives **351.0 input and 73.4 output tokens per attempt**, so 1,200 attempts projects to 421,236 input and 88,064 output. The pinned table `config/pricing/2026-04-15.yaml` has no `gpt-5.2` rate; at its only usable anchor, gpt-4o, that is **about $1.93**, and about $19 even if the real rate is ten times the anchor. The proposed $50 allocation is therefore ample rather than unfounded — but the anchor is not this model's price, and the provider-metered ledger remains the only truth about spend.

Host effort is dominated by the harness, not by inference. Recorded per-attempt latency is **2.83 s**, so 1,200 attempts is about 0.94 h of inference against the ~11.1 s per case of wall clock measured on the X3/X2.4 runs — roughly 8 s per case of staging, evaluation and proof work. Ten-case blocks mean **120 runs and 120 proofs** for a 400-case single pass and 240 for two rounds, every one bound by the lock; that overhead, not tokens, is what a two-round design actually costs.

### What the peer recommends

Restated after four rounds of correction, with the strict failure rule left exactly as the protocol writes it. Accepted by independent review on 2026-09-15 for this qualification scope; X6.2 is specified in [`bfcl-repeat-spec.md`](bfcl-repeat-spec.md).

1. **Operational candidate:** 400 cases, **40 blocks × 10**, **one round**, three arms — 120 runs, 1,200 attempts. This is an operational preference, not a statistically mandated choice: it needs no round scheduling, halves the runs and proofs against a two-round design, and carries the better completion forecast. At equal attempts the statistics barely distinguish it from repeating the 200-case cohort.
2. **No cap on rounds.** Round 2's two-round prohibition is withdrawn; there is no round-driven false-positive effect on a fixed cohort whose mean effect is zero.
3. **The smallest useful effect at 1,200 attempts is eight points, under the declared active-share family.** It clears 80% in every cell of that family, worst case .902, at an achieved mean discordance equal to the nominal baseline. Round 1's eight points was selected from one favourable scenario and round 2's ten points from one inadmissible one; this number rests on a named family spanning 0 to 44 points of heterogeneity — not on a universal guarantee, and not on weak-null validity, which is a separate question these simulations do not settle.
4. **The five-point half-width target is met** by the 400-case one-round design throughout that family, worst case 4.75 points. Round 2's claim to the contrary is withdrawn. Coverage is .944 or better everywhere and rises toward 1.000 as heterogeneity concentrates, so the interval is conservative rather than exact away from the homogeneous end.
5. **No-go as drafted stands:** neither drafted one-pass design at a five-point target should be frozen. At five points the 400-case design reaches .687 at q=.12 and .508 at q=.20, and the best joint probability of a usable result is .419 (Jeffreys) or .278 (uniform).

Under the unchanged strict rule, the recommended shape carries a completion forecast of .663 (Jeffreys) or .440 (uniform) and a joint probability of a usable result between .398 and .599 at an eight-point effect in the worse discordance scenario. Those are forecasts from zero observed failures, not a reliability measurement.

Nothing here is frozen and no implementation has begun. If the design owner adopts (1)–(3), X6.2 may proceed. The minimal implementation delta is unchanged: `exposure_protocol.py` (schedule identity, block partition, assignment draw, frozen record), `exposure_repeat.py` (three-arm estimand, constrained randomization test over the **per-round** assignment space, observable interval), reuse of `stats.py`, CLI subcommands, a new 400-case selection/slice/study identity, and two behavioural spec modules. No scheduler, transform framework, second route, or report engine is implied.

**Four** numerical oracle families must travel into that spec, because each caught a defect that every other check passed: the F001 assignment-space counterexample (1/18 against 1/3 on identical data), the observable-versus-latent interval contrast, the F005 cohort-mean and probability constraints (every simulated probability inside [0,1], every cohort mean equal to its declared target), and the F006 heterogeneous-discordance counterexamples that break the constant-`q` bound. The recurring failure across all four rounds was the same one: a quantity assumed to be what it was named, and was not.

Two wordings must survive into the spec unchanged. Five points is a **median planning half-width in the evaluated scenarios**, not a promise about the interval this study will produce. And an imprecise or nonsignificant result is reportable and inconclusive; it never authorizes replacement attempts.
