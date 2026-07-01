#!/usr/bin/env bash
# Micro-benchmarks for control-plane hot paths (verify-performance).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
readonly REPO_ROOT

cd "${REPO_ROOT}"

export PYTHONPATH="${REPO_ROOT}/src:${PYTHONPATH:-}"

printf '=== BenchEval verify-performance ===\n'
printf 'Host: %s\n' "$(hostname)"
printf 'Python: %s\n' "$(uv run python -V 2>&1)"

uv run python - <<'PY'
from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime

from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import load_benchmark_catalog
from bencheval.config_cache import clear_config_loader_caches
from bencheval.evidence import EvidenceRecord
from bencheval.evidence_compare import compare_evidence_runs


def bench(name: str, fn, *, iterations: int = 200) -> None:
    samples: list[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    p50 = samples[len(samples) // 2]
    p99 = samples[int(len(samples) * 0.99)]
    mean = statistics.fmean(samples)
    print(f"{name}: n={iterations} mean={mean:.3f}ms p50={p50:.3f}ms p99={p99:.3f}ms")


clear_config_loader_caches()
bench("load_benchmark_catalog(cold)", load_benchmark_catalog, iterations=5)
bench("load_benchmark_catalog(warm)", load_benchmark_catalog, iterations=50)

clear_config_loader_caches()
plan_control_plane(
    benchmark_id="bfcl-v4",
    slice_id="smoke-5",
    runtime_id="native-api",
    model_id="openai/gpt-test",
)
bench(
    "plan_control_plane(bfcl warm)",
    lambda: plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id="native-api",
        model_id="openai/gpt-test",
    ),
)

bench(
    "plan_control_plane(terminal-bench warm)",
    lambda: plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="runtime-default",
    ),
)


def _row(task_id: str, *, passed: bool = True) -> EvidenceRecord:
    return EvidenceRecord(
        run_id="r",
        task_id=task_id,
        model_id="mockllm/model",
        execution_profile="E0",
        backend="local",
        primary_pass=passed,
        partial_score=1.0 if passed else 0.0,
        cost_usd=0.0,
        latency_sec=0.1,
        failure_labels=[],
        artifact_paths=[],
        verifier_log_path=None,
        adapter_metadata={},
        created_at=datetime(2026, 5, 29, tzinfo=UTC),
    )


baseline = [_row(f"task-{i}") for i in range(50)]
current = [_row(f"task-{i}", passed=(i % 2 == 0)) for i in range(50)]

bench(
    "compare_evidence_runs(50 rows)",
    lambda: compare_evidence_runs(baseline, current),
    iterations=100,
)
PY

printf '\n=== pytest timing (domain subset) ===\n'
/usr/bin/time -p uv run pytest -q \
  tests/test_benchmark_plan.py \
  tests/test_evidence_compare.py \
  tests/test_model_compare.py \
  tests/test_runtime_compare.py \
  tests/test_paths.py \
  2>&1 | tail -8

printf '\n=== full suite (wall clock) ===\n'
/usr/bin/time -p uv run pytest -q 2>&1 | tail -5
