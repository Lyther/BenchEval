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


_PRODUCT_IDS = {
    "bfcl-v4",
    "cybergym",
    "exploitgym",
    "gpqa-diamond",
    "hle",
    "swe-bench-pro",
    "swe-bench-verified",
    "terminal-bench",
}


def test_benchmark_list_json_reports_product_catalog() -> None:
    result = _run("benchmark", "list", "--execution-support", "all", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["count"] == 8
    ids = {benchmark["id"] for benchmark in payload["benchmarks"]}
    assert ids == _PRODUCT_IDS


def test_benchmark_list_defaults_to_executable_only() -> None:
    result = _run("benchmark", "list", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["count"] == 4
    ids = {benchmark["id"] for benchmark in payload["benchmarks"]}
    assert ids == {"terminal-bench", "gpqa-diamond", "hle", "bfcl-v4"}
    assert {"swe-bench-verified", "swe-bench-pro", "cybergym", "exploitgym"}.isdisjoint(
        ids,
    )


def test_benchmark_show_resolves_alias() -> None:
    result = _run("benchmark", "show", "t-bench")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["id"] == "terminal-bench"


def test_catalog_benchmark_list_matches() -> None:
    result = _run("catalog", "benchmark", "list", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["count"] == 4
