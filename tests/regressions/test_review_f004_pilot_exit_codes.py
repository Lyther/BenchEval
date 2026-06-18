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
    assert "require_evidence_records" in content
    assert "checking evidence completeness" in content
    assert "BENCHEVAL_PILOT_TB_EXPECTED_INSTANCES" in content


def test_live_pilot_preflights_unsupported_bfcl_model() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"

    content = script.read_text(encoding="utf-8")

    assert "bfcl_model_supported" in content
    assert "bfcl models" in content
    assert "BENCHEVAL_PILOT_BFCL_MODEL" in content
    assert "bfcl model is not supported" in content


def test_live_pilot_can_enable_anthropic_role_shim() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"

    content = script.read_text(encoding="utf-8")

    assert "BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM" in content
    assert "python -m bencheval.anthropic_role_shim" in content
    assert "BENCHEVAL_ANTHROPIC_UPSTREAM:-http://127.0.0.1:4000" in content
    assert "BENCHEVAL_DOCKER_HOST_GATEWAY:-172.17.0.1" in content
    assert "BENCHEVAL_ANTHROPIC_SYSTEM_ROLE_SHIM_HOST:-${docker_host}" in content


def test_live_pilot_supports_per_runtime_model_aliases() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"

    content = script.read_text(encoding="utf-8")

    assert "BENCHEVAL_PILOT_CLAUDE_MODEL" in content
    assert "BENCHEVAL_PILOT_CODEX_MODEL" in content
    assert 'model="${TB_CLAUDE_MODEL}"' in content
    assert 'model="${TB_CODEX_MODEL}"' in content


def test_live_pilot_maps_bytellm_key_for_claude_and_codex() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"

    content = script.read_text(encoding="utf-8")

    assert "configure_bytellm_client_env" in content
    assert "BENCHEVAL_DUMMY_RUNTIME_API_KEY:-bencheval-local-shim" in content
    assert "BENCHEVAL_SHIM_AUTH_TOKEN_ENV" in content
    assert "BENCHEVAL_OPENAI_VIA_ROLE_SHIM" in content
    assert "BENCHEVAL_CODEX_ENV_KEY" in content
    assert "--auth-token-env" in content


def test_claude_code_installer_configures_npm_proxy_and_timeout() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    wrapper = repo_root / "src" / "bencheval" / "harbor_claude_code_npm.py"

    content = wrapper.read_text(encoding="utf-8")

    assert "npm config set proxy" in content
    assert "npm config set https-proxy" in content
    assert "fetch-timeout" in content
    assert "fetch-retries" in content
    assert "ca-certificates" in content
    assert "--no-audit --no-fund" in content
