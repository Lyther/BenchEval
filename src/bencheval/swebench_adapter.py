"""SWE-bench Verified adapter (control-plane P4, swebench-native harness)."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bencheval.backends import INSPECT_BACKEND
from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.ids import new_run_id
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.run_isolation import (
    AUTHORITATIVE_ARTIFACT_NAMES,
    dir_identity_error,
    open_owned_dir_fd,
    prepare_instance_artifacts_dir,
    read_json_at_nofollow,
    write_text_at_exclusive,
)
from bencheval.runtime_registry import load_runtime_catalog

SWEBENCH_ADAPTER_ID = "swebench"
_INSTANCE_DIR_ROLE = "swebench instance directory"
_OFFICIAL_REPORT_NAME = "report.json"
_WORKSPACE_DIFF_NAME = "workspace.diff"
_PREDICTIONS_NAME = "predictions.jsonl"
_SWE_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_INSPECT_SOLVER_BY_RUNTIME = {
    "codex-cli": "inspect_swe/codex_cli",
    "claude-code": "inspect_swe/claude_code",
}


def _as_bool_verdict(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class SwebenchCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SwebenchInstanceOutcome:
    instance_id: str
    primary_pass: bool
    partial_score: float
    cost_usd: float
    latency_sec: float
    native_score: dict[str, object]
    failure_class: FailureLabel | None
    stdout_path: str | None
    stderr_path: str | None
    verifier_log_path: str | None
    workspace_diff_path: str | None
    adapter_metadata: dict[str, str]


class SwebenchProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> SwebenchCliResult: ...


def build_swebench_run_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[str, ...]:
    """Inspect Evals generation command for the selected pinned runtime solver."""
    validate_control_plane_instance_id(instance_id)
    solver = _INSPECT_SOLVER_BY_RUNTIME.get(plan.runtime_id or "")
    if solver is None:
        raise BenchEvalError(
            f"swebench adapter expects runtime_id in {tuple(_INSPECT_SOLVER_BY_RUNTIME)}, "
            f"got {plan.runtime_id!r}",
        )
    try:
        runtime = load_runtime_catalog().by_id(plan.runtime_id or "")
    except KeyError as e:
        raise BenchEvalError(f"unknown runtime {plan.runtime_id!r}") from e
    pin = runtime.versioning.agent_version_pin
    if pin is None or not pin.strip():
        raise BenchEvalError(f"runtime {plan.runtime_id!r} has no agent_version_pin")
    return (
        "inspect",
        "eval",
        "inspect_evals/swe_bench",
        "--sample-id",
        instance_id,
        "--solver",
        solver,
        "-S",
        f"version={pin.strip()}",
        "--log-dir",
        str(artifacts_dir),
    )


def _validate_swe_run_id(run_id: str) -> str:
    if not run_id or not _SWE_RUN_ID_PATTERN.fullmatch(run_id):
        raise BenchEvalError(
            f"invalid swebench run_id {run_id!r}: use alphanumeric, dot, underscore, hyphen",
        )
    return run_id


def build_swebench_eval_command(
    *,
    instance_id: str,
    predictions_path: Path,
    run_id: str,
    report_dir: Path,
) -> tuple[str, ...]:
    validate_control_plane_instance_id(instance_id)
    return (
        "swebench",
        "eval",
        "verified",
        "-p",
        str(predictions_path),
        "-i",
        instance_id,
        "-j",
        "1",
        "--run-id",
        _validate_swe_run_id(run_id),
        "--report-dir",
        str(report_dir),
    )


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
) -> SwebenchCliResult:
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
            f"swebench harness timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"swebench_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"swebench harness launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"swebench_command": " ".join(command)},
        ) from e
    return SwebenchCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def _rel_path(path: str, repo_root: Path) -> str:
    absolute = Path(os.path.abspath(path))
    root = Path(os.path.abspath(repo_root))
    try:
        return str(absolute.relative_to(root))
    except ValueError:
        return str(absolute)


def _reject_instance_swap(
    *,
    instance_dir: Path,
    instance_fd: int,
    cli: SwebenchCliResult,
) -> None:
    identity_error = dir_identity_error(instance_fd, instance_dir, role=_INSTANCE_DIR_ROLE)
    if identity_error is not None:
        raise AdapterFailureError(
            identity_error,
            failure_label="evidence_corrupt",
            latency_sec=cli.latency_sec,
            adapter_metadata={"swebench_command": " ".join(cli.command)},
        )


def _write_owned_logs(
    *,
    instance_dir: Path,
    instance_fd: int,
    cli: SwebenchCliResult,
) -> tuple[str, str]:
    _reject_instance_swap(instance_dir=instance_dir, instance_fd=instance_fd, cli=cli)
    write_text_at_exclusive(instance_fd, "stdout.log", cli.stdout)
    write_text_at_exclusive(instance_fd, "stderr.log", cli.stderr)
    _reject_instance_swap(instance_dir=instance_dir, instance_fd=instance_fd, cli=cli)
    return str((instance_dir / "stdout.log").resolve()), str(
        (instance_dir / "stderr.log").resolve(),
    )


def _read_official_report_json(instance_fd: int) -> dict[str, object] | None:
    _, parsed = read_json_at_nofollow(instance_fd, _OFFICIAL_REPORT_NAME)
    return parsed if isinstance(parsed, dict) else None


def _owned_regular_file_path(
    instance_fd: int,
    name: str,
    artifacts_dir: Path,
) -> str | None:
    try:
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=instance_fd)
    except OSError:
        return None
    try:
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode):
            return None
    finally:
        os.close(file_fd)
    return os.path.abspath(artifacts_dir / name)


def _clear_owned_name(instance_fd: int, name: str) -> None:
    try:
        os.unlink(name, dir_fd=instance_fd)
    except FileNotFoundError:
        return
    except OSError as e:
        raise BenchEvalError(f"cannot clear leftover {name}: {e}") from e


def _inspect_model_patch(sample: object) -> str | None:
    scores = getattr(sample, "scores", None)
    if not isinstance(scores, Mapping):
        return None
    scorer = scores.get("swe_bench_scorer")
    if scorer is None:
        return None
    metadata = (
        scorer.get("metadata")
        if isinstance(scorer, Mapping)
        else getattr(
            scorer,
            "metadata",
            None,
        )
    )
    if not isinstance(metadata, Mapping):
        return None
    patch = metadata.get("model_patch")
    return patch if isinstance(patch, str) else None


def _prediction_row_from_inspect_log(
    log_path: Path,
    *,
    instance_id: str,
    model_name_or_path: str,
) -> dict[str, str] | None:
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        return None
    try:
        log = read_eval_log(str(log_path))
    except (OSError, UnicodeDecodeError, ValueError, TypeError):
        return None
    samples = getattr(log, "samples", None)
    if not isinstance(samples, list):
        return None
    patches = [
        patch
        for sample in samples
        if str(getattr(sample, "id", "")) == instance_id
        for patch in (_inspect_model_patch(sample),)
        if patch is not None
    ]
    if len(patches) != 1:
        return None
    return {
        "instance_id": instance_id,
        "model_name_or_path": model_name_or_path,
        "model_patch": patches[0],
    }


def _owned_eval_log_names(instance_fd: int) -> tuple[str, ...]:
    try:
        names = os.listdir(instance_fd)
    except OSError:
        return ()
    owned: list[str] = []
    for name in names:
        if not name.endswith(".eval"):
            continue
        try:
            file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=instance_fd)
        except OSError:
            continue
        try:
            if stat.S_ISREG(os.fstat(file_fd).st_mode):
                owned.append(name)
        finally:
            os.close(file_fd)
    return tuple(owned)


def _ensure_official_predictions(
    *,
    instance_dir: Path,
    instance_fd: int,
    instance_id: str,
    model_name_or_path: str,
) -> str | None:
    existing = _owned_regular_file_path(instance_fd, _PREDICTIONS_NAME, instance_dir)
    if existing is not None:
        return existing
    rows: list[dict[str, str]] = []
    for name in _owned_eval_log_names(instance_fd):
        row = _prediction_row_from_inspect_log(
            instance_dir / name,
            instance_id=instance_id,
            model_name_or_path=model_name_or_path,
        )
        if row is not None:
            rows.append(row)
    if len(rows) != 1:
        return None
    write_text_at_exclusive(instance_fd, _PREDICTIONS_NAME, json.dumps(rows[0]) + "\n")
    return _owned_regular_file_path(instance_fd, _PREDICTIONS_NAME, instance_dir)


def _find_eval_instance_report(
    instance_dir: Path,
    *,
    instance_id: str,
    run_id: str,
) -> Path | None:
    root = instance_dir / "logs" / "run_evaluation" / run_id
    try:
        if root.is_symlink() or not root.is_dir():
            return None
        children = list(root.iterdir())
    except OSError:
        return None
    matches: list[Path] = []
    for model_dir in children:
        try:
            if model_dir.is_symlink() or not model_dir.is_dir():
                continue
            candidate = model_dir / instance_id / _OFFICIAL_REPORT_NAME
            if candidate.is_symlink() or not candidate.is_file():
                continue
        except OSError:
            continue
        matches.append(candidate)
    if len(matches) != 1:
        return None
    return matches[0]


def _materialize_official_instance_report(
    *,
    instance_dir: Path,
    instance_fd: int,
    instance_id: str,
    run_id: str,
) -> None:
    if _owned_regular_file_path(instance_fd, _OFFICIAL_REPORT_NAME, instance_dir):
        return
    found = _find_eval_instance_report(
        instance_dir,
        instance_id=instance_id,
        run_id=run_id,
    )
    if found is None:
        return
    try:
        text = found.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    write_text_at_exclusive(instance_fd, _OFFICIAL_REPORT_NAME, text)


def _missing_predictions_outcome(
    *,
    instance_id: str,
    cli: SwebenchCliResult,
    instance_dir: Path,
    repo_root: Path,
    harness_version: str | None,
    instance_fd: int,
) -> SwebenchInstanceOutcome:
    stdout_abs, stderr_abs = _write_owned_logs(
        instance_dir=instance_dir,
        instance_fd=instance_fd,
        cli=cli,
    )
    metadata = {
        "adapter_id": SWEBENCH_ADAPTER_ID,
        "harness_kind": "swebench-native",
        "swebench_command": " ".join(cli.command),
        "interpretation_label": "diagnostic_only",
        "missing_artifact": _PREDICTIONS_NAME,
    }
    if harness_version:
        metadata["harness_version"] = harness_version
    return SwebenchInstanceOutcome(
        instance_id=instance_id,
        primary_pass=False,
        partial_score=0.0,
        cost_usd=0.0,
        latency_sec=cli.latency_sec,
        native_score={"returncode": cli.returncode, "backend": INSPECT_BACKEND},
        failure_class="runtime_output_unparseable",
        stdout_path=_rel_path(stdout_abs, repo_root),
        stderr_path=_rel_path(stderr_abs, repo_root),
        verifier_log_path=None,
        workspace_diff_path=None,
        adapter_metadata=metadata,
    )


def _official_instance_report(
    instance_fd: int,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[bool, dict[str, object], str] | None:
    parsed = _read_official_report_json(instance_fd)
    if parsed is None or instance_id not in parsed:
        return None
    instance = parsed[instance_id]
    if not isinstance(instance, dict):
        return None
    resolved = _as_bool_verdict(instance.get("resolved"))
    if resolved is None:
        return None
    return resolved, instance, os.path.abspath(artifacts_dir / _OFFICIAL_REPORT_NAME)


def _score_from_official(
    *,
    cli: SwebenchCliResult,
    official: tuple[bool, dict[str, object], str] | None,
) -> tuple[bool, float, FailureLabel | None, dict[str, object], str | None, float]:
    native: dict[str, object] = {"returncode": cli.returncode, "backend": INSPECT_BACKEND}
    if official is None:
        failure: FailureLabel = (
            "harness_failure" if cli.returncode != 0 else "runtime_output_unparseable"
        )
        return False, 0.0, failure, native, None, 0.0
    resolved, instance, verifier_path = official
    native = {**native, **instance}
    cost = instance.get("cost_usd")
    cost_usd = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else 0.0
    if cli.returncode != 0:
        return False, 0.0, "harness_failure", native, verifier_path, cost_usd
    if resolved:
        return True, 1.0, None, native, verifier_path, cost_usd
    return False, 0.0, "model_wrong_solution", native, verifier_path, cost_usd


def parse_swebench_instance_outcome(
    *,
    instance_id: str,
    cli: SwebenchCliResult,
    artifacts_dir: Path,
    repo_root: Path,
    harness_version: str | None,
    artifacts_fd: int | None = None,
) -> SwebenchInstanceOutcome:
    owned_fd = artifacts_fd is None
    instance_fd = artifacts_fd
    if instance_fd is None:
        instance_fd = open_owned_dir_fd(artifacts_dir, role=_INSTANCE_DIR_ROLE)
    try:
        stdout_abs, stderr_abs = _write_owned_logs(
            instance_dir=artifacts_dir,
            instance_fd=instance_fd,
            cli=cli,
        )
        official = _official_instance_report(instance_fd, instance_id, artifacts_dir)
        _reject_instance_swap(instance_dir=artifacts_dir, instance_fd=instance_fd, cli=cli)
        diff_path = _owned_regular_file_path(
            instance_fd,
            _WORKSPACE_DIFF_NAME,
            artifacts_dir,
        )
        _reject_instance_swap(instance_dir=artifacts_dir, instance_fd=instance_fd, cli=cli)
        primary_pass, partial_score, failure_class, native, verifier_path, cost_usd = (
            _score_from_official(cli=cli, official=official)
        )
        metadata = {
            "adapter_id": SWEBENCH_ADAPTER_ID,
            "harness_kind": "swebench-native",
            "swebench_command": " ".join(cli.command),
            "interpretation_label": "diagnostic_only",
        }
        if harness_version:
            metadata["harness_version"] = harness_version
        outcome = SwebenchInstanceOutcome(
            instance_id=instance_id,
            primary_pass=primary_pass,
            partial_score=partial_score,
            cost_usd=cost_usd,
            latency_sec=cli.latency_sec,
            native_score=native,
            failure_class=failure_class,
            stdout_path=_rel_path(stdout_abs, repo_root),
            stderr_path=_rel_path(stderr_abs, repo_root),
            verifier_log_path=_rel_path(verifier_path, repo_root) if verifier_path else None,
            workspace_diff_path=_rel_path(diff_path, repo_root) if diff_path else None,
            adapter_metadata=metadata,
        )
        _reject_instance_swap(instance_dir=artifacts_dir, instance_fd=instance_fd, cli=cli)
        return outcome
    finally:
        if owned_fd:
            os.close(instance_fd)


def _score_swe_phase(
    *,
    instance_id: str,
    cli: SwebenchCliResult,
    instance_dir: Path,
    repo_root: Path,
    harness_version: str | None,
    instance_fd: int,
) -> SwebenchInstanceOutcome:
    return parse_swebench_instance_outcome(
        instance_id=instance_id,
        cli=cli,
        artifacts_dir=instance_dir,
        repo_root=repo_root,
        harness_version=harness_version,
        artifacts_fd=instance_fd,
    )


def _run_generation_then_eval(
    *,
    plan: RunPlan,
    instance_id: str,
    instance_dir: Path,
    instance_fd: int,
    repo_root: Path,
    runner: SwebenchProcessRunner,
    wall: int,
    harness_version: str | None,
    run_id: str,
) -> SwebenchInstanceOutcome:
    generate = build_swebench_run_command(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=instance_dir,
    )
    generation = runner(generate, cwd=repo_root, timeout_sec=wall)
    _reject_instance_swap(instance_dir=instance_dir, instance_fd=instance_fd, cli=generation)
    if generation.returncode != 0:
        return _score_swe_phase(
            instance_id=instance_id,
            cli=generation,
            instance_dir=instance_dir,
            repo_root=repo_root,
            harness_version=harness_version,
            instance_fd=instance_fd,
        )
    predictions = _ensure_official_predictions(
        instance_dir=instance_dir,
        instance_fd=instance_fd,
        instance_id=instance_id,
        model_name_or_path=plan.model_id,
    )
    if predictions is None:
        return _missing_predictions_outcome(
            instance_id=instance_id,
            cli=generation,
            instance_dir=instance_dir,
            repo_root=repo_root,
            harness_version=harness_version,
            instance_fd=instance_fd,
        )
    return _evaluate_official_predictions(
        instance_id=instance_id,
        instance_dir=instance_dir,
        instance_fd=instance_fd,
        repo_root=repo_root,
        runner=runner,
        wall=wall,
        harness_version=harness_version,
        run_id=run_id,
        generation=generation,
        predictions=predictions,
    )


def _evaluate_official_predictions(
    *,
    instance_id: str,
    instance_dir: Path,
    instance_fd: int,
    repo_root: Path,
    runner: SwebenchProcessRunner,
    wall: int,
    harness_version: str | None,
    run_id: str,
    generation: SwebenchCliResult,
    predictions: str,
) -> SwebenchInstanceOutcome:
    _clear_owned_name(instance_fd, _OFFICIAL_REPORT_NAME)
    evaluate = build_swebench_eval_command(
        instance_id=instance_id,
        predictions_path=Path(predictions),
        run_id=run_id,
        report_dir=instance_dir,
    )
    remaining = wall - int(generation.latency_sec)
    if remaining <= 0:
        raise AdapterFailureError(
            "no remaining wall budget for official SWE-bench evaluation",
            failure_label="runtime_budget_exceeded",
            latency_sec=generation.latency_sec,
            adapter_metadata={"swebench_command": " ".join(evaluate)},
        )
    scored = runner(evaluate, cwd=instance_dir, timeout_sec=remaining)
    scored = SwebenchCliResult(
        returncode=scored.returncode,
        stdout=generation.stdout + scored.stdout,
        stderr=generation.stderr + scored.stderr,
        latency_sec=generation.latency_sec + scored.latency_sec,
        command=scored.command,
    )
    _materialize_official_instance_report(
        instance_dir=instance_dir,
        instance_fd=instance_fd,
        instance_id=instance_id,
        run_id=run_id,
    )
    return _score_swe_phase(
        instance_id=instance_id,
        cli=scored,
        instance_dir=instance_dir,
        repo_root=repo_root,
        harness_version=harness_version,
        instance_fd=instance_fd,
    )


def run_swebench_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: SwebenchProcessRunner | None = None,
    timeout_sec: int | None = None,
    harness_version: str | None = None,
    run_id: str | None = None,
) -> SwebenchInstanceOutcome:
    if plan.adapter_id != SWEBENCH_ADAPTER_ID:
        raise BenchEvalError(f"swebench adapter cannot run adapter_id={plan.adapter_id!r}")
    if process_runner is None:
        raise BenchEvalError(
            "swebench default process runner is disabled until the diagnostic "
            "identity and dependency contract is complete",
        )
    validate_control_plane_instance_id(instance_id)
    instance_dir = prepare_instance_artifacts_dir(
        artifacts_dir / instance_id,
        clear_names=AUTHORITATIVE_ARTIFACT_NAMES
        | frozenset({_OFFICIAL_REPORT_NAME, _WORKSPACE_DIFF_NAME, _PREDICTIONS_NAME}),
    )
    instance_fd = open_owned_dir_fd(instance_dir, role=_INSTANCE_DIR_ROLE)
    try:
        wall = (
            timeout_sec if timeout_sec is not None else max(1, plan.max_wall_clock_sec_per_instance)
        )
        return _run_generation_then_eval(
            plan=plan,
            instance_id=instance_id,
            instance_dir=instance_dir,
            instance_fd=instance_fd,
            repo_root=repo_root,
            runner=process_runner or _default_process_runner,
            wall=wall,
            harness_version=harness_version,
            run_id=_validate_swe_run_id(run_id) if run_id is not None else new_run_id(),
        )
    finally:
        os.close(instance_fd)


__all__ = [
    "SWEBENCH_ADAPTER_ID",
    "SwebenchCliResult",
    "SwebenchInstanceOutcome",
    "SwebenchProcessRunner",
    "build_swebench_eval_command",
    "build_swebench_run_command",
    "parse_swebench_instance_outcome",
    "run_swebench_instance",
]
