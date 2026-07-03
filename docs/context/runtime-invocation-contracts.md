# Runtime invocation contracts (operational)

**Status:** production v1 pins executable paths only. CyBench has no native
four-axis adapter (`metadata_only`), but it runs today through the config-driven
**external-command** adapter: the active `config/runs/momo-cybench.yaml` profile
drives Claude Code in a profile-owned container (see § Claude Code in container).
The Kilo demo (`config/runs/cybench-kilo-showcase.yaml`) is the same adapter path.
**Scope:** per-runtime fields BenchEval adapters must honor—see also `config/runtimes/*.yaml`.

## Harbor + Terminal-Bench (`terminal-bench-harbor` adapter)

| Field | Contract |
|-------|----------|
| Binary | `harbor` on PATH |
| Version | `harbor --version` |
| Command shape | `harbor run` with dataset/slice, `--agent <runtime>`, `--model <model-id>` (exact flags in adapter) |
| Docker | **Required** (official TB 2.0 harness) |
| Network | Benchmark-defined; default deny in eval runtimes |
| Env (names only) | Provider keys per agent (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)—never commit values |
| Outputs | Verifier logs under `--artifacts-dir`; Harbor stdout/stderr captured by adapter |
| Timeout | `config/runtimes/*.yaml` `timeout_sec_default`; slice may tighten |
| Parser | Harbor exit code + structured agent output → `EvidenceRecord` |
| Failure | `failure_class` from harness/verifier; invalid attempts excluded from Pass@k when capped |

Runtimes using Harbor agents: `claude-code`, `codex-cli` (`config/runtimes/claude-code.yaml`, `codex-cli.yaml`).

## mini-SWE-agent + SWE-bench (`swe-bench-verified` adapter)

| Field | Contract |
|-------|----------|
| Binary | `mini-extra` (mini-SWE-agent install) on PATH |
| Version | package version via `pip show mini-swe-agent` or project pin |
| Command shape | `mini-extra swebench` batch / single modes per adapter |
| Container | Docker or Singularity per upstream harness |
| Env (names only) | Model provider env vars; no secrets in evidence export (`public` redaction) |
| Outputs | SWE-bench harness logs under artifacts dir |
| Timeout | Per-instance wall clock in adapter plan |
| Parser | Harness pass/fail → `primary_pass`, `partial_score` |

Runtime profile: `mini-swe-agent` (`config/runtimes/mini-swe-agent.yaml`).

## BFCL v4 native (`bfcl-v4` adapter)

| Field | Contract |
|-------|----------|
| Package | **`bfcl-eval`**; it installs the `bfcl` console script |
| Version | `bfcl version` or package metadata |
| Command shape | `bfcl generate --test-category <category> --result-dir <artifacts> --model <model>` for smoke generation; official scoring needs the matching `bfcl evaluate` step before `benchmark_native_claim` |
| Docker | Usually not required for smoke-5; full suite per Gorilla docs |
| Env (names only) | Model API env vars for generation |
| Outputs | BFCL result files → normalized evidence rows |
| Parser | Official BFCL scoring → pass/partial |

Runtime profile: `native-api` (`config/runtimes/native-api.yaml`).

## Claude Code in container (active CyBench external-command profile)

**Status:** config-driven `external-command` adapter path (`adapter_id:
external-command`), **not** a native four-axis runtime adapter. Active profile:
`config/runs/momo-cybench.yaml`; operator runbook
[`docs/ops/momo-cybench.md`](../ops/momo-cybench.md).

| Field | Contract |
|-------|----------|
| Solver CLI | `momo solve` (`command.argv_prefix`); the runtime is selected inside MOMO and passed through `{runtime_id}` = `claude-code` |
| Runtime command | `claude -p --output-format stream-json --include-partial-messages --verbose --dangerously-skip-permissions --model {runtime_model_id}` (profile env `MOMO_CLAUDE_CODE_COMMAND`) |
| Container | Profile launches `docker run` (foreground `exec`, `--rm`, named `momo-cybench-{instance_id}`) with a pre-run same-id self-heal. Abnormal-exit removal is BenchEval's first-class `cleanup:` block (`docker rm -f`, run after every attempt), **not** a shell `trap`: `killpg` reaps native children but cannot reach dockerd containers, so cleanup is a separate step. BenchEval core ships no Docker plane |
| Termination | Progress-aware `deadline.no_progress_sec` (committed 900s, adaptive to streaming cadence) terminates a wedged solver container-safe (process-group SIGTERM→grace→SIGKILL) and classifies it `runtime_no_progress_stall` (invalid, excluded from pass@k), distinct from a task-difficulty fail. An absolute `wall_clock_sec` ceiling is operator-supplied at launch (`--wall-clock-sec`), not committed |
| Variant | `claude-code-mixed-model`: `model_id: bytellm/glm-5.2` is the requested primary; Claude Code may issue auxiliary ByteLLM-routed model calls, so the run is reported mixed-model, not GLM-5.2-only |
| Provenance | Evidence `adapter_metadata` carries `configured_model_id`, `served_model_id`, and `model_attribution` (`authoritative` / `mixed_model` / `attribution_not_captured`). Plain-lines streams capture nothing, so this profile reports `attribution_not_captured` — never silently the requested model |
| Telemetry | `X-Experiment-ID`/`X-Request-ID` injected via `ANTHROPIC_CUSTOM_HEADERS`; `telemetry_id`/`trace_id` = `{run_id}:{instance_id}:attempt{N}` recorded in evidence `adapter_metadata`; ByteLLM telemetry is source of truth for the actual model mix |
| Stream | `parser: plain-lines` — MOMO emits progress plus a verbatim final answer, not kilo-json |
| Verification | `manifest-value-regex`, strict (`allow_observed_without_expected: false`); BenchEval owns flag extraction against the private manifest |
| Output cap | `stream.output_token_max` (131072) → `runtime_output_cap_reached` → `attempt_validity=invalid` |

## Kilo CLI (legacy demo)

**Status:** legacy demo profile (`config/runs/cybench-kilo-showcase.yaml`), same
`external-command` adapter path; `adapter_pending` for any native four-axis runtime.

| Field | Requirement (target) |
|-------|----------------------|
| Permission model | `--auto` is autonomous mode, **not** output budget |
| Output cap | `KILO_EXPERIMENTAL_OUTPUT_TOKEN_MAX` when needed |
| Format | `--format json` (`parser: kilo-json`) |
| Workdir | `--dir <attempt-workdir>` per instance |
| Evidence | `runtime_output_cap_reached` → `attempt_validity=invalid`, `counts_toward_pass_at_k=false` by default |

## Monitor semantics (target product)

Do **not** fail on log silence alone. Distinguish: clean exit, alive-but-quiet, wall-clock exceeded, output cap, operator interrupt.

## Attempt validity (evidence v0.3 additive fields)

| Field | Meaning |
|-------|---------|
| `attempt_validity` | `valid` \| `invalid` |
| `invalid_reason` | e.g. `output_cap_reached`, `operator_interrupted` |
| `counts_toward_pass_at_k` | whether the row consumes Pass@k budget |
| `physical_launch_id` / `logical_attempt_number` | separate physical launches from logical attempts |
| `runtime_output_cap` | cap env/config in effect |

## Execution support vs catalog

| Label | Meaning |
|-------|---------|
| `executable_adapter` | TB / SWE-verified / BFCL v4 control-plane adapters |
| `manifest_only` | Slice/manifest without full lifecycle adapter |
| `metadata_only` | Catalog entry only (e.g. CyBench until adapter ships) |

Dry-run JSON includes `slice_resolution.execution_support`. Non-dry-run `run` refuses anything except `executable_adapter`.
