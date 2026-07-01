#!/usr/bin/env bash
set -euo pipefail

warn() {
  echo "verify_auth: $*" >&2
}

die() {
  warn "error: $*"
  exit 1
}

curl_probe() {
  curl --noproxy "127.0.0.1,localhost,::1,0.0.0.0,172.17.0.1,host.docker.internal" \
    --fail --silent --show-error --max-time 10 "$@"
}

mask_tail() {
  local v="${1:-}"
  local n="${#v}"
  if [ "$n" -le 4 ]; then
    printf '****'
  else
    printf '****%s' "${v: -4}"
  fi
}

models_url_from_base() {
  local base="${1:-}"
  base="${base%/}"
  if [[ ${base} == */v1 ]]; then
    printf '%s/models' "${base}"
  else
    printf '%s/v1/models' "${base}"
  fi
}

root_from_v1_base() {
  local base="${1:-}"
  base="${base%/}"
  if [[ ${base} == */v1 ]]; then
    printf '%s' "${base%/v1}"
  else
    printf '%s' "${base}"
  fi
}

probe_bytellm() {
  local key="$1"
  local base="${BYTELLM_BASE_URL:-}"
  if [ -z "${base}" ] && [ -n "${ANTHROPIC_BASE_URL:-}" ]; then
    base="$(root_from_v1_base "${ANTHROPIC_BASE_URL}")"
  fi
  if [ -z "${base}" ] && [ -n "${OPENAI_BASE_URL:-}" ]; then
    base="$(root_from_v1_base "${OPENAI_BASE_URL}")"
  fi
  base="${base:-http://127.0.0.1:4000}"
  base="${base%/}"
  warn "probing ByteLLM at ${base} (key $(mask_tail "${key}"))"
  if ! curl_probe \
    -X POST \
    -H "Authorization: Bearer ${key}" \
    -H "x-api-key: ${key}" \
    -H "anthropic-version: 2023-06-01" \
    -H "Content-Type: application/json" \
    --data '{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"hello"}]}' \
    "${base}/v1/messages/count_tokens" >/dev/null; then
    die "ByteLLM credential probe failed (HTTP)"
  fi
}

bytellm_key="${BYTELLM_API_KEY:-${BYTELLM_PROXY_API_KEY:-}}"
if [ -n "${bytellm_key}" ]; then
  probe_bytellm "${bytellm_key}"
  warn "all configured ByteLLM credentials passed"
  exit 0
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${MOONSHOT_API_KEY:-}" ]; then
  warn "no BYTELLM_API_KEY, BYTELLM_PROXY_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY, or MOONSHOT_API_KEY set; nothing to probe"
  exit 0
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  anthropic_base="${ANTHROPIC_BASE_URL:-https://api.anthropic.com/v1}"
  anthropic_url="$(models_url_from_base "${anthropic_base}")"
  warn "probing Anthropic at ${anthropic_url} (key $(mask_tail "${ANTHROPIC_API_KEY}"))"
  if ! curl_probe \
    -H "x-api-key: ${ANTHROPIC_API_KEY}" \
    -H "anthropic-version: 2023-06-01" \
    "${anthropic_url}" >/dev/null; then
    die "Anthropic credential probe failed (HTTP)"
  fi
fi

if [ -n "${OPENAI_API_KEY:-}" ]; then
  openai_base="${OPENAI_BASE_URL:-https://api.openai.com/v1}"
  openai_url="$(models_url_from_base "${openai_base}")"
  warn "probing OpenAI at ${openai_url} (key $(mask_tail "${OPENAI_API_KEY}"))"
  if ! curl_probe \
    -H "Authorization: Bearer ${OPENAI_API_KEY}" \
    -H "Content-Type: application/json" \
    "${openai_url}" >/dev/null; then
    die "OpenAI credential probe failed (HTTP)"
  fi
fi

if [ -n "${MOONSHOT_API_KEY:-}" ]; then
  base="${MOONSHOT_BASE_URL:-https://api.moonshot.ai/v1}"
  base="${base%/}"
  url="${base}/models"
  warn "probing Moonshot at ${url} (key $(mask_tail "${MOONSHOT_API_KEY}"))"
  if ! curl_probe \
    -H "Authorization: Bearer ${MOONSHOT_API_KEY}" \
    "${url}" >/dev/null; then
    die "Moonshot credential probe failed (HTTP)"
  fi
fi

warn "all configured baseline credentials passed"
