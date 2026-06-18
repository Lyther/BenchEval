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
readonly TB_CLAUDE_MODEL="${BENCHEVAL_PILOT_CLAUDE_MODEL:-${MODEL}}"
readonly TB_CODEX_MODEL="${BENCHEVAL_PILOT_CODEX_MODEL:-${MODEL}}"
readonly BFCL_MODEL="${BENCHEVAL_PILOT_BFCL_MODEL:-${MODEL}}"
readonly SWE_MODEL="${BENCHEVAL_PILOT_SWE_MODEL:-${MODEL}}"
export BENCHEVAL_HARBOR_FORWARD_PROXY="${BENCHEVAL_HARBOR_FORWARD_PROXY:-1}"

PASSED=0
BLOCKED=0
FAILED=0
SHIM_PID=""

# Invoked indirectly by the EXIT trap.
# shellcheck disable=SC2317,SC2329
cleanup() {
    if [[ -n "${SHIM_PID}" ]]; then
        kill "${SHIM_PID}" 2>/dev/null || true
        wait "${SHIM_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

cd "${REPO_ROOT}"
mkdir -p results/evidence results/raw results/reports results/bundles results/preflight results/compare

start_anthropic_role_shim() {
    [[ "${BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM:-}" == "1" ]] || return 0

    local host="${BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM_HOST:-127.0.0.1}"
    local port="${BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM_PORT:-4011}"
    local upstream="${BENCHEVAL_ANTHROPIC_UPSTREAM:-http://127.0.0.1:4000}"
    local docker_host="${BENCHEVAL_DOCKER_HOST_GATEWAY:-172.17.0.1}"
    local log="results/raw/anthropic-role-shim-${STAMP}.log"

    uv run --no-sync python -m bencheval.anthropic_role_shim \
        --host "${host}" --port "${port}" --upstream "${upstream}" >"${log}" 2>&1 &
    SHIM_PID="$!"

    local ready=0
    for _ in {1..50}; do
        if curl -fsS "http://${host}:${port}/healthz" >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 0.1
    done
    if [[ "${ready}" -ne 1 ]]; then
        printf 'error: Anthropic role shim did not become ready; see %s\n' "${log}" >&2
        exit 1
    fi

    export ANTHROPIC_BASE_URL="http://${docker_host}:${port}"
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

    [[ -s "${evidence}" ]] || return 0
    uv run --no-sync bencheval report "${evidence}" --output "results/reports/${tag}.md"
    if [[ -d "${raw}" ]]; then
        uv run --no-sync bencheval export-run \
            --evidence "${evidence}" --raw-dir "${raw}" \
            --output "results/bundles/${tag}" --redaction private
    fi
}

run_tb() {
    local runtime="$1"
    local model="${MODEL}"
    if [[ "${runtime}" == "claude-code" ]]; then
        model="${TB_CLAUDE_MODEL}"
    elif [[ "${runtime}" == "codex-cli" ]]; then
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
        FAILED=$((FAILED + 1))
        return 1
    fi
    if ! uv run --no-sync bencheval run \
        --benchmark terminal-bench --slice smoke-5 --runtime "${runtime}" \
        --model "${model}" --output "${evidence}" --artifacts-dir "${raw}"; then
        emit_artifacts "${tag}" "${evidence}" "${raw}" || true
        FAILED=$((FAILED + 1))
        return 1
    fi
    emit_artifacts "${tag}" "${evidence}" "${raw}"
    PASSED=$((PASSED + 1))
}

run_bfcl() {
    local tag="bfcl-smoke5-${STAMP}"
    local evidence="results/evidence/${tag}.jsonl"
    local raw="results/raw/${tag}"
    if ! command -v bfcl-eval >/dev/null 2>&1; then
        preflight "results/preflight/${tag}.json" \
            --benchmark bfcl-v4 --slice smoke-5 --runtime native-api \
            --model "${BFCL_MODEL}" --ok false --reason "bfcl-eval not on PATH"
        return 1
    fi
    if ! uv run --no-sync bencheval run \
        --benchmark bfcl-v4 --slice smoke-5 --runtime native-api \
        --model "${BFCL_MODEL}" --output "${evidence}" --artifacts-dir "${raw}"; then
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
            --runtime mini-swe-agent --model "${SWE_MODEL}" --ok false \
            --reason "mini-extra not on PATH"
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        preflight "results/preflight/${tag}.json" \
            --benchmark swe-bench-verified --slice swe-bench-verified-smoke-10 \
            --runtime mini-swe-agent --model "${SWE_MODEL}" --ok false \
            --reason "docker not available"
        return 1
    fi
    if ! uv run --no-sync bencheval run \
        --benchmark swe-bench-verified --slice swe-bench-verified-smoke-10 \
        --runtime mini-swe-agent --model "${SWE_MODEL}" \
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

printf 'Pilot matrix stamp=%s default_model=%s tb_claude_model=%s tb_codex_model=%s\n' \
    "${STAMP}" "${MODEL}" "${TB_CLAUDE_MODEL}" "${TB_CODEX_MODEL}"
start_anthropic_role_shim

TB_CC=0
TB_CX=0
if run_tb claude-code; then
    TB_CC=1
fi
if run_tb codex-cli; then
    TB_CX=1
fi
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
