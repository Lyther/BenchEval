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

# Analytics export is a product path. Fail instead of silently skipping its real
# PyArrow/DuckDB round trips when the optional production-gate extra is absent.
run uv run --no-sync python -c 'import duckdb, pyarrow'
run ./scripts/check-domain-coverage.sh
run uv run --no-sync ruff check src tests scripts/
run uv run --no-sync ruff format --check src tests scripts/
run shellcheck scripts/*.sh
run bash -n scripts/*.sh
run uv lock --check

payload="$(uv run --no-sync bencheval benchmark list --execution-support executable_adapter --format json)"
count="$(printf '%s' "${payload}" | uv run --no-sync python -c 'import json,sys; print(json.load(sys.stdin)["count"])')"
if [[ ${count} != "4" ]]; then
  printf 'error: expected 4 executable_adapter benchmarks, got %s\n' "${count}" >&2
  exit 1
fi

unknown_err="$(mktemp)"
trap 'rm -f "${unknown_err}"' EXIT
if uv run --no-sync bencheval run \
  no-such-benchmark/smoke-5 \
  --runtime claude-code \
  --model kimi-k2.7-code \
  --dry-run 2>"${unknown_err}"; then
  printf 'error: unknown benchmark run should fail before execute\n' >&2
  exit 1
fi
if ! grep -qiE 'benchmark not found|unknown' "${unknown_err}"; then
  printf 'error: unknown-benchmark stderr missing not-found hint:\n%s\n' "$(cat "${unknown_err}")" >&2
  exit 1
fi

printf 'check-production-v1: passed\n'
