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
            "BENCHEVAL_PILOT_MODEL": "kimi-k2.7-code",
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
    # H3: row-count-only admission was replaced by live_proof lane qualification
    # (eligible native-harness rows + provenance + artifacts). A scored model
    # failure makes `bencheval run` nonzero but remains a valid native attempt.
    assert "require_qualified_lane" in content
    assert "python -m bencheval.live_proof qualify-lane" in content
    assert "checking evidence completeness" in content
    assert "lane disqualified (live proof requires a clean run)" not in content
    assert "BENCHEVAL_PILOT_TB_EXPECTED_INSTANCES" in content


def test_live_pilot_does_not_invoke_bfcl_or_swe_lanes() -> None:
    """F001/F002/F017: non-pilot lanes must not run in the minimum-proof matrix."""
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"

    content = script.read_text(encoding="utf-8")

    assert "run_bfcl" not in content
    assert "run_swe" not in content
    assert "BENCHEVAL_PILOT_BFCL_MODEL" not in content
    assert "bfcl_model_supported" not in content
    assert "outside the Terminal-Bench pilot matrix" in content
    assert "need TB claude-code + codex-cli evidence and compare" in content


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
