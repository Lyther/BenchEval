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


def test_benchmark_list_json_reports_large_catalog() -> None:
    result = _run("benchmark", "list", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["count"] >= 50
    ids = {benchmark["id"] for benchmark in payload["benchmarks"]}
    assert {"swe-bench-verified", "exploitgym", "deepswe"}.issubset(ids)


def test_benchmark_show_resolves_deepswe_alias() -> None:
    result = _run("benchmark", "show", "DeepSWE", "--format", "json")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["id"] == "deepswe"
    assert payload["adapter_status"] == "unverified"


def test_benchmark_list_filters_restricted_security_text() -> None:
    result = _run(
        "benchmark",
        "list",
        "--category",
        "cybersecurity",
        "--safety",
        "offensive_restricted",
    )
    assert result.returncode == 0, result.stderr
    assert "exploitgym" in result.stdout
    assert "cybench" not in result.stdout
