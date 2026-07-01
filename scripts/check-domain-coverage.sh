#!/usr/bin/env bash
# Domain modules gate (excludes cli.py and other boilerplate).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT

cd "${REPO_ROOT}"
uv run pytest -q \
  --cov=bencheval.paths \
  --cov=bencheval.path_safety \
  --cov=bencheval.control_plane_executor \
  --cov=bencheval.evidence_compare \
  --cov-report=term-missing \
  --cov-fail-under=80
