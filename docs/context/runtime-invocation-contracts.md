# Runtime invocation contracts (operational)

**Status:** production v1 pins executable paths only; CyBench/Kilo remain design backlog.
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
| Package | **`bfcl-eval`** (not PyPI `bfcl`); pin e.g. `2025.12.17` per leaderboard |
| Version | `bfcl-eval --version` or import metadata |
| Command shape | Generation/eval commands implemented in `bfcl_native` adapter |
| Docker | Usually not required for smoke-5; full suite per Gorilla docs |
| Env (names only) | Model API env vars for generation |
| Outputs | BFCL result files → normalized evidence rows |
| Parser | Official BFCL scoring → pass/partial |

Runtime profile: `native-api` (`config/runtimes/native-api.yaml`).

## Kilo CLI

**Status:** `adapter_pending` — not a production v1 executable runtime until a Harbor/selftest adapter exists and live proof is recorded.

| Field | Requirement (target) |
|-------|----------------------|
| Permission model | `--auto` is autonomous mode, **not** output budget |
| Output cap | `KILO_EXPERIMENTAL_OUTPUT_TOKEN_MAX` when needed |
| Format | `--format json` |
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
