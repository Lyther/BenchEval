"""F004: live pilot script must exit non-zero when minimum proof is missing."""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_live_pilot_exits_nonzero_without_proof() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"
    proc = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env={
            **__import__("os").environ,
            "PATH": "/usr/bin:/bin",
            "BENCHEVAL_PILOT_MODEL": "openai/gpt-test",
        },
    )
    assert proc.returncode != 0
    assert "minimum live proof not met" in (proc.stderr + proc.stdout).lower()


def test_live_pilot_uses_cli_supported_doctor_profile() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"

    content = script.read_text(encoding="utf-8")

    assert "--profile E4" not in content


def test_live_pilot_exports_failed_terminal_bench_evidence() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"

    content = script.read_text(encoding="utf-8")

    assert 'emit_artifacts "${tag}" "${evidence}" "${raw}" || true' in content


def test_live_pilot_can_enable_anthropic_role_shim() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"

    content = script.read_text(encoding="utf-8")

    assert "BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM" in content
    assert "python -m bencheval.anthropic_role_shim" in content
    assert "BENCHEVAL_ANTHROPIC_UPSTREAM:-http://127.0.0.1:4000" in content
    assert "BENCHEVAL_DOCKER_HOST_GATEWAY:-172.17.0.1" in content
