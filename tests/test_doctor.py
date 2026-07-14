from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import pytest

from bencheval.cli import main
from bencheval.doctor import PILOT_DOCTOR_BACKEND, run_doctor, run_pilot_doctor

_PILOT_BINARIES = ("harbor", "bfcl", "mini-extra")


def _patch_binaries(
    monkeypatch: pytest.MonkeyPatch,
    *,
    present: set[str],
    versions: dict[str, str] | None = None,
) -> None:
    versions = versions or {}
    monkeypatch.setattr(
        "bencheval.doctor.binary_on_path",
        lambda name: name in present,
    )
    monkeypatch.setattr(
        "bencheval.doctor._version_line",
        lambda binary: versions.get(binary),
    )


def _patch_pilot_host(
    monkeypatch: pytest.MonkeyPatch,
    *,
    present: set[str] | None = None,
    docker_ok: bool = True,
    versions: dict[str, str] | None = None,
) -> None:
    if present is None:
        present = set(_PILOT_BINARIES)
    versions = versions or {}
    _patch_binaries(monkeypatch, present=present, versions=versions)

    def fake_probe(binary: str, args: tuple[str, ...]) -> tuple[bool, str | None]:
        if binary not in present:
            return False, f"{binary} missing"
        if binary == "bfcl" and args == ("version",):
            return True, versions.get("bfcl")
        return True, versions.get(binary)

    monkeypatch.setattr("bencheval.doctor._probe_binary_args", fake_probe)
    monkeypatch.setattr("bencheval.doctor.docker_available", lambda: docker_ok)


def test_pilot_doctor_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(
        monkeypatch,
        versions={"harbor": "0.9.0", "bfcl": "2025.8.6.2", "mini-extra": "1.2.0"},
    )
    report = run_pilot_doctor()
    assert report.backend == PILOT_DOCTOR_BACKEND
    assert report.ok is True
    assert [c.name for c in report.checks] == [
        "harbor_cli",
        "docker",
        "bfcl_eval",
        "mini_extra",
    ]


def test_pilot_doctor_missing_bfcl_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch, present={"harbor", "mini-extra"})
    report = run_pilot_doctor()
    bfcl = next(c for c in report.checks if c.name == "bfcl_eval")
    assert bfcl.status == "fail"
    assert "bfcl" in bfcl.message
    assert report.ok is False


def test_pilot_doctor_broken_bfcl_cli_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch)
    monkeypatch.setattr(
        "bencheval.doctor._probe_binary_args",
        lambda binary, args: (
            (
                False,
                "ModuleNotFoundError: No module named 'soundfile'",
            )
            if binary == "bfcl"
            else (True, None)
        ),
    )
    report = run_pilot_doctor()
    bfcl = next(c for c in report.checks if c.name == "bfcl_eval")
    assert bfcl.status == "fail"
    assert "soundfile" in bfcl.message
    assert report.ok is False


def test_pilot_doctor_missing_mini_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch, present={"harbor", "bfcl"})
    report = run_pilot_doctor()
    mini = next(c for c in report.checks if c.name == "mini_extra")
    assert mini.status == "fail"
    assert report.ok is False


def test_pilot_doctor_missing_harbor(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch, present={"bfcl", "mini-extra"})
    report = run_pilot_doctor()
    harbor = next(c for c in report.checks if c.name == "harbor_cli")
    assert harbor.status == "fail"
    assert report.ok is False


def test_pilot_doctor_docker_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch, docker_ok=False)
    report = run_pilot_doctor()
    docker = next(c for c in report.checks if c.name == "docker")
    assert docker.status == "fail"
    assert report.ok is False


def test_pilot_doctor_version_probe_failure_still_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    # On PATH but --version unavailable must not be a failure (lenient gate).
    _patch_pilot_host(monkeypatch, versions={})
    report = run_pilot_doctor()
    bfcl = next(c for c in report.checks if c.name == "bfcl_eval")
    assert bfcl.status == "pass"
    assert "available" in bfcl.message
    assert report.ok is True


def test_pilot_doctor_bytellm_route_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("BYTELLM_API_KEY", "sk-test")
    report = run_pilot_doctor(model_id="glm-5.2")
    cred = next(c for c in report.checks if c.name == "provider_credentials")
    assert cred.status == "pass"
    assert "BYTELLM_API_KEY" in cred.message
    assert "sk-test" not in cred.message
    assert report.ok is True


def test_pilot_doctor_bytellm_route_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch)
    monkeypatch.delenv("BYTELLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    report = run_pilot_doctor(model_id="glm-5.2")
    cred = next(c for c in report.checks if c.name == "provider_credentials")
    assert cred.status == "fail"
    assert "BYTELLM_API_KEY" in cred.message
    assert report.ok is False


def test_pilot_doctor_model_credentials_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    report = run_pilot_doctor(model_id="anthropic/claude-test")
    cred = next(c for c in report.checks if c.name == "provider_credentials")
    assert cred.status == "fail"
    assert report.ok is False


def test_pilot_doctor_requires_provider_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    report = run_pilot_doctor(model_id="openai/gpt-test")
    cred = next(c for c in report.checks if c.name == "provider_credentials")
    assert cred.status == "fail"
    assert report.ok is False


def test_cli_doctor_profile_pilot_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(
        monkeypatch,
        versions={"harbor": "0.9.0", "bfcl": "2025.8.6.2", "mini-extra": "1.2.0"},
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    buf = StringIO()
    with redirect_stdout(buf):
        code = main(["doctor", "--profile", "pilot", "--model", "openai/gpt-test"])
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["backend"] == PILOT_DOCTOR_BACKEND
    assert payload["ok"] is True
    names = [c["name"] for c in payload["checks"]]
    assert names == ["harbor_cli", "docker", "bfcl_eval", "mini_extra", "provider_credentials"]


def test_cli_doctor_pilot_requires_no_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    buf = StringIO()
    with redirect_stdout(buf):
        code = main(["doctor", "--profile", "pilot", "--model", "openai/gpt-test"])
    assert code in (0, 1)
    payload = json.loads(buf.getvalue())
    assert payload["backend"] == PILOT_DOCTOR_BACKEND


def test_cli_doctor_requires_backend_without_pilot() -> None:
    buf = StringIO()
    with redirect_stderr(buf):
        code = main(["doctor", "--model", "openai/gpt-test"])
    assert code == 2
    assert "--backend" in buf.getvalue()


def test_run_doctor_provider_check_unchanged_after_refactor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bencheval.doctor._try_import_inspect_ai", lambda: ("0.3.0", None))
    monkeypatch.setattr("bencheval.doctor.docker_available", lambda: True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    report = run_doctor("inspect", model_id="openai/gpt-test")
    cred = next(c for c in report.checks if c.name == "provider_credentials")
    assert cred.status == "pass"
    assert report.backend == "inspect"
