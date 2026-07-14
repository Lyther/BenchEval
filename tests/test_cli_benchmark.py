from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "bencheval.cli", *args],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )


def test_benchmark_list_json_reports_product_catalog() -> None:
    result = _run("benchmark", "list", "--execution-support", "all", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["count"] == 3
    ids = {benchmark["id"] for benchmark in payload["benchmarks"]}
    assert ids == {"swe-bench-verified", "terminal-bench", "bfcl-v4"}


def test_benchmark_list_defaults_to_executable_only() -> None:
    result = _run("benchmark", "list", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["count"] == 3
    ids = {benchmark["id"] for benchmark in payload["benchmarks"]}
    assert ids == {"bfcl-v4", "swe-bench-verified", "terminal-bench"}


def test_benchmark_show_resolves_alias() -> None:
    result = _run("benchmark", "show", "t-bench")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["id"] == "terminal-bench"


def test_catalog_benchmark_list_matches() -> None:
    result = _run("catalog", "benchmark", "list", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["count"] == 3
