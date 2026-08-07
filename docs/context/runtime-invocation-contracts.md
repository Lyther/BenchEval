# Runtime invocation contracts (operational)

**Status:** production v1 pins executable paths only. CyBench has no native
four-axis adapter (`metadata_only`), and the generic **external-command**
adapter lane has been removed from the product surface; BenchEval does not
ship solver-specific CyBench profiles or duplicate the official benchmark
scorer/assets.
**Scope:** per-runtime fields BenchEval adapters must honor—see also `config/runtimes/*.yaml`.

## Harbor + Terminal-Bench (`terminal-bench-harbor` adapter)

| Field | Contract |
|-------|----------|
| Binary | `harbor` on PATH |
| Version | `harbor --version` |
| Command shape | `harbor run` with dataset/slice, `--agent <runtime>`, `--model <model-id>` (exact flags in adapter) |
| Docker | **Required** (official TB 2.0 harness) |
| Network | `benchmark_required` (Harbor rejects `network_policy=deny`; proxy forwarding is opt-in) |
| Env (names only) | Provider keys per agent (e.g. `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`)—never commit values |
| Outputs | Verifier logs under `--artifacts-dir`; Harbor stdout/stderr captured by adapter |
| Timeout | `config/runtimes/*.yaml` `timeout_sec_default`; slice may tighten |
| Parser | Harbor exit code + structured agent output → `EvidenceRecord` |
| Failure | `failure_class` from harness/verifier; invalid attempts excluded from Pass@k when capped |

Runtimes using Harbor agents: `claude-code`, `codex-cli` (`config/runtimes/claude-code.yaml`, `codex-cli.yaml`).

## Diagnostic only: mini-SWE-agent + SWE-bench

`swe-bench-verified` is cataloged but non-executable. The table documents retained
adapter research; it is not a pilot prerequisite or a supported `run` path.

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

Runtime profiles: `claude-code`, `codex-cli` (`config/runtimes/claude-code.yaml`, `config/runtimes/codex-cli.yaml`). mini-SWE-agent is the harness binary, not a BenchEval runtime profile — the old `mini-swe-agent` profile was removed from `config/runtimes/`.

## Diagnostic only: BFCL v4

`bfcl-v4` is cataloged but non-executable. The retained module can characterize
generation artifacts, but the CLI/executor refuses it until generation and official
evaluation are wired as one lifecycle.

| Field | Contract |
|-------|----------|
| Package | **`bfcl-eval`**; it installs the `bfcl` console script |
| Version | `bfcl version` or package metadata |
| Command shape | **Diagnostic:** `bfcl generate --test-category <category> --result-dir <artifacts> --model <model>`. This is not score authority. Official scoring requires a matching `bfcl evaluate` step before executability or any comparison claim. |
| Docker | Usually not required for smoke-5; full suite per Gorilla docs |
| Env (names only) | Provider credential env for generation (via model `provider_route`) |
| Outputs | Diagnostic BFCL generation files only; no admitted evidence lifecycle |
| Parser | Generation-path parser retained for development; official BFCL evaluate score parsing **not wired** |

If admitted later, BFCL will be model-only (omit `--runtime` / `--agent`). Deleted
profiles such as `native-api` remain unadmitted.

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
| `executable_adapter` | TB / GPQA / HLE control-plane adapters (`swe-bench-verified` / `bfcl-v4` demoted until official evaluate) |
| `manifest_only` | Slice/manifest without full lifecycle adapter |
| `metadata_only` | Catalog entry only (e.g. CyBench until adapter ships) |

Dry-run JSON includes `slice_resolution.execution_support`. Non-dry-run `run` refuses anything except `executable_adapter`.
