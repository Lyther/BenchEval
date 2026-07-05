# Runtime invocation contracts (operational)

**Status:** production v1 pins executable paths only. CyBench has no native
four-axis adapter (`metadata_only`). If an operator runs CyBench through the
config-driven **external-command** adapter, the profile is an operator artifact;
BenchEval does not ship solver-specific CyBench profiles or duplicate the
official benchmark scorer/assets.
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

## External-command operator profiles

**Status:** generic adapter path (`adapter_id: external-command`), **not** a
native four-axis runtime adapter. Profiles define their own solver CLI,
container policy, cleanup commands, stream parser, and verification policy.
Benchmark-specific profiles should live with the operator run artifacts unless
BenchEval owns an official adapter for that benchmark.

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
