"""Preflight checks for live Inspect/Harbor execution backends."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Literal

from bencheval.backends import HARBOR_BACKEND, INSPECT_BACKEND, ExecutionBackend
from bencheval.exceptions import BenchEvalError
from bencheval.task_contract import ExecutionProfile

CheckStatus = Literal["pass", "fail", "skip"]


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    message: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    backend: ExecutionBackend
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
    lowered = model_id.lower()
    if lowered.startswith("openai/") or lowered.startswith("gpt-"):
        return ("OPENAI_API_KEY",)
    if lowered.startswith("anthropic/") or lowered.startswith("claude"):
        return ("ANTHROPIC_API_KEY",)
    if lowered.startswith("google/") or lowered.startswith("gemini"):
        return ("GOOGLE_API_KEY",)
    if lowered.startswith("mockllm/"):
        return ()
    return ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY")


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
        if execution_profile == "E1":
            if docker_available():
                checks.append(
                    DoctorCheck("docker", "pass", "docker daemon reachable"),
                )
            else:
                checks.append(
                    DoctorCheck(
                        "docker",
                        "fail",
                        "docker is required for E1 Inspect runs but is unavailable",
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
        env_names = provider_env_vars_for_model(model_id)
        if not env_names:
            checks.append(
                DoctorCheck(
                    "provider_credentials",
                    "pass",
                    f"model {model_id!r} does not require provider credentials",
                ),
            )
        else:
            present = [name for name in env_names if env_var_present(name)]
            if present:
                checks.append(
                    DoctorCheck(
                        "provider_credentials",
                        "pass",
                        f"provider env present: {', '.join(present)}",
                    ),
                )
            else:
                checks.append(
                    DoctorCheck(
                        "provider_credentials",
                        "fail",
                        (
                            f"missing provider env for {model_id!r}; "
                            f"expected one of: {', '.join(env_names)}"
                        ),
                    ),
                )

    ok = all(check.status != "fail" for check in checks)
    return DoctorReport(backend=backend, ok=ok, checks=tuple(checks))


def require_doctor_ok(report: DoctorReport) -> None:
    if report.ok:
        return
    failed = [f"{check.name}: {check.message}" for check in report.checks if check.status == "fail"]
    raise BenchEvalError("backend preflight failed: " + "; ".join(failed))
