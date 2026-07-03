# momo-cybench — CyBench external-command profile (operational)

Operational runbook for the **primary/active** CyBench external-command profile,
[`config/runs/momo-cybench.yaml`](../../config/runs/momo-cybench.yaml). It drives
the MOMO solver CLI against a **Claude Code mixed-model runtime** running inside a
profile-owned container. BenchEval owns launching and scoring; MOMO owns solving.

- Adapter contract: [`docs/api/internal-contracts.md`](../api/internal-contracts.md) § External command profiles.
- Runtime invocation shape: [`docs/context/runtime-invocation-contracts.md`](../context/runtime-invocation-contracts.md) § Claude Code in container.
- Design source of truth: [`docs/context/concept-hld.md`](../context/concept-hld.md).
- Legacy demo counterpart: [`config/runs/cybench-kilo-showcase.yaml`](../../config/runs/cybench-kilo-showcase.yaml) (Kilo).

This profile is **not** a fourth Production v1 (four-axis) adapter. CyBench stays
`metadata_only` in the control-plane catalog; it runs today only through the
config-driven `external-command` adapter
([`src/bencheval/external_command_adapter.py`](../../src/bencheval/external_command_adapter.py)).

## Identity at a glance

Every value below is read directly from `config/runs/momo-cybench.yaml`.

| Field | Value |
|---|---|
| `name` | `momo-cybench` |
| `benchmark_id` / `benchmark_version` / `slice_id` | `cybench` / `hard-39-private` / `cybench-showcase` |
| `adapter_id` / `harness_kind` | `external-command` / `local-harness` |
| `runtime_id` / `runtime_kind` | `claude-code` / `cli_agent` |
| `model_id` | `bytellm/glm-5.2` (requested primary; see below) |
| `variant` | `claude-code-mixed-model` |
| `execution_profile` | `E2` |
| `interpretation_label` | `offensive_restricted` |
| `contamination_label` / `reward_hack_risk_label` | `public_possible` / `known_public_risk` |
| `verifier_integrity_label` | `native` |
| `stream.parser` | `plain-lines` |
| `stream.output_token_max` | `131072` |
| `concurrency` / `max_attempts` / `pass_at_k_budget` | `1` / `1` / `1` |
| `instances` | 39 CyBench hard-39 ids (`avatar` … `were_pickle_phreaks_revenge`) |

## Mixed-model Claude Code runtime

`variant: claude-code-mixed-model` is deliberate. `model_id: bytellm/glm-5.2` is
the **requested primary** model, **not** a GLM-5.2-only benchmark:

- The solver argv (`command.args_template`) passes `--model {model_id}` =
  `bytellm/glm-5.2` to MOMO, and the container command passes
  `--model {runtime_model_id}` to `claude`. `runtime_model_id` is the provider
  prefix stripped by `_runtime_model_id()` (`bytellm/glm-5.2` → `glm-5.2`), routed
  back through ByteLLM via `ANTHROPIC_BASE_URL`.
- Claude Code may issue **auxiliary runtime calls to other ByteLLM-routed
  models**. The config header states this explicitly. The run is therefore
  reported as a mixed-model Claude Code runtime run, not a single-model run.
- The variant is propagated into results and reports: the adapter's
  `adapter_metadata` records `variant` and `configured_model_id`
  (`_write_evidence`), `summary.json` carries a `variant` key, and `SUMMARY.md`
  gains a `- Variant: ...` line (`_write_summary`). The live console `model`
  event also appends `variant=...` when set.

## Container launch is profile-owned; cleanup is a first-class BenchEval step

Consistent with "BenchEval ships no Docker plane": the container *launch* belongs
to the **profile**, in `command.env.MOMO_CLAUDE_CODE_COMMAND` (MOMO shlex-splits
it into `sh -c <script>`). Container *removal* on abnormal exit is BenchEval's
first-class `cleanup:` block, not a profile shell `trap` — `killpg` reaps native
children but cannot reach dockerd-managed containers, so cleanup runs as a
separate adapter step after every attempt.

- **Container identity + launch:** `cid=momo-cybench-{instance_id}`, a pre-run
  `docker rm -f $cid` same-id self-heal, then a trap-free foreground
  `exec docker run --rm --name $cid ...`. `exec` replaces the shell so BenchEval's
  SIGTERM reaches `docker run` directly; `-i` forwards MOMO's piped prompt on
  inherited stdin. No `trap` / backgrounding / fd juggling.
- **Abnormal-exit cleanup (first-class):** the profile `cleanup:` block runs
  `docker rm -f momo-cybench-{instance_id} || true` after every attempt — success,
  failure, or stall-kill (`ExternalCleanupConfig`, `_run_cleanup`). The outcome is
  recorded in evidence as `cleanup_result`.
- **Progress-aware termination:** `deadline.no_progress_sec` (900s) terminates a
  wedged solver container-safe (process-group SIGTERM → grace → SIGKILL) and
  classifies it `runtime_no_progress_stall` (invalid, excluded from pass@k),
  distinct from a task-difficulty fail. An absolute ceiling is operator-supplied at
  launch via `--wall-clock-sec`, never a committed guess.
- **Mounts / identity:** `--network host`, `--user {host_uid}:{host_gid}`,
  read-only `/etc/passwd` + `/etc/group`, `-v {work_dir}:{work_dir}`,
  `-v {run_root}/keys/{instance_id}:/tmp/momo-cybench-key:ro`, and
  `-e HOME={work_dir}/.container-home`.
- **Image + runtime command:** image `momo:cybench-runner`, invoked as
  `claude -p --output-format stream-json --include-partial-messages --verbose
  --dangerously-skip-permissions --model {runtime_model_id}`.

Core BenchEval launches `command.argv_prefix` (`momo solve`), templates the env
string, and owns termination + container cleanup + stall classification.

## Per-attempt telemetry join

Each attempt is stamped with a deterministic id so ByteLLM experiment/stream
telemetry can be joined back to the BenchEval attempt:

- `telemetry_id = "{run_id}:{instance_id}:attempt{N}"` — `_telemetry_id()` in
  `external_command_adapter.py` (sanitized to `[A-Za-z0-9_.:-]`). In the template
  context `trace_id` is set to the same value.
- The profile injects both into the container via `ANTHROPIC_CUSTOM_HEADERS`:
  `X-Experiment-ID: {telemetry_id}` and `X-Request-ID: {trace_id}`.
- Both are persisted in evidence under `adapter_metadata` as `telemetry_id` and
  `trace_id` (`_write_evidence`).
- **ByteLLM telemetry is the source of truth** for the actual per-request model
  mix. BenchEval records what it requested and the join keys; it does not itself
  observe which model served each auxiliary call.
- Evidence also carries first-class provenance: `configured_model_id`,
  `served_model_id`, and `model_attribution`. A plain-lines stream surfaces no
  served-model signal, so this profile records `model_attribution =
  attribution_not_captured` — never silently the requested `bytellm/glm-5.2`.

## Scoring

Verification is strict and official-scorer-only (`verification` block):

- `kind: manifest-value-regex` with `allow_observed_without_expected: false`.
  An observed value passes **only** when it matches the expected value from the
  private manifest. A missing/empty expected value is a **fail**, never a
  self-certified pass (peer review F001; `_classify_result`).
- Expected values are read from `manifest_paths` (`meta/manifest.private.json`,
  then `meta/manifest.full.private.json`), keyed by `manifest_id_field: name`
  with `manifest_value_field: flag` (`_expected_value` / `_find_manifest_value`).
- **BenchEval owns flag extraction.** MOMO emits plain progress lines plus its
  runtime's final answer verbatim (`stream.parser: plain-lines`); the profile —
  not MOMO — extracts the challenge value via `verification.observed_regex` and
  compares it to the manifest. MOMO does not self-report pass/fail.

## Running it

`MOMO_CYBENCH_RUN_ROOT` (the `input.root_env`) points at the operator-prepared
run root. `bencheval run` preflights it fail-fast via `validate_external_run_root`:
for every selected instance the root must contain a prompt
(`run-prompts/{instance_id}.txt` or `prompts/{instance_id}.prompt.txt`) and the
private manifest under `verification.manifest_paths`. A per-task SSH key
(`keys/{instance_id}`, the `required_path_templates` entry) is required **only
when the selected prompt references it** — prompt-only instances with no key pass
preflight (peer review F003).

```bash
cd /path/to/BenchEval
export MOMO_CYBENCH_RUN_ROOT=/path/to/prepared/cybench/root

# Validate config + run root, print the resolved plan, launch nothing:
uv run bencheval run --config config/runs/momo-cybench.yaml --dry-run

# Live run (requires MOMO on PATH, Docker, and ByteLLM ANTHROPIC_* env):
uv run bencheval run --config config/runs/momo-cybench.yaml
# or the wrapper:
scripts/external-command-run.sh --config config/runs/momo-cybench.yaml
```

Provider/proxy env (`ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY`) is forwarded into
the container by the profile; set it the same way as the Phase B pilot — see
[`docs/ops/dev-box-pilot.md`](dev-box-pilot.md) § Provider access. Artifacts land
under `results/` (gitignored): raw run record `events.jsonl`, `EvidenceRecord`
JSONL, `summary.json`, `SUMMARY.md`, per-instance stream logs, and `SHA256SUMS.txt`.

## Honest status

**No full CyBench-39 rerun has been completed after the mixed-model policy
change.** Any prior 28/39-style figure predates `variant: claude-code-mixed-model`
and was captured without per-request model attribution; treat such numbers as
"mixed-model, attribution not captured" or superseded. This runbook deliberately
states **no pass count**. Score the current profile only from a fresh run whose
ByteLLM telemetry join (`telemetry_id`/`trace_id`) is retained.
