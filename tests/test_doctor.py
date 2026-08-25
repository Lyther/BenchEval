from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

import pytest

from bencheval.cli import main
from bencheval.doctor import PILOT_DOCTOR_BACKEND, run_doctor, run_pilot_doctor
from bencheval.domain import ExecutionProfile

# SUBSTITUTE_JUSTIFICATION
# - substitute: pytest monkeypatch controls for binary discovery, version/command probes,
#   Docker availability, Inspect import state, and credential environment
# - replaces: host PATH binaries, Docker daemon state, provider env, and Inspect import
# - necessity: covered tests deterministically exercise present, absent, broken, and
#   credential-missing states that one real host cannot expose simultaneously and safely
# - real-option: real doctor commands cannot force every negative state without mutating
#   the operator host
# - proof-limit: proves doctor decision logic only, not real host/provider availability
# - real-proof: BLOCKED until scripts/doctor-pilot.sh runs on the provisioned dev-box
# - covered tests: test_pilot_doctor_all_present,
#   test_pilot_doctor_ignores_bfcl_dependency,
#   test_pilot_doctor_ignores_broken_bfcl_cli,
#   test_pilot_doctor_ignores_demoted_swe_dependency,
#   test_pilot_doctor_missing_harbor, test_pilot_doctor_docker_unavailable,
#   test_pilot_doctor_version_probe_failure_still_pass,
#   test_pilot_doctor_bytellm_route_credentials,
#   test_pilot_doctor_bytellm_route_missing_key, test_pilot_doctor_model_credentials_fail,
#   test_pilot_doctor_requires_provider_credentials, test_cli_doctor_profile_pilot_json,
#   test_cli_doctor_pilot_requires_no_backend, and
#   test_run_doctor_provider_check_unchanged_after_refactor,
#   test_inspect_doctor_docker_requirement_matches_profile

_PILOT_BINARIES = ("harbor",)


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

    monkeypatch.setattr("bencheval.doctor.docker_available", lambda: docker_ok)


def test_pilot_doctor_all_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(
        monkeypatch,
        versions={"harbor": "0.9.0"},
    )
    report = run_pilot_doctor()
    assert report.backend == PILOT_DOCTOR_BACKEND
    assert report.ok is True
    assert [c.name for c in report.checks] == ["harbor_cli", "docker"]


def test_pilot_doctor_ignores_bfcl_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pilot_host(monkeypatch, present={"harbor"})
    report = run_pilot_doctor()
    assert all(c.name != "bfcl_eval" for c in report.checks)
    assert report.ok is True


def test_pilot_doctor_ignores_broken_bfcl_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pilot_host(monkeypatch, present={"harbor"})
    report = run_pilot_doctor()
    assert all(c.name != "bfcl_eval" for c in report.checks)
    assert report.ok is True


def test_pilot_doctor_ignores_demoted_swe_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_pilot_host(monkeypatch, present={"harbor"})
    report = run_pilot_doctor()
    assert all(c.name != "mini_extra" for c in report.checks)
    assert report.ok is True


def test_pilot_doctor_missing_harbor(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch, present=set())
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
    harbor = next(c for c in report.checks if c.name == "harbor_cli")
    assert harbor.status == "pass"
    assert "PATH" in harbor.message
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
    report = run_pilot_doctor(model_id="kimi-k2.7-code")
    cred = next(c for c in report.checks if c.name == "provider_credentials")
    assert cred.status == "fail"
    assert report.ok is False


def test_cli_doctor_profile_pilot_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(
        monkeypatch,
        versions={"harbor": "0.9.0"},
    )
    monkeypatch.setenv("BYTELLM_API_KEY", "sk-test")
    buf = StringIO()
    with redirect_stdout(buf):
        code = main(["doctor", "--profile", "pilot", "--model", "kimi-k2.7-code"])
    assert code == 0
    payload = json.loads(buf.getvalue())
    assert payload["backend"] == PILOT_DOCTOR_BACKEND
    assert payload["ok"] is True
    names = [c["name"] for c in payload["checks"]]
    assert names == ["harbor_cli", "docker", "provider_credentials"]


def test_cli_doctor_pilot_requires_no_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pilot_host(monkeypatch)
    monkeypatch.setenv("BYTELLM_API_KEY", "sk-test")
    buf = StringIO()
    with redirect_stdout(buf):
        code = main(["doctor", "--profile", "pilot", "--model", "kimi-k2.7-code"])
    assert code in (0, 1)
    payload = json.loads(buf.getvalue())
    assert payload["backend"] == PILOT_DOCTOR_BACKEND


def test_cli_doctor_requires_backend_without_pilot() -> None:
    buf = StringIO()
    with redirect_stderr(buf):
        code = main(["doctor", "--model", "kimi-k2.7-code"])
    assert code == 2
    assert "--backend" in buf.getvalue()


def test_run_doctor_provider_check_unchanged_after_refactor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("bencheval.doctor._try_import_inspect_ai", lambda: ("0.3.0", None))
    monkeypatch.setattr("bencheval.doctor.docker_available", lambda: True)
    monkeypatch.setenv("BYTELLM_API_KEY", "sk-test")
    report = run_doctor("inspect", model_id="kimi-k2.7-code")
    cred = next(c for c in report.checks if c.name == "provider_credentials")
    assert cred.status == "pass"
    assert report.backend == "inspect"


@pytest.mark.parametrize(
    ("profile", "expected_status"),
    [("E0", "skip"), ("E1", "fail"), ("E3", "skip"), ("E4", "fail")],
)
def test_inspect_doctor_docker_requirement_matches_profile(
    monkeypatch: pytest.MonkeyPatch,
    profile: ExecutionProfile,
    expected_status: str,
) -> None:
    monkeypatch.setattr("bencheval.doctor._try_import_inspect_ai", lambda: ("0.3.0", None))
    monkeypatch.setattr("bencheval.doctor.docker_available", lambda: False)

    report = run_doctor("inspect", execution_profile=profile)

    docker = next(check for check in report.checks if check.name == "docker")
    assert docker.status == expected_status
