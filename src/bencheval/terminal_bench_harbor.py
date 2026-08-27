"""Terminal-Bench 2.1 adapter via Harbor CLI (control-plane)."""

from __future__ import annotations

import json
import math
import os
import stat
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from bencheval.doctor import harbor_revision
from bencheval.domain import FailureLabel, RunPlan, RuntimeCatalog
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.run_isolation import (
    dir_identity_error,
    open_owned_dir_fd,
    open_untrusted_regular_leaf,
    prepare_instance_artifacts_dir,
    write_bytes_at_exclusive,
    write_text_at_exclusive,
)
from bencheval.runtime_registry import load_runtime_catalog

# Harbor Hub dataset id for Terminal-Bench 2.1 (host pulls tasks/images).
HARBOR_DATASET = "terminal-bench/terminal-bench-2-1"
# Harbor 0.17 dataset task ids are namespaced: ``terminal-bench/fix-git``.
# BenchEval instance ids stay unprefixed (``fix-git``); only the CLI filter
# uses this prefix.
HARBOR_DATASET_TASK_PREFIX = "terminal-bench/"
# Concrete release identity stamped on evidence (replaces provisional plan labels).
TERMINAL_BENCH_RELEASE_VERSION = "terminal-bench@2.1"
TERMINAL_BENCH_ADAPTER_ID = "terminal-bench-harbor"
# Harbor's job tree is transient. Official result bytes are copied to this
# owned name before cleanup removes harbor-package.
HARBOR_JOBS_DIR_NAME = "harbor-package"
HARBOR_OFFICIAL_RESULT_NAME = "harbor-official-result.json"
CLAUDE_CODE_NPM_IMPORT_PATH = "bencheval.harbor_claude_code_npm:ClaudeCodeNpmInstall"
CODEX_NPM_IMPORT_PATH = "bencheval.harbor_codex_npm:CodexNpmInstall"

_RUNTIME_TO_HARBOR_AGENT: dict[str, str] = {
    "codex-cli": "codex",
}
_PROXY_FORWARD_FLAG = "BENCHEVAL_HARBOR_FORWARD_PROXY"
_PROXY_ENV_NAMES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)
_CODEX_PROVIDER_ID = "bytellm"
_CODEX_CONFIG_TARGET = "/logs/agent/config.toml"
_CLI_AGENT_SETUP_TIMEOUT_MULTIPLIER = "8"
_CLAUDE_CODE_ALLOWED_TOOLS_ENV = "BENCHEVAL_CLAUDE_CODE_ALLOWED_TOOLS"
_PROVIDER_BASE_URL_ENVS = ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL")


def _as_bool_verdict(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class HarborCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerminalBenchInstanceOutcome:
    instance_id: str
    primary_pass: bool
    partial_score: float
    cost_usd: float
    latency_sec: float
    native_score: dict[str, object]
    failure_class: FailureLabel | None
    stdout_path: str | None
    stderr_path: str | None
    raw_result_path: str | None
    adapter_metadata: dict[str, str]
    # Container-side agent identity from the trial result's ``agent_info``
    # (extracted whenever the artifact parses; compared against the catalog
    # pin when the run path passes expectations).
    agent_name: str | None = None
    agent_version: str | None = None


class HarborProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> HarborCliResult: ...


def harbor_agent_for_runtime(runtime_id: str) -> str:
    if runtime_id == "claude-code":
        return "claude-code"
    agent = _RUNTIME_TO_HARBOR_AGENT.get(runtime_id)
    if agent is None:
        raise BenchEvalError(
            f"runtime {runtime_id!r} has no Harbor --agent mapping; "
            f"known: {sorted((*_RUNTIME_TO_HARBOR_AGENT, 'claude-code'))}",
        )
    return agent


def harbor_dataset_task_name(instance_id: str) -> str:
    """Map a BenchEval instance id onto the Harbor 0.17 dataset task name."""
    validate_control_plane_instance_id(instance_id)
    return f"{HARBOR_DATASET_TASK_PREFIX}{instance_id}"


_UNSAFE_AGENT_ENV_CHARS = frozenset("\n\r\t =")


def _harbor_claude_custom_model_args(plan: RunPlan) -> list[str]:
    """Allow Harbor Claude to use a catalog model that is not an Anthropic SKU."""
    if plan.runtime_id != "claude-code":
        return []
    model = plan.model_id
    if model == "runtime-default":
        return []
    if not model or any(character in model for character in _UNSAFE_AGENT_ENV_CHARS):
        raise BenchEvalError(
            f"model_id {model!r} cannot be placed on Harbor ANTHROPIC_CUSTOM_MODEL_OPTION",
        )
    return ["--agent-env", f"ANTHROPIC_CUSTOM_MODEL_OPTION={model}"]


def _harbor_provider_base_url_args() -> list[str]:
    """Pass provider base URLs into Harbor extra_env. Never keys or userinfo."""
    args: list[str] = []
    for name in _PROVIDER_BASE_URL_ENVS:
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        parsed = urlsplit(raw)
        if parsed.username or parsed.password or "@" in raw:
            raise BenchEvalError(
                f"{name} contains userinfo; refuse to place it on Harbor argv",
            )
        if parsed.query or parsed.fragment:
            raise BenchEvalError(
                f"{name} contains a query or fragment; refuse to place it on Harbor argv",
            )
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise BenchEvalError(f"{name} is not a usable http(s) URL")
        args.extend(["--agent-env", f"{name}={raw}"])
    return args


def _harbor_agent_version_pin(runtime_id: str, *, catalog: RuntimeCatalog | None = None) -> str:
    """Launch-time agent version pin for a Harbor runtime; a missing pin cannot launch.

    Harbor installs and executes the agent inside the container, so the host
    ``version_command`` cannot prove what actually ran. The catalog pin is the
    only identity the launch boundary can enforce (``--agent-kwarg version=``)
    and compare against the trial result's ``agent_info.version`` after the run.
    """
    runtime_catalog = catalog if catalog is not None else load_runtime_catalog()
    try:
        profile = runtime_catalog.by_id(runtime_id)
    except KeyError as e:
        raise BenchEvalError(f"unknown runtime {runtime_id!r} for agent version pin") from e
    pin = profile.versioning.agent_version_pin
    if pin is None or not pin.strip():
        raise BenchEvalError(
            f"runtime {runtime_id!r} has no versioning.agent_version_pin; "
            "an unpinned agent version cannot launch under Harbor",
        )
    return pin


def write_harbor_proxy_env_file(*, network_policy: str) -> Path | None:
    # Plan policy wins over the operator opt-in flag: deny never forwards host
    # proxy into the Harbor task env (even when BENCHEVAL_HARBOR_FORWARD_PROXY=1).
    if network_policy == "deny":
        return None
    if network_policy not in ("allow", "benchmark_required"):
        return None
    if os.environ.get(_PROXY_FORWARD_FLAG) != "1":
        return None

    lines: list[str] = []
    for name in _PROXY_ENV_NAMES:
        value = os.environ.get(name)
        if not value or "\n" in value:
            continue
        lines.append(f"{name}={value}")
    if not lines:
        return None

    # Outside the evidence/raw tree so private bundles cannot archive credentials.
    fd, name = tempfile.mkstemp(prefix="bencheval-harbor-proxy-", suffix=".env")
    env_file = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        env_file.chmod(0o600)
    except OSError:
        env_file.unlink(missing_ok=True)
        raise
    return env_file


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _write_codex_provider_config(
    artifacts_dir: Path,
    instance_dir_fd: int | None = None,
) -> Path | None:
    base_url = os.environ.get("OPENAI_BASE_URL")
    if not base_url:
        return None
    env_key = os.environ.get("BENCHEVAL_CODEX_ENV_KEY")
    if not env_key:
        env_key = "OPENAI_API_KEY"

    config_file = artifacts_dir / ".bencheval-codex-config.toml"
    content = "\n".join(
        [
            f"model_provider = {_toml_string(_CODEX_PROVIDER_ID)}",
            "",
            f"[model_providers.{_CODEX_PROVIDER_ID}]",
            f"name = {_toml_string('ByteLLM')}",
            f"base_url = {_toml_string(base_url)}",
            f"env_key = {_toml_string(env_key)}",
            "supports_websockets = false",
            f"wire_api = {_toml_string('responses')}",
            "",
        ],
    )
    # Anchored, no-follow, exclusive recreate: "pre-launch" is no boundary for
    # instances >= 2 (a prior instance's toolchain code can plant a symlink at
    # this path), so the write is anchored to the descriptor pinned before any
    # launch — never an unchecked pathname.
    owns_fd = instance_dir_fd is None
    dir_fd = (
        open_owned_dir_fd(artifacts_dir, role="terminal-bench instance artifacts directory")
        if owns_fd
        else instance_dir_fd
    )
    try:
        write_text_at_exclusive(dir_fd, config_file.name, content)
    finally:
        if owns_fd:
            os.close(dir_fd)
    return config_file


def _codex_config_mounts_json(config_file: Path) -> str:
    return json.dumps(
        [
            {
                "type": "bind",
                "source": str(config_file.resolve()),
                "target": _CODEX_CONFIG_TARGET,
                "read_only": True,
                "bind": {"create_host_path": False},
            },
        ],
    )


def build_harbor_run_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    dataset: str = HARBOR_DATASET,
    proxy_env_file: Path | None = None,
    instance_dir_fd: int | None = None,
) -> tuple[str, ...]:
    validate_control_plane_instance_id(instance_id)
    if plan.runtime_id is None:
        raise BenchEvalError("Harbor adapter requires runtime_id (use --runtime)")
    # Harbor cannot disable container egress; deny is an unenforceable claim.
    if plan.network_policy == "deny":
        raise BenchEvalError(
            "Harbor adapter cannot enforce network_policy=deny "
            "(no container network isolation); use benchmark_required or allow",
        )
    agent = harbor_agent_for_runtime(plan.runtime_id)
    model = plan.model_id
    cmd: list[str] = [
        "harbor",
        "run",
        "--yes",
    ]
    # Caller owns lifecycle (create via write_harbor_proxy_env_file + finally unlink).
    if proxy_env_file is not None:
        # Proxy credentials stay in the mode-0600 env file only — never argv.
        cmd.extend(["--env-file", str(proxy_env_file.resolve())])
    if plan.runtime_id == "claude-code":
        # Harbor 0.17+ takes a custom agent as --agent module:Class.
        cmd.extend(["--agent", CLAUDE_CODE_NPM_IMPORT_PATH])
        allowed_tools = os.environ.get(_CLAUDE_CODE_ALLOWED_TOOLS_ENV)
        if allowed_tools and "\n" not in allowed_tools:
            cmd.extend(["--agent-kwarg", f"allowed_tools={allowed_tools}"])
    elif plan.runtime_id == "codex-cli":
        cmd.extend(["--agent", CODEX_NPM_IMPORT_PATH])
    else:
        cmd.extend(["--agent", agent])
    if plan.runtime_id in {"claude-code", "codex-cli"}:
        cmd.extend(
            [
                "--agent-setup-timeout-multiplier",
                _CLI_AGENT_SETUP_TIMEOUT_MULTIPLIER,
            ],
        )
        # Pin the agent version at launch: the container-side install must be
        # exactly the catalog-pinned version the post-run agent_info check
        # compares against.
        cmd.extend(["--agent-kwarg", f"version={_harbor_agent_version_pin(plan.runtime_id)}"])
    cmd.extend(_harbor_provider_base_url_args())
    cmd.extend(_harbor_claude_custom_model_args(plan))
    if plan.runtime_id == "codex-cli":
        codex_config = _write_codex_provider_config(artifacts_dir, instance_dir_fd)
        if codex_config is not None:
            cmd.extend(["--mounts-json", _codex_config_mounts_json(codex_config)])
    cmd.extend(
        [
            "--dataset",
            dataset,
            "--include-task-name",
            harbor_dataset_task_name(instance_id),
            "--jobs-dir",
            str((artifacts_dir / HARBOR_JOBS_DIR_NAME).resolve()),
            "--n-concurrent",
            "1",
        ],
    )
    if model != "runtime-default":
        cmd.extend(["--model", model])
    return tuple(cmd)


def _sanitized_command_for_metadata(command: Sequence[str]) -> str:
    """Render a harbor argv for evidence metadata with secret values removed.

    Proxy secrets are forwarded via ``--env-file`` (not argv). Keep defense-in-depth
    redaction for any residual ``--agent-env NAME=value`` tokens so credentialed
    values never reach evidence (public bundles serialize ``adapter_metadata``).
    """
    parts: list[str] = []
    redact_next = False
    for arg in command:
        if redact_next:
            redact_next = False
            name, sep, _ = arg.partition("=")
            parts.append(f"{name}=[redacted]" if sep else "[redacted]")
            continue
        parts.append(arg)
        if arg == "--agent-env":
            redact_next = True
    return " ".join(parts)


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
) -> HarborCliResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"harbor CLI timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"harbor_command": _sanitized_command_for_metadata(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"harbor CLI launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"harbor_command": _sanitized_command_for_metadata(command)},
        ) from e
    return HarborCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def _locate_native_result(artifacts_dir: Path, *, instance_id: str) -> Path | None:
    direct_candidates = [
        artifacts_dir / "result.json",
        artifacts_dir / "results.json",
        artifacts_dir / "harbor_result.json",
    ]
    try:
        nested = sorted(artifacts_dir.rglob("result.json"))
    except OSError as e:
        # e.g. a harness-planted symlink cycle (ELOOP): fail closed instead of
        # leaking a raw OSError past the adapter boundary.
        raise AdapterFailureError(
            f"harbor result locate failed: {e}",
            failure_label="evidence_corrupt",
            latency_sec=0.0,
            adapter_metadata={"harbor_artifacts_dir": str(artifacts_dir)},
        ) from e
    candidates = sorted({path for path in (*direct_candidates, *nested) if path.is_file()})
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Official Harbor jobs contain a job-level aggregate ``result.json`` plus
    # one per-trial result. Trial directories are named either exactly for the
    # task or ``<task>__<trial-id>``. Select only the requested instance; never
    # let lexical ordering turn the aggregate into scoring authority.
    trial_prefix = f"{instance_id}__"
    instance_candidates = [
        path
        for path in candidates
        if path.name == "result.json"
        and (path.parent.name == instance_id or path.parent.name.startswith(trial_prefix))
    ]
    if len(instance_candidates) == 1:
        return instance_candidates[0]
    raise AdapterFailureError(
        f"harbor result layout is ambiguous for instance {instance_id!r}",
        failure_label="evidence_corrupt",
        latency_sec=0.0,
        adapter_metadata={"harbor_artifacts_dir": str(artifacts_dir)},
    )


@dataclass(frozen=True)
class _ResultPin:
    """Identity of the harness result, bound at the post-run identity check.

    Harbor nests the job result below ``--jobs-dir`` (real layout:
    ``<jobs-dir>/<job-timestamp>/result.json``), so the pre-launch instance-dir
    pin alone cannot bind it. The pin walks every directory component from the
    pinned root with O_NOFOLLOW (a symlink or swap mid-chain fails closed at
    pin time) and records the file's (dev, ino); the scored read then compares
    both the opened fd and the pathname against this identity.
    """

    found: bool
    rel: Path | None = None
    chain_fd: int | None = None  # terminal dir fd when nested; owned by caller
    dev: int = 0
    ino: int = 0


def _pin_native_result(
    instance_fd: int,
    instance_dir: Path,
    *,
    instance_id: str,
    cli: HarborCliResult,
) -> _ResultPin:
    """Locate and pin the harness result chain; fail closed on any anomaly."""
    located = _locate_native_result(instance_dir, instance_id=instance_id)
    if located is None:
        return _ResultPin(found=False)
    rel = located.relative_to(instance_dir)
    owned: int | None = None
    try:
        current = instance_fd
        for part in rel.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            if owned is not None:
                os.close(owned)
            owned = next_fd
            current = next_fd
        st = os.stat(rel.parts[-1], dir_fd=current, follow_symlinks=False)
    except OSError as e:
        if owned is not None:
            os.close(owned)
        raise AdapterFailureError(
            f"harbor result path failed the pinned-chain check: {e}",
            failure_label="evidence_corrupt",
            latency_sec=cli.latency_sec,
            adapter_metadata={"harbor_command": _sanitized_command_for_metadata(cli.command)},
        ) from e
    if not stat.S_ISREG(st.st_mode):
        if owned is not None:
            os.close(owned)
        raise AdapterFailureError(
            f"harbor result path is not a regular file under the pinned tree: {located}",
            failure_label="evidence_corrupt",
            latency_sec=cli.latency_sec,
            adapter_metadata={"harbor_command": _sanitized_command_for_metadata(cli.command)},
        )
    return _ResultPin(found=True, rel=rel, chain_fd=owned, dev=st.st_dev, ino=st.st_ino)


def _read_result_bytes(
    result_file: Path,
    artifacts_dir: Path,
    instance_dir_fd: int | None,
    result_pin: _ResultPin | None = None,
) -> bytes:
    """Read located result bytes, bound to the post-run pin when present."""
    if result_pin is None:
        return result_file.read_bytes()
    rel = result_file.relative_to(artifacts_dir)
    if not result_pin.found or rel != result_pin.rel:
        raise AdapterFailureError(
            "harbor result layout changed between the post-run pin and the scored read",
            failure_label="evidence_corrupt",
        )
    parent_fd = result_pin.chain_fd if result_pin.chain_fd is not None else instance_dir_fd
    try:
        fd = open_untrusted_regular_leaf(result_file.name, dir_fd=parent_fd)
    except OSError as e:
        raise AdapterFailureError(
            f"harbor result vanished from the pinned chain: {e}",
            failure_label="evidence_corrupt",
        ) from e
    try:
        st = os.fstat(fd)
        with os.fdopen(fd, "rb") as handle:
            data = handle.read()
    except OSError as e:
        raise AdapterFailureError(
            f"harbor result read from the pinned chain failed: {e}",
            failure_label="evidence_corrupt",
        ) from e
    if (st.st_dev, st.st_ino) != (result_pin.dev, result_pin.ino):
        raise AdapterFailureError(
            "harbor result inode changed between the post-run pin and the scored read",
            failure_label="evidence_corrupt",
        )
    try:
        current = result_file.stat()
    except OSError as e:
        raise AdapterFailureError(
            f"harbor result pathname no longer resolves after the post-run pin: {e}",
            failure_label="evidence_corrupt",
        ) from e
    if (current.st_dev, current.st_ino) != (result_pin.dev, result_pin.ino):
        raise AdapterFailureError(
            "harbor result pathname no longer names the pinned inode",
            failure_label="evidence_corrupt",
        )
    return data


def _read_result_text(
    result_file: Path,
    artifacts_dir: Path,
    instance_dir_fd: int | None,
    result_pin: _ResultPin | None = None,
) -> str:
    """Read a located result file, bound to the post-run pin when present.

    With a pin, the bytes come from the pinned chain (O_NOFOLLOW relative to
    the terminal dir fd) and both the opened fd and the pathname must still
    name the pinned inode — a rename-and-recreate or symlink swap of any
    component after the post-run check fails closed. fd-less direct callers
    keep the documented pathname fallback. Honest residual (shared by all
    four adapters): dirfd pinning cannot detect an in-place rewrite of a
    harness-authored score file — it closes the swap variant.
    """
    if result_pin is None:
        return result_file.read_text(encoding="utf-8")
    return _read_result_bytes(
        result_file,
        artifacts_dir,
        instance_dir_fd,
        result_pin,
    ).decode("utf-8")


def _read_direct_child_bytes(dir_fd: int, name: str) -> bytes:
    if "/" in name or name in ("", ".", ".."):
        raise BenchEvalError(f"unsafe dirfd-relative file name: {name!r}")
    descriptor = open_untrusted_regular_leaf(name, dir_fd=dir_fd)
    try:
        handle = os.fdopen(descriptor, "rb")
        descriptor = -1
        with handle:
            return handle.read()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _numeric_gt_zero(value: object) -> bool:
    return isinstance(value, (int, float)) and value > 0


def _official_verifier_reward(verifier_result: object) -> float | None:
    """Harbor ``TrialResult.verifier_result`` → reward in [0, 1]; None when malformed.

    Official passing rule (``harbor/analyze/analyzer.py``): the trial passes
    iff ``verifier_result.rewards["reward"] == 1.0`` (and ``exception_info`` is
    null, which the caller checks first). Sub-1.0 rewards are partial credit.
    """
    if not isinstance(verifier_result, dict):
        return None
    rewards = verifier_result.get("rewards")
    if not isinstance(rewards, dict) or "reward" not in rewards:
        return None
    reward = rewards["reward"]
    if isinstance(reward, bool) or not isinstance(reward, (int, float)):
        return None
    reward = float(reward)
    if not math.isfinite(reward) or not 0.0 <= reward <= 1.0:
        return None
    return reward


def _agent_identity(parsed: dict[str, object]) -> tuple[str | None, str | None]:
    """Trial result ``agent_info`` → (name, version); (None, None) when absent/malformed."""
    info = parsed.get("agent_info")
    if not isinstance(info, dict):
        return None, None
    name = info.get("name")
    version = info.get("version")
    return (
        name if isinstance(name, str) and name else None,
        version if isinstance(version, str) and version else None,
    )


def _harbor_result_has_errors(parsed: dict[str, object]) -> bool:
    if isinstance(parsed.get("exception_info"), dict):
        return True

    stats = parsed.get("stats")
    if not isinstance(stats, dict):
        return False
    if _numeric_gt_zero(stats.get("n_errors")):
        return True

    evals = stats.get("evals")
    if not isinstance(evals, dict):
        return False
    for eval_summary in evals.values():
        if not isinstance(eval_summary, dict):
            continue
        if _numeric_gt_zero(eval_summary.get("n_errors")):
            return True
        exception_stats = eval_summary.get("exception_stats")
        if isinstance(exception_stats, dict) and exception_stats:
            return True
    return False


def parse_harbor_instance_outcome(
    *,
    instance_id: str,
    cli: HarborCliResult,
    artifacts_dir: Path,
    repo_root: Path,
    harness_version: str | None,
    network_policy: str = "",
    instance_dir_fd: int | None = None,
    result_pin: _ResultPin | None = None,
    expected_agent_name: str | None = None,
    expected_agent_version: str | None = None,
) -> TerminalBenchInstanceOutcome:
    stdout_file = artifacts_dir / "stdout.log"
    stderr_file = artifacts_dir / "stderr.log"
    # Anchored, no-follow, exclusive recreates: a symlink or hard link planted
    # at these paths by the Harbor CLI (handed this tree via --jobs-dir) is
    # unlinked — never opened, truncated, or followed — and replaced by a
    # fresh regular file. The runner pins the descriptor before launch and
    # passes it in; direct callers get an at-parse pin (no launch window).
    owns_fd = instance_dir_fd is None
    dir_fd = (
        open_owned_dir_fd(artifacts_dir, role="terminal-bench instance artifacts directory")
        if owns_fd
        else instance_dir_fd
    )
    try:
        write_text_at_exclusive(dir_fd, "stdout.log", cli.stdout)
        write_text_at_exclusive(dir_fd, "stderr.log", cli.stderr)
    finally:
        if owns_fd:
            os.close(dir_fd)
    stdout_rel = str(stdout_file.resolve())
    stderr_rel = str(stderr_file.resolve())

    raw_path: str | None = None
    native: dict[str, object] = {"harbor_returncode": cli.returncode}
    primary_pass = cli.returncode == 0
    partial_score = 1.0 if primary_pass else 0.0
    failure_class: FailureLabel | None = None
    cost_usd = 0.0
    agent_name: str | None = None
    agent_version: str | None = None

    result_file = _locate_native_result(artifacts_dir, instance_id=instance_id)
    if result_pin is not None:
        # The candidate set must be identical to what the post-run pin bound:
        # a planted or vanished candidate between pin and parse fails closed.
        expected = (artifacts_dir / result_pin.rel) if result_pin.found else None
        if result_file != expected:
            raise AdapterFailureError(
                "harbor result layout changed between the post-run pin and the scored read",
                failure_label="evidence_corrupt",
                latency_sec=cli.latency_sec,
                adapter_metadata={
                    "harbor_command": _sanitized_command_for_metadata(cli.command),
                },
            )
    if result_file is not None:
        if instance_dir_fd is not None:
            # Re-verify immediately before the scored read (F107 parity): the
            # post-run check in the runner cannot see a rename-and-recreate
            # swap that lands between it and this read.
            identity_error = dir_identity_error(
                instance_dir_fd,
                artifacts_dir,
                role="terminal-bench instance artifacts directory",
            )
            if identity_error is not None:
                raise AdapterFailureError(
                    identity_error,
                    failure_label="evidence_corrupt",
                    latency_sec=cli.latency_sec,
                    adapter_metadata={
                        "harbor_command": _sanitized_command_for_metadata(cli.command),
                    },
                )
        raw_path = str(result_file.resolve())
        try:
            parsed = json.loads(
                _read_result_text(result_file, artifacts_dir, instance_dir_fd, result_pin),
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            failure_class = "runtime_output_unparseable"
            primary_pass = False
            partial_score = 0.0
        else:
            if isinstance(parsed, dict):
                native = {**native, **parsed}
                agent_name, agent_version = _agent_identity(parsed)
                if isinstance(parsed.get("exception_info"), dict):
                    primary_pass = False
                    partial_score = 0.0
                    failure_class = "runtime_launch_failure"
                elif parsed.get("exception_info") is not None:
                    # exception_info must be absent, null, or an ExceptionInfo
                    # object; a present-but-non-object value violates the
                    # official schema, so even a pass-bearing reward cannot
                    # rescue the artifact.
                    primary_pass = False
                    partial_score = 0.0
                    failure_class = "runtime_output_unparseable"
                elif _harbor_result_has_errors(parsed):
                    primary_pass = False
                    partial_score = 0.0
                    failure_class = "harness_failure"
                elif "verifier_result" in parsed:
                    # Official Harbor trial schema: the verifier reward is the
                    # only verdict authority once the key is present — no
                    # fallback to the legacy top-level booleans.
                    reward = _official_verifier_reward(parsed["verifier_result"])
                    if reward is None:
                        failure_class = "runtime_output_unparseable"
                        primary_pass = False
                        partial_score = 0.0
                    else:
                        native["verdict_provenance"] = "harbor_verifier_result"
                        primary_pass = reward == 1.0
                        partial_score = reward
                elif "resolved" in parsed:
                    verdict = _as_bool_verdict(parsed["resolved"])
                    if verdict is None:
                        failure_class = "runtime_output_unparseable"
                        primary_pass = False
                        partial_score = 0.0
                    else:
                        native["verdict_provenance"] = "legacy_top_level_boolean"
                        primary_pass = verdict
                        partial_score = 1.0 if primary_pass else 0.0
                elif "success" in parsed:
                    verdict = _as_bool_verdict(parsed["success"])
                    if verdict is None:
                        failure_class = "runtime_output_unparseable"
                        primary_pass = False
                        partial_score = 0.0
                    else:
                        native["verdict_provenance"] = "legacy_top_level_boolean"
                        primary_pass = verdict
                        partial_score = 1.0 if primary_pass else 0.0
                else:
                    failure_class = "runtime_output_unparseable"
                    primary_pass = False
                    partial_score = 0.0
                if "cost_usd" in parsed and isinstance(parsed["cost_usd"], (int, float)):
                    cost_usd = float(parsed["cost_usd"])
            else:
                failure_class = "runtime_output_unparseable"
                primary_pass = False
                partial_score = 0.0
    elif cli.returncode != 0:
        failure_class = "harness_failure"
    elif cli.returncode == 0:
        failure_class = "harness_failure"
        primary_pass = False
        partial_score = 0.0

    # Process failure dominates: artifact verdicts are diagnostic only when rc != 0.
    if cli.returncode != 0:
        primary_pass = False
        partial_score = 0.0
        if failure_class is None:
            failure_class = "harness_failure"

    # Uncaptured agent provenance fails closed: when the run path declares the
    # expected agent identity (catalog pin), a missing or mismatched agent_info
    # means the artifact cannot prove which agent produced the verdict, so the
    # pass is forfeited as runtime_config_drift.
    if (
        expected_agent_name is not None
        and failure_class is None
        and (agent_name != expected_agent_name or agent_version != expected_agent_version)
    ):
        primary_pass = False
        partial_score = 0.0
        failure_class = "runtime_config_drift"

    if not primary_pass and failure_class is None:
        failure_class = "model_wrong_solution"

    def _rel(p: str) -> str:
        try:
            return str(Path(p).resolve().relative_to(repo_root))
        except ValueError:
            return p

    metadata = {
        "adapter_id": TERMINAL_BENCH_ADAPTER_ID,
        "harbor_dataset": HARBOR_DATASET,
        "harbor_command": _sanitized_command_for_metadata(cli.command),
        "network_policy": network_policy,
        "proxy_forwarded": "1" if "--env-file" in cli.command else "0",
    }
    if harness_version:
        metadata["harness_version"] = harness_version

    return TerminalBenchInstanceOutcome(
        instance_id=instance_id,
        primary_pass=primary_pass,
        partial_score=partial_score,
        cost_usd=cost_usd,
        latency_sec=cli.latency_sec,
        native_score=native,
        failure_class=failure_class,
        stdout_path=_rel(stdout_rel),
        stderr_path=_rel(stderr_rel),
        raw_result_path=_rel(raw_path) if raw_path else None,
        adapter_metadata=metadata,
        agent_name=agent_name,
        agent_version=agent_version,
    )


def _retain_pinned_harbor_bytes(
    result_pin: _ResultPin,
    *,
    instance_dir: Path,
    instance_fd: int,
    repo_root: Path,
    latency_sec: float,
    command: Sequence[str],
) -> str | None:
    """Copy pinned Harbor result bytes out of the transient jobs tree."""
    if not result_pin.found or result_pin.rel is None:
        return None
    source = instance_dir / result_pin.rel
    metadata = {"harbor_command": _sanitized_command_for_metadata(command)}
    try:
        data = _read_result_bytes(source, instance_dir, instance_fd, result_pin)
        write_bytes_at_exclusive(instance_fd, HARBOR_OFFICIAL_RESULT_NAME, data)
        written = _read_direct_child_bytes(instance_fd, HARBOR_OFFICIAL_RESULT_NAME)
        if written != data:
            raise AdapterFailureError(
                "retained Harbor official result bytes do not match the scored bytes",
                failure_label="evidence_corrupt",
                latency_sec=latency_sec,
                adapter_metadata=metadata,
            )
    except (OSError, BenchEvalError) as e:
        if isinstance(e, AdapterFailureError):
            raise
        raise AdapterFailureError(
            f"cannot retain official Harbor result bytes: {e}",
            failure_label="evidence_corrupt",
            latency_sec=latency_sec,
            adapter_metadata=metadata,
        ) from e
    retained = instance_dir / HARBOR_OFFICIAL_RESULT_NAME
    try:
        return str(retained.resolve().relative_to(repo_root))
    except ValueError:
        return str(retained.resolve())


def _retain_located_harbor_result(
    *,
    instance_dir: Path,
    instance_fd: int,
    instance_id: str,
    repo_root: Path,
    cli: HarborCliResult,
) -> str | None:
    result_pin = _pin_native_result(
        instance_fd,
        instance_dir,
        instance_id=instance_id,
        cli=cli,
    )
    try:
        return _retain_pinned_harbor_bytes(
            result_pin,
            instance_dir=instance_dir,
            instance_fd=instance_fd,
            repo_root=repo_root,
            latency_sec=cli.latency_sec,
            command=cli.command,
        )
    finally:
        if result_pin.chain_fd is not None:
            os.close(result_pin.chain_fd)


def _try_retain_after_budget_exceeded(
    *,
    instance_dir: Path,
    instance_fd: int,
    instance_id: str,
    repo_root: Path,
    command: Sequence[str],
    latency_sec: float,
) -> str | None:
    timeout_cli = HarborCliResult(-1, "", "", latency_sec, tuple(command))
    try:
        return _retain_located_harbor_result(
            instance_dir=instance_dir,
            instance_fd=instance_fd,
            instance_id=instance_id,
            repo_root=repo_root,
            cli=timeout_cli,
        )
    except AdapterFailureError as retain_error:
        if retain_error.failure_label != "evidence_corrupt":
            raise
        return None


def run_harbor_dataset_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    dataset: str,
    expected_adapter_id: str,
    process_runner: HarborProcessRunner | None = None,
    timeout_sec: int | None = None,
) -> TerminalBenchInstanceOutcome:
    if plan.adapter_id != expected_adapter_id:
        raise BenchEvalError(
            f"Harbor adapter {expected_adapter_id!r} cannot run adapter_id={plan.adapter_id!r}",
        )
    runtime_id = plan.runtime_id
    if runtime_id is None:
        raise BenchEvalError("Harbor adapter requires runtime_id (use --runtime)")
    revision = harbor_revision()
    if revision is None and process_runner is None:
        raise AdapterFailureError(
            "harbor CLI is not available",
            failure_label="runtime_launch_failure",
        )

    validate_control_plane_instance_id(instance_id)
    instance_dir = prepare_instance_artifacts_dir(artifacts_dir / instance_id)
    # Pin the instance directory inode before launching Harbor: the CLI is
    # handed this tree via --jobs-dir, the post-run identity check proves the
    # path still names the pinned inode, and the log writes stay anchored to
    # the descriptor.
    instance_fd = open_owned_dir_fd(
        instance_dir,
        role="terminal-bench instance artifacts directory",
    )
    proxy_env = write_harbor_proxy_env_file(network_policy=plan.network_policy)
    try:
        command = build_harbor_run_command(
            plan=plan,
            instance_id=instance_id,
            artifacts_dir=instance_dir,
            dataset=dataset,
            proxy_env_file=proxy_env,
            instance_dir_fd=instance_fd,
        )
        if timeout_sec is not None:
            wall = timeout_sec
        else:
            wall = max(1, plan.max_wall_clock_sec_per_instance)
        runner = process_runner or _default_process_runner
        start = time.monotonic()
        try:
            cli = runner(command, cwd=repo_root, timeout_sec=wall)
        except (subprocess.TimeoutExpired, AdapterFailureError) as e:
            if isinstance(e, AdapterFailureError) and e.failure_label != "runtime_budget_exceeded":
                raise
            elapsed = (
                e.latency_sec
                if isinstance(e, AdapterFailureError) and e.latency_sec
                else time.monotonic() - start
            )
            retained_rel = _try_retain_after_budget_exceeded(
                instance_dir=instance_dir,
                instance_fd=instance_fd,
                instance_id=instance_id,
                repo_root=repo_root,
                command=command,
                latency_sec=elapsed,
            )
            if isinstance(e, AdapterFailureError):
                if retained_rel is not None:
                    e.adapter_metadata["harbor_official_result"] = retained_rel
                raise
            timeout_metadata = {
                "harbor_command": _sanitized_command_for_metadata(command),
            }
            if retained_rel is not None:
                timeout_metadata["harbor_official_result"] = retained_rel
            raise AdapterFailureError(
                f"harbor CLI timed out after {wall}s",
                failure_label="runtime_budget_exceeded",
                latency_sec=elapsed,
                adapter_metadata=timeout_metadata,
            ) from e
        except OSError as e:
            elapsed = time.monotonic() - start
            raise AdapterFailureError(
                f"harbor CLI launch failed: {e}",
                failure_label="runtime_launch_failure",
                latency_sec=elapsed,
                adapter_metadata={"harbor_command": _sanitized_command_for_metadata(command)},
            ) from e
        identity_error = dir_identity_error(
            instance_fd,
            instance_dir,
            role="terminal-bench instance artifacts directory",
        )
        if identity_error is not None:
            # The launched CLI swapped the approved directory mid-run; the
            # dirfd-anchored writes stay on the pinned inode, so fail closed
            # instead of publishing attacker-controlled content.
            raise AdapterFailureError(
                identity_error,
                failure_label="evidence_corrupt",
                latency_sec=cli.latency_sec,
                adapter_metadata={"harbor_command": _sanitized_command_for_metadata(cli.command)},
            )
        # Harbor nests the job result below --jobs-dir; bind the located chain
        # now (same window-free region as the root check) so the scored read
        # in parse cannot be redirected by a post-check swap. Retain before
        # parse so a later AdapterFailureError cannot lose official bytes to
        # harbor-package cleanup.
        result_pin = _pin_native_result(
            instance_fd,
            instance_dir,
            instance_id=instance_id,
            cli=cli,
        )
        try:
            retained_rel = _retain_pinned_harbor_bytes(
                result_pin,
                instance_dir=instance_dir,
                instance_fd=instance_fd,
                repo_root=repo_root,
                latency_sec=cli.latency_sec,
                command=cli.command,
            )
            outcome = parse_harbor_instance_outcome(
                instance_id=instance_id,
                cli=cli,
                artifacts_dir=instance_dir,
                repo_root=repo_root,
                harness_version=revision,
                network_policy=plan.network_policy,
                instance_dir_fd=instance_fd,
                result_pin=result_pin,
                expected_agent_name=harbor_agent_for_runtime(runtime_id),
                expected_agent_version=_harbor_agent_version_pin(runtime_id),
            )
            if retained_rel is None:
                return outcome
            return replace(outcome, raw_result_path=retained_rel)
        finally:
            if result_pin.chain_fd is not None:
                os.close(result_pin.chain_fd)
    finally:
        if proxy_env is not None:
            proxy_env.unlink(missing_ok=True)
        os.close(instance_fd)


def run_terminal_bench_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: HarborProcessRunner | None = None,
    timeout_sec: int | None = None,
) -> TerminalBenchInstanceOutcome:
    return run_harbor_dataset_instance(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=artifacts_dir,
        repo_root=repo_root,
        dataset=HARBOR_DATASET,
        expected_adapter_id=TERMINAL_BENCH_ADAPTER_ID,
        process_runner=process_runner,
        timeout_sec=timeout_sec,
    )


__all__ = [
    "CLAUDE_CODE_NPM_IMPORT_PATH",
    "CODEX_NPM_IMPORT_PATH",
    "HARBOR_DATASET",
    "TERMINAL_BENCH_ADAPTER_ID",
    "HarborCliResult",
    "HarborProcessRunner",
    "TerminalBenchInstanceOutcome",
    "build_harbor_run_command",
    "harbor_agent_for_runtime",
    "parse_harbor_instance_outcome",
    "run_harbor_dataset_instance",
    "run_terminal_bench_instance",
    "write_harbor_proxy_env_file",
]
