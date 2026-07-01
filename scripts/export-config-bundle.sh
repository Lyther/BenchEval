#!/usr/bin/env bash
# Copy the control-plane config tree for wheel-only installs (BENCHEVAL_HOME).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT
readonly DEST="${1:-}"

if [[ -z ${DEST} ]]; then
  printf 'Usage: %s <bundle-dest-dir>\n' "$(basename "$0")" >&2
  printf 'Then: export BENCHEVAL_HOME=<bundle-dest-dir>\n' >&2
  exit 1
fi

if ! command -v rsync >/dev/null 2>&1; then
  printf 'error: rsync is required on PATH\n' >&2
  exit 1
fi

mkdir -p "${DEST}/config/runtimes" "${DEST}/config/slices" "${DEST}/config/manifests"
rsync -a \
  "${REPO_ROOT}/config/benchmarks.yaml" \
  "${REPO_ROOT}/config/models.yaml" \
  "${REPO_ROOT}/config/suites.yaml" \
  "${DEST}/config/"
rsync -a "${REPO_ROOT}/config/runtimes/" "${DEST}/config/runtimes/"
rsync -a "${REPO_ROOT}/config/slices/" "${DEST}/config/slices/"
rsync -a "${REPO_ROOT}/config/manifests/" "${DEST}/config/manifests/"
printf 'Bundle written to %s\n' "${DEST}"
