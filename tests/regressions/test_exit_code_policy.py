"""Regression (F002): a benchmark profile classifies a nonzero solver exit as a
VALID failure (scored FAIL, consumes Pass@k budget) instead of an infra INVALID.

Different benchmarks own their own exit-code semantics through
``ExternalRunConfig.exit_code_policy``; the adapter hard-codes none. A solver that
used its whole budget without solving (e.g. a wall-clock/budget-exhausted run that
exits nonzero) must count as a failed attempt, not a free retry.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bencheval.cli import main
from bencheval.evidence import read_evidence_jsonl
from bencheval.external_command_adapter import _classify_nonzero_exit


def test_unlisted_nonzero_exit_stays_invalid() -> None:
    # Backward-compatible default: no policy -> nonzero is infra INVALID.
    valid, failure_class, invalid_reason = _classify_nonzero_exit(2, {})
    assert valid is False
    assert failure_class == "runtime_tool_failure"
    assert invalid_reason == "process_exit=2"


def test_policy_exit_code_is_valid_fail() -> None:
    # Profile declares exit 2 a valid solver failure -> scored FAIL, no invalid_reason.
    valid, failure_class, invalid_reason = _classify_nonzero_exit(
        2,
        {2: "runtime_wall_clock_timeout"},
    )
    assert valid is True
    assert failure_class == "runtime_wall_clock_timeout"
    assert invalid_reason is None


def test_policy_does_not_leak_to_other_exit_codes() -> None:
    # Only the declared code is a valid fail; every other nonzero stays INVALID.
    valid, failure_class, invalid_reason = _classify_nonzero_exit(
        3,
        {2: "runtime_wall_clock_timeout"},
    )
    assert valid is False
    assert failure_class == "runtime_tool_failure"
    assert invalid_reason == "process_exit=3"


def test_policy_exit_code_writes_valid_failed_evidence(tmp_path: Path) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("solve the task\n", encoding="utf-8")
    config = tmp_path / "profile.yaml"
    config.write_text(
        "\n".join(
            [
                'schema_version: "external_command_run_v1"',
                'name: "exit-policy"',
                'benchmark_id: "external-smoke"',
                'runtime_id: "dummy-runtime"',
                'model_id: "dummy-model"',
                "command:",
                f'  argv_prefix: ["{sys.executable}", "-c", "import sys; sys.exit(2)"]',
                "verification:",
                '  kind: "none"',
                "exit_code_policy:",
                '  "2": "runtime_wall_clock_timeout"',
                "instances:",
                '  - id: "one"',
                f'    prompt_file: "{prompt}"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    results = tmp_path / "results"

    rc = main(
        [
            "run",
            "--config",
            str(config),
            "--results-root",
            str(results),
            "--run-id",
            "exit-policy-run",
            "--no-color",
        ],
    )

    assert rc == 1
    [record] = read_evidence_jsonl(results / "evidence" / "exit-policy-run.jsonl")
    assert record.primary_pass is False
    assert record.failure_class == "runtime_wall_clock_timeout"
    assert record.attempt_validity == "valid"
    assert record.invalid_reason is None
    assert record.counts_toward_pass_at_k is True
