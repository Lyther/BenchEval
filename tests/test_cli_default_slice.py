"""Bare benchmark ids resolve catalog default_slice; slash form still works."""

from __future__ import annotations

import json

import pytest

from bencheval.cli import _parse_target, main
from bencheval.exceptions import BenchEvalError


def test_parse_target_bare_uses_default_slice() -> None:
    benchmark_id, slice_id = _parse_target("gpqa-diamond")
    assert benchmark_id == "gpqa-diamond"
    assert slice_id == "smoke"


def test_parse_target_explicit_slice() -> None:
    benchmark_id, slice_id = _parse_target("terminal-bench/smoke-5")
    assert benchmark_id == "terminal-bench"
    assert slice_id == "smoke-5"


def test_parse_target_unknown_benchmark() -> None:
    with pytest.raises(BenchEvalError, match="benchmark not found"):
        _parse_target("no-such-bench")


def test_dry_run_bare_gpqa(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "run",
            "gpqa-diamond",
            "--model",
            "kimi-k2.7-code",
            "--provider",
            "bytellm",
            "--dry-run",
        ],
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["benchmark_id"] == "gpqa-diamond"
    assert payload["slice_id"] == "smoke"
    assert payload["runtime_id"] is None
    assert payload["agent_id"] is None


def test_dry_run_bare_terminal_bench_needs_runtime(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run", "terminal-bench", "--model", "kimi-k2.7-code", "--dry-run"])
    assert code == 1
    err = capsys.readouterr().err
    assert "runtime" in err.lower() or "agent" in err.lower()
