"""Generic external-command benchmark adapter.

This adapter is the bridge for benchmark/runtime combinations that are best
driven by an existing external CLI instead of a BenchEval-native harness. It
launches a configured command per instance/attempt, streams raw output into a
canonical run record, writes EvidenceRecord JSONL, and leaves benchmark-specific
execution semantics in configuration.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import sys
import time
import warnings
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from string import Formatter
from typing import Literal

import yaml
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
)

from bencheval.backends import LOCAL_BACKEND, ExecutionBackend
from bencheval.domain import (
    ContaminationLabel,
    FailureLabel,
    InterpretationLabel,
    RewardHackRiskLabel,
    RuntimeKind,
    VerifierIntegrityLabel,
)
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root

ExternalEventKind = Literal[
    "system",
    "target",
    "model",
    "queue",
    "start",
    "llm",
    "tool",
    "debug",
    "break",
    "pass",
    "fail",
    "invalid",
    "artifact",
    "summary",
]
StreamParserKind = Literal["kilo-json", "plain-lines"]
VerificationKind = Literal["none", "regex", "manifest-value-regex"]

ANSI_RESET = "\033[0m"
ANSI_COLORS: dict[ExternalEventKind, str] = {
    "system": "\033[36m",
    "target": "\033[35m",
    "model": "\033[34m",
    "queue": "\033[36m",
    "start": "\033[1;34m",
    "llm": "\033[37m",
    "tool": "\033[34m",
    "debug": "\033[90m",
    "break": "\033[1;33m",
    "pass": "\033[1;32m",
    "fail": "\033[1;31m",
    "invalid": "\033[1;33m",
    "artifact": "\033[36m",
    "summary": "\033[1;36m",
}

DEFAULT_FLAG_REGEX = r"(?im)^FLAG:\s*(?P<value>\S[^\r\n]*)"
LEGACY_PRIVATE_ROOT_ALIAS = "/tmp/bencheval-cybench-real-vps"


class ExternalInstance(BaseModel):
    """One instance selected for an external command run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    title: str | None = None
    prompt_file: str | None = None


class ExternalInputConfig(BaseModel):
    """How prompts and required per-instance files are found under a run root."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    root_env: str | None = None
    prompt_path_templates: tuple[str, ...] = (
        "run-prompts/{instance_id}.txt",
        "prompts/{instance_id}.prompt.txt",
    )
    required_path_templates: tuple[str, ...] = ()
    prompt_replacements: dict[str, str] = Field(default_factory=dict)


class ExternalCommandConfig(BaseModel):
    """External process argv/env template.

    Template fields are resolved per attempt from ``model_id``, ``runtime_id``,
    ``variant``, ``instance_id``, ``attempt``, ``run_root``, ``work_dir``,
    ``prompt`` and ``output_token_max``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    argv_prefix: tuple[str, ...] = Field(min_length=1)
    args_template: tuple[str, ...] = Field(default_factory=tuple)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Literal["work_dir", "run_root", "repo_root"] = "work_dir"


class ExternalStreamConfig(BaseModel):
    """How stdout is interpreted into display events and metrics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    parser: StreamParserKind = "plain-lines"
    output_token_max: int | None = Field(default=None, ge=1)


class ExternalVerificationConfig(BaseModel):
    """How an instance result is classified after the process exits."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: VerificationKind = "none"
    observed_regex: str = DEFAULT_FLAG_REGEX
    manifest_paths: tuple[str, ...] = ()
    manifest_id_field: str = "name"
    manifest_value_field: str = "flag"
    allow_observed_without_expected: bool = True

    @field_validator("observed_regex")
    @classmethod
    def _regex_compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid observed_regex: {exc}") from exc
        return value


class ExternalSnapshotConfig(BaseModel):
    """Optional host snapshot after the run.

    This is deliberately generic. Docker is not a BenchEval-wide requirement;
    if a benchmark runtime needs Docker, that runtime owns it and may expose
    Docker commands here as ordinary snapshot commands.

    Snapshot commands are trusted profile-owned strings. Do not build them from
    unescaped user input; the SSH transport executes them through the remote
    shell.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = False
    timeout_sec: float = Field(default=15.0, gt=0)
    commands: dict[str, str] = Field(default_factory=dict)


class ExternalRunConfig(BaseModel):
    """Config file for a generic external-command run."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: Literal["external_command_run_v1"] = "external_command_run_v1"
    name: str = Field(min_length=1)
    benchmark_id: str = Field(min_length=1)
    benchmark_version: str | None = None
    slice_id: str | None = None
    adapter_id: str = "external-command"
    harness_kind: str = "local-harness"
    runtime_id: str = Field(
        validation_alias=AliasChoices("runtime_id", "runtime"),
        min_length=1,
    )
    runtime_kind: RuntimeKind = "cli_agent"
    model_id: str = Field(
        validation_alias=AliasChoices("model_id", "model"),
        min_length=1,
    )
    variant: str | None = None
    backend: ExecutionBackend = LOCAL_BACKEND
    execution_profile: Literal["E0", "E1", "E2", "E3", "E4"] = "E2"
    interpretation_label: InterpretationLabel = "adapter_smoke"
    contamination_label: ContaminationLabel | None = None
    reward_hack_risk_label: RewardHackRiskLabel | None = None
    verifier_integrity_label: VerifierIntegrityLabel | None = None
    target_host: str | None = None
    banner_title: str = "BenchEval"
    banner_subtitle: str = "External Runtime Evaluation"
    banner_detail: str | None = None
    command: ExternalCommandConfig
    input: ExternalInputConfig = Field(default_factory=ExternalInputConfig)
    stream: ExternalStreamConfig = Field(default_factory=ExternalStreamConfig)
    verification: ExternalVerificationConfig = Field(
        default_factory=ExternalVerificationConfig,
    )
    snapshot: ExternalSnapshotConfig = Field(default_factory=ExternalSnapshotConfig)
    concurrency: int = Field(default=1, ge=1, le=10)
    max_attempts: int = Field(default=1, ge=1, le=10)
    pass_at_k_budget: int = Field(default=1, ge=1, le=10)
    instances: list[ExternalInstance] = Field(
        validation_alias=AliasChoices("instances", "challenges"),
        min_length=1,
    )

    @field_validator("pass_at_k_budget")
    @classmethod
    def _budget_not_above_attempts(cls, value: int, info: object) -> int:
        data = getattr(info, "data", {})
        max_attempts = data.get("max_attempts") if isinstance(data, dict) else None
        if isinstance(max_attempts, int) and value > max_attempts:
            raise ValueError("pass_at_k_budget cannot exceed max_attempts")
        return value


@dataclass(frozen=True, slots=True)
class ExternalRunPaths:
    """Resolved output paths for one external-command run."""

    run_id: str
    run_dir: Path
    console_ansi_log: Path
    console_plain_log: Path
    events_jsonl: Path
    evidence_jsonl: Path
    summary_json: Path
    summary_md: Path
    stream_dir: Path
    work_dir: Path
    snapshot_dir: Path


@dataclass(frozen=True, slots=True)
class ExternalAttemptResult:
    """Outcome of one physical external process launch."""

    instance_id: str
    attempt: int
    valid: bool
    passed: bool
    observed_value: str | None
    expected_value: str | None
    value_match: bool | None
    failure_class: FailureLabel | None
    invalid_reason: str | None
    raw_log: Path
    stderr_log: Path
    work_dir: Path
    started_at: datetime
    ended_at: datetime
    latency_sec: float
    steps: int
    token_usage: dict[str, int]


@dataclass(frozen=True, slots=True)
class ExternalInstanceResult:
    """Final logical result for one selected instance."""

    instance_id: str
    attempts: tuple[ExternalAttemptResult, ...]

    @property
    def final(self) -> ExternalAttemptResult:
        return self.attempts[-1]


class TeeConsole:
    """Write colored terminal output plus ANSI/plain logs."""

    def __init__(self, ansi_log: Path, plain_log: Path, *, color: bool = True) -> None:
        self._color = color
        ansi_log.parent.mkdir(parents=True, exist_ok=True)
        self._ansi = ansi_log.open("w", encoding="utf-8")
        self._plain = plain_log.open("w", encoding="utf-8")

    def close(self) -> None:
        self._ansi.flush()
        self._plain.flush()
        self._ansi.close()
        self._plain.close()

    def line(self, text: str, *, kind: ExternalEventKind = "system") -> None:
        colored = _colorize(text, kind, enabled=self._color)
        sys.stdout.write(colored + "\n")
        sys.stdout.flush()
        self._ansi.write(colored + "\n")
        self._ansi.flush()
        self._plain.write(_strip_ansi(colored) + "\n")
        self._plain.flush()


class ExternalEventSink:
    """Terminal event writer with canonical raw run-record capture."""

    def __init__(
        self,
        console: TeeConsole,
        path: Path,
        started_monotonic: float,
        *,
        config: ExternalRunConfig,
        run_id: str,
        producer_command: str | None = None,
    ) -> None:
        from bencheval.replay import RunRecordWriter

        self._console = console
        self._started_monotonic = started_monotonic
        self._writer = RunRecordWriter(
            path,
            run_id=run_id,
            benchmark_id=config.benchmark_id,
            slice_id=config.slice_id,
            runtime_id=config.runtime_id,
            model_id=config.model_id,
            backend=config.backend,
            adapter_id=config.adapter_id,
            producer_command=producer_command,
            host_label=config.target_host,
        )

    def close(self) -> None:
        self._writer.close()

    def write_footer(
        self,
        *,
        exit_code: int = 0,
        summary: dict[str, JsonValue] | None = None,
        evidence_sha256: str | None = None,
    ) -> None:
        self._writer.write_footer(
            exit_code=exit_code,
            summary=summary,
            evidence_sha256=evidence_sha256,
        )

    def emit(
        self,
        kind: ExternalEventKind,
        message: str,
        *,
        instance_id: str | None = None,
        attempt: int | None = None,
        data: dict[str, JsonValue] | None = None,
    ) -> None:
        elapsed = time.monotonic() - self._started_monotonic
        label = kind.upper().ljust(8)
        prefix = f"[{_format_elapsed(elapsed)}] {label}"
        if instance_id:
            prefix += f" {instance_id}"
            if attempt is not None:
                prefix += f"#{attempt}"
        display = f"{prefix}  {message}"
        self._writer.write_event(
            kind=kind,
            message=message,
            elapsed_sec=round(elapsed, 3),
            time=datetime.now(UTC),
            instance_id=instance_id,
            challenge_id=instance_id,
            attempt=attempt,
            data=data or {},
            display=display,
        )
        self._console.line(display, kind=kind)


def load_external_run_config(path: Path) -> ExternalRunConfig:
    """Load and validate an external-command run config."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BenchEvalError(f"cannot parse external run config {path}: {exc}") from exc
    except OSError as exc:
        raise BenchEvalError(f"cannot read external run config {path}: {exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BenchEvalError(f"external run config {path} must be a YAML mapping")
    normalized = _normalize_legacy_config(raw)
    try:
        return ExternalRunConfig.model_validate(normalized)
    except ValidationError as exc:
        raise BenchEvalError(f"invalid external run config {path}: {exc}") from exc


def new_run_id(prefix: str = "external-run") -> str:
    """Create a display-safe run id."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}"


def make_external_run_paths(results_root: Path, run_id: str) -> ExternalRunPaths:
    """Create the output directory layout for one external-command run."""
    run_dir = results_root / "raw" / run_id
    return ExternalRunPaths(
        run_id=run_id,
        run_dir=run_dir,
        console_ansi_log=run_dir / "console.ansi.log",
        console_plain_log=run_dir / "console.plain.log",
        events_jsonl=run_dir / "events.jsonl",
        evidence_jsonl=results_root / "evidence" / f"{run_id}.jsonl",
        summary_json=run_dir / "summary.json",
        summary_md=run_dir / "SUMMARY.md",
        stream_dir=run_dir / "streams",
        work_dir=run_dir / "work",
        snapshot_dir=run_dir / "snapshot",
    )


def validate_external_run_root(
    config: ExternalRunConfig,
    run_root: Path | None,
) -> None:
    """Check that the run root has the configured prompts and required files."""
    if run_root is None:
        if config.input.root_env:
            raise BenchEvalError(
                f"set {config.input.root_env} or pass --run-root for config {config.name!r}",
            )
        return
    if not run_root.is_dir():
        raise BenchEvalError(
            f"external run root does not exist or is not a dir: {run_root}",
        )
    missing: list[str] = []
    for instance in config.instances:
        if not _prompt_path(config, run_root, instance).is_file():
            missing.append(f"prompt:{instance.id}")
            # Without the prompt we cannot tell which private material it needs; the
            # missing prompt is already the reported gap, so skip the per-prompt checks.
            continue
        prompt_text = _required_path_prompt_text(config, run_root, instance)
        for template in config.input.required_path_templates:
            rel = _format_template(
                template,
                _template_context(
                    config,
                    run_root,
                    instance,
                    attempt=1,
                    work_dir=run_root,
                ),
            )
            # Require private material only when the SELECTED prompt actually references
            # it (e.g. `ssh -i .../keys/<id>`). A prompt-only challenge that never SSHes
            # does not need a per-task key, so a blanket `keys/{id}` requirement must not
            # block it (peer review F003). The prompt text is alias-rewritten, so both the
            # legacy and run-root path forms contain the rendered `rel` substring.
            if rel not in prompt_text:
                continue
            path = Path(rel)
            candidate = path if path.is_absolute() else run_root / path
            if not candidate.is_file():
                missing.append(f"required:{instance.id}:{rel}")
    if missing:
        joined = ", ".join(missing)
        raise BenchEvalError(f"external run root is incomplete: {joined}")


def plan_external_run(
    *,
    config: ExternalRunConfig,
    run_root: Path | None,
    results_root: Path,
    run_id: str | None = None,
) -> dict[str, JsonValue]:
    """Return a JSON-serializable plan without launching the external command."""
    resolved_run_id = run_id or new_run_id(config.name)
    paths = make_external_run_paths(results_root, resolved_run_id)
    return {
        "schema_version": config.schema_version,
        "dry_run": True,
        "run_id": resolved_run_id,
        "name": config.name,
        "benchmark_id": config.benchmark_id,
        "benchmark_version": config.benchmark_version,
        "slice_id": config.slice_id,
        "adapter_id": config.adapter_id,
        "runtime_id": config.runtime_id,
        "runtime_kind": config.runtime_kind,
        "model_id": config.model_id,
        "variant": config.variant,
        "target_host": config.target_host,
        "instance_count": len(config.instances),
        "instances": [i.id for i in config.instances],
        "stream_parser": config.stream.parser,
        "verification_kind": config.verification.kind,
        "concurrency": config.concurrency,
        "max_attempts": config.max_attempts,
        "pass_at_k_budget": config.pass_at_k_budget,
        "run_root": str(run_root.resolve()) if run_root else None,
        "results_root": str(results_root.resolve()),
        "events": str(paths.events_jsonl.resolve()),
        "evidence": str(paths.evidence_jsonl.resolve()),
        "snapshot_enabled": config.snapshot.enabled,
    }


async def run_external_command(
    *,
    config: ExternalRunConfig,
    run_root: Path | None,
    results_root: Path,
    run_id: str | None = None,
    color: bool = True,
    snapshot: bool | None = None,
    producer_command: str | None = None,
) -> int:
    """Execute a configured external-command run and write evidence artifacts."""
    resolved_run_id = run_id or new_run_id(config.name)
    paths = make_external_run_paths(results_root, resolved_run_id)
    _create_output_dirs(paths)
    validate_external_run_root(config, run_root)

    console = TeeConsole(paths.console_ansi_log, paths.console_plain_log, color=color)
    sink: ExternalEventSink | None = None
    try:
        sink = ExternalEventSink(
            console,
            paths.events_jsonl,
            time.monotonic(),
            config=config,
            run_id=resolved_run_id,
            producer_command=producer_command,
        )
        _emit_banner(console, config)
        sink.emit("system", f"run_id={resolved_run_id}")
        if config.target_host:
            sink.emit("target", f"host={config.target_host}")
        model_line = f"{config.model_id} runtime={config.runtime_id}"
        if config.variant:
            model_line += f" variant={config.variant}"
        sink.emit("model", model_line)
        sink.emit(
            "queue",
            f"{len(config.instances)} instances loaded; concurrency={config.concurrency}",
        )
        results = await _run_instances(config, run_root, paths, sink)
        evidence_sha256 = _write_evidence_and_sha256(config, paths, results)
        _write_summary(config, paths, results)
        should_snapshot = snapshot if snapshot is not None else config.snapshot.enabled
        if should_snapshot:
            await _capture_snapshot(config, paths, sink)
        _write_sha256s(paths)
        passed = sum(1 for result in results if result.final.passed)
        failed = len(results) - passed
        sink.emit(
            "summary",
            f"passed={passed} failed={failed} artifacts={paths.run_dir}",
            data={"passed": passed, "failed": failed, "run_dir": str(paths.run_dir)},
        )
        exit_code = 0 if failed == 0 else 1
        sink.write_footer(
            exit_code=exit_code,
            summary={"passed": passed, "failed": failed},
            evidence_sha256=evidence_sha256,
        )
        return exit_code
    finally:
        if sink is not None:
            sink.close()
        console.close()


def replay(events_path: Path, *, color: bool = True, speed: float = 1.0) -> int:
    """Replay a captured run record through the general replay module."""
    from bencheval.replay import replay as general_replay

    return general_replay(events_path, color=color, speed=speed)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for ``python -m bencheval.external_command_adapter``."""
    parser = argparse.ArgumentParser(description="BenchEval external command runner")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument(
        "--run-root",
        type=Path,
        default=None,
        help="prepared benchmark root; may also come from config input.root_env",
    )
    parser.add_argument("--results-root", type=Path, default=repo_root() / "results")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument(
        "--snapshot",
        dest="snapshot",
        action="store_true",
        default=None,
        help="force configured host snapshot even if the config disables it",
    )
    parser.add_argument(
        "--no-snapshot",
        dest="snapshot",
        action="store_false",
        help="disable configured host snapshot for this run",
    )
    parser.add_argument(
        "--replay",
        type=Path,
        default=None,
        help="replay an events.jsonl file",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="replay speed multiplier",
    )
    args = parser.parse_args(argv)

    try:
        if args.replay is not None:
            return replay(args.replay, color=not args.no_color, speed=args.speed)

        config = load_external_run_config(args.config)
        run_root = args.run_root or _env_path(config.input.root_env)
        if args.dry_run:
            validate_external_run_root(config, run_root)
            payload = plan_external_run(
                config=config,
                run_root=run_root,
                results_root=args.results_root,
                run_id=args.run_id,
            )
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
            return 0
        return asyncio.run(
            run_external_command(
                config=config,
                run_root=run_root,
                results_root=args.results_root,
                run_id=args.run_id,
                color=not args.no_color,
                snapshot=args.snapshot,
                producer_command="python -m bencheval.external_command_adapter",
            ),
        )
    except BenchEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


async def _run_instances(
    config: ExternalRunConfig,
    run_root: Path | None,
    paths: ExternalRunPaths,
    sink: ExternalEventSink,
) -> list[ExternalInstanceResult]:
    semaphore = asyncio.Semaphore(config.concurrency)

    async def run_one(instance: ExternalInstance) -> ExternalInstanceResult:
        async with semaphore:
            return await _run_instance(config, run_root, paths, instance, sink)

    tasks = [asyncio.create_task(run_one(instance)) for instance in config.instances]
    return await asyncio.gather(*tasks)


async def _run_instance(
    config: ExternalRunConfig,
    run_root: Path | None,
    paths: ExternalRunPaths,
    instance: ExternalInstance,
    sink: ExternalEventSink,
) -> ExternalInstanceResult:
    attempts: list[ExternalAttemptResult] = []
    expected = _expected_value(config, run_root, instance.id)
    for attempt in range(1, config.max_attempts + 1):
        result = await _run_attempt(
            config,
            run_root,
            paths,
            instance,
            attempt,
            expected,
            sink,
        )
        attempts.append(result)
        if result.passed:
            return ExternalInstanceResult(
                instance_id=instance.id,
                attempts=tuple(attempts),
            )
        if not result.valid:
            sink.emit(
                "invalid",
                f"{result.invalid_reason}; retry does not consume Pass@k budget",
                instance_id=instance.id,
                attempt=attempt,
            )
            continue
        if attempt >= config.pass_at_k_budget:
            return ExternalInstanceResult(
                instance_id=instance.id,
                attempts=tuple(attempts),
            )
    return ExternalInstanceResult(instance_id=instance.id, attempts=tuple(attempts))


async def _run_attempt(
    config: ExternalRunConfig,
    run_root: Path | None,
    paths: ExternalRunPaths,
    instance: ExternalInstance,
    attempt: int,
    expected_value: str | None,
    sink: ExternalEventSink,
) -> ExternalAttemptResult:
    stream_dir = paths.stream_dir / instance.id
    stream_dir.mkdir(parents=True, exist_ok=True)
    work_dir = paths.work_dir / instance.id / f"attempt{attempt}"
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_log = stream_dir / f"attempt{attempt}.stdout"
    if config.stream.parser == "kilo-json":
        raw_log = raw_log.with_suffix(".jsonl")
    stderr_log = stream_dir / f"attempt{attempt}.stderr"
    prompt = _prompt_text(config, run_root, instance)
    context = _template_context(
        config,
        run_root,
        instance,
        attempt=attempt,
        work_dir=work_dir,
    )
    context["prompt"] = prompt
    env = os.environ.copy()
    env.update(
        {key: _format_template(value, context) for key, value in config.command.env.items()},
    )
    cmd = [
        *config.command.argv_prefix,
        *(_format_template(part, context) for part in config.command.args_template),
    ]
    cwd = _cwd_for_attempt(config, run_root, work_dir)
    started_at = datetime.now(UTC)
    monotonic_start = time.monotonic()
    sink.emit(
        "start",
        "launching external command",
        instance_id=instance.id,
        attempt=attempt,
    )
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    combined_text: list[str] = []
    counters = {"steps": 0}
    token_usage: dict[str, int] = {}
    stderr_task = asyncio.create_task(_copy_stream(proc.stderr, stderr_log))
    with raw_log.open("w", encoding="utf-8") as raw_file:
        assert proc.stdout is not None
        async for raw_line in _iter_unbounded_lines(proc.stdout):
            text_line = raw_line.decode("utf-8", errors="replace")
            raw_file.write(text_line)
            raw_file.flush()
            _handle_stream_line(
                text_line,
                parser=config.stream.parser,
                instance_id=instance.id,
                attempt=attempt,
                sink=sink,
                combined_text=combined_text,
                counters=counters,
                token_usage=token_usage,
                observed_regex=config.verification.observed_regex,
            )
    returncode = await proc.wait()
    await stderr_task
    ended_at = datetime.now(UTC)
    latency_sec = time.monotonic() - monotonic_start
    observed = _extract_observed_value(
        "\n".join(combined_text),
        config.verification.observed_regex,
    )
    passed, value_match = _classify_result(
        config=config,
        returncode=returncode,
        observed=observed,
        expected=expected_value,
    )
    output_cap = _hit_output_cap(token_usage, config.stream.output_token_max)
    valid = not output_cap and returncode == 0
    failure_class: FailureLabel | None = None
    invalid_reason: str | None = None
    if output_cap:
        failure_class = "runtime_output_cap_reached"
        invalid_reason = f"output_tokens>={config.stream.output_token_max}"
        valid = False
        passed = False
    elif returncode != 0:
        failure_class = "runtime_tool_failure"
        invalid_reason = f"process_exit={returncode}"
        valid = False
        passed = False
    elif not passed:
        failure_class = "model_wrong_solution"
    if passed:
        status = "match" if value_match else "observed"
        sink.emit(
            "pass",
            f"result verified ({status})",
            instance_id=instance.id,
            attempt=attempt,
        )
    elif valid:
        sink.emit(
            "fail",
            "completed without verified result",
            instance_id=instance.id,
            attempt=attempt,
        )
    return ExternalAttemptResult(
        instance_id=instance.id,
        attempt=attempt,
        valid=valid,
        passed=passed,
        observed_value=observed,
        expected_value=expected_value,
        value_match=value_match,
        failure_class=failure_class,
        invalid_reason=invalid_reason,
        raw_log=raw_log,
        stderr_log=stderr_log,
        work_dir=work_dir,
        started_at=started_at,
        ended_at=ended_at,
        latency_sec=latency_sec,
        steps=counters["steps"],
        token_usage=token_usage,
    )


async def _copy_stream(stream: asyncio.StreamReader | None, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        if stream is None:
            return
        while True:
            chunk = await stream.read(8192)
            if not chunk:
                break
            f.write(chunk)
            f.flush()


async def _iter_unbounded_lines(
    stream: asyncio.StreamReader,
    *,
    chunk_size: int = 1024 * 1024,
) -> AsyncIterator[bytes]:
    """Yield newline-delimited records without ``StreamReader.readline`` limits."""
    buffer = b""
    while True:
        chunk = await stream.read(chunk_size)
        if not chunk:
            break
        buffer += chunk
        while True:
            newline = buffer.find(b"\n")
            if newline < 0:
                break
            line = buffer[: newline + 1]
            buffer = buffer[newline + 1 :]
            yield line
    if buffer:
        yield buffer


def _handle_stream_line(
    line: str,
    *,
    parser: StreamParserKind,
    instance_id: str,
    attempt: int,
    sink: ExternalEventSink,
    combined_text: list[str],
    counters: dict[str, int],
    token_usage: dict[str, int],
    observed_regex: str,
) -> None:
    stripped = line.strip()
    if not stripped:
        return
    if parser == "plain-lines":
        combined_text.append(stripped)
        kind: ExternalEventKind = (
            "break" if _extract_observed_value(stripped, observed_regex) else "llm"
        )
        sink.emit(kind, _compact(stripped), instance_id=instance_id, attempt=attempt)
        counters["steps"] += 1
        return
    _handle_kilo_json_line(
        stripped,
        instance_id=instance_id,
        attempt=attempt,
        sink=sink,
        combined_text=combined_text,
        counters=counters,
        token_usage=token_usage,
        observed_regex=observed_regex,
    )


def _handle_kilo_json_line(
    stripped: str,
    *,
    instance_id: str,
    attempt: int,
    sink: ExternalEventSink,
    combined_text: list[str],
    counters: dict[str, int],
    token_usage: dict[str, int],
    observed_regex: str,
) -> None:
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        combined_text.append(stripped)
        sink.emit("debug", stripped, instance_id=instance_id, attempt=attempt)
        return
    if not isinstance(event, dict):
        return
    counters["steps"] += 1
    _merge_token_usage(token_usage, event)
    event_type = str(event.get("type", "event"))
    part = event.get("part")
    if isinstance(part, dict):
        if part.get("type") == "text":
            text = _part_text(part)
            if text:
                combined_text.append(text)
                kind: ExternalEventKind = (
                    "break" if _extract_observed_value(text, observed_regex) else "llm"
                )
                sink.emit(
                    kind,
                    _compact(text),
                    instance_id=instance_id,
                    attempt=attempt,
                )
            return
        if part.get("type") == "tool":
            message, output = _tool_message(part)
            if output:
                combined_text.append(output)
            sink.emit("tool", message, instance_id=instance_id, attempt=attempt)
            if output:
                sink.emit(
                    "debug",
                    _compact(output),
                    instance_id=instance_id,
                    attempt=attempt,
                )
            return
    sink.emit(
        "debug",
        f"runtime_event={event_type}",
        instance_id=instance_id,
        attempt=attempt,
    )


def _part_text(part: dict[object, object]) -> str:
    value = part.get("text")
    return value if isinstance(value, str) else ""


def _tool_message(part: dict[object, object]) -> tuple[str, str]:
    tool = str(part.get("tool", "tool"))
    state = part.get("state")
    title = str(part.get("title", tool))
    if isinstance(state, dict):
        status = str(state.get("status", "unknown"))
        input_obj = state.get("input")
        description = ""
        if isinstance(input_obj, dict):
            desc = input_obj.get("description")
            command = input_obj.get("command")
            if isinstance(desc, str) and desc.strip():
                description = desc.strip()
            elif isinstance(command, str):
                description = command.strip().splitlines()[0][:120]
        output = state.get("output")
        output_text = output if isinstance(output, str) else ""
        label = f"{tool}:{status}"
        if description:
            label += f" {description}"
        return label, output_text
    return title, ""


def _merge_token_usage(target: dict[str, int], event: dict[object, object]) -> None:
    tokens_obj = event.get("tokens")
    if not isinstance(tokens_obj, dict):
        return
    for key in ("total", "input", "output", "reasoning", "cache_read", "cache_write"):
        value = tokens_obj.get(key)
        if isinstance(value, int):
            target[key] = max(target.get(key, 0), value)
    cache_obj = tokens_obj.get("cache")
    if isinstance(cache_obj, dict):
        for source, dest in (("read", "cache_read"), ("write", "cache_write")):
            value = cache_obj.get(source)
            if isinstance(value, int):
                target[dest] = max(target.get(dest, 0), value)


def _write_evidence(
    config: ExternalRunConfig,
    paths: ExternalRunPaths,
    results: list[ExternalInstanceResult],
) -> None:
    sink = JsonlEvidenceSink()
    for result in results:
        final = result.final
        metadata = {
            "run_kind": "external_command",
            "runtime_id": config.runtime_id,
            "stream_parser": config.stream.parser,
            "verification_kind": config.verification.kind,
            "target_host": config.target_host or "",
            "raw_log": str(final.raw_log.relative_to(paths.run_dir)),
            "stderr_log": str(final.stderr_log.relative_to(paths.run_dir)),
            "result_check": _result_check_label(final),
        }
        record = EvidenceRecord(
            run_id=paths.run_id,
            task_id=f"{config.benchmark_id}/{result.instance_id}",
            model_id=config.model_id,
            execution_profile=config.execution_profile,
            backend=config.backend,
            primary_pass=final.passed,
            partial_score=1.0 if final.passed else 0.0,
            cost_usd=0.0,
            latency_sec=round(final.latency_sec, 3),
            failure_labels=[] if final.passed else [final.failure_class or "model_wrong_solution"],
            artifact_paths=[
                str(final.raw_log),
                str(final.stderr_log),
                str(final.work_dir),
            ],
            verifier_log_path=str(final.raw_log),
            adapter_metadata=metadata,
            created_at=final.ended_at,
            benchmark_id=config.benchmark_id,
            benchmark_version=config.benchmark_version,
            slice_id=config.slice_id,
            adapter_id=config.adapter_id,
            harness_kind=config.harness_kind,
            runtime_id=config.runtime_id,
            runtime_kind=config.runtime_kind,
            instance_id=result.instance_id,
            steps=final.steps,
            token_usage=final.token_usage or None,
            normalized_score=1.0 if final.passed else 0.0,
            interpretation_label=config.interpretation_label,
            contamination_label=config.contamination_label,
            reward_hack_risk_label=config.reward_hack_risk_label,
            verifier_integrity_label=(
                config.verifier_integrity_label
                or ("native" if final.value_match is not None else "unknown")
            ),
            cleanup_result="skipped",
            failure_class=final.failure_class,
            attempt_validity="valid" if final.valid else "invalid",
            invalid_reason=final.invalid_reason,
            counts_toward_pass_at_k=final.valid,
            physical_launch_id=f"{paths.run_id}:{result.instance_id}:attempt{final.attempt}",
            logical_attempt_number=final.attempt,
            runtime_output_cap=config.stream.output_token_max,
        )
        sink.append_jsonl(paths.evidence_jsonl, record)


def _write_evidence_and_sha256(
    config: ExternalRunConfig,
    paths: ExternalRunPaths,
    results: list[ExternalInstanceResult],
) -> str:
    """Write evidence rows and return the digest of the finalized JSONL file."""
    _write_evidence(config, paths, results)
    return hashlib.sha256(paths.evidence_jsonl.read_bytes()).hexdigest()


def _write_summary(
    config: ExternalRunConfig,
    paths: ExternalRunPaths,
    results: list[ExternalInstanceResult],
) -> None:
    rows = []
    for result in results:
        final = result.final
        rows.append(
            {
                "instance_id": result.instance_id,
                "status": "passed" if final.passed else "failed",
                "attempts": len(result.attempts),
                "valid": final.valid,
                "failure_class": final.failure_class,
                "invalid_reason": final.invalid_reason,
                "steps": final.steps,
                "token_usage": final.token_usage,
                "raw_log": str(final.raw_log.relative_to(paths.run_dir)),
            },
        )
    passed = sum(1 for row in rows if row["status"] == "passed")
    payload = {
        "schema_version": "external_command_summary_v1",
        "run_id": paths.run_id,
        "name": config.name,
        "benchmark_id": config.benchmark_id,
        "benchmark_version": config.benchmark_version,
        "slice_id": config.slice_id,
        "target_host": config.target_host,
        "model_id": config.model_id,
        "variant": config.variant,
        "runtime_id": config.runtime_id,
        "stream_parser": config.stream.parser,
        "output_token_max": config.stream.output_token_max,
        "passed": passed,
        "failed": len(rows) - passed,
        "rows": rows,
    }
    paths.summary_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# External Command Run",
        "",
        f"- Run ID: `{paths.run_id}`",
        f"- Benchmark: `{config.benchmark_id}`",
        f"- Slice: `{config.slice_id or ''}`",
        f"- Target: `{config.target_host or ''}`",
        f"- Model: `{config.model_id}`",
        f"- Runtime: `{config.runtime_id}`",
        f"- Result: `{passed}/{len(rows)}` passed",
        "",
        "| Instance | Status | Attempts | Steps | Failure |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {instance_id} | {status} | {attempts} | {steps} | {failure} |".format(
                instance_id=row["instance_id"],
                status=row["status"],
                attempts=row["attempts"],
                steps=row["steps"],
                failure=row["failure_class"] or "",
            ),
        )
    lines.extend(
        [
            "",
            "Canonical raw logs may contain benchmark secrets, credentials, commands, "
            "and model output.",
        ],
    )
    paths.summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _capture_snapshot(
    config: ExternalRunConfig,
    paths: ExternalRunPaths,
    sink: ExternalEventSink,
) -> None:
    if not config.target_host:
        sink.emit("artifact", "snapshot skipped: target_host is not configured")
        return
    if not config.snapshot.commands:
        sink.emit("artifact", "snapshot skipped: no commands configured")
        return
    if not shutil.which("ssh"):
        sink.emit("artifact", "ssh unavailable; snapshot skipped")
        return
    paths.snapshot_dir.mkdir(parents=True, exist_ok=True)
    for filename, command in config.snapshot.commands.items():
        out_path = paths.snapshot_dir / filename
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            config.target_host,
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output, _ = await asyncio.wait_for(
                proc.communicate(),
                timeout=config.snapshot.timeout_sec,
            )
        except TimeoutError:
            cleanup_errors: list[str] = []
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            except Exception as exc:  # pragma: no cover - platform/process dependent
                cleanup_errors.append(f"kill failed: {exc}")
            try:
                await proc.communicate()
            except Exception as exc:
                cleanup_errors.append(f"cleanup after timeout failed: {exc}")
                wait = getattr(proc, "wait", None)
                if callable(wait):
                    try:
                        await wait()
                    except Exception as wait_exc:  # pragma: no cover - defensive best effort
                        cleanup_errors.append(f"wait after timeout failed: {wait_exc}")
            marker = f"snapshot command timed out after {config.snapshot.timeout_sec:.1f}s\n"
            if cleanup_errors:
                marker += "\n".join(cleanup_errors) + "\n"
            out_path.write_text(marker, encoding="utf-8")
            sink.emit("artifact", f"snapshot timed out for {filename}")
            continue
        out_path.write_bytes(output)
    sink.emit("artifact", f"snapshot captured at {paths.snapshot_dir}")


def _write_sha256s(paths: ExternalRunPaths) -> None:
    lines: list[str] = []
    for path in sorted(p for p in paths.run_dir.rglob("*") if p.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(paths.run_dir)}")
    (paths.run_dir / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def _create_output_dirs(paths: ExternalRunPaths) -> None:
    for path in (
        paths.run_dir,
        paths.evidence_jsonl.parent,
        paths.stream_dir,
        paths.work_dir,
        paths.snapshot_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _prompt_path(
    config: ExternalRunConfig,
    run_root: Path | None,
    instance: ExternalInstance,
) -> Path:
    if instance.prompt_file:
        path = Path(instance.prompt_file)
        if path.is_absolute():
            return path
        if run_root is not None:
            return run_root / path
        return path
    if run_root is None:
        raise BenchEvalError(
            "run root is required when instance.prompt_file is not absolute",
        )
    context = _template_context(
        config,
        run_root,
        instance,
        attempt=1,
        work_dir=run_root,
    )
    for template in config.input.prompt_path_templates:
        rel = _format_template(template, context)
        path = Path(rel)
        candidate = path if path.is_absolute() else run_root / path
        if candidate.exists():
            return candidate
    first = config.input.prompt_path_templates[0] if config.input.prompt_path_templates else ""
    return run_root / _format_template(first, context)


def _prompt_text(
    config: ExternalRunConfig,
    run_root: Path | None,
    instance: ExternalInstance,
) -> str:
    text = _raw_prompt_text(config, run_root, instance)
    context = _template_context(
        config,
        run_root,
        instance,
        attempt=1,
        work_dir=run_root or Path(),
    )
    replacements = {
        _format_template(old, context): _format_template(new, context)
        for old, new in config.input.prompt_replacements.items()
    }
    if run_root is not None:
        replacements.setdefault(LEGACY_PRIVATE_ROOT_ALIAS, str(run_root.resolve()))
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _raw_prompt_text(
    config: ExternalRunConfig,
    run_root: Path | None,
    instance: ExternalInstance,
) -> str:
    path = _prompt_path(config, run_root, instance)
    return path.read_text(encoding="utf-8")


def _required_path_prompt_text(
    config: ExternalRunConfig,
    run_root: Path,
    instance: ExternalInstance,
) -> str:
    """Prompt text used only to decide whether private material is referenced.

    Runtime prompt rewrites may replace a private host path with a container-local
    mount path. Preflight must still validate the original referenced material,
    so it checks the raw prompt plus the historical root-alias expansion, not the
    final runtime prompt.
    """
    text = _raw_prompt_text(config, run_root, instance)
    return text.replace(LEGACY_PRIVATE_ROOT_ALIAS, str(run_root.resolve()))


def _expected_value(
    config: ExternalRunConfig,
    run_root: Path | None,
    instance_id: str,
) -> str | None:
    verification = config.verification
    if verification.kind != "manifest-value-regex" or run_root is None:
        return None
    for rel in verification.manifest_paths:
        path = Path(rel)
        manifest_path = path if path.is_absolute() else run_root / path
        if not manifest_path.is_file():
            continue
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        value = _find_manifest_value(payload, verification, instance_id)
        if value:
            return value
    return None


def _find_manifest_value(
    payload: object,
    verification: ExternalVerificationConfig,
    instance_id: str,
) -> str | None:
    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            if item.get(verification.manifest_id_field) == instance_id:
                value = item.get(verification.manifest_value_field)
                return value if isinstance(value, str) and value else None
    if isinstance(payload, dict):
        direct = payload.get(instance_id)
        if isinstance(direct, str) and direct:
            return direct
        instances = payload.get("instances")
        if isinstance(instances, list):
            return _find_manifest_value(instances, verification, instance_id)
    return None


def _extract_observed_value(text: str, pattern: str) -> str | None:
    regex = re.compile(pattern)
    matches = list(regex.finditer(text))
    if not matches:
        return None
    last = matches[-1]
    if "value" in last.groupdict():
        return last.group("value").strip()
    if last.groups():
        return last.group(1).strip()
    return last.group(0).strip()


def _classify_result(
    *,
    config: ExternalRunConfig,
    returncode: int,
    observed: str | None,
    expected: str | None,
) -> tuple[bool, bool | None]:
    if returncode != 0:
        return False, None
    kind = config.verification.kind
    if kind == "none":
        return True, None
    if observed is None:
        return False, None
    if kind == "regex":
        return True, None
    if expected:
        return observed == expected, observed == expected
    return bool(config.verification.allow_observed_without_expected), None


def _hit_output_cap(token_usage: dict[str, int], cap: int | None) -> bool:
    if cap is None:
        return False
    output = token_usage.get("output")
    if output is not None:
        return output >= cap
    total = token_usage.get("total")
    return total is not None and total >= cap


def _result_check_label(result: ExternalAttemptResult) -> str:
    if result.value_match is True:
        return "value_match"
    if result.value_match is False:
        return "value_mismatch"
    if result.observed_value:
        return "value_observed_unverified"
    if result.passed:
        return "process_success"
    return "no_value_observed"


def _template_context(
    config: ExternalRunConfig,
    run_root: Path | None,
    instance: ExternalInstance,
    *,
    attempt: int,
    work_dir: Path,
) -> dict[str, str]:
    return {
        "name": config.name,
        "benchmark_id": config.benchmark_id,
        "slice_id": config.slice_id or "",
        "model_id": config.model_id,
        "runtime_model_id": _runtime_model_id(config.model_id),
        "runtime_id": config.runtime_id,
        "variant": config.variant or "",
        "target_host": config.target_host or "",
        "instance_id": instance.id,
        "attempt": str(attempt),
        "run_root": str(run_root.resolve()) if run_root else "",
        "work_dir": str(work_dir.resolve()),
        "output_token_max": str(config.stream.output_token_max or ""),
        "host_uid": str(os.getuid()),
        "host_gid": str(os.getgid()),
    }


def _runtime_model_id(model_id: str) -> str:
    provider, sep, bare_model = model_id.partition("/")
    return bare_model if sep and provider and bare_model else model_id


def _format_template(template: str, context: Mapping[str, str]) -> str:
    try:
        return template.format(**context)
    except KeyError as exc:
        fields = sorted(
            field_name
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name is not None
        )
        raise BenchEvalError(
            f"unknown template field {exc.args[0]!r} in {template!r}; fields={fields}",
        ) from exc


def _cwd_for_attempt(
    config: ExternalRunConfig,
    run_root: Path | None,
    work_dir: Path,
) -> Path:
    if config.command.cwd == "work_dir":
        return work_dir
    if config.command.cwd == "repo_root":
        return repo_root()
    if run_root is None:
        raise BenchEvalError(
            "command.cwd=run_root requires --run-root or input.root_env",
        )
    return run_root


def _normalize_legacy_config(raw: dict[object, object]) -> dict[object, object]:
    """Accept the earlier reference config shape while producing the generic schema."""
    if raw.get("schema_version") == "external_command_run_v1":
        return raw
    normalized = dict(raw)
    if "challenges" not in normalized and "instances" not in normalized:
        return normalized
    warnings.warn(
        "legacy external command config shape is deprecated; "
        "migrate to schema_version='external_command_run_v1'",
        DeprecationWarning,
        stacklevel=2,
    )
    normalized.setdefault("schema_version", "external_command_run_v1")
    normalized.setdefault("benchmark_id", "cybench")
    normalized.setdefault("benchmark_version", "hard-39-private")
    normalized.setdefault("slice_id", "cybench-showcase")
    normalized.setdefault("adapter_id", "external-command")
    normalized.setdefault("harness_kind", "local-harness")
    normalized.setdefault("runtime_kind", "cli_agent")
    normalized.setdefault("execution_profile", "E2")
    normalized.setdefault("interpretation_label", "offensive_restricted")
    normalized.setdefault("contamination_label", "public_possible")
    normalized.setdefault("reward_hack_risk_label", "known_public_risk")
    normalized.setdefault("banner_title", "BenchEval")
    normalized.setdefault("banner_subtitle", "External Runtime Evaluation")
    if "runtime" in normalized and "runtime_id" not in normalized:
        normalized["runtime_id"] = normalized.pop("runtime")
    normalized.setdefault("runtime_id", "kilo")
    if "model" in normalized and "model_id" not in normalized:
        normalized["model_id"] = normalized.pop("model")
    if "challenges" in normalized and "instances" not in normalized:
        normalized["instances"] = normalized.pop("challenges")
    output_token_max = normalized.pop("output_token_max", None)
    argv_prefix = normalized.pop("kilo_argv_prefix", None)
    if "command" not in normalized:
        normalized["command"] = {
            "argv_prefix": argv_prefix or ["kilo", "run"],
            "args_template": [
                "-m",
                "{model_id}",
                "--variant",
                "{variant}",
                "--auto",
                "--format",
                "json",
                "--dir",
                "{work_dir}",
                "{prompt}",
            ],
            "env": {"KILO_EXPERIMENTAL_OUTPUT_TOKEN_MAX": "{output_token_max}"},
            "cwd": "work_dir",
        }
    normalized.setdefault(
        "input",
        {
            "root_env": "MOMO_CYBENCH_RUN_ROOT",
            "prompt_path_templates": [
                "run-prompts/{instance_id}.txt",
                "prompts/{instance_id}.prompt.txt",
            ],
            "required_path_templates": ["keys/{instance_id}"],
        },
    )
    normalized.setdefault(
        "stream",
        {
            "parser": "kilo-json",
            "output_token_max": output_token_max,
        },
    )
    normalized.setdefault(
        "verification",
        {
            "kind": "manifest-value-regex",
            "observed_regex": DEFAULT_FLAG_REGEX,
            "manifest_paths": [
                "meta/manifest.private.json",
                "meta/manifest.full.private.json",
            ],
            "manifest_id_field": "name",
            "manifest_value_field": "flag",
            "allow_observed_without_expected": True,
        },
    )
    snapshot_enabled = normalized.pop("remote_snapshot", False)
    snapshot_timeout = normalized.pop("remote_snapshot_timeout_sec", 15.0)
    normalized.setdefault(
        "snapshot",
        {
            "enabled": snapshot_enabled,
            "timeout_sec": snapshot_timeout,
            "commands": {},
        },
    )
    normalized.pop("flag_policy", None)
    return normalized


def _compact(text: str, limit: int = 260) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1] + "..."


def _format_elapsed(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _emit_banner(console: TeeConsole, config: ExternalRunConfig) -> None:
    width = 64
    lines = [
        "=" * width,
        _center(config.banner_title, width),
        _center(config.banner_subtitle, width),
    ]
    if config.banner_detail:
        lines.append(_center(config.banner_detail, width))
    lines.append("=" * width)
    for line in lines:
        console.line(line, kind="summary")


def _center(text: str, width: int) -> str:
    return text[:width].center(width)


def _colorize(text: str, kind: ExternalEventKind, *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{ANSI_COLORS.get(kind, '')}{text}{ANSI_RESET}"


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _env_path(name: str | None) -> Path | None:
    if name is None:
        return None
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


__all__ = [
    "ExternalAttemptResult",
    "ExternalCommandConfig",
    "ExternalEventSink",
    "ExternalInputConfig",
    "ExternalInstance",
    "ExternalInstanceResult",
    "ExternalRunConfig",
    "ExternalRunPaths",
    "ExternalSnapshotConfig",
    "ExternalStreamConfig",
    "ExternalVerificationConfig",
    "TeeConsole",
    "load_external_run_config",
    "main",
    "make_external_run_paths",
    "new_run_id",
    "plan_external_run",
    "replay",
    "run_external_command",
    "validate_external_run_root",
]


if __name__ == "__main__":
    raise SystemExit(main())
