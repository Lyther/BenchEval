"""SWE-bench Pro adapter via Harbor dataset ``swebenchpro`` (host pulls images)."""

from __future__ import annotations

from pathlib import Path

from bencheval.domain import RunPlan
from bencheval.terminal_bench_harbor import (
    HarborProcessRunner,
    TerminalBenchInstanceOutcome,
    run_harbor_dataset_instance,
)

SWEBENCH_PRO_ADAPTER_ID = "swebench-pro-harbor"
SWEBENCH_PRO_HARBOR_DATASET = "swebenchpro"


def run_swebench_pro_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: HarborProcessRunner | None = None,
    timeout_sec: int | None = None,
) -> TerminalBenchInstanceOutcome:
    return run_harbor_dataset_instance(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=artifacts_dir,
        repo_root=repo_root,
        dataset=SWEBENCH_PRO_HARBOR_DATASET,
        expected_adapter_id=SWEBENCH_PRO_ADAPTER_ID,
        process_runner=process_runner,
        timeout_sec=timeout_sec,
    )


__all__ = [
    "SWEBENCH_PRO_ADAPTER_ID",
    "SWEBENCH_PRO_HARBOR_DATASET",
    "run_swebench_pro_instance",
]
