# CyBench Hard-39 Run Difficulties

**Date:** 2026-06-18
**Run:** CyBench hard-39, local Kilo runtime, `ollama-cloud/glm-5.2`, remote Docker sandboxes on `vps.0xb105.com`
**Final outcome:** 39/39 passed after correcting runtime accounting and output-limit handling.
**Private evidence bundle:** `results/raw/cybench-hard-39-glm52-20260618T022156Z-FULL-PRIVATE.tar.gz`

This note records operational difficulties observed during the live CyBench run. It is intended to guide BenchEval product and adapter design. It intentionally does not include flags, private key contents, or raw model outputs.

---

## Executive Summary

The benchmark result was strong, but the run exposed several control-plane gaps:

1. BenchEval could catalog CyBench, but did not yet provide a complete CyBench execution adapter.
2. External benchmark runs need a first-class single-task lifecycle: materialize, run, verify, archive evidence, cleanup, and retry.
3. Runtime-specific knobs matter. Kilo headless mode required both `--auto` and `KILO_EXPERIMENTAL_OUTPUT_TOKEN_MAX=131072`; model metadata alone was not sufficient in practice.
4. Quiet agent sessions are not necessarily stalled. They may be waiting on model calls, subagents, or remote tool work.
5. Exact output-cap exits must be classified as infrastructure/runtime invalid attempts, not model failures.
6. Evidence export must preserve private raw artifacts while producing a sanitized index and summary for project discussion.
7. Remote Docker evidence collection needs timeouts and best-effort failure handling.

---

## Difficulties Encountered

### 1. Catalog Support Was Not Execution Support

BenchEval had benchmark metadata and manifest concepts, but the first CyBench run still required manual orchestration:

- remote sandbox setup on `vps.0xb105.com`;
- forced-command SSH key generation and task routing;
- per-task prompt construction;
- Kilo process launch and monitoring;
- pass detection from raw JSONL logs;
- manual export of local and remote evidence.

**BenchEval implication:** a benchmark registry entry should not be considered "supported" unless it has an executable adapter path or is clearly labeled `metadata_only` / `dry_run_only`.

### 2. CyBench Quantity and Slice Semantics Were Ambiguous

There was confusion between "CyBench-35" and the executed `cybench-inspect-evals-hard-39` slice. The concrete run target had 39 challenges, while earlier operational assumptions referred to 35.

**BenchEval implication:** benchmark slices must be versioned, named, and count-checked before execution. A run plan should print:

- benchmark id;
- slice id;
- source manifest path/hash;
- expected task count;
- resolved task ids;
- excluded task ids, if any.

### 3. Initial Host Choice Was Fragile

The requested topology was local Kilo -> `dev-box-cpu`, but Docker and network/proxy constraints made that path unreliable. The run moved to `vps.0xb105.com`, where Docker was available and the benchmark could complete.

**BenchEval implication:** remote-runtime selection needs explicit preflight:

- Docker daemon availability;
- disk budget;
- image pull access;
- apt/pip/docker proxy configuration;
- SSH reachability;
- host cleanup permissions;
- expected benchmark image availability.

The system should fail before launching tasks if these checks do not pass.

### 4. Proxy Configuration Was a Hard Operational Requirement

Docker, apt, and pip proxy handling was not consistently represented. This created avoidable uncertainty during image/materialization work.

**BenchEval implication:** remote hosts should have a structured proxy profile with separate fields for:

- Docker daemon proxy;
- Docker build proxy;
- apt proxy;
- pip proxy;
- HTTP(S) runtime proxy;
- no-proxy entries for internal service names such as benchmark Compose services.

Preflight should report effective proxy state without printing secrets.

### 5. Stale-Looking Sessions Were Not Necessarily Stale

Some Kilo sessions produced no top-level JSONL output for long intervals. Early interpretation treated these as stale failures. Later inspection showed that quiet sessions could still have live child processes, subagent work, model calls, or remote tool activity.

**BenchEval implication:** do not classify failure based on wall-clock silence alone. A monitor should distinguish:

- process exited with stop marker;
- process exited without parseable output;
- process alive but log quiet;
- child/subagent active;
- remote command active;
- model request pending;
- output cap reached;
- explicit timeout budget exceeded.

Only explicit budget exhaustion should count as timeout failure.

### 6. Premature Kills Corrupted Attempt Accounting

Some attempts were killed due to perceived staleness. These attempts could not be counted as valid model failures. They had to be archived and rerun.

**BenchEval implication:** interrupted attempts need a distinct failure class such as `interrupted_by_harness` or `operator_interrupted`. They must not consume Pass@1/Pass@k attempt budget unless the benchmark policy explicitly says so.

### 7. Stream Scheduling Was Required

The user wanted a continuous stream with up to 10 concurrent Kilo workers: as soon as one challenge passed, launch the next challenge. Chunked scheduling would have wasted time.

**BenchEval implication:** suite execution needs a bounded worker-pool scheduler:

- global concurrency cap;
- per-runtime concurrency cap;
- per-host concurrency cap;
- immediate refill on terminal states;
- no waiting for a whole batch to finish;
- retry scheduling based on attempt policy.

### 8. Pass Detection Needed Private Manifest Access

The run detected passes by checking raw logs against private challenge flags. This is valid for private evidence generation but unsafe for public reporting.

**BenchEval implication:** evidence storage should separate:

- private verifier inputs, including flags;
- raw logs;
- sanitized pass/fail summary;
- public-safe redacted report.

The report layer should never print flags or key material by default.

### 9. Kilo `--auto` Was Misunderstood

`--auto` is permission auto-approval for headless/pipeline use. It is not auto-compaction and does not control output token limits.

**BenchEval implication:** runtime adapters must encode runtime-specific semantics instead of assuming similarly named flags mean budget or context control.

For Kilo:

```bash
KILO_EXPERIMENTAL_OUTPUT_TOKEN_MAX=131072 \
kilo run \
  --auto \
  --model ollama-cloud/glm-5.2 \
  --variant max \
  --format json \
  --dir <attempt-workdir> \
  "<prompt>"
```

### 10. Output Limit Had a Hidden Runtime Fallback

Kilo model metadata and config showed `limit.output=131072`, but repeated attempts stopped exactly at 32,000 output tokens. Official docs indicated a fallback/internal default that can be overridden with `KILO_EXPERIMENTAL_OUTPUT_TOKEN_MAX`.

**Observed effect:** exact-32,000 stops were invalid runtime/output-cap events. After relaunching with `KILO_EXPERIMENTAL_OUTPUT_TOKEN_MAX=131072`, the tail tasks completed.

**BenchEval implication:** output-cap detection should be explicit:

- if stop reason is normal but output tokens equal a known runtime cap, classify as `output_cap_reached`;
- do not count the attempt as a model failure unless benchmark policy says capped output is a valid failure;
- record the runtime cap and environment variables used;
- automatically relaunch if the attempt is invalid and retry policy permits.

### 11. Model Context and Output Are Separate Budgets

Some active tasks had large total token counts but small output token counts. Treating total context pressure as output exhaustion would have been wrong.

**BenchEval implication:** evidence records should store at least:

- input tokens;
- output tokens;
- total tokens;
- reasoning tokens, if available;
- cache read/write tokens;
- runtime output cap;
- runtime context cap.

Failure classifiers must use the correct field.

### 12. Monitor Ownership Matters

Manual relaunches briefly duplicated Kilo workers. The correct behavior was to let one scheduler own attempts, logs, PID files, and retry state.

**BenchEval implication:** attempt ownership should be centralized. A run manager should:

- allocate attempt ids;
- create work dirs;
- write PID files;
- own process lifecycle;
- archive invalid attempts;
- prevent duplicate workers for the same task/attempt.

Manual intervention should be represented as an explicit operator action in evidence.

### 13. Attempt Numbering Needed Invalid-Attempt Semantics

Exact-32,000 output-cap attempts, config-failed launches, and operator-interrupted attempts had to be removed from valid attempt counts. The monitor had to keep "valid attempt" count separate from physical launch count.

**BenchEval implication:** attempt metadata needs:

- physical launch id;
- logical attempt number;
- validity status;
- invalid reason;
- whether it consumes Pass@k budget;
- archive path;
- replacement attempt id, if any.

### 14. Process Cleanup Needed PID-Tree Precision

When a task passed but its Kilo process tree was still alive, cleanup needed to terminate only that solved task's PID tree. Killing process groups or broad name matches could terminate unrelated workers.

**BenchEval implication:** runtime adapters should track process trees and cleanup by owned PID tree only. Cleanup should be idempotent and logged.

### 15. Remote Docker Snapshot Collection Was Partially Blocking

During final export, one `docker diff` command hung. The already collected remote evidence was preserved, the stuck command was terminated, and the snapshot was packaged with a note.

**BenchEval implication:** remote evidence collection should use per-command timeouts and best-effort collection:

- `docker inspect`: required if container exists;
- `docker logs`: best effort with size/time caps;
- `docker diff`: best effort with timeout;
- `docker top` / `docker stats`: best effort;
- final snapshot notes must record missing or interrupted collectors.

### 16. Summary Generation Had a Path-Type Bug

The first summary generator selected the remote tarball path instead of the extracted remote snapshot directory because both matched the same glob prefix. This produced wrong remote counts until fixed.

**BenchEval implication:** artifact summaries should validate path type and schema:

- tarball path must be a file;
- unpacked snapshot path must be a directory;
- expected subdirectories should exist;
- counts should be recomputed after summary generation;
- final checksum should be computed after all derived files are written.

### 17. Final Active Worker Count Needed Post-Cleanup Recompute

The monitor initially wrote `active_kilo=1` after marking the final task passed because the count was computed before terminating the solved worker. A post-cleanup process check showed no workers, and the summary was normalized.

**BenchEval implication:** terminal summary should recompute live process state after cleanup, not before.

### 18. Evidence Privacy Was Easy to Violate Accidentally

The full evidence bundle includes private flags, task SSH keys, raw logs, manifests, and container artifacts. Chat summaries and project docs must be sanitized.

**BenchEval implication:** evidence export should produce two tiers by default:

- full private archive;
- redacted public/project summary.

The CLI should name private archives clearly, for example `FULL-PRIVATE`, and should generate a redaction manifest.

### 19. External Benchmark Runs Need Durable Export Manifests

The final export needed:

- local run root;
- local work dirs;
- remote host snapshot;
- remote container metadata;
- invalid-attempt archives;
- sanitized index;
- private tarball;
- checksums.

This was assembled manually.

**BenchEval implication:** `bencheval export-run` should build the same structure automatically and verify it:

- `SUMMARY.md`;
- `evidence-index.json`;
- `manifest.redacted.json`;
- `SHA256SUMS.txt`;
- `FILES.txt`;
- full private tarball;
- optional public redacted tarball.

### 20. Live Benchmark Runs Need an Operator Audit Trail

Several important decisions happened during the run:

- switched host from dev-box-cpu to VPS;
- corrected stale-session handling;
- corrected output token env;
- archived invalid attempts;
- relaunched replacement attempts;
- killed only solved PID trees;
- stopped one stuck `docker diff` during evidence export.

**BenchEval implication:** run metadata should include operator actions with timestamps and reasons. This is essential for post-run trust.

---

## Suggested BenchEval Work Items

### P0: Runtime Invocation Contract

Add runtime-specific launch contracts. For Kilo, include:

- binary path;
- model id;
- variant;
- `--auto`;
- `--format json`;
- work directory;
- required environment variables, especially `KILO_EXPERIMENTAL_OUTPUT_TOKEN_MAX`;
- permission model;
- expected JSONL event schema.

### P0: Attempt Validity Model

Represent physical launches separately from valid benchmark attempts. Add invalid reasons:

- `operator_interrupted`;
- `config_failed`;
- `output_cap_reached`;
- `runtime_crash`;
- `remote_infra_failure`;
- `evidence_corrupt`;
- `duplicate_launch`.

### P0: Bounded Streaming Scheduler

Implement a scheduler with:

- max concurrency;
- stream refill;
- owned process trees;
- task-level retry policy;
- no stale-silence failure classification;
- explicit timeout-budget failure only.

### P0: External Benchmark Single-Task Lifecycle

For large public benchmarks, implement:

```text
materialize one task
launch runtime
monitor process and verifier
append evidence
archive raw logs
cleanup workspace/container
schedule next task
```

This is required for CyBench, SWE-bench-like suites, and other large container benchmarks.

### P1: Output-Cap and Runtime-Cap Classifier

Detect exact-cap stop conditions and classify them as runtime or infrastructure failures unless the benchmark policy says otherwise.

### P1: Remote Host Preflight

Preflight should verify:

- Docker;
- disk;
- image pull;
- proxy configuration;
- SSH forced-command path;
- no-proxy for Compose service names;
- cleanup permissions.

### P1: Evidence Export Command

Add an export command that builds:

- full private archive;
- redacted summary;
- redacted manifest;
- evidence index;
- local and remote snapshots;
- checksums;
- tarball.

### P1: Remote Snapshot Collector with Timeouts

Wrap every remote collector command with a timeout and record partial failures.

### P2: Operator Action Log

Record manual overrides, monitor restarts, invalid attempt archivals, process kills, and export interruptions as structured events.

### P2: Redaction Boundary

Generate public-safe summaries by default and require an explicit flag for full-private archives.

---

## Resulting Design Principle

BenchEval should treat benchmark execution as an evidence-preserving distributed systems problem, not just a loop over task ids. The run succeeded because invalid infrastructure/runtime events were separated from model failures, quiet workers were allowed to continue, and raw evidence was preserved. Those behaviors should be first-class product features.
