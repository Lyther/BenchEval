#!/usr/bin/env bash
# Compatibility launcher for the generic external-command runner.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT

cd "${REPO_ROOT}"

usage() {
  cat >&2 <<'EOF'
Usage: scripts/momo-cybench-live.sh [args...]

Compatibility wrapper for the CyBench Kilo external-command profile.
Prefer:
  scripts/external-command-run.sh --config config/runs/cybench-kilo-showcase.yaml

Required for live mode:
  MOMO_CYBENCH_RUN_ROOT   Prepared CyBench root containing run-prompts/ and keys/.

Common args:
  --dry-run               Validate config and private run root without launching Kilo.
  --replay EVENTS.jsonl   Replay a previously captured run record.
  --no-snapshot           Skip configured host metadata capture.

Example:
  MOMO_CYBENCH_RUN_ROOT=/tmp/bencheval-cybench-real-vps \
    scripts/momo-cybench-live.sh --dry-run
EOF
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

uv run --no-sync python -m bencheval.momo_cybench "$@"
