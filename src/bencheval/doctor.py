"""Preflight checks for live Inspect/Harbor execution backends."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from bencheval.backends import HARBOR_BACKEND, INSPECT_BACKEND, ExecutionBackend
from bencheval.domain import ExecutionProfile, RunPlan
from bencheval.exceptions import BenchEvalError
from bencheval.model_registry import ModelRegistry
from bencheval.paths import describe_config_root, is_project_checkout

CheckStatus = Literal["pass", "fail", "skip"]

# Scope label for the Terminal-Bench minimum pilot host-dependency report.
# It is not an ExecutionBackend because the profile combines Harbor and Docker.
PILOT_DOCTOR_BACKEND = "pilot"
OPERATOR_DOCTOR_BACKENDS = (
    "inspect",
    "harbor",
    "bfcl-native",
    "hle-native",
    "swebench-native",
)


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    status: CheckStatus
    message: str


@dataclass(frozen=True, slots=True)
class PreparationRecipe:
    """One locked preparation recipe per official harness (architecture §23.7)."""

    harness_kind: str
    install: str
    # Where ``install`` can run: a BenchEval checkout at its lockfile. No
    # installed-environment preparation path is claimed (architecture §23.7).
    context: Literal["checkout"]
    external: tuple[str, ...]
    docs: str

    def to_dict(self) -> dict[str, object]:
        return {
            "harness_kind": self.harness_kind,
            "install": self.install,
            "context": self.context,
            "external": list(self.external),
            "docs": self.docs,
        }


_EVAL_EXTRA_SYNC = "uv sync --extra eval"
_PROVIDER_ENV_PREREQ = (
    "provider credential env for the selected route (config/providers/*.yaml api_key_env)"
)
# The lock is exercised on CPython 3.12 only; the checkout's .python-version
# makes uv select it even when newer managed interpreters exist (a clean host
# with 3.14 otherwise fails to sync locked wheels).
_PYTHON_PREREQ = "CPython 3.12, selected by the checkout's .python-version"

# One locked recipe per official harness; ``install`` runs only in a BenchEval
# checkout at its uv.lock (the wheel ships no dependency groups), and
# ``external`` names what uv cannot provide. Failing preparation checks cite it.
PREPARATION_RECIPES: Mapping[str, PreparationRecipe] = {
    "harbor": PreparationRecipe(
        harness_kind="harbor",
        install=_EVAL_EXTRA_SYNC,
        context="checkout",
        external=(
            _PYTHON_PREREQ,
            "Docker daemon reachable by the operator user (Harbor task containers)",
            _PROVIDER_ENV_PREREQ,
            "Harbor pulls the terminal-bench-2-1 dataset and images on first use",
        ),
        docs="docs/ops/benchmarks/terminal-bench.md",
    ),
    "inspect-evals": PreparationRecipe(
        harness_kind="inspect-evals",
        install=_EVAL_EXTRA_SYNC,
        context="checkout",
        external=(
            _PYTHON_PREREQ,
            _PROVIDER_ENV_PREREQ,
            "the pinned GPQA CSV is downloaded once into the inspect_evals cache",
        ),
        docs="docs/ops/benchmarks/gpqa-diamond.md",
    ),
    "hle-native": PreparationRecipe(
        harness_kind="hle-native",
        install=_EVAL_EXTRA_SYNC,
        context="checkout",
        external=(
            _PYTHON_PREREQ,
            "BENCHEVAL_HLE_HOME pointing at the pinned centerforaisafety/hle checkout",
            "HF_TOKEN authorized for the gated cais/hle dataset",
            "network egress to huggingface.co for the pinned snapshot (on a proxied host "
            "export HTTPS_PROXY/NO_PROXY for the run; a timeout fails closed before charge)",
            "provider credential env for the candidate route and the slice-pinned judge route",
        ),
        docs="docs/ops/benchmarks/hle.md",
    ),
    "bfcl-native": PreparationRecipe(
        harness_kind="bfcl-native",
        install="uv sync --group bfcl",
        context="checkout",
        external=(_PYTHON_PREREQ, _PROVIDER_ENV_PREREQ),
        docs="docs/ops/benchmarks/bfcl-v4.md",
    ),
    "swebench-native": PreparationRecipe(
        harness_kind="swebench-native",
        install="uv sync --extra eval --group swe",
        context="checkout",
        external=(
            _PYTHON_PREREQ,
            "Docker daemon for the pinned official SWE-bench evaluator",
            "HF access to the pinned SWE-bench Verified snapshot",
            "the selected runtime binary for prediction",
        ),
        docs="docs/ops/benchmarks/swe-bench-verified.md",
    ),
}

# Failing checks whose remedy is the harness's preparation recipe.
_PREPARATION_CHECKS = frozenset(
    {
        "harbor_cli",
        "inspect_ai_import",
        "inspect_openai_client",
        "inspect_evals_import",
        "hle_dependencies",
        "bfcl_harness",
        "bfcl_package_data",
        "swe_generation_dependencies",
    }
)
_BACKEND_BY_HARNESS: Mapping[str, str] = {
    "harbor": HARBOR_BACKEND,
    "inspect-evals": INSPECT_BACKEND,
    "bfcl-native": "bfcl-native",
    "hle-native": "hle-native",
    "swebench-native": "swebench-native",
}


@dataclass(frozen=True, slots=True)
class DoctorReport:
    backend: str
    ok: bool
    checks: tuple[DoctorCheck, ...]
    # Plan-aware form only (CF3.1): the resolved selection, its recipe, and the host roots.
    selection: Mapping[str, object] | None = None
    recipe: PreparationRecipe | None = None
    host: Mapping[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "ok": self.ok,
            "selection": dict(self.selection) if self.selection is not None else None,
            "recipe": self.recipe.to_dict() if self.recipe is not None else None,
            "host": dict(self.host) if self.host is not None else None,
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
            encoding="utf-8",
            errors="replace",
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
            encoding="utf-8",
            errors="replace",
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
            encoding="utf-8",
            errors="replace",
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


def _route_credentials_check(name: str, provider_id: str, *, subject: str) -> DoctorCheck:
    """The credential of one resolved provider route, as launch resolves it.

    Every real execution path binds its route through
    ``resolve_openai_compatible_launch``; the doctor asks the same resolver, so
    the route a plan selected for a model that declares no ``provider_route``
    (``--provider`` or the shipped default) fails here, before reservation.
    """
    from bencheval.provider_registry import (
        load_provider_catalog,
        resolve_openai_compatible_launch,
    )

    try:
        env_name = load_provider_catalog().by_id(provider_id).provider.api_key_env
        resolve_openai_compatible_launch(provider_id)
    except KeyError:
        return DoctorCheck(name, "fail", f"{subject}: unknown provider {provider_id!r}")
    except BenchEvalError as e:
        return DoctorCheck(name, "fail", f"{subject}: {e}")
    return DoctorCheck(
        name,
        "pass",
        f"{subject}: provider {provider_id!r} credential env present and "
        f"effective client env resolved: {env_name}",
    )


def _plan_credentials_check(plan: RunPlan) -> DoctorCheck:
    """The candidate's confirmed route: the model binding snapshot, else the plan's provider."""
    snapshot = plan.model_binding_snapshot
    provider_id = snapshot.provider_id if snapshot is not None else plan.provider_id
    return _route_credentials_check(
        "provider_credentials", provider_id, subject=f"model {plan.model_id!r}"
    )


def _judge_credentials_check(plan: RunPlan) -> DoctorCheck:
    """The slice-pinned judge calls its own resolved route (the judge binding
    snapshot; a legacy plan without one keeps the candidate provider, as the
    HLE adapter does): its credential is a preflight condition."""
    name = "judge_provider_credentials"
    if plan.judge_model_id is None:
        return DoctorCheck(name, "skip", "slice pins no judge model")
    snapshot = plan.judge_binding_snapshot
    provider_id = snapshot.provider_id if snapshot is not None else plan.provider_id
    return _route_credentials_check(
        name, provider_id, subject=f"judge model {plan.judge_model_id!r}"
    )


def _provider_credentials_check(model_id: str) -> DoctorCheck:
    """Legacy model-only form (``--backend``/``--profile`` doctors): the model's
    declared route, or nothing for an unrouted entry. Plan-aware preflight uses
    :func:`_plan_credentials_check` on the route the plan actually selected."""
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


def harbor_actor_binding_check(
    *, runtime_id: str | None = None, agent_id: str | None = None
) -> DoctorCheck:
    """Verify the plan's runtime or native-agent binding against the installed Harbor."""
    from bencheval.actor_binding import actor_binding_for_agent
    from bencheval.agent_registry import load_agent_catalog
    from bencheval.terminal_bench_harbor import (
        harbor_launch_binding,
        installed_harbor_agent_names,
        verify_harbor_runtime_binding,
    )

    name = "harbor_actor_binding"
    try:
        installed = installed_harbor_agent_names()
        if runtime_id is not None:
            binding = harbor_launch_binding(runtime_id)
            verify_harbor_runtime_binding(binding, installed_agents=installed)
            recipe = f" via recipe {binding.install_recipe}" if binding.install_recipe else ""
            return DoctorCheck(
                name,
                "pass",
                f"runtime {runtime_id!r} launches installed Harbor agent {binding.agent!r}{recipe}",
            )
        if agent_id is None:
            return DoctorCheck(name, "skip", "no runtime or agent selected")
        profile = load_agent_catalog().by_id(agent_id)
        actor = actor_binding_for_agent(profile)
        if actor.harbor_agent is None:
            return DoctorCheck(
                name,
                "fail",
                f"agent {agent_id!r} selects an import path; not a wired launch path yet",
            )
        if actor.harbor_agent not in installed:
            return DoctorCheck(
                name,
                "fail",
                f"agent {agent_id!r} selects {actor.harbor_agent!r}, "
                "which is not an installed Harbor agent",
            )
        return DoctorCheck(
            name,
            "pass",
            f"agent {agent_id!r} is installed Harbor agent {actor.harbor_agent!r} "
            f"(version pin {actor.agent_version_pin}, {profile.admission})",
        )
    except KeyError as e:
        return DoctorCheck(name, "fail", f"unknown agent {agent_id!r}: {e}")
    except BenchEvalError as e:
        return DoctorCheck(name, "fail", str(e))


def _inspect_checks(
    execution_profile: ExecutionProfile | None, *, with_evals: bool
) -> list[DoctorCheck]:
    """Inspect AI import, optional inspect_evals import, and the profile's Docker need."""
    checks: list[DoctorCheck] = []
    version, import_error = _try_import_inspect_ai()
    if import_error is not None:
        checks.append(DoctorCheck("inspect_ai_import", "fail", import_error))
    elif version is None:
        checks.append(
            DoctorCheck(
                "inspect_ai_import",
                "fail",
                "inspect_ai is not installed; run `uv sync --extra eval`",
            ),
        )
    else:
        checks.append(DoctorCheck("inspect_ai_import", "pass", f"inspect_ai {version} available"))
    if with_evals:
        checks.append(_inspect_openai_client_check())
        evals_ok = _module_available("inspect_evals")
        checks.append(
            DoctorCheck(
                "inspect_evals_import",
                "pass" if evals_ok else "fail",
                "inspect_evals available"
                if evals_ok
                else "inspect_evals is not installed; run `uv sync --extra eval`",
            ),
        )
    if execution_profile in ("E1", "E4"):
        if docker_available():
            checks.append(DoctorCheck("docker", "pass", "docker daemon reachable"))
        else:
            checks.append(
                DoctorCheck(
                    "docker",
                    "fail",
                    f"docker is required for {execution_profile} Inspect runs but is unavailable",
                ),
            )
    elif execution_profile is None:
        checks.append(
            DoctorCheck("docker", "skip", "docker not checked without execution profile"),
        )
    else:
        checks.append(
            DoctorCheck("docker", "skip", f"docker not required for {execution_profile}"),
        )
    return checks


def _inspect_openai_client_check() -> DoctorCheck:
    """Inspect's own floor on the installed ``openai`` client for OpenAI-compatible routes.

    A locked ``inspect-ai`` can refuse the locked ``openai`` at runtime (0.3.253+
    needs openai>=3.1.0); the refusal must surface here, not after reservation.
    """
    name = "inspect_openai_client"
    if not _module_available("inspect_ai"):
        return DoctorCheck(name, "skip", "not checked: inspect_ai is not installed")
    try:
        from inspect_ai.model._providers.providers import validate_openai_client
    except ImportError as e:
        return DoctorCheck(name, "fail", _sanitize_import_error(e))
    try:
        validate_openai_client("OpenAI API")
    except Exception as e:  # Inspect raises its own pip-dependency error type
        message = str(e).split("\n", maxsplit=1)[0].strip()[:200]
        return DoctorCheck(name, "fail", message or f"{type(e).__name__}")
    return DoctorCheck(name, "pass", "installed openai client satisfies Inspect's floor")


def _harbor_host_checks() -> list[DoctorCheck]:
    """Harbor CLI and the Docker daemon every Harbor run needs."""
    checks: list[DoctorCheck] = []
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
        checks.append(DoctorCheck("harbor_cli", "pass", f"harbor {revision} available"))
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
    return checks


def run_doctor(
    backend: ExecutionBackend,
    *,
    model_id: str | None = None,
    execution_profile: ExecutionProfile | None = None,
    runtime_id: str | None = None,
    agent_id: str | None = None,
) -> DoctorReport:
    """Legacy backend-form preflight (``--backend``); the plan form is :func:`run_plan_doctor`."""
    if backend == INSPECT_BACKEND:
        checks = _inspect_checks(execution_profile, with_evals=False)
    elif backend == HARBOR_BACKEND:
        checks = _harbor_host_checks()
        if runtime_id is not None or agent_id is not None:
            checks.append(harbor_actor_binding_check(runtime_id=runtime_id, agent_id=agent_id))
    else:
        raise BenchEvalError(f"doctor does not support backend {backend!r}")

    if model_id is not None:
        checks.append(_provider_credentials_check(model_id))

    ok = all(check.status != "fail" for check in checks)
    return DoctorReport(backend=backend, ok=ok, checks=tuple(checks))


def _harbor_launch_identity_check(plan: RunPlan) -> DoctorCheck:
    """Resolve the launch identity the executor would bind, without launching."""
    from bencheval.terminal_bench_harbor import preflight_harbor_launch

    name = "harbor_launch_identity"
    try:
        metadata = preflight_harbor_launch(plan, real_runner=True)
    except BenchEvalError as e:
        return DoctorCheck(name, "fail", str(e))
    described = ", ".join(f"{key}={metadata[key]}" for key in sorted(metadata))
    return DoctorCheck(name, "pass", f"launch identity confirmed ({described})")


def plan_selection(plan: RunPlan) -> dict[str, object]:
    """The non-secret identity the plan resolved; what doctor and evidence share."""
    return {
        "benchmark_id": plan.benchmark_id,
        "slice_id": plan.slice_id,
        "harness_kind": plan.harness_kind,
        "adapter_id": plan.adapter_id,
        "runtime_id": plan.runtime_id,
        "agent_id": plan.agent_id,
        "provider_id": plan.provider_id,
        "model_id": plan.model_id,
        "judge_model_id": plan.judge_model_id,
        "diagnostic": plan.diagnostic,
        "instance_count": len(plan.instances),
        "model_binding_sha256": (
            plan.model_binding_snapshot.sha256 if plan.model_binding_snapshot else None
        ),
        "actor_binding_sha256": (
            plan.actor_binding_snapshot.sha256 if plan.actor_binding_snapshot else None
        ),
    }


def _preparation_hint(recipe: PreparationRecipe, context: str, root: Path) -> str:
    if context == "checkout":
        return (
            f"run `{recipe.install}` in the BenchEval checkout {root} (locked by its uv.lock; "
            "uv sync is exact, so combine extras/groups on a host that runs several families)"
        )
    where = (
        "this process runs from an installed wheel with no project"
        if context == "installed_wheel"
        else f"{root} is a config bundle without pyproject.toml/uv.lock"
    )
    return (
        f"`{recipe.install}` needs a BenchEval checkout at its lockfile (uv.lock); "
        f"{where}, so prepare and run from a checkout"
    )


def preparation_section(recipe: PreparationRecipe) -> tuple[dict[str, object], str]:
    """Whether the recipe can run from this config root, and the actionable hint."""
    root, source = describe_config_root()
    checkout = is_project_checkout(root)
    if checkout:
        context = "checkout"
    elif source == "wheel":
        context = "installed_wheel"
    else:
        context = "config_bundle"
    hint = _preparation_hint(recipe, context, root)
    return {"context": context, "checkout": str(root) if checkout else None, "hint": hint}, hint


def host_section(recipe: PreparationRecipe) -> tuple[dict[str, object], str]:
    """Where config comes from, where results go, and whether the recipe can run here."""
    root, source = describe_config_root()
    preparation, hint = preparation_section(recipe)
    host: dict[str, object] = {
        "config_root": str(root),
        "config_source": source,
        "results_root": str(Path.cwd() / "results"),
        "preparation": preparation,
    }
    return host, hint


def _with_preparation_hint(check: DoctorCheck, hint: str) -> DoctorCheck:
    """Cite the recipe on dependency failures (named checks, or any 'not installed')."""
    if check.status != "fail":
        return check
    if check.name not in _PREPARATION_CHECKS and "installed" not in check.message:
        return check
    return DoctorCheck(check.name, check.status, f"{check.message}; prepare: {hint}")


def run_plan_doctor(plan: RunPlan) -> DoctorReport:
    """Preflight exactly the selection a frozen :class:`RunPlan` resolved.

    Shared by ``bencheval doctor <benchmark>[/<slice>] …``, the console's
    preflight, and the executor's real-runner gate before any output is
    reserved. Checks are keyed by the plan's official harness; the report
    carries the resolved selection, the harness's preparation recipe, and
    the host roots so a clean-host rehearsal can be read off the JSON.
    """
    harness = plan.harness_kind
    recipe = PREPARATION_RECIPES.get(harness)
    if recipe is None:
        raise BenchEvalError(f"doctor has no preparation recipe for harness {harness!r}")
    # The Docker need comes from the frozen plan, as the executor derives it,
    # not from a catalog re-read: a model-only row stays E0.
    profile: ExecutionProfile = "E1" if plan.requires_sandbox else "E0"
    if harness == "harbor":
        checks = _harbor_host_checks()
        checks.append(
            harbor_actor_binding_check(runtime_id=plan.runtime_id, agent_id=plan.agent_id)
        )
        checks.append(_harbor_launch_identity_check(plan))
    elif harness == "inspect-evals":
        checks = _inspect_checks(profile, with_evals=True)
    elif harness == "bfcl-native":
        checks = _bfcl_native_checks(plan.model_id)
    elif harness == "hle-native":
        checks = _hle_native_checks()
    else:
        checks = _swebench_native_checks()
    checks.append(_plan_credentials_check(plan))
    if harness == "hle-native":
        checks.append(_judge_credentials_check(plan))
    host, hint = host_section(recipe)
    final = tuple(_with_preparation_hint(check, hint) for check in checks)
    return DoctorReport(
        backend=_BACKEND_BY_HARNESS[harness],
        ok=all(check.status != "fail" for check in final),
        checks=final,
        selection=plan_selection(plan),
        recipe=recipe,
        host=host,
    )


def _pinned_registry_text() -> str:
    """Pristine installed registry text verified against the reviewed pin."""
    from bencheval.bfcl_native_adapter import (
        _bfcl_package_root,
        bfcl_registry_pin,
        catalog_benchmark_identity_for_bfcl,
    )
    from bencheval.bfcl_package import BfclPackageSource, read_pinned_registry

    return read_pinned_registry(
        BfclPackageSource(
            package_root=_bfcl_package_root(),
            identity=catalog_benchmark_identity_for_bfcl(),
            registry_sha256=bfcl_registry_pin(),
        )
    )


def bfcl_model_support_check(
    model_id: str | None,
    *,
    models: ModelRegistry | None = None,
    registry_text: str | None = None,
) -> DoctorCheck:
    """Whether the BFCL launch gate would accept ``model_id``.

    Pass: the model's binding is a configured registration (extension) the run
    will generate, or a pinned upstream registration whose registered API model
    is the confirmed ``api_model`` (read from the pinned registry, never from
    the allowlist alone). ``registry_text`` injects that registry for tests.
    """
    from bencheval.bfcl_native_adapter import bfcl_supported_models
    from bencheval.bfcl_package import verify_upstream_binding
    from bencheval.model_binding import resolve_model_binding

    if model_id is None:
        return DoctorCheck("bfcl_model_support", "skip", "model id not supplied")
    try:
        supported_models = bfcl_supported_models()
        resolved = resolve_model_binding(model_id, models=models)
    except (BenchEvalError, OSError) as exc:
        return DoctorCheck("bfcl_model_support", "fail", f"cannot resolve BFCL support: {exc}")
    binding = resolved.bfcl
    if binding is not None and binding.mode == "configured":
        return DoctorCheck(
            "bfcl_model_support",
            "pass",
            f"model {model_id!r} uses a configured BFCL registration "
            f"({binding.registry_id!r}, {binding.handler}); diagnostic only",
        )
    registry_id = binding.registry_id if binding is not None else model_id
    if registry_id not in supported_models:
        return DoctorCheck(
            "bfcl_model_support",
            "fail",
            f"model {model_id!r} is not supported by the pinned BFCL evaluator: "
            f"{registry_id!r} is not a pinned registration"
            + ("" if binding is not None else " and the model declares no BFCL binding"),
        )
    try:
        text = registry_text if registry_text is not None else _pinned_registry_text()
        entry = verify_upstream_binding(resolved, text)
    except (BenchEvalError, OSError) as exc:
        return DoctorCheck(
            "bfcl_model_support",
            "fail",
            f"model {model_id!r} is not supported by the pinned BFCL evaluator: {exc}",
        )
    return DoctorCheck(
        "bfcl_model_support",
        "pass",
        f"model is the pinned upstream BFCL registration {registry_id!r} "
        f"(API model {entry.model_name!r}, {entry.handler_class})",
    )


def _bfcl_native_checks(model_id: str | None) -> list[DoctorCheck]:
    from bencheval.benchmark_registry import BfclPackageDataIdentity, load_benchmark_catalog
    from bencheval.bfcl_native_adapter import (
        bfcl_harness_version,
        capture_bfcl_benchmark_identity,
    )

    model_check = bfcl_model_support_check(model_id)
    identity = load_benchmark_catalog().by_id_or_alias("bfcl-v4").identity
    if not isinstance(identity, BfclPackageDataIdentity):
        return [
            model_check,
            DoctorCheck("bfcl_harness", "fail", "BFCL catalog identity is missing"),
        ]
    expected = f"bfcl-eval@{identity.bfcl_eval_version}"
    captured = bfcl_harness_version()
    checks = [
        model_check,
        DoctorCheck(
            "bfcl_harness",
            "pass" if captured == expected else "fail",
            f"captured {captured} matches the pinned harness"
            if captured == expected
            else f"expected {expected}; captured {captured}",
        ),
    ]
    try:
        capture_bfcl_benchmark_identity(identity)
    except (BenchEvalError, OSError) as exc:
        checks.append(DoctorCheck("bfcl_package_data", "fail", str(exc)))
    else:
        checks.append(
            DoctorCheck("bfcl_package_data", "pass", "pinned BFCL package data verified"),
        )
    return checks


def _hle_native_checks() -> list[DoctorCheck]:
    from bencheval.hle_adapter import hle_harness_version

    try:
        version = hle_harness_version()
        harness_error = None
    except (BenchEvalError, OSError) as exc:
        version = None
        harness_error = f"cannot inspect pinned official HLE checkout: {exc}"
    harness_ok = version is not None and not version.endswith("-dirty")
    checks = [
        DoctorCheck(
            "hle_harness",
            "pass" if harness_ok else "fail",
            f"pinned official HLE checkout available: {version}"
            if harness_ok
            else harness_error
            or "pinned official HLE checkout unavailable; set BENCHEVAL_HLE_HOME",
        ),
    ]
    missing_modules = [
        name for name in ("datasets", "huggingface_hub") if not _module_available(name)
    ]
    checks.append(
        DoctorCheck(
            "hle_dependencies",
            "fail" if missing_modules else "pass",
            f"missing modules: {', '.join(missing_modules)}; run `uv sync --extra eval`"
            if missing_modules
            else "datasets and huggingface_hub available",
        ),
    )
    token_present = any(env_var_present(name) for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"))
    if not token_present and _module_available("huggingface_hub"):
        try:
            from huggingface_hub import get_token

            token_present = bool(get_token())
        except (ImportError, OSError):
            token_present = False
    checks.append(
        DoctorCheck(
            "hle_dataset_token",
            "pass" if token_present else "fail",
            "Hugging Face token present for gated cais/hle"
            if token_present
            else "HF_TOKEN is required for the gated cais/hle dataset",
        ),
    )
    return checks


def _swebench_native_checks() -> list[DoctorCheck]:
    version, import_error = _try_import_inspect_ai()
    checks = [
        DoctorCheck(
            "inspect_ai_import",
            "pass" if version is not None and import_error is None else "fail",
            f"inspect_ai {version} available"
            if version is not None and import_error is None
            else import_error or "inspect_ai is not installed; run `uv sync --extra eval`",
        ),
    ]
    missing_modules = [
        name
        for name in ("inspect_evals", "inspect_swe", "huggingface_hub")
        if not _module_available(name)
    ]
    checks.append(
        DoctorCheck(
            "swe_generation_dependencies",
            "fail" if missing_modules else "pass",
            f"missing modules: {', '.join(missing_modules)}; run `uv sync --extra eval`"
            if missing_modules
            else "Inspect SWE generation dependencies available",
        ),
    )
    checks.append(
        _binary_check("uv_cli", "uv", "install uv to launch the pinned evaluator group"),
    )
    from bencheval.swebench_adapter import swebench_project_root

    group_ok = swebench_project_root() is not None
    checks.append(
        DoctorCheck(
            "swe_evaluator_group",
            "pass" if group_ok else "fail",
            "pinned SWE evaluator dependency group configured"
            if group_ok
            else "pinned SWE evaluator group requires a BenchEval project checkout",
        ),
    )
    docker_ok = docker_available()
    checks.append(
        DoctorCheck(
            "docker",
            "pass" if docker_ok else "fail",
            "docker daemon reachable"
            if docker_ok
            else "docker daemon is required for official SWE evaluation",
        ),
    )
    return checks


def run_native_doctor(
    harness_kind: str,
    *,
    model_id: str | None = None,
    execution_profile: ExecutionProfile | None = None,
) -> DoctorReport:
    """Preflight adapter-owned native harness requirements before a charged launch."""
    _ = execution_profile
    if harness_kind == "bfcl-native":
        checks = _bfcl_native_checks(model_id)
    elif harness_kind == "hle-native":
        checks = _hle_native_checks()
    elif harness_kind == "swebench-native":
        checks = _swebench_native_checks()
    else:
        raise BenchEvalError(f"doctor does not support native harness {harness_kind!r}")
    if model_id is not None:
        checks.append(_provider_credentials_check(model_id))
    return DoctorReport(
        backend=harness_kind,
        ok=all(check.status != "fail" for check in checks),
        checks=tuple(checks),
    )


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
