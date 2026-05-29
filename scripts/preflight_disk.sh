#!/usr/bin/env bash
set -euo pipefail

runtime="${BENCHEVAL_RUNTIME:-local}"
if [ "${runtime}" = "harbor" ]; then
  exit 0
fi

target="${BENCHEVAL_RESULTS_RAW:-results/raw}"
script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "${script_dir}/.." && pwd)"
dir="${repo_root}/${target}"
mkdir -p "${dir}"

# POSIX: df -P -k prints 1024-byte blocks; Available is column 4 on line 2.
avail_kb="$(df -P -k "${dir}" | awk 'NR==2 {print $4}')"
need_kb=$((100 * 1024 * 1024))

if [ "${avail_kb}" -lt "${need_kb}" ]; then
  echo "preflight_disk: need >= 100 GiB free for ${dir} (avail_kib=${avail_kb}, need_kib=${need_kb})" >&2
  exit 1
fi
