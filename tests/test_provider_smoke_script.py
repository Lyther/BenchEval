from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "run_provider_smoke.sh"


def _run_script(
    *args: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", str(_SCRIPT), *args],
        cwd=cwd or _ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=merged,
    )


def test_provider_smoke_usage_without_models() -> None:
    proc = _run_script()
    assert proc.returncode == 1
    assert "Usage:" in proc.stderr


def test_provider_smoke_invalid_backend_exits_nonzero() -> None:
    proc = _run_script(
        "openai/gpt-test",
        env={"BENCHEVAL_SMOKE_BACKEND": "not-a-backend"},
    )
    assert proc.returncode == 1, proc.stderr
    assert "unsupported BENCHEVAL_SMOKE_BACKEND" in proc.stderr
    assert "skip openai/gpt-test" not in proc.stderr


def test_provider_smoke_invalid_profile_exits_nonzero() -> None:
    proc = _run_script(
        "openai/gpt-test",
        env={"BENCHEVAL_SMOKE_PROFILE": "BAD"},
    )
    assert proc.returncode == 1, proc.stderr
    assert "unsupported BENCHEVAL_SMOKE_PROFILE" in proc.stderr
    assert "skip openai/gpt-test" not in proc.stderr


def test_provider_smoke_unexpected_doctor_failure_exits_nonzero(tmp_path: Path) -> None:
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\nprintf 'synthetic uv failure\\n' >&2\nexit 42\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    proc = _run_script(
        "openai/gpt-test",
        env={"PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
    )
    assert proc.returncode == 1, proc.stderr
    assert "fail openai/gpt-test: doctor failed unexpectedly" in proc.stderr
    assert "skip openai/gpt-test" not in proc.stderr
    assert "failed=1" in proc.stderr


def test_provider_smoke_skips_models_without_credentials(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    raw_dir = tmp_path / "raw"
    report_dir = tmp_path / "reports"
    proc = _run_script(
        "openai/gpt-test",
        "anthropic/claude-test",
        env={
            "BENCHEVAL_EVIDENCE_DIR": str(evidence_dir),
            "BENCHEVAL_RAW_DIR": str(raw_dir),
            "BENCHEVAL_REPORT_DIR": str(report_dir),
            "BENCHEVAL_RUN_ID": "test-run",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
        },
    )
    assert proc.returncode == 0, proc.stderr
    combined = proc.stderr
    assert "skip openai/gpt-test" in combined
    assert "skip anthropic/claude-test" in combined
    assert "ran=0" in combined
    assert "skipped=2" in combined
    assert "failed=0" in combined
    assert list(evidence_dir.glob("*.jsonl")) == []


def test_provider_smoke_accepts_bencheval_models_env(tmp_path: Path) -> None:
    proc = _run_script(
        env={
            "BENCHEVAL_MODELS": "openai/gpt-test",
            "BENCHEVAL_EVIDENCE_DIR": str(tmp_path / "evidence"),
            "BENCHEVAL_RAW_DIR": str(tmp_path / "raw"),
            "BENCHEVAL_REPORT_DIR": str(tmp_path / "reports"),
            "BENCHEVAL_RUN_ID": "env-run",
            "OPENAI_API_KEY": "",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert "skip openai/gpt-test" in proc.stderr


def test_provider_smoke_never_prints_secret_values() -> None:
    secret = "super-secret-provider-key-value"
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    env["OPENAI_API_KEY"] = secret
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "bencheval.cli",
            "doctor",
            "--backend",
            "inspect",
            "--model",
            "openai/gpt-test",
            "--profile",
            "E0",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    combined = proc.stdout + proc.stderr
    assert secret not in combined
    assert "OPENAI_API_KEY" in combined


def test_provider_smoke_doctor_json_shape_on_skip() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "bencheval.cli",
            "doctor",
            "--backend",
            "inspect",
            "--model",
            "openai/gpt-test",
            "--profile",
            "E0",
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"},
    )
    payload = json.loads(proc.stdout)
    assert payload["backend"] == "inspect"
    assert payload["ok"] is False
    cred = next(item for item in payload["checks"] if item["name"] == "provider_credentials")
    assert cred["status"] == "fail"
    assert "OPENAI_API_KEY" in cred["message"]
