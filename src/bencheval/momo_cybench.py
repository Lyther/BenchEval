"""MOMO CyBench live runner and terminal evidence recorder.

This module is intentionally a thin operational wrapper around Kilo. It does
not make CyBench a production BenchEval adapter; it records a private,
operator-facing run that can later be lifted into a first-class record/replay
feature.
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
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from bencheval.domain import FailureLabel
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root

FlagPolicy = Literal["redact", "show"]
EventKind = Literal[
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


ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_COLORS: dict[EventKind, str] = {
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

FLAG_PATTERN = re.compile(r"(?im)^FLAG:\s*(?P<flag>\S[^\r\n]*)")
EMBEDDED_FLAG_PATTERN = re.compile(r"\b[A-Z0-9_]+\{[^}\r\n]{1,240}\}")
SECRETISH_PATTERN = re.compile(
    r"(?i)(sk-[a-z0-9_\-]{8,}|api[_-]?key\s*[=:]\s*[^\s]+|authorization:\s*[^\s]+)",
)
LEGACY_PRIVATE_ROOT_ALIAS = "/tmp/bencheval-cybench-real-vps"


class MomoChallenge(BaseModel):
    """One CyBench challenge selected for the MOMO terminal run."""

    id: str = Field(min_length=1)
    title: str | None = None
    prompt_file: str | None = None


class MomoCybenchConfig(BaseModel):
    """Config file for the MOMO CyBench runner."""

    model_config = ConfigDict(extra="forbid")

    name: str = "momo-cybench-glm52"
    target_host: str = "vps.0xb105.com"
    model: str = "ollama-cloud/glm-5.2"
    variant: str = "max"
    runtime: str = "kilo"
    kilo_argv_prefix: list[str] = Field(default_factory=lambda: ["kilo", "run"], min_length=1)
    output_token_max: int = Field(default=131072, ge=1)
    concurrency: int = Field(default=2, ge=1, le=10)
    max_attempts: int = Field(default=1, ge=1, le=3)
    pass_at_k_budget: int = Field(default=1, ge=1, le=3)
    flag_policy: FlagPolicy = "redact"
    remote_snapshot: bool = True
    remote_snapshot_timeout_sec: float = Field(default=15.0, gt=0)
    challenges: list[MomoChallenge] = Field(min_length=1)

    @field_validator("runtime")
    @classmethod
    def _runtime_is_kilo(cls, value: str) -> str:
        if value != "kilo":
            raise ValueError("MOMO CyBench currently supports runtime='kilo' only")
        return value


@dataclass(frozen=True, slots=True)
class RunPaths:
    """Resolved output paths for one MOMO run."""

    run_id: str
    run_dir: Path
    console_ansi_log: Path
    console_plain_log: Path
    events_jsonl: Path
    evidence_jsonl: Path
    summary_json: Path
    summary_md: Path
    kilo_dir: Path
    work_dir: Path
    remote_dir: Path


@dataclass(frozen=True, slots=True)
class AttemptResult:
    """Outcome of a single physical Kilo process launch."""

    challenge_id: str
    attempt: int
    valid: bool
    passed: bool
    flag_observed: bool
    flag_match: bool | None
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
class ChallengeResult:
    """Final logical result for one selected challenge."""

    challenge_id: str
    attempts: tuple[AttemptResult, ...]

    @property
    def final(self) -> AttemptResult:
        return self.attempts[-1]


class TeeConsole:
    """Write colored terminal output plus ANSI/plain logs."""

    def __init__(self, ansi_log: Path, plain_log: Path, *, color: bool = True) -> None:
        self._color = color
        ansi_log.parent.mkdir(parents=True, exist_ok=True)
        self._ansi = ansi_log.open("w", encoding="utf-8")
        self._plain = plain_log.open("w", encoding="utf-8")

    def close(self) -> None:
        self._ansi.close()
        self._plain.close()

    def line(self, text: str, *, kind: EventKind = "system") -> None:
        colored = _colorize(text, kind, enabled=self._color)
        sys.stdout.write(colored + "\n")
        sys.stdout.flush()
        self._ansi.write(colored + "\n")
        self._ansi.flush()
        self._plain.write(_strip_ansi(colored) + "\n")
        self._plain.flush()


class EventSink:
    """Terminal event writer with JSONL capture."""

    def __init__(self, console: TeeConsole, path: Path, started_monotonic: float) -> None:
        self._console = console
        self._path = path
        self._started_monotonic = started_monotonic
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("w", encoding="utf-8")

    def close(self) -> None:
        self._file.close()

    def emit(
        self,
        kind: EventKind,
        message: str,
        *,
        challenge_id: str | None = None,
        attempt: int | None = None,
        data: dict[str, str | int | float | bool | None] | None = None,
    ) -> None:
        elapsed = time.monotonic() - self._started_monotonic
        label = kind.upper().ljust(8)
        prefix = f"[{_format_elapsed(elapsed)}] {label}"
        if challenge_id:
            prefix += f" {challenge_id}"
            if attempt is not None:
                prefix += f"#{attempt}"
        display = f"{prefix}  {message}"
        record = {
            "schema_version": "momo_event_v1",
            "time": datetime.now(UTC).isoformat(),
            "elapsed_sec": round(elapsed, 3),
            "kind": kind,
            "challenge_id": challenge_id,
            "attempt": attempt,
            "message": message,
            "data": data or {},
            "display": display,
        }
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()
        self._console.line(display, kind=kind)


def load_config(path: Path) -> MomoCybenchConfig:
    """Load and validate a MOMO CyBench YAML config file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BenchEvalError(f"cannot read MOMO config {path}: {exc}") from exc
    if raw is None:
        raw = {}
    try:
        return MomoCybenchConfig.model_validate(raw)
    except ValidationError as exc:
        raise BenchEvalError(f"invalid MOMO config {path}: {exc}") from exc


def new_run_id(prefix: str = "momo-cybench") -> str:
    """Create a display-safe run id."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}"


def make_run_paths(results_root: Path, run_id: str) -> RunPaths:
    """Create the output directory layout for one run."""
    run_dir = results_root / "raw" / run_id
    return RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        console_ansi_log=run_dir / "console.ansi.log",
        console_plain_log=run_dir / "console.plain.log",
        events_jsonl=run_dir / "events.jsonl",
        evidence_jsonl=results_root / "evidence" / f"{run_id}.jsonl",
        summary_json=run_dir / "summary.json",
        summary_md=run_dir / "SUMMARY.md",
        kilo_dir=run_dir / "kilo",
        work_dir=run_dir / "work",
        remote_dir=run_dir / "remote",
    )


def validate_run_root(config: MomoCybenchConfig, run_root: Path) -> None:
    """Check that a private CyBench run root has required prompts and keys."""
    if not run_root.is_dir():
        raise BenchEvalError(f"MOMO_CYBENCH_RUN_ROOT does not exist or is not a dir: {run_root}")
    missing: list[str] = []
    for challenge in config.challenges:
        if not _prompt_path(run_root, challenge).is_file():
            missing.append(f"prompt:{challenge.id}")
        key_path = run_root / "keys" / challenge.id
        if not key_path.is_file():
            missing.append(f"key:{challenge.id}")
    if missing:
        joined = ", ".join(missing)
        raise BenchEvalError(f"private CyBench run root is incomplete: {joined}")


async def run_live(
    *,
    config: MomoCybenchConfig,
    run_root: Path,
    results_root: Path,
    run_id: str | None = None,
    color: bool = True,
    remote_snapshot: bool | None = None,
) -> int:
    """Execute a live MOMO CyBench run and write terminal/evidence artifacts."""
    resolved_run_id = run_id or new_run_id()
    paths = make_run_paths(results_root, resolved_run_id)
    _create_output_dirs(paths)
    validate_run_root(config, run_root)

    console = TeeConsole(paths.console_ansi_log, paths.console_plain_log, color=color)
    sink = EventSink(console, paths.events_jsonl, time.monotonic())
    try:
        _emit_banner(console)
        sink.emit("system", f"run_id={resolved_run_id}")
        sink.emit("target", f"host={config.target_host}")
        sink.emit("model", f"{config.model} variant={config.variant} runtime={config.runtime}")
        sink.emit(
            "queue",
            f"{len(config.challenges)} challenges loaded; concurrency={config.concurrency}",
        )
        results = await _run_challenges(config, run_root, paths, sink)
        _write_evidence(config, paths, results)
        _write_summary(config, paths, results)
        should_snapshot = remote_snapshot if remote_snapshot is not None else config.remote_snapshot
        if should_snapshot:
            await _capture_remote_snapshot(config, paths, sink)
        _write_sha256s(paths)
        passed = sum(1 for result in results if result.final.passed)
        failed = len(results) - passed
        sink.emit(
            "summary",
            f"passed={passed} failed={failed} artifacts={paths.run_dir}",
            data={"passed": passed, "failed": failed, "run_dir": str(paths.run_dir)},
        )
        return 0 if failed == 0 else 1
    finally:
        sink.close()
        console.close()


def replay(events_path: Path, *, color: bool = True, speed: float = 1.0) -> int:
    """Replay a captured MOMO event stream to the terminal."""
    if speed <= 0:
        raise BenchEvalError("--speed must be > 0")
    previous_elapsed = 0.0
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        elapsed = float(record.get("elapsed_sec", 0.0))
        delay = max(0.0, elapsed - previous_elapsed) / speed
        if delay > 0:
            time.sleep(min(delay, 2.0))
        previous_elapsed = elapsed
        kind = _event_kind(record.get("kind"))
        display = str(record.get("display", record.get("message", "")))
        sys.stdout.write(_colorize(display, kind, enabled=color) + "\n")
        sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for ``python -m bencheval.momo_cybench``."""
    parser = argparse.ArgumentParser(description="MOMO CyBench live terminal runner")
    parser.add_argument(
        "--config",
        type=Path,
        default=repo_root() / "config" / "momo" / "cybench-showcase.yaml",
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=None,
        help="private prepared CyBench root; defaults to MOMO_CYBENCH_RUN_ROOT",
    )
    parser.add_argument("--results-root", type=Path, default=repo_root() / "results")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument(
        "--remote-snapshot",
        dest="remote_snapshot",
        action="store_true",
        default=None,
        help="force host-level remote snapshot even if the config disables it",
    )
    parser.add_argument(
        "--no-remote-snapshot",
        dest="remote_snapshot",
        action="store_false",
        help="disable host-level remote snapshot for this run",
    )
    parser.add_argument("--replay", type=Path, default=None, help="replay an events.jsonl file")
    parser.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier")
    args = parser.parse_args(argv)

    try:
        if args.replay is not None:
            return replay(args.replay, color=not args.no_color, speed=args.speed)

        config = load_config(args.config)
        run_root = args.run_root or _env_path("MOMO_CYBENCH_RUN_ROOT")
        if run_root is None:
            raise BenchEvalError("set MOMO_CYBENCH_RUN_ROOT or pass --run-root")
        if args.dry_run:
            validate_run_root(config, run_root)
            challenge_ids = ", ".join(challenge.id for challenge in config.challenges)
            print(
                "MOMO plan: "
                f"host={config.target_host} model={config.model} challenges={challenge_ids}",
            )
            return 0
        return asyncio.run(
            run_live(
                config=config,
                run_root=run_root,
                results_root=args.results_root,
                run_id=args.run_id,
                color=not args.no_color,
                remote_snapshot=args.remote_snapshot,
            ),
        )
    except BenchEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


async def _run_challenges(
    config: MomoCybenchConfig,
    run_root: Path,
    paths: RunPaths,
    sink: EventSink,
) -> list[ChallengeResult]:
    semaphore = asyncio.Semaphore(config.concurrency)

    async def run_one(challenge: MomoChallenge) -> ChallengeResult:
        async with semaphore:
            return await _run_challenge(config, run_root, paths, challenge, sink)

    tasks = [asyncio.create_task(run_one(challenge)) for challenge in config.challenges]
    return await asyncio.gather(*tasks)


async def _run_challenge(
    config: MomoCybenchConfig,
    run_root: Path,
    paths: RunPaths,
    challenge: MomoChallenge,
    sink: EventSink,
) -> ChallengeResult:
    attempts: list[AttemptResult] = []
    expected_flag = _expected_flag(run_root, challenge.id)
    for attempt in range(1, config.max_attempts + 1):
        result = await _run_attempt(
            config,
            run_root,
            paths,
            challenge,
            attempt,
            expected_flag,
            sink,
        )
        attempts.append(result)
        if result.passed:
            return ChallengeResult(challenge_id=challenge.id, attempts=tuple(attempts))
        if not result.valid:
            sink.emit(
                "invalid",
                f"{result.invalid_reason}; retry does not consume Pass@k budget",
                challenge_id=challenge.id,
                attempt=attempt,
            )
            continue
        if attempt >= config.pass_at_k_budget:
            return ChallengeResult(challenge_id=challenge.id, attempts=tuple(attempts))
    return ChallengeResult(challenge_id=challenge.id, attempts=tuple(attempts))


async def _run_attempt(
    config: MomoCybenchConfig,
    run_root: Path,
    paths: RunPaths,
    challenge: MomoChallenge,
    attempt: int,
    expected_flag: str | None,
    sink: EventSink,
) -> AttemptResult:
    challenge_dir = paths.kilo_dir / challenge.id
    challenge_dir.mkdir(parents=True, exist_ok=True)
    work_dir = paths.work_dir / challenge.id / f"attempt{attempt}"
    work_dir.mkdir(parents=True, exist_ok=True)
    raw_log = challenge_dir / f"attempt{attempt}.jsonl"
    stderr_log = challenge_dir / f"attempt{attempt}.stderr"
    prompt = _prepare_prompt_text(
        _prompt_path(run_root, challenge).read_text(encoding="utf-8"),
        run_root,
    )
    env = os.environ.copy()
    env["KILO_EXPERIMENTAL_OUTPUT_TOKEN_MAX"] = str(config.output_token_max)
    cmd = [
        *config.kilo_argv_prefix,
        "-m",
        config.model,
        "--variant",
        config.variant,
        "--auto",
        "--format",
        "json",
        "--dir",
        str(work_dir),
        prompt,
    ]
    started_at = datetime.now(UTC)
    monotonic_start = time.monotonic()
    sink.emit("start", "launching Kilo", challenge_id=challenge.id, attempt=attempt)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=work_dir,
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
            _handle_kilo_line(
                text_line,
                challenge_id=challenge.id,
                attempt=attempt,
                sink=sink,
                combined_text=combined_text,
                counters=counters,
                token_usage=token_usage,
                flag_policy=config.flag_policy,
            )
    returncode = await proc.wait()
    await stderr_task
    ended_at = datetime.now(UTC)
    latency_sec = time.monotonic() - monotonic_start
    observed_flag = _extract_flag("\n".join(combined_text))
    flag_match = None
    if observed_flag and expected_flag:
        flag_match = observed_flag == expected_flag
    passed = bool(observed_flag and (flag_match is not False))
    output_cap = _hit_output_cap(token_usage, config.output_token_max)
    valid = not output_cap and returncode == 0
    failure_class: FailureLabel | None = None
    invalid_reason: str | None = None
    if output_cap:
        failure_class = "runtime_output_cap_reached"
        invalid_reason = f"output_tokens>={config.output_token_max}"
        valid = False
    elif returncode != 0:
        failure_class = "runtime_launch_failure"
        invalid_reason = f"kilo_exit={returncode}"
        valid = False
    elif not passed:
        failure_class = "model_wrong_solution"
    if passed:
        sink.emit(
            "pass",
            f"flag verified ({'match' if flag_match else 'observed'})",
            challenge_id=challenge.id,
            attempt=attempt,
        )
    elif valid:
        sink.emit(
            "fail",
            "completed without verified flag",
            challenge_id=challenge.id,
            attempt=attempt,
        )
    return AttemptResult(
        challenge_id=challenge.id,
        attempt=attempt,
        valid=valid,
        passed=passed,
        flag_observed=observed_flag is not None,
        flag_match=flag_match,
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


def _handle_kilo_line(
    line: str,
    *,
    challenge_id: str,
    attempt: int,
    sink: EventSink,
    combined_text: list[str],
    counters: dict[str, int],
    token_usage: dict[str, int],
    flag_policy: FlagPolicy,
) -> None:
    stripped = line.strip()
    if not stripped:
        return
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        combined_text.append(stripped)
        sink.emit(
            "debug",
            _sanitize_for_terminal(stripped, flag_policy),
            challenge_id=challenge_id,
            attempt=attempt,
        )
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
                kind: EventKind = "break" if _extract_flag(text) else "llm"
                sink.emit(
                    kind,
                    _sanitize_for_terminal(_compact(text), flag_policy),
                    challenge_id=challenge_id,
                    attempt=attempt,
                )
            return
        if part.get("type") == "tool":
            message, output = _tool_message(part)
            if output:
                combined_text.append(output)
            sink.emit(
                "tool",
                _sanitize_for_terminal(message, flag_policy),
                challenge_id=challenge_id,
                attempt=attempt,
            )
            if output:
                sink.emit(
                    "debug",
                    _sanitize_for_terminal(_compact(output), flag_policy),
                    challenge_id=challenge_id,
                    attempt=attempt,
                )
            return
    sink.emit("debug", f"kilo_event={event_type}", challenge_id=challenge_id, attempt=attempt)


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
    config: MomoCybenchConfig,
    paths: RunPaths,
    results: list[ChallengeResult],
) -> None:
    sink = JsonlEvidenceSink()
    for result in results:
        final = result.final
        metadata = {
            "run_kind": "momo_cybench_live",
            "runtime": config.runtime,
            "target_host": config.target_host,
            "raw_log": str(final.raw_log.relative_to(paths.run_dir)),
            "stderr_log": str(final.stderr_log.relative_to(paths.run_dir)),
            "flag_check": _flag_check_label(final),
        }
        record = EvidenceRecord(
            run_id=paths.run_id,
            task_id=f"cybench/{result.challenge_id}",
            model_id=config.model,
            execution_profile="E2",
            backend="local",
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
            benchmark_id="cybench",
            benchmark_version="hard-39-private",
            slice_id="momo-showcase",
            adapter_id="momo-cybench-kilo",
            harness_kind="inspect",
            runtime_id=config.runtime,
            runtime_kind="cli_agent",
            instance_id=result.challenge_id,
            steps=final.steps,
            token_usage=final.token_usage or None,
            normalized_score=1.0 if final.passed else 0.0,
            interpretation_label="offensive_restricted",
            contamination_label="public_possible",
            reward_hack_risk_label="known_public_risk",
            verifier_integrity_label="native" if final.flag_match is not None else "unknown",
            cleanup_result="skipped",
            failure_class=final.failure_class,
            attempt_validity="valid" if final.valid else "invalid",
            invalid_reason=final.invalid_reason,
            counts_toward_pass_at_k=final.valid,
            physical_launch_id=f"{paths.run_id}:{result.challenge_id}:attempt{final.attempt}",
            logical_attempt_number=final.attempt,
            runtime_output_cap=config.output_token_max,
        )
        sink.append_jsonl(paths.evidence_jsonl, record)


def _write_summary(
    config: MomoCybenchConfig,
    paths: RunPaths,
    results: list[ChallengeResult],
) -> None:
    rows = []
    for result in results:
        final = result.final
        rows.append(
            {
                "challenge_id": result.challenge_id,
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
        "schema_version": "momo_summary_v1",
        "run_id": paths.run_id,
        "name": config.name,
        "target_host": config.target_host,
        "model": config.model,
        "variant": config.variant,
        "runtime": config.runtime,
        "output_token_max": config.output_token_max,
        "passed": passed,
        "failed": len(rows) - passed,
        "rows": rows,
    }
    paths.summary_json.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# MOMO CyBench Run",
        "",
        f"- Run ID: `{paths.run_id}`",
        f"- Target: `{config.target_host}`",
        f"- Model: `{config.model}`",
        f"- Variant: `{config.variant}`",
        f"- Output token max: `{config.output_token_max}`",
        f"- Result: `{passed}/{len(rows)}` passed",
        "",
        "| Challenge | Status | Attempts | Steps | Failure |",
        "|---|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| {challenge_id} | {status} | {attempts} | {steps} | {failure} |".format(
                challenge_id=row["challenge_id"],
                status=row["status"],
                attempts=row["attempts"],
                steps=row["steps"],
                failure=row["failure_class"] or "",
            ),
        )
    lines.extend(
        [
            "",
            "Private raw logs may contain challenge flags, SSH keys, commands, and model output.",
        ],
    )
    paths.summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _capture_remote_snapshot(
    config: MomoCybenchConfig,
    paths: RunPaths,
    sink: EventSink,
) -> None:
    if not shutil.which("ssh"):
        sink.emit("artifact", "ssh unavailable; remote snapshot skipped")
        return
    paths.remote_dir.mkdir(parents=True, exist_ok=True)
    commands = {
        "host.txt": "hostname; uname -a; date -u +%Y-%m-%dT%H:%M:%SZ",
        "docker-ps-a.txt": "docker ps -a --no-trunc",
        "docker-images.txt": "docker images --digests",
        "docker-networks.txt": "docker network ls",
        "docker-stats.txt": "docker stats --no-stream",
    }
    for filename, command in commands.items():
        out_path = paths.remote_dir / filename
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
                timeout=config.remote_snapshot_timeout_sec,
            )
        except TimeoutError:
            proc.kill()
            output, _ = await proc.communicate()
            out_path.write_text(
                f"remote snapshot command timed out after "
                f"{config.remote_snapshot_timeout_sec:.1f}s\n",
                encoding="utf-8",
            )
            sink.emit("artifact", f"remote snapshot timed out for {filename}")
            continue
        out_path.write_bytes(output)
    sink.emit("artifact", f"remote snapshot captured at {paths.remote_dir}")


def _write_sha256s(paths: RunPaths) -> None:
    lines: list[str] = []
    for path in sorted(p for p in paths.run_dir.rglob("*") if p.is_file()):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(paths.run_dir)}")
    (paths.run_dir / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _create_output_dirs(paths: RunPaths) -> None:
    for path in (
        paths.run_dir,
        paths.evidence_jsonl.parent,
        paths.kilo_dir,
        paths.work_dir,
        paths.remote_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _prompt_path(run_root: Path, challenge: MomoChallenge) -> Path:
    if challenge.prompt_file:
        path = Path(challenge.prompt_file)
        return path if path.is_absolute() else run_root / path
    run_prompt = run_root / "run-prompts" / f"{challenge.id}.txt"
    if run_prompt.exists():
        return run_prompt
    return run_root / "prompts" / f"{challenge.id}.prompt.txt"


def _prepare_prompt_text(prompt: str, run_root: Path) -> str:
    """Point archived private prompts at the active local run root."""
    return prompt.replace(LEGACY_PRIVATE_ROOT_ALIAS, str(run_root.resolve()))


def _expected_flag(run_root: Path, challenge_id: str) -> str | None:
    for rel in (
        Path("meta") / "manifest.private.json",
        Path("meta") / "manifest.full.private.json",
    ):
        path = run_root / rel
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, list):
            for item in payload:
                if isinstance(item, dict) and item.get("name") == challenge_id:
                    flag = item.get("flag")
                    return flag if isinstance(flag, str) and flag else None
    return None


def _extract_flag(text: str) -> str | None:
    matches = list(FLAG_PATTERN.finditer(text))
    if not matches:
        return None
    return matches[-1].group("flag").strip()


def _hit_output_cap(token_usage: dict[str, int], cap: int) -> bool:
    output = token_usage.get("output")
    return output is not None and output >= cap


def _flag_check_label(result: AttemptResult) -> str:
    if result.flag_match is True:
        return "flag_match"
    if result.flag_match is False:
        return "flag_mismatch"
    if result.flag_observed:
        return "flag_observed_unverified"
    return "no_flag_observed"


def _sanitize_for_terminal(text: str, flag_policy: FlagPolicy) -> str:
    sanitized = text
    if flag_policy == "redact":
        sanitized = FLAG_PATTERN.sub("FLAG: [redacted]", sanitized)
        sanitized = EMBEDDED_FLAG_PATTERN.sub("[redacted-flag]", sanitized)
    sanitized = SECRETISH_PATTERN.sub("[redacted-secret]", sanitized)
    return sanitized


def _compact(text: str, limit: int = 260) -> str:
    one_line = " ".join(text.strip().split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1] + "…"


def _format_elapsed(seconds: float) -> str:
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _emit_banner(console: TeeConsole) -> None:
    banner = [
        "╔════════════════════════════════════════════════════════════════╗",
        "║                            MOMO                              ║",
        "║             Model-Orchestrated Mission Operations            ║",
        "║             GLM 5.2 / Kilo / CyBench Live Run                ║",
        "╚════════════════════════════════════════════════════════════════╝",
    ]
    for line in banner:
        console.line(line, kind="summary")


def _colorize(text: str, kind: EventKind, *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{ANSI_COLORS.get(kind, '')}{text}{ANSI_RESET}"


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _event_kind(value: object) -> EventKind:
    allowed = set(ANSI_COLORS)
    if isinstance(value, str) and value in allowed:
        return cast("EventKind", value)
    return "system"


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


if __name__ == "__main__":
    raise SystemExit(main())
