#!/usr/bin/env bash
# Production v1 internal-pilot gate (no live Harbor/Docker required).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT

cd "${REPO_ROOT}"

run() {
  printf '+ %s\n' "$*"
  "$@"
}

run uv run --no-sync pytest -q
run uv run --no-sync ruff check src tests scripts/
run uv run --no-sync ruff format --check src tests scripts/
run shellcheck scripts/*.sh
run bash -n scripts/*.sh
run uv lock --check

payload="$(uv run --no-sync bencheval benchmark list --execution-support executable_adapter --format json)"
count="$(printf '%s' "${payload}" | uv run --no-sync python -c 'import json,sys; print(json.load(sys.stdin)["count"])')"
if [[ ${count} != "3" ]]; then
  printf 'error: expected 3 executable_adapter benchmarks, got %s\n' "${count}" >&2
  exit 1
fi

cybench_err="$(mktemp)"
trap 'rm -f "${cybench_err}"' EXIT
if uv run --no-sync bencheval run \
  --benchmark cybench \
  --slice cybench-smoke-5 \
  --runtime native-api \
  --model openai/gpt-test \
  --output /tmp/bencheval-cybench-nope.jsonl 2>"${cybench_err}"; then
  printf 'error: cybench run should fail before execute\n' >&2
  exit 1
fi
if ! grep -qiE 'metadata_only|execution_support' "${cybench_err}"; then
  printf 'error: cybench stderr missing execution_support hint:\n%s\n' "$(cat "${cybench_err}")" >&2
  exit 1
fi

printf 'check-production-v1: passed\n'
