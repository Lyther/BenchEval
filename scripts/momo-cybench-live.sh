#!/usr/bin/env bash
# MOMO CyBench live terminal runner.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT

cd "${REPO_ROOT}"

usage() {
    cat >&2 <<'EOF'
Usage: scripts/momo-cybench-live.sh [args...]

Runs the MOMO CyBench terminal workflow through local Kilo + GLM 5.2.

Required for live mode:
  MOMO_CYBENCH_RUN_ROOT   Private prepared CyBench root containing run-prompts/ and keys/.

Common args:
  --dry-run               Validate config and private run root without launching Kilo.
  --replay EVENTS.jsonl   Replay a previously captured MOMO event stream.
  --no-remote-snapshot    Skip VPS docker/host metadata capture.

Example:
  MOMO_CYBENCH_RUN_ROOT=/tmp/bencheval-cybench-real-vps \
    scripts/momo-cybench-live.sh --dry-run
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
fi

uv run --no-sync python -m bencheval.momo_cybench "$@"
