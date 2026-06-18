#!/usr/bin/env bash
# Phase B: live control-plane pilot (native subprocesses). Credential/Docker gated.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
readonly STAMP
readonly MODEL="${BENCHEVAL_PILOT_MODEL:-openai/gpt-test}"

PASSED=0
BLOCKED=0
FAILED=0

cd "${REPO_ROOT}"
mkdir -p results/evidence results/raw results/reports results/bundles results/preflight results/compare

preflight() {
    local out="$1"
    shift
    uv run --no-sync python "${SCRIPT_DIR}/write_preflight.py" --output "${out}" "$@"
    BLOCKED=$((BLOCKED + 1))
}

run_tb() {
    local runtime="$1"
    local tag="tb-${runtime}-${STAMP}"
    local evidence="results/evidence/${tag}.jsonl"
    local raw="results/raw/${tag}"
    if ! uv run --no-sync bencheval doctor --backend harbor --model "${MODEL}" --profile E4; then
        preflight "results/preflight/${tag}.json" \
            --benchmark terminal-bench --slice smoke-5 --runtime "${runtime}" \
            --model "${MODEL}" --ok false --doctor-backend harbor \
            --reason "harbor doctor failed"
        FAILED=$((FAILED + 1))
        return 1
    fi
    if ! uv run --no-sync bencheval run \
        --benchmark terminal-bench --slice smoke-5 --runtime "${runtime}" \
        --model "${MODEL}" --output "${evidence}" --artifacts-dir "${raw}"; then
        FAILED=$((FAILED + 1))
        return 1
    fi
    uv run --no-sync bencheval report "${evidence}" --output "results/reports/${tag}.md"
    uv run --no-sync bencheval export-run \
        --evidence "${evidence}" --raw-dir "${raw}" \
        --output "results/bundles/${tag}" --redaction private
    PASSED=$((PASSED + 1))
}

run_bfcl() {
    local tag="bfcl-smoke5-${STAMP}"
    local evidence="results/evidence/${tag}.jsonl"
    local raw="results/raw/${tag}"
    if ! command -v bfcl-eval >/dev/null 2>&1; then
        preflight "results/preflight/${tag}.json" \
            --benchmark bfcl-v4 --slice smoke-5 --runtime native-api \
            --model "${MODEL}" --ok false --reason "bfcl-eval not on PATH"
        return 1
    fi
    if ! uv run --no-sync bencheval run \
        --benchmark bfcl-v4 --slice smoke-5 --runtime native-api \
        --model "${MODEL}" --output "${evidence}" --artifacts-dir "${raw}"; then
        FAILED=$((FAILED + 1))
        return 1
    fi
    uv run --no-sync bencheval report "${evidence}" --output "results/reports/${tag}.md"
    uv run --no-sync bencheval export-run \
        --evidence "${evidence}" --raw-dir "${raw}" \
        --output "results/bundles/${tag}" --redaction private
    PASSED=$((PASSED + 1))
}

run_swe() {
    local tag="swe-smoke10-${STAMP}"
    local evidence="results/evidence/${tag}.jsonl"
    local raw="results/raw/${tag}"
    if ! command -v mini-extra >/dev/null 2>&1; then
        preflight "results/preflight/${tag}.json" \
            --benchmark swe-bench-verified --slice swe-bench-verified-smoke-10 \
            --runtime mini-swe-agent --model "${MODEL}" --ok false \
            --reason "mini-extra not on PATH"
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        preflight "results/preflight/${tag}.json" \
            --benchmark swe-bench-verified --slice swe-bench-verified-smoke-10 \
            --runtime mini-swe-agent --model "${MODEL}" --ok false \
            --reason "docker not available"
        return 1
    fi
    if ! uv run --no-sync bencheval run \
        --benchmark swe-bench-verified --slice swe-bench-verified-smoke-10 \
        --runtime mini-swe-agent --model "${MODEL}" \
        --output "${evidence}" --artifacts-dir "${raw}"; then
        FAILED=$((FAILED + 1))
        return 1
    fi
    uv run --no-sync bencheval report "${evidence}" --output "results/reports/${tag}.md"
    uv run --no-sync bencheval export-run \
        --evidence "${evidence}" --raw-dir "${raw}" \
        --output "results/bundles/${tag}" --redaction private
    PASSED=$((PASSED + 1))
}

printf 'Pilot matrix stamp=%s model=%s\n' "${STAMP}" "${MODEL}"

TB_CC=0
TB_CX=0
run_tb claude-code && TB_CC=1 || true
run_tb codex-cli && TB_CX=1 || true
run_bfcl || true
run_swe || true

COMPARE_OK=0
base="results/evidence/tb-claude-code-${STAMP}.jsonl"
cur="results/evidence/tb-codex-cli-${STAMP}.jsonl"
if [[ "${TB_CC}" -eq 1 && "${TB_CX}" -eq 1 ]]; then
    if uv run --no-sync bencheval compare "${base}" "${cur}" \
        --format md --output "results/compare/tb-runtime-${STAMP}.md"; then
        COMPARE_OK=1
    fi
fi

printf 'Pilot summary: passed=%s blocked_preflight=%s failed=%s tb_compare=%s\n' \
    "${PASSED}" "${BLOCKED}" "${FAILED}" "${COMPARE_OK}"

if [[ "${TB_CC}" -eq 1 && "${TB_CX}" -eq 1 && "${COMPARE_OK}" -eq 1 ]]; then
    bfcl_ev="results/evidence/bfcl-smoke5-${STAMP}.jsonl"
    if [[ -f "${bfcl_ev}" ]]; then
        printf 'Live pilot minimum proof: OK (TB×2 + compare + BFCL)\n'
        exit 0
    fi
    if [[ "${BENCHEVAL_ALLOW_PREFLIGHT_ONLY:-}" == "1" ]]; then
        printf 'Live pilot: TB proof OK; BFCL waived (BENCHEVAL_ALLOW_PREFLIGHT_ONLY=1)\n'
        exit 0
    fi
    printf 'error: TB proof OK but BFCL evidence missing (set BENCHEVAL_ALLOW_PREFLIGHT_ONLY=1 to waive)\n' >&2
    exit 2
fi

if [[ "${BENCHEVAL_ALLOW_PREFLIGHT_ONLY:-}" == "1" && "${BLOCKED}" -gt 0 && "${FAILED}" -eq 0 ]]; then
    printf 'Live pilot: preflight-only mode (no live evidence)\n'
    exit 0
fi

printf 'error: minimum live proof not met (need TB claude-code + codex-cli evidence and compare)\n' >&2
exit 1
