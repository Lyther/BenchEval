#!/usr/bin/env bash
# Phase B pilot doctor: harbor/docker/bfcl/mini-extra + optional provider creds.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT

usage() {
    cat >&2 <<EOF
Usage: $(basename "${BASH_SOURCE[0]}") [--model MODEL] [--no-auth]

Runs: uv run bencheval doctor --profile pilot [--model MODEL]
Optionally runs scripts/verify_auth.sh first (baseline provider probe).

Environment:
  BENCHEVAL_PILOT_MODEL  default model when --model omitted
EOF
    exit 1
}

model="${BENCHEVAL_PILOT_MODEL:-openai/gpt-test}"
verify_auth=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)
            [[ $# -ge 2 ]] || usage
            model="$2"
            shift 2
            ;;
        --no-auth)
            verify_auth=0
            shift
            ;;
        -h | --help)
            usage
            ;;
        *)
            printf 'doctor-pilot: unknown argument: %s\n' "$1" >&2
            usage
            ;;
    esac
done

cd "${REPO_ROOT}"

if [[ "${verify_auth}" -eq 1 ]]; then
    if ! "${SCRIPT_DIR}/verify_auth.sh"; then
        printf 'doctor-pilot: verify_auth.sh failed; fix baseline credentials before the pilot\n' >&2
        exit 1
    fi
fi

if ! uv run --no-sync bencheval doctor --profile pilot --model "${model}"; then
    exit 1
fi

printf 'doctor-pilot: OK\n'
