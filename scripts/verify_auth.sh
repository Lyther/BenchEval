#!/usr/bin/env bash
set -euo pipefail

warn() {
  echo "verify_auth: $*" >&2
}

die() {
  warn "error: $*"
  exit 1
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

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${MOONSHOT_API_KEY:-}" ]; then
  warn "no ANTHROPIC_API_KEY, OPENAI_API_KEY, or MOONSHOT_API_KEY set; nothing to probe"
  exit 0
fi

if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  warn "probing Anthropic (key $(mask_tail "${ANTHROPIC_API_KEY}"))"
  if ! curl --fail --silent --show-error --max-time 10 \
    -H "x-api-key: ${ANTHROPIC_API_KEY}" \
    -H "anthropic-version: 2023-06-01" \
    "https://api.anthropic.com/v1/models" >/dev/null; then
    die "Anthropic credential probe failed (HTTP)"
  fi
fi

if [ -n "${OPENAI_API_KEY:-}" ]; then
  warn "probing OpenAI (key $(mask_tail "${OPENAI_API_KEY}"))"
  if ! curl --fail --silent --show-error --max-time 10 \
    -H "Authorization: Bearer ${OPENAI_API_KEY}" \
    -H "Content-Type: application/json" \
    "https://api.openai.com/v1/models" >/dev/null; then
    die "OpenAI credential probe failed (HTTP)"
  fi
fi

if [ -n "${MOONSHOT_API_KEY:-}" ]; then
  base="${MOONSHOT_BASE_URL:-https://api.moonshot.ai/v1}"
  base="${base%/}"
  url="${base}/models"
  warn "probing Moonshot at ${url} (key $(mask_tail "${MOONSHOT_API_KEY}"))"
  if ! curl --fail --silent --show-error --max-time 10 \
    -H "Authorization: Bearer ${MOONSHOT_API_KEY}" \
    "${url}" >/dev/null; then
    die "Moonshot credential probe failed (HTTP)"
  fi
fi

warn "all configured baseline credentials passed"
