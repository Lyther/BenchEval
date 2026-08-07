"""Terminal-Bench 2.1 adapter via Harbor CLI (control-plane)."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bencheval.doctor import harbor_revision
from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id

# Harbor Hub dataset id for Terminal-Bench 2.1 (host pulls tasks/images).
HARBOR_DATASET = "terminal-bench/terminal-bench-2-1"
# Concrete release identity stamped on evidence (replaces provisional plan labels).
TERMINAL_BENCH_RELEASE_VERSION = "terminal-bench@2.1"
TERMINAL_BENCH_ADAPTER_ID = "terminal-bench-harbor"
CLAUDE_CODE_NPM_IMPORT_PATH = "bencheval.harbor_claude_code_npm:ClaudeCodeNpmInstall"

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


def _write_codex_provider_config(artifacts_dir: Path) -> Path | None:
    base_url = os.environ.get("OPENAI_BASE_URL")
    if not base_url:
        return None
    env_key = os.environ.get("BENCHEVAL_CODEX_ENV_KEY")
    if not env_key:
        env_key = "OPENAI_API_KEY"

    config_file = artifacts_dir / ".bencheval-codex-config.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        "\n".join(
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
        ),
        encoding="utf-8",
    )
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
        cmd.extend(["--agent-import-path", CLAUDE_CODE_NPM_IMPORT_PATH])
        allowed_tools = os.environ.get(_CLAUDE_CODE_ALLOWED_TOOLS_ENV)
        if allowed_tools and "\n" not in allowed_tools:
            cmd.extend(["--agent-kwarg", f"allowed_tools={allowed_tools}"])
    else:
        cmd.extend(["--agent", agent])
    if plan.runtime_id in {"claude-code", "codex-cli"}:
        cmd.extend(
            [
                "--agent-setup-timeout-multiplier",
                _CLI_AGENT_SETUP_TIMEOUT_MULTIPLIER,
            ],
        )
    if plan.runtime_id == "codex-cli":
        codex_config = _write_codex_provider_config(artifacts_dir)
        if codex_config is not None:
            cmd.extend(["--mounts-json", _codex_config_mounts_json(codex_config)])
    cmd.extend(
        [
            "--dataset",
            dataset,
            "--task-name",
            instance_id,
            "--jobs-dir",
            str(artifacts_dir.resolve()),
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


def _write_text_artifact(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return str(path.resolve())


def _locate_native_result(artifacts_dir: Path) -> Path | None:
    candidates = [
        artifacts_dir / "result.json",
        artifacts_dir / "results.json",
        artifacts_dir / "harbor_result.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    for path in sorted(artifacts_dir.rglob("result.json")):
        if path.is_file():
            return path
    return None


def _numeric_gt_zero(value: object) -> bool:
    return isinstance(value, (int, float)) and value > 0


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
) -> TerminalBenchInstanceOutcome:
    stdout_file = artifacts_dir / "stdout.log"
    stderr_file = artifacts_dir / "stderr.log"
    stdout_rel = _write_text_artifact(stdout_file, cli.stdout)
    stderr_rel = _write_text_artifact(stderr_file, cli.stderr)

    raw_path: str | None = None
    native: dict[str, object] = {"harbor_returncode": cli.returncode}
    primary_pass = cli.returncode == 0
    partial_score = 1.0 if primary_pass else 0.0
    failure_class: FailureLabel | None = None
    cost_usd = 0.0

    result_file = _locate_native_result(artifacts_dir)
    if result_file is not None:
        raw_path = str(result_file.resolve())
        try:
            parsed = json.loads(result_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failure_class = "runtime_output_unparseable"
            primary_pass = False
            partial_score = 0.0
        else:
            if isinstance(parsed, dict):
                native = {**native, **parsed}
                if isinstance(parsed.get("exception_info"), dict):
                    primary_pass = False
                    partial_score = 0.0
                    failure_class = "runtime_launch_failure"
                elif _harbor_result_has_errors(parsed):
                    primary_pass = False
                    partial_score = 0.0
                    failure_class = "harness_failure"
                elif "resolved" in parsed:
                    verdict = _as_bool_verdict(parsed["resolved"])
                    if verdict is None:
                        failure_class = "runtime_output_unparseable"
                        primary_pass = False
                        partial_score = 0.0
                    else:
                        primary_pass = verdict
                        partial_score = 1.0 if primary_pass else 0.0
                elif "success" in parsed:
                    verdict = _as_bool_verdict(parsed["success"])
                    if verdict is None:
                        failure_class = "runtime_output_unparseable"
                        primary_pass = False
                        partial_score = 0.0
                    else:
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
    )


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
    revision = harbor_revision()
    if revision is None and process_runner is None:
        raise AdapterFailureError(
            "harbor CLI is not available",
            failure_label="runtime_launch_failure",
        )

    validate_control_plane_instance_id(instance_id)
    from bencheval.run_isolation import prepare_instance_artifacts_dir

    instance_dir = prepare_instance_artifacts_dir(artifacts_dir / instance_id)
    proxy_env = write_harbor_proxy_env_file(network_policy=plan.network_policy)
    try:
        command = build_harbor_run_command(
            plan=plan,
            instance_id=instance_id,
            artifacts_dir=instance_dir,
            dataset=dataset,
            proxy_env_file=proxy_env,
        )
        if timeout_sec is not None:
            wall = timeout_sec
        else:
            n = max(len(plan.instances), 1)
            wall = max(1, plan.max_wall_clock_sec // n)
        runner = process_runner or _default_process_runner
        start = time.monotonic()
        try:
            cli = runner(command, cwd=repo_root, timeout_sec=wall)
        except subprocess.TimeoutExpired as e:
            elapsed = time.monotonic() - start
            raise AdapterFailureError(
                f"harbor CLI timed out after {wall}s",
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
        return parse_harbor_instance_outcome(
            instance_id=instance_id,
            cli=cli,
            artifacts_dir=instance_dir,
            repo_root=repo_root,
            harness_version=revision,
            network_policy=plan.network_policy,
        )
    finally:
        if proxy_env is not None:
            proxy_env.unlink(missing_ok=True)


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
