# Phase B on dev-box-cpu — live pilot runbook

Operational runbook for executing the Phase B live control-plane pilot on a
**dev-box-cpu** (or equivalent operator VPS). Tier definitions:
[`docs/context/production-readiness.md`](../context/production-readiness.md).
Scope summary: [`docs/context/production-v1-pilot.md`](../context/production-v1-pilot.md).
Design: [`docs/context/concept-hld.md`](../context/concept-hld.md).

Phase B = live matrix with real credentials and **native harness runtimes**. It is gated and
non-fatal to blockers: blocked steps produce **negative preflight evidence**
(`results/preflight/*.json`), never fake passes.

**Scope boundary:** BenchEval core does not ship a Docker control plane. Docker (or other
sandbox) appears here only when a **benchmark adapter’s official harness** requires it
(e.g. Harbor for Terminal-Bench). Local Tier 0 development and CI do not require Docker on
the host.

## Scope and what counts as proof

The minimum live proof this runbook targets (matches
`scripts/run-live-pilot-matrix.sh` exit codes):

1. `terminal-bench` `smoke-5` for **both** `claude-code` and `codex-cli`
   Harbor runtimes (same `model_id` so the compare is runtime-only).
2. `bencheval compare` of those two evidence files succeeds (single axis:
   `runtime_comparison`).
3. `bfcl-v4` `smoke-5` via `native-api`.

SWE (`swe-bench-verified` smoke-10 via `mini-swe-agent`) is exercised but is
**not** part of the minimum proof.

## 1. Prerequisites on dev-box-cpu

| Dependency | Why | Check |
|---|---|---|
| Python 3.12+, `uv` | control plane | `uv --version` |
| Docker daemon | Harbor TB harness (when used), some SWE materialization | `docker info` (dev-box only when running those adapters) |
| `harbor` CLI | TB runtime | `harbor --version` (or `uv sync --extra eval`) |
| `bfcl` | BFCL lane (`bfcl-eval` package) | `command -v bfcl && bfcl --help` |
| `mini-extra` | SWE lane | `command -v mini-extra` |
| Provider env vars | live model calls | `verify_auth.sh` (below) |

```bash
uv sync
uv sync --extra eval          # inspect_ai / harbor extras
```

`bfcl` and `mini-extra` are host/runtime CLIs, not part of the `eval` extra.
Install them separately before claiming a full Phase B matrix.

Keep all artifacts under `results/` — it is gitignored. Do not commit live
evidence, raw outputs, or bundles unless you explicitly intend to publish.

## 2. Provider access and proxy verification

Provider reachability has two independent layers. Verify **both** before the
matrix, in this order.

### 2a. Credential probe — `scripts/verify_auth.sh`

`verify_auth.sh` prefers ByteLLM when `BYTELLM_API_KEY` or
`BYTELLM_PROXY_API_KEY` is set. That path probes the protected
`/v1/messages/count_tokens` endpoint with bearer and `x-api-key` headers, so a
stale proxy key fails before the live matrix starts. When no ByteLLM key is
set, it falls back to a real HTTP `/v1/models` (or Moonshot equivalent) call
against each baseline provider whose key is set:

- `BYTELLM_API_KEY` / `BYTELLM_PROXY_API_KEY` → `${BYTELLM_BASE_URL}` or the root derived from `OPENAI_BASE_URL`
- `ANTHROPIC_API_KEY` → `https://api.anthropic.com/v1/models`
- `OPENAI_API_KEY` → `https://api.openai.com/v1/models`
- `MOONSHOT_API_KEY` → `${MOONSHOT_BASE_URL:-https://api.moonshot.ai/v1}/models`

Semantics (generic, not provider-specific):

- **No baseline key set** → exits `0`, prints `nothing to probe`. Safe no-op,
  e.g. when you only route through a local gateway.
- **Key set + HTTP probe succeeds** → exits `0`.
- **Key set + HTTP probe fails** → exits non-zero with the provider name.
  This is the only failure mode; it never claims success without a real call.

Keys are masked to the last 4 chars in stderr. Run it directly:

```bash
bash scripts/verify_auth.sh
```

### 2b. Outbound proxy — `HTTP_PROXY` / `NO_PROXY`

`dev-box-cpu` commonly reaches providers through a forward proxy. The control
plane forwards proxy env vars into Harbor task containers when
`BENCHEVAL_HARBOR_FORWARD_PROXY=1` (the matrix sets this by default). The
forwarded set is `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY` (and lowercase
variants); `NO_PROXY` is also injected per-agent via `--agent-env`.

Generic checklist:

```bash
# 1. Export both upper- and lowercase variants; libraries differ.
export HTTP_PROXY="http://your-proxy:port"
export HTTPS_PROXY="$HTTP_PROXY"
export NO_PROXY="127.0.0.1,localhost,.internal"
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"
export no_proxy="$NO_PROXY"

# 2. Confirm the proxy can actually reach a provider endpoint.
curl -fsS --max-time 10 https://api.openai.com/v1/models -H "Authorization: Bearer $OPENAI_API_KEY" >/dev/null

# 3. Then re-run the credential probe through the proxy.
bash scripts/verify_auth.sh
```

If you point providers at ByteLLM on `127.0.0.1:4000`, keep that host in
`NO_PROXY` so the proxy is not double-applied. Use `BYTELLM_API_KEY` as the
client proxy key. The matrix maps it to `ANTHROPIC_AUTH_TOKEN` for Claude Code
and to the Codex provider key as **dummy runtime credentials**; the host shim
injects the real ByteLLM key upstream via `BENCHEVAL_SHIM_AUTH_TOKEN_ENV`.
This avoids exposing the real key through Harbor `docker compose exec -e ...`
process arguments. The matrix also derives `ANTHROPIC_BASE_URL` from
`OPENAI_BASE_URL` when only the `/v1` URL is set.
For Anthropic-compatible routers that require a top-level `system` field, set
`BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM=1` (the matrix then starts
`bencheval.anthropic_role_shim` and rewrites `ANTHROPIC_BASE_URL` for
containers).

### 2c. One-shot combined check

```bash
scripts/doctor-pilot.sh
```

Runs `verify_auth.sh` (unless `--no-auth`), then
`uv run bencheval doctor --profile pilot --model <model>` (harbor, docker,
`bfcl`, `mini-extra`, provider env). Equivalent to the native CLI:

```bash
uv run bencheval doctor --profile pilot --model "${BENCHEVAL_PILOT_MODEL}"
```

## 3. Running Phase B

```bash
cd /path/to/BenchEval
export BYTELLM_API_KEY='sk-...'                         # latest proxy key
export BYTELLM_BASE_URL='http://127.0.0.1:4000'         # or set OPENAI_BASE_URL=http://.../v1
export BENCHEVAL_PILOT_MODEL='gpt-5.3-codex-2026-02-24'
export BENCHEVAL_PILOT_CLAUDE_MODEL='gpt-5.3-codex-2026-02-24'
export BENCHEVAL_PILOT_CODEX_MODEL='gpt-5.3-codex-2026-02-24'

# Optional: Anthropic system-role shim, npm registry override, tool allowlist
export BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM=1
export BENCHEVAL_SHIM_AUTH_TOKEN_ENV=BYTELLM_PROXY_API_KEY
export BENCHEVAL_CLAUDE_CODE_NPM_REGISTRY='https://registry.npmjs.org/'
export BENCHEVAL_CLAUDE_CODE_ALLOWED_TOOLS='Bash,Read,Write'

./scripts/run-live-pilot-matrix.sh
```

What it does, per step:

- `terminal-bench` lanes (`claude-code`, `codex-cli`): `bencheval doctor
  --backend harbor --model <m> --profile E2` then `bencheval run
  --benchmark terminal-bench --slice smoke-5 --runtime <rt>`. On doctor fail
  → preflight record + step fails. On run fail → artifacts emitted, step
  fails.
- `bfcl-v4` lane: skipped-with-preflight if `bfcl` is not on `PATH`;
  otherwise `bencheval run --benchmark bfcl-v4 --slice smoke-5
  --runtime native-api`.
- `swe-bench-verified` lane: skipped-with-preflight if `mini-extra` missing
  or Docker unavailable; otherwise `bencheval run --runtime mini-swe-agent`.
- Compare: only when **both** TB lanes produced evidence, runs
  `bencheval compare` of `tb-claude-code-<stamp>` vs `tb-codex-cli-<stamp>`.

Artifacts written under `results/` (all gitignored):

- `evidence/*.jsonl` — vNext `EvidenceRecord` lines (primary scoring input)
- `reports/*.md` — human-readable per-run reports
- `bundles/<tag>/` — `export-run --redaction private` redacted bundles
- `compare/*.md` — runtime compare reports
- `preflight/*.json` — `preflight_v1` negative evidence for blocked steps
- `raw/<tag>/` — adapter raw outputs (private)

## 4. Minimum live evidence checklist (exit codes)

The matrix exits with a code that encodes how much proof was collected.
Treat the exit code as the definition of done, then verify the files exist.

| Exit | Meaning | Required evidence present |
|---|---|---|
| `0` | **Full proof** | `evidence/tb-claude-code-<s>.jsonl`, `evidence/tb-codex-cli-<s>.jsonl`, `compare/tb-runtime-<s>.md`, `evidence/bfcl-smoke5-<s>.jsonl` |
| `0` | **TB proof, BFCL waived** | TB×2 + compare present; BFCL missing; `BENCHEVAL_ALLOW_PREFLIGHT_ONLY=1` set |
| `0` | **Preflight-only** | No live evidence; only `preflight/*.json`; `BENCHEVAL_ALLOW_PREFLIGHT_ONLY=1`, `BLOCKED>0`, `FAILED=0` |
| `2` | **TB proof OK, BFCL missing, no waiver** | TB×2 + compare present; BFCL missing; waiver not set |
| `1` | **Minimum proof not met** | TB pair or compare incomplete |

The summary line tells you which row you hit:

```text
Pilot summary: passed=<n> blocked_preflight=<n> failed=<n> tb_compare=<0|1>
Live pilot minimum proof: OK (TB×2 + compare + BFCL)        # full
Live pilot: TB proof OK; BFCL waived (...)                   # waived
Live pilot: preflight-only mode (no live evidence)           # preflight-only
```

Verify the same-`model_id` invariant before treating a compare as
runtime-only: open both TB evidence files and confirm the `model_id` field is
identical. Harbor agents can bind different model aliases per runtime; if the
axes drift, `bencheval compare` exits with a dual-axis error rather than
producing a misleading runtime delta.

## 5. Registering a manual one-off run

Record a manual one-off run by following the matrix's file conventions so the same
report/compare/export tooling picks it up:

1. Run the lane directly:

   ```bash
   STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
   uv run bencheval run \
       --benchmark terminal-bench --slice smoke-5 --runtime codex-cli \
       --model "$BENCHEVAL_PILOT_MODEL" \
       --output "results/evidence/tb-codex-cli-${STAMP}.jsonl" \
       --artifacts-dir "results/raw/tb-codex-cli-${STAMP}"
   ```

2. Name the evidence file `<benchmark>-<runtime>-<stamp>.jsonl` under
   `results/evidence/` so `report`/`compare`/`export-run` resolve it the same
   way the matrix does.

3. For a blocked one-off (e.g. doctor or Docker unavailable), write a
   preflight record instead of an evidence file:

   ```bash
   uv run python scripts/write_preflight.py \
       --output "results/preflight/tb-codex-cli-${STAMP}.json" \
       --benchmark terminal-bench --slice smoke-5 --runtime codex-cli \
       --model "$BENCHEVAL_PILOT_MODEL" --ok false \
       --reason "docker not available"
   ```

4. Audit ledger (gitignored JSONL):

   ```bash
   uv run bencheval evidence register \
       --run-id "tb-codex-cli-${STAMP}" \
       --benchmark terminal-bench --slice smoke-5 --runtime codex-cli \
       --model "${BENCHEVAL_PILOT_MODEL}" \
       --evidence "results/evidence/tb-codex-cli-${STAMP}.jsonl" \
       --report "results/reports/tb-codex-cli-${STAMP}.md" \
       --status passed \
       --notes "manual one-off on dev-box"
   ```

   See `results/manifests/README.md`. Example Peer run:
   `tb-claude-code-haiku-one-20260618T150500Z` with `--model claude-haiku-4-5`,
   `--slice smoke-5`, `--status passed`.

Compare and report against a manual run exactly as the matrix does:

```bash
uv run bencheval report results/evidence/tb-codex-cli-<stamp>.jsonl \
    --output results/reports/tb-codex-cli-<stamp>.md
uv run bencheval compare \
    results/evidence/tb-claude-code-<stamp>.jsonl \
    results/evidence/tb-codex-cli-<stamp>.jsonl \
    --format md --output results/compare/tb-runtime-<stamp>.md
```

## 6. `BENCHEVAL_ALLOW_PREFLIGHT_ONLY` semantics

This flag controls whether a run with **no live evidence** is acceptable.
It never converts a failure into a pass; it only relaxes the
"live evidence required" gate.

| Situation | Without flag | With `=1` |
|---|---|---|
| Full proof (TB×2 + compare + BFCL) | exit `0` | exit `0` |
| TB×2 + compare, **BFCL missing** | **exit `2`** | exit `0` (BFCL waived) |
| Some steps **blocked** (`BLOCKED>0`), **none failed** (`FAILED=0`) | exit `1` | exit `0` (preflight-only) |
| Any step **failed** (`FAILED>0`) | exit `1` | **exit `1`** — failures are never waived |

Rules of thumb:

- Leave it unset for a real Phase B gate — you want exit `0` to mean "live
  proof collected".
- Set `=1` only for credential/Docker-blocked environments where preflight
  negative evidence is the intended artifact, or to waive BFCL when TB proof
  is the actual goal. It still requires `FAILED=0`; a true run failure is
  never waived.
- Exit `2` specifically means "TB proof is good, just set the flag to accept
  the missing BFCL lane" — re-running with `BENCHEVAL_ALLOW_PREFLIGHT_ONLY=1`
  is the documented remedy.

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `verify_auth.sh` non-zero for a set key | proxy / key / network | re-run proxy checklist (§2b); confirm key in `.env` |
| Harbor doctor `fail` | `harbor` CLI not installed | `uv sync --extra eval` |
| Docker doctor `fail` | daemon down / socket perms | `docker info`; start daemon |
| Compare exits with dual-axis error | TB runtimes used different `model_id` | set `BENCHEVAL_PILOT_CLAUDE_MODEL`/`_CODEX_MODEL` to the same alias |
| BFCL lane preflighted | `bfcl` not on `PATH` or the `bfcl-eval` install is broken | install/repair `bfcl-eval`; or accept TB-only with the waiver flag |
| Anthropic router rejects `messages[].role=system` | needs top-level `system` | `BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM=1` |
| npm slow inside TB container | default registry throttled | `BENCHEVAL_CLAUDE_CODE_NPM_REGISTRY` |
