#!/usr/bin/env bash
# Phase B: live control-plane pilot (native subprocesses). Credential/Docker gated.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly STAMP
readonly MODEL="${BENCHEVAL_PILOT_MODEL:-kimi-k2.7-code}"
readonly TB_CLAUDE_MODEL="${BENCHEVAL_PILOT_CLAUDE_MODEL:-${MODEL}}"
readonly TB_CODEX_MODEL="${BENCHEVAL_PILOT_CODEX_MODEL:-${MODEL}}"
readonly TB_EXPECTED_INSTANCES="${BENCHEVAL_PILOT_TB_EXPECTED_INSTANCES:-5}"
export BENCHEVAL_HARBOR_FORWARD_PROXY="${BENCHEVAL_HARBOR_FORWARD_PROXY:-1}"

cd "${REPO_ROOT}"

if ! grep -Eq "^[[:space:]]*- id:[[:space:]]*${MODEL}[[:space:]]*$" \
  "${REPO_ROOT}/config/models.yaml"; then
  printf 'error: pilot model %s is not in config/models.yaml\n' "${MODEL}" >&2
  printf 'hint: uv run --no-sync bencheval catalog model list\n' >&2
  printf 'hint: set BENCHEVAL_PILOT_MODEL to a registered id (default: kimi-k2.7-code)\n' >&2
  exit 1
fi

PASSED=0
BLOCKED=0
FAILED=0
SHIM_PID=""

# Invoked indirectly by the EXIT trap.
# shellcheck disable=SC2317,SC2329
cleanup() {
  if [[ -n ${SHIM_PID} ]]; then
    kill "${SHIM_PID}" 2>/dev/null || true
    wait "${SHIM_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

mkdir -p results/evidence results/raw results/reports results/bundles results/preflight results/compare

root_from_v1_base() {
  local base="${1%/}"
  if [[ ${base} == */v1 ]]; then
    printf '%s\n' "${base%/v1}"
  else
    printf '%s\n' "${base}"
  fi
}

v1_from_root_base() {
  local base="${1%/}"
  if [[ ${base} == */v1 ]]; then
    printf '%s\n' "${base}"
  else
    printf '%s/v1\n' "${base}"
  fi
}

configure_bytellm_client_env() {
  local key="${BYTELLM_API_KEY:-${BYTELLM_PROXY_API_KEY:-}}"
  if [[ -n ${key} ]]; then
    export BYTELLM_PROXY_API_KEY="${key}"
    export OPENAI_API_KEY="${BENCHEVAL_DUMMY_RUNTIME_API_KEY:-bencheval-local-shim}"
    export ANTHROPIC_API_KEY="${BENCHEVAL_DUMMY_RUNTIME_API_KEY:-bencheval-local-shim}"
    export ANTHROPIC_AUTH_TOKEN="${BENCHEVAL_DUMMY_RUNTIME_API_KEY:-bencheval-local-shim}"
    export BENCHEVAL_SHIM_AUTH_TOKEN_ENV="${BENCHEVAL_SHIM_AUTH_TOKEN_ENV:-BYTELLM_PROXY_API_KEY}"
    export BENCHEVAL_OPENAI_VIA_ROLE_SHIM="${BENCHEVAL_OPENAI_VIA_ROLE_SHIM:-1}"
    export BENCHEVAL_CODEX_ENV_KEY="${BENCHEVAL_CODEX_ENV_KEY:-OPENAI_API_KEY}"
  fi

  local root_base="${BYTELLM_BASE_URL:-}"
  if [[ -z ${root_base} && -n ${ANTHROPIC_BASE_URL:-} ]]; then
    root_base="$(root_from_v1_base "${ANTHROPIC_BASE_URL}")"
  fi
  if [[ -z ${root_base} && -n ${OPENAI_BASE_URL:-} ]]; then
    root_base="$(root_from_v1_base "${OPENAI_BASE_URL}")"
  fi
  if [[ -n ${root_base} ]]; then
    export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-${root_base}}"
    export OPENAI_BASE_URL="${OPENAI_BASE_URL:-$(v1_from_root_base "${root_base}")}"
    export BENCHEVAL_ANTHROPIC_UPSTREAM="${BENCHEVAL_ANTHROPIC_UPSTREAM:-${root_base}}"
  fi
}

start_anthropic_role_shim() {
  [[ ${BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM:-} == "1" ]] || return 0

  local port="${BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM_PORT:-4011}"
  local upstream="${BENCHEVAL_ANTHROPIC_UPSTREAM:-http://127.0.0.1:4000}"
  local docker_host="${BENCHEVAL_DOCKER_HOST_GATEWAY:-172.17.0.1}"
  local host="${BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM_HOST:-${docker_host}}"
  local log="results/raw/anthropic-role-shim-${STAMP}.log"

  local shim_cmd=(
    uv run --no-sync python -m bencheval.anthropic_role_shim
    --host "${host}" --port "${port}" --upstream "${upstream}"
  )
  if [[ -n ${BENCHEVAL_SHIM_AUTH_TOKEN_ENV:-} ]]; then
    if [[ -z ${BENCHEVAL_SHIM_INBOUND_TOKEN:-} ]]; then
      BENCHEVAL_SHIM_INBOUND_TOKEN="$(openssl rand -hex 24)"
    fi
    export BENCHEVAL_SHIM_INBOUND_TOKEN
    shim_cmd+=(--auth-token-env "${BENCHEVAL_SHIM_AUTH_TOKEN_ENV}")
    shim_cmd+=(--inbound-token-env BENCHEVAL_SHIM_INBOUND_TOKEN)
    # Agents present the inbound capability; upstream secret stays in AUTH_TOKEN_ENV.
    export ANTHROPIC_API_KEY="${BENCHEVAL_SHIM_INBOUND_TOKEN}"
    export ANTHROPIC_AUTH_TOKEN="${BENCHEVAL_SHIM_INBOUND_TOKEN}"
    if [[ ${BENCHEVAL_OPENAI_VIA_ROLE_SHIM:-} == "1" ]]; then
      export OPENAI_API_KEY="${BENCHEVAL_SHIM_INBOUND_TOKEN}"
    fi
  fi
  "${shim_cmd[@]}" >"${log}" 2>&1 &
  SHIM_PID="$!"

  local ready=0
  for _ in {1..50}; do
    if curl -fsS "http://${host}:${port}/healthz" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 0.1
  done
  if [[ ${ready} -ne 1 ]]; then
    printf 'error: Anthropic role shim did not become ready; see %s\n' "${log}" >&2
    exit 1
  fi

  export ANTHROPIC_BASE_URL="http://${docker_host}:${port}"
  if [[ ${BENCHEVAL_OPENAI_VIA_ROLE_SHIM:-} == "1" ]]; then
    export OPENAI_BASE_URL="${ANTHROPIC_BASE_URL%/}/v1"
  fi
  printf 'Anthropic role shim enabled: upstream=%s container_base=%s\n' \
    "${upstream}" "${ANTHROPIC_BASE_URL}"
}

preflight() {
  local out="$1"
  shift
  uv run --no-sync python "${SCRIPT_DIR}/write_preflight.py" --output "${out}" "$@"
  BLOCKED=$((BLOCKED + 1))
}

emit_artifacts() {
  local tag="$1"
  local evidence="$2"
  local raw="$3"

  [[ -s ${evidence} ]] || return 0
  uv run --no-sync bencheval report "${evidence}" --output "results/reports/${tag}.md"
  if [[ -d ${raw} ]]; then
    uv run --no-sync bencheval export-run \
      --evidence "${evidence}" --raw-dir "${raw}" \
      --output "results/bundles/${tag}" --redaction private
  fi
}

require_qualified_lane() {
  local evidence="$1"
  local expected="$2"
  local tag="$3"
  shift 3
  local qstatus=0
  uv run --no-sync python -m bencheval.live_proof qualify-lane "${evidence}" \
    --expected "${expected}" "$@" || qstatus=$?
  if [[ ${qstatus} -eq 0 ]]; then
    return 0
  fi
  printf 'error: %s evidence did not qualify for live proof (exit %s)\n' \
    "${tag}" "${qstatus}" >&2
  return 1
}

run_tb() {
  local runtime="$1"
  local model="${MODEL}"
  if [[ ${runtime} == "claude-code" ]]; then
    model="${TB_CLAUDE_MODEL}"
  elif [[ ${runtime} == "codex-cli" ]]; then
    model="${TB_CODEX_MODEL}"
  fi
  local tag="tb-${runtime}-${STAMP}"
  local evidence="results/evidence/${tag}.jsonl"
  local raw="results/raw/${tag}"
  if ! uv run --no-sync bencheval doctor --backend harbor --model "${model}" --profile E2; then
    preflight "results/preflight/${tag}.json" \
      --benchmark terminal-bench --slice smoke-5 --runtime "${runtime}" \
      --model "${model}" --ok false --doctor-backend harbor \
      --reason "harbor doctor failed"
    return 1
  fi
  local run_status=0
  uv run --no-sync bencheval run "terminal-bench/smoke-5" \
    --runtime "${runtime}" \
    --model "${model}" -y --output "${evidence}" --artifacts-dir "${raw}" || run_status=$?
  emit_artifacts "${tag}" "${evidence}" "${raw}" || true
  if [[ ${run_status} -ne 0 ]]; then
    printf 'note: %s run exited %s; checking evidence completeness\n' \
      "${tag}" "${run_status}" >&2
  fi
  if ! require_qualified_lane "${evidence}" "${TB_EXPECTED_INSTANCES}" "${tag}" \
    --benchmark-id terminal-bench --slice-id smoke-5 --require-runtime; then
    FAILED=$((FAILED + 1))
    return 1
  fi
  PASSED=$((PASSED + 1))
}

printf 'Pilot matrix stamp=%s default_model=%s tb_claude_model=%s tb_codex_model=%s\n' \
  "${STAMP}" "${MODEL}" "${TB_CLAUDE_MODEL}" "${TB_CODEX_MODEL}"
configure_bytellm_client_env
start_anthropic_role_shim

TB_CC=0
TB_CX=0
# bfcl-v4 / swe-bench-verified are demoted (non-executable). Do not invoke them here:
# CLI refuse increments FAILED and poisons BENCHEVAL_ALLOW_PREFLIGHT_ONLY.
if run_tb claude-code; then
  TB_CC=1
fi
if run_tb codex-cli; then
  TB_CX=1
fi

COMPARE_OK=0
base="results/evidence/tb-claude-code-${STAMP}.jsonl"
cur="results/evidence/tb-codex-cli-${STAMP}.jsonl"
if [[ ${TB_CC} -eq 1 && ${TB_CX} -eq 1 ]]; then
  if uv run --no-sync bencheval compare "${base}" "${cur}" \
    --format md --output "results/compare/tb-runtime-${STAMP}.md"; then
    COMPARE_OK=1
  fi
fi

SHARED_ELIGIBLE=0
if [[ ${COMPARE_OK} -eq 1 ]]; then
  shared_count=""
  if shared_count="$(uv run --no-sync python -m bencheval.live_proof shared-instances \
    "${base}" "${cur}" --require-runtime)"; then
    SHARED_ELIGIBLE="${shared_count}"
  fi
fi

printf 'Pilot summary: passed=%s blocked_preflight=%s failed=%s tb_compare=%s shared_eligible=%s\n' \
  "${PASSED}" "${BLOCKED}" "${FAILED}" "${COMPARE_OK}" "${SHARED_ELIGIBLE}"

if [[ ${TB_CC} -eq 1 && ${TB_CX} -eq 1 && ${COMPARE_OK} -eq 1 && ${SHARED_ELIGIBLE} -ge 1 ]]; then
  printf 'Live pilot minimum proof: OK (TB runtime comparison on %s shared eligible instances)\n' \
    "${SHARED_ELIGIBLE}"
  exit 0
fi

if [[ ${BENCHEVAL_ALLOW_PREFLIGHT_ONLY:-} == "1" && ${BLOCKED} -gt 0 && ${FAILED} -eq 0 ]]; then
  printf 'Live pilot: preflight-only mode (no live evidence)\n'
  exit 0
fi

printf 'error: minimum live proof not met (need TB claude-code + codex-cli evidence and compare)\n' >&2
exit 1
