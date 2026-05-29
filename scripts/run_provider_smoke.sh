#!/usr/bin/env bash
#
# run_provider_smoke.sh — bounded Inspect E0 provider smoke for Core-8 T1.
#
# Runs doctor per model, skips models without credentials, executes runnable
# models, and writes evidence/reports under results/.
#
# Usage:
#   BENCHEVAL_MODELS="openai/gpt-4o anthropic/claude-sonnet" ./scripts/run_provider_smoke.sh
#   ./scripts/run_provider_smoke.sh openai/gpt-4o anthropic/claude-sonnet
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly SCRIPT_DIR REPO_ROOT

readonly DEFAULT_TASK="be-core-t1-single-structured-call"
readonly DEFAULT_PROFILE="E0"
readonly DEFAULT_BACKEND="inspect"

readonly EVIDENCE_DIR="${BENCHEVAL_EVIDENCE_DIR:-results/evidence}"
readonly RAW_DIR="${BENCHEVAL_RAW_DIR:-results/raw}"
readonly REPORT_DIR="${BENCHEVAL_REPORT_DIR:-results/reports}"

TASK="${BENCHEVAL_SMOKE_TASK:-${DEFAULT_TASK}}"
PROFILE="${BENCHEVAL_SMOKE_PROFILE:-${DEFAULT_PROFILE}}"
BACKEND="${BENCHEVAL_SMOKE_BACKEND:-${DEFAULT_BACKEND}}"
RUN_ID="${BENCHEVAL_RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

log() {
  printf 'run_provider_smoke: %s\n' "$*" >&2
}

die() {
  log "error: $*"
  exit 1
}

usage() {
  cat >&2 <<EOF
Usage: $(basename "$0") [model_id ...]

Environment:
  BENCHEVAL_MODELS          Space-separated model ids (used when no args)
  BENCHEVAL_SMOKE_TASK      Task id (default: ${DEFAULT_TASK})
  BENCHEVAL_SMOKE_PROFILE   Doctor/run profile (default: ${DEFAULT_PROFILE})
  BENCHEVAL_SMOKE_BACKEND   Backend (default: ${DEFAULT_BACKEND}; inspect only)
  BENCHEVAL_RUN_ID          Run stamp for output paths (default: UTC timestamp)
  BENCHEVAL_EVIDENCE_DIR    Evidence root (default: results/evidence)
  BENCHEVAL_RAW_DIR         Artifacts root (default: results/raw)
  BENCHEVAL_REPORT_DIR      Report root (default: results/reports)

Models without provider credentials are reported as skipped, not failed runs.
Unknown doctor or configuration failures exit non-zero.
EOF
  exit 1
}

validate_config() {
  [[ "${BACKEND}" == "inspect" ]] || die "unsupported BENCHEVAL_SMOKE_BACKEND=${BACKEND} (inspect only)"
  [[ "${PROFILE}" == "E0" || "${PROFILE}" == "E1" || "${PROFILE}" == "E2" ]] \
    || die "unsupported BENCHEVAL_SMOKE_PROFILE=${PROFILE} (expected E0, E1, or E2)"
}

doctor_ok() {
  local model_id="$1"
  local report
  if ! report="$(uv run --no-sync bencheval doctor \
    --backend "${BACKEND}" \
    --model "${model_id}" \
    --profile "${PROFILE}" 2>&1)"; then
    :
  fi
  printf '%s' "${report}"
  if printf '%s' "${report}" | grep -q '"ok": true'; then
    return 0
  fi
  return 1
}

doctor_skip_reason() {
  local report="$1"
  if printf '%s' "${report}" | grep -q 'missing provider env'; then
    printf 'missing provider credentials'
    return 0
  fi
  if printf '%s' "${report}" | grep -q 'docker is required'; then
    printf 'docker unavailable'
    return 0
  fi
  if printf '%s' "${report}" | grep -q 'inspect_ai import failed'; then
    printf 'inspect_ai unavailable'
    return 0
  fi
  if printf '%s' "${report}" | grep -q 'inspect_ai is not installed'; then
    printf 'inspect_ai unavailable'
    return 0
  fi
  return 1
}

model_slug() {
  local model_id="$1"
  printf '%s' "${model_id}" | tr '/:' '__'
}

collect_models() {
  MODELS=()
  if [[ $# -gt 0 ]]; then
    while [[ $# -gt 0 ]]; do
      MODELS+=("$1")
      shift
    done
    return 0
  fi
  if [[ -n "${BENCHEVAL_MODELS:-}" ]]; then
    # shellcheck disable=SC2206
    MODELS=(${BENCHEVAL_MODELS})
    return 0
  fi
  return 1
}

main() {
  cd "${REPO_ROOT}" || die "failed to cd to repo root"

  if ! collect_models "$@"; then
    usage
  fi

  validate_config

  mkdir -p "${EVIDENCE_DIR}" "${RAW_DIR}" "${REPORT_DIR}"

  local skipped=0
  local ran=0
  local failed=0

  log "run_id=${RUN_ID} task=${TASK} profile=${PROFILE} backend=${BACKEND}"
  log "models: ${MODELS[*]}"

  local model_id
  for model_id in "${MODELS[@]}"; do
    local slug
    slug="$(model_slug "${model_id}")"
    local evidence_path="${EVIDENCE_DIR}/${RUN_ID}-${slug}.jsonl"
    local artifacts_path="${RAW_DIR}/${RUN_ID}-${slug}"
    local report_path="${REPORT_DIR}/${RUN_ID}-${slug}.md"
    local doctor_report

    log "doctor ${model_id} ..."
    if doctor_report="$(doctor_ok "${model_id}")"; then
      log "run ${model_id} -> ${evidence_path}"
      mkdir -p "${artifacts_path}"
      if uv run --no-sync bencheval run \
        --task "${TASK}" \
        --backend "${BACKEND}" \
        --model "${model_id}" \
        --output "${evidence_path}" \
        --artifacts-dir "${artifacts_path}" 2>&1 | tee "${artifacts_path}/run.log" >/dev/null; then
        uv run --no-sync bencheval report "${evidence_path}" --output "${report_path}" >/dev/null
        log "pass ${model_id} evidence=${evidence_path} report=${report_path}"
        ran=$((ran + 1))
      else
        log "fail ${model_id} (run exited non-zero; see ${artifacts_path}/run.log)"
        failed=$((failed + 1))
      fi
    else
      local reason
      if reason="$(doctor_skip_reason "${doctor_report}")"; then
        log "skip ${model_id}: ${reason}"
        log "doctor: ${doctor_report}"
        skipped=$((skipped + 1))
      else
        log "fail ${model_id}: doctor failed unexpectedly"
        log "doctor: ${doctor_report}"
        failed=$((failed + 1))
      fi
    fi
  done

  log "summary ran=${ran} skipped=${skipped} failed=${failed}"

  if [[ "${failed}" -gt 0 ]]; then
    exit 1
  fi
  if [[ "${ran}" -eq 0 && "${skipped}" -gt 0 ]]; then
    log "no runnable models; all skipped due to preflight blockers"
    exit 0
  fi
  if [[ "${ran}" -eq 0 ]]; then
    die "no models processed"
  fi
}

main "$@"
