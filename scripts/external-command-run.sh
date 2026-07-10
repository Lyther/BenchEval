#!/usr/bin/env bash
# Run a BenchEval external-command profile.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT

cd "${REPO_ROOT}"

usage() {
  cat >&2 <<'EOF'
Usage: scripts/external-command-run.sh --config CONFIG [args...]

Runs a structured BenchEval external-command profile. The profile owns the
benchmark id, runtime id, model id, command template, stream parser, and
evidence layout.

Common args:
  --dry-run          Validate/print the resolved plan without launching.
  --run-root PATH    Prepared benchmark root when the config needs one.
  --results-root DIR Results root; default is results/.
  --no-snapshot      Disable configured host snapshot.

Example:
  scripts/external-command-run.sh \
    --config /path/to/external-command-profile.yaml \
    --dry-run
EOF
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exit 0
fi

uv run --no-sync bencheval run "$@"
