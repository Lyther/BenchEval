#!/usr/bin/env bash
# Production package coverage gate. Coverage is supporting evidence; behavioral
# regressions remain the correctness oracle.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT

cd "${REPO_ROOT}"

COVERAGE_FILE="${TMPDIR:-/tmp}/bencheval-domain-coverage-$$"
readonly COVERAGE_FILE
export COVERAGE_FILE

cleanup() {
  if [[ -e ${COVERAGE_FILE} ]]; then
    rm -- "${COVERAGE_FILE}"
  fi
}
trap cleanup EXIT

# Timing assertions must retain their real threshold and run without instrumentation.
# Deselect only that assertion here; the complete production package remains measured.
uv run --no-sync coverage run --source=src/bencheval -m pytest -q \
  --deselect tests/test_config_cache.py::test_plan_control_plane_reuses_cache_across_calls
uv run --no-sync coverage report \
  --show-missing \
  --fail-under=80
uv run --no-sync pytest -q \
  tests/test_config_cache.py::test_plan_control_plane_reuses_cache_across_calls
