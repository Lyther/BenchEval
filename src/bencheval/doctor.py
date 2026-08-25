"""Preflight checks for live Inspect/Harbor execution backends."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

from bencheval.backends import HARBOR_BACKEND, INSPECT_BACKEND, ExecutionBackend
from bencheval.domain import ExecutionProfile
from bencheval.exceptions import BenchEvalError

CheckStatus = Literal["pass", "fail", "skip"]

# Scope label for the Terminal-Bench minimum pilot host-dependency report.
# It is not an ExecutionBackend because the profile combines Harbor and Docker.
PILOT_DOCTOR_BACKEND = "pilot"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    message: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    backend: str
    ok: bool
    checks: tuple[DoctorCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "ok": self.ok,
            "checks": [
                {"name": c.name, "status": c.status, "message": c.message} for c in self.checks
            ],
        }


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def provider_env_vars_for_model(model_id: str) -> tuple[str, ...]:
    """Resolve credential env names via model registry → provider registry.

    Returns an empty tuple only when the model is registered and has no
    ``provider_route``. Unknown models fall back to legacy name-prefix heuristics.
    A registered route that points at a missing provider profile raises
    :class:`~bencheval.exceptions.BenchEvalError` so doctor cannot silently pass.
    """
    from bencheval.model_registry import load_model_registry
    from bencheval.provider_registry import load_provider_catalog

    key = model_id.strip()
    if not key:
        return ()
    try:
        model = load_model_registry().by_id(key)
    except KeyError:
        lowered = key.lower()
        if lowered.startswith(("openai/", "gpt-")):
            return ("OPENAI_API_KEY",)
        if lowered.startswith(("anthropic/", "claude")):
            return ("ANTHROPIC_API_KEY",)
        if lowered.startswith(("google/", "gemini")):
            return ("GOOGLE_API_KEY",)
        return ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")
    route = model.provider_route
    if route is None:
        return ()
    try:
        provider = load_provider_catalog().by_id(route)
    except KeyError as e:
        raise BenchEvalError(
            f"model {key!r} routes to unknown provider {route!r}",
        ) from e
    return (provider.provider.api_key_env,)


def env_var_present(name: str) -> bool:
    value = os.environ.get(name)
    return value is not None and value.strip() != ""


def _sanitize_import_error(exc: BaseException) -> str:
    message = str(exc).split("\n", maxsplit=1)[0].strip()
    if len(message) > 200:
        message = message[:197] + "..."
    return f"inspect_ai import failed: {type(exc).__name__}: {message}"


def _try_import_inspect_ai() -> tuple[str | None, str | None]:
    if not _module_available("inspect_ai"):
        return None, None
    try:
        import inspect_ai
    except ImportError as e:
        return None, _sanitize_import_error(e)
    except Exception as e:
        return None, _sanitize_import_error(e)
    version = getattr(inspect_ai, "__version__", None)
    return (version or "unknown"), None


def inspect_ai_version() -> str | None:
    version, import_error = _try_import_inspect_ai()
    if import_error is not None:
        return None
    return version


def harbor_revision() -> str | None:
    if shutil.which("harbor") is None:
        return None
    try:
        proc = subprocess.run(
            ["harbor", "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or proc.stderr.strip() or None


def binary_on_path(name: str) -> bool:
    return shutil.which(name) is not None


def _version_line(binary: str) -> str | None:
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or proc.stderr or "").strip()
    if not text:
        return None
    return text.splitlines()[0][:200]


def _binary_check(check_name: str, binary: str, install_hint: str) -> DoctorCheck:
    if not binary_on_path(binary):
        return DoctorCheck(check_name, "fail", f"{binary} not on PATH; {install_hint}")
    version = _version_line(binary)
    if version is not None:
        return DoctorCheck(check_name, "pass", f"{binary} {version} available")
    return DoctorCheck(check_name, "pass", f"{binary} on PATH (version unavailable)")


def _provider_credentials_check(model_id: str) -> DoctorCheck:
    try:
        env_names = provider_env_vars_for_model(model_id)
    except BenchEvalError as e:
        return DoctorCheck("provider_credentials", "fail", str(e))
    if not env_names:
        return DoctorCheck(
            "provider_credentials",
            "pass",
            f"model {model_id!r} does not require provider credentials",
        )
    present = [name for name in env_names if env_var_present(name)]
    if present:
        from bencheval.model_registry import load_model_registry
        from bencheval.provider_registry import (
            load_provider_catalog,
            resolve_openai_compatible_launch,
        )

        try:
            model = load_model_registry().by_id(model_id.strip())
            route = model.provider_route
            if route is not None:
                profile = load_provider_catalog().by_id(route)
                if profile.provider.kind == "openai_compatible":
                    resolve_openai_compatible_launch(route)
        except (KeyError, BenchEvalError) as e:
            return DoctorCheck("provider_credentials", "fail", str(e))
        return DoctorCheck(
            "provider_credentials",
            "pass",
            f"provider env present and effective client env resolved: {', '.join(present)}",
        )
    return DoctorCheck(
        "provider_credentials",
        "fail",
        f"missing provider env for {model_id!r}; expected one of: {', '.join(env_names)}",
    )


def run_doctor(
    backend: ExecutionBackend,
    *,
    model_id: str | None = None,
    execution_profile: ExecutionProfile | None = None,
) -> DoctorReport:
    checks: list[DoctorCheck] = []

    if backend == INSPECT_BACKEND:
        version, import_error = _try_import_inspect_ai()
        if import_error is not None:
            checks.append(
                DoctorCheck(
                    "inspect_ai_import",
                    "fail",
                    import_error,
                ),
            )
        elif version is None:
            checks.append(
                DoctorCheck(
                    "inspect_ai_import",
                    "fail",
                    "inspect_ai is not installed; run `uv sync --extra eval`",
                ),
            )
        else:
            checks.append(
                DoctorCheck(
                    "inspect_ai_import",
                    "pass",
                    f"inspect_ai {version} available",
                ),
            )
        if execution_profile in ("E1", "E4"):
            if docker_available():
                checks.append(
                    DoctorCheck("docker", "pass", "docker daemon reachable"),
                )
            else:
                checks.append(
                    DoctorCheck(
                        "docker",
                        "fail",
                        f"docker is required for {execution_profile} Inspect runs "
                        "but is unavailable",
                    ),
                )
        elif execution_profile is None:
            checks.append(
                DoctorCheck(
                    "docker",
                    "skip",
                    "docker not checked without execution profile",
                ),
            )
        else:
            checks.append(
                DoctorCheck(
                    "docker",
                    "skip",
                    f"docker not required for {execution_profile}",
                ),
            )
    elif backend == HARBOR_BACKEND:
        revision = harbor_revision()
        if revision is None:
            checks.append(
                DoctorCheck(
                    "harbor_cli",
                    "fail",
                    "harbor CLI is not available; run `uv sync --extra eval`",
                ),
            )
        else:
            checks.append(
                DoctorCheck(
                    "harbor_cli",
                    "pass",
                    f"harbor {revision} available",
                ),
            )
        docker_ok = docker_available()
        checks.append(
            DoctorCheck(
                "docker",
                "pass" if docker_ok else "fail",
                "docker daemon reachable"
                if docker_ok
                else "docker is required for Harbor runs but is unavailable",
            ),
        )
    else:
        raise BenchEvalError(f"doctor does not support backend {backend!r}")

    if model_id is not None:
        checks.append(_provider_credentials_check(model_id))

    ok = all(check.status != "fail" for check in checks)
    return DoctorReport(backend=backend, ok=ok, checks=tuple(checks))


def run_pilot_doctor(*, model_id: str | None = None) -> DoctorReport:
    """Preflight the active Terminal-Bench minimum pilot matrix.

    The Terminal-Bench lanes are the blocking profile; BFCL/SWE checks are
    deliberately outside it (bfcl-v4 is executable but not a pilot lane).
    When a model id is supplied, provider credential env vars are also checked.
    """
    checks: list[DoctorCheck] = [
        _binary_check("harbor_cli", "harbor", "run `uv sync --extra eval`"),
    ]
    docker_ok = docker_available()
    checks.append(
        DoctorCheck(
            "docker",
            "pass" if docker_ok else "fail",
            "docker daemon reachable"
            if docker_ok
            else "docker daemon unreachable; required for pilot runs",
        ),
    )
    if model_id is not None:
        checks.append(_provider_credentials_check(model_id))
    ok = all(check.status != "fail" for check in checks)
    return DoctorReport(backend=PILOT_DOCTOR_BACKEND, ok=ok, checks=tuple(checks))


def require_doctor_ok(report: DoctorReport) -> None:
    if report.ok:
        return
    failed = [f"{check.name}: {check.message}" for check in report.checks if check.status == "fail"]
    raise BenchEvalError("backend preflight failed: " + "; ".join(failed))
