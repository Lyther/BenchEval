"""Humanity's Last Exam model-only adapter (official CAIS scripts on host)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.provenance_gates import is_captured_harness_version
from bencheval.provider_registry import resolve_openai_compatible_launch
from bencheval.run_isolation import (
    dir_identity_error,
    open_owned_dir_fd,
    write_bytes_at_exclusive,
    write_text_at_exclusive,
)

HLE_ADAPTER_ID = "hle"
_HLE_HOME_ENV = "BENCHEVAL_HLE_HOME"
_MIN_HLE_WORKERS = 2
_SAFE_TOKEN_RE = re.compile(r"[^A-Za-z0-9._+-]+")
_HLE_CALIBRATION_BIN_SIZE = 100
_HLE_SMALL_SLICE_CALIBRATION_MARKERS = (
    "run_judge_results.py",
    "in dump_metrics",
    "calib_err(",
    "bins[-1]",
    "IndexError: list index out of range",
)


def _path_is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


@dataclass(frozen=True, slots=True)
class HleCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HleOfficialScore:
    accuracy: float
    correct: int
    total: int
    source: str


@dataclass(frozen=True, slots=True)
class HleInstanceOutcome:
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
    adapter_metadata: dict[str, str]
    counts_toward_pass_at_k: bool


@dataclass(frozen=True, slots=True)
class HleRunPaths:
    work_dir: Path
    predictions_path: Path
    judged_path: Path
    default_predictions_path: Path


class HleProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> HleCliResult: ...


def _hle_root() -> Path:
    raw = os.environ.get(_HLE_HOME_ENV)
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd()


_HLE_SCRIPT_NAMES = ("run_model_predictions.py", "run_judge_results.py")
_HLE_DATASET_ENV = "BENCHEVAL_HLE_DATASET"
_DEFAULT_HLE_DATASET = "cais/hle"


def _hle_dataset_name() -> str:
    """Dataset argument passed to the official scripts (default ``cais/hle``).

    Air-gapped or mirror environments can point the official harness at a
    local parquet export via ``BENCHEVAL_HLE_DATASET``; the pinned script
    bytes are untouched either way, and the value is stamped into evidence
    metadata so a non-official source is never hidden.
    """
    return os.environ.get(_HLE_DATASET_ENV, "").strip() or _DEFAULT_HLE_DATASET


def _hle_scripts(root: Path) -> tuple[Path, Path] | None:
    """The official script pair, or None when absent or unsafe to execute.

    Symlinked scripts — or scripts resolving outside the checkout — are
    rejected: their content would not be identified by the checkout revision,
    and the run path must never resolve a foreign executable target.
    """
    eval_dir = _hle_eval_dir(root)
    scripts: list[Path] = []
    for name in _HLE_SCRIPT_NAMES:
        script = eval_dir / name
        if script.is_symlink() or not script.is_file():
            return None
        if not _path_is_under(script, root):
            return None
        scripts.append(script)
    return (scripts[0], scripts[1])


def _hle_scripts_digest(scripts: tuple[Path, Path]) -> str:
    digest = hashlib.sha256()
    for script in scripts:
        digest.update(script.name.encode())
        digest.update(b"\0")
        digest.update(script.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def _hle_worktree_dirty(root: Path) -> bool:
    """True when the checkout differs from HEAD (or state cannot be determined)."""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    if proc.returncode != 0:
        return True
    return bool(proc.stdout.strip())


@dataclass(frozen=True, slots=True)
class HleHarnessPin:
    """Immutable expected identity of the official CAIS HLE harness.

    ``commit`` is the verified upstream git revision; ``script_sha256`` maps
    each executed script name to its expected content digest at that commit.
    Provenance is captured only when the checkout matches BOTH exactly — a
    self-asserted git remote URL is metadata, not source identity.
    """

    commit: str
    script_sha256: dict[str, str]


# Verified against the official CAIS HLE upstream
# (https://github.com/centerforaisafety/hle) on 2026-08-10 via
# `git ls-remote` plus a shallow clone: HEAD matched the commit below and the
# two executed scripts hashed to the digests below. Re-pin procedure: clone
# upstream, confirm the intended revision, sha256 both scripts, update this
# constant and the verification date.
_DEFAULT_HLE_PIN = HleHarnessPin(
    commit="73ae974b1844c3ffa64c3f4343d9f1f259575700",
    script_sha256={
        "run_model_predictions.py": (
            "d2062d8afcfb8968f350bbae953e897d4303a6f72a4ae7d97b7db0137a333b17"
        ),
        "run_judge_results.py": (
            "a796e74d6e58beab3bd88f46182f599443a102308b2d1c7e0b4b22f578468446"
        ),
    },
)


def _hle_harness_version(root: Path, *, pin: HleHarnessPin | None = None) -> str | None:
    """Source-owned identity of the CAIS HLE checkout, or None when unavailable.

    The provenance gate requires a captured, non-fallback harness version. The
    identity binds the pinned upstream revision to the actual executed
    content: the two official scripts must be plain in-checkout files whose
    bytes sha256-match the pin, and HEAD must equal the pinned commit (an
    arbitrary git repository with same-named scripts — or a self-asserted
    remote URL — is not the CAIS harness). A dirty worktree stamps a
    ``-dirty`` suffix that the provenance gate rejects as mutable. Never
    fabricate a placeholder label — an unpinned or drifted checkout simply
    fails Tier-1 qualification.
    """
    expected = pin if pin is not None else _DEFAULT_HLE_PIN
    scripts = _hle_scripts(root)
    if scripts is None:
        # Without the official in-checkout scripts this is not an HLE checkout;
        # attributing a revision (e.g. the cwd repo's, when BENCHEVAL_HLE_HOME
        # is unset) would fabricate provenance.
        return None
    for script in scripts:
        expected_digest = expected.script_sha256.get(script.name)
        if expected_digest is None:
            return None
        if hashlib.sha256(script.read_bytes()).hexdigest() != expected_digest:
            return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD", "--show-toplevel"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    lines = proc.stdout.splitlines()
    if len(lines) != 2:
        return None
    sha, toplevel = lines[0].strip(), lines[1].strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None
    # Attribute only when the checkout root is the repository root: git walks up,
    # so a nested directory would otherwise borrow an unrelated repo's revision.
    try:
        if Path(toplevel).resolve() != root.resolve():
            return None
    except OSError:
        return None
    if sha != expected.commit:
        return None
    version = f"hle@{sha}+scripts-{_hle_scripts_digest(scripts)}"
    if _hle_worktree_dirty(root):
        version += "-dirty"
    return version


def _hle_eval_dir(root: Path) -> Path:
    return root / "hle_eval"


def _safe_token(value: str) -> str:
    cleaned = _SAFE_TOKEN_RE.sub("_", value.strip())
    return cleaned.strip("._") or "unknown"


def _model_basename(model_id: str) -> str:
    return _safe_token(Path(model_id).name.replace(os.sep, "_"))


def hle_work_dir(artifacts_dir: Path) -> Path:
    return artifacts_dir.resolve() / "hle-work"


def hle_output_stem(*, run_id: str, provider_id: str, model_id: str) -> str:
    """Stable stem including run_id and full provider/model identity."""
    return f"{_safe_token(run_id)}__{_safe_token(provider_id)}__{_safe_token(model_id)}"


def hle_run_paths(
    *,
    artifacts_dir: Path,
    run_id: str,
    provider_id: str,
    model_id: str,
) -> HleRunPaths:
    work_dir = hle_work_dir(artifacts_dir)
    stem = hle_output_stem(run_id=run_id, provider_id=provider_id, model_id=model_id)
    predictions = work_dir / f"hle_{stem}.json"
    return HleRunPaths(
        work_dir=work_dir,
        predictions_path=predictions,
        # CAIS uses f"judged_{basename(predictions)}.json". The predictions
        # basename already ends in .json, yielding the official .json.json name.
        judged_path=work_dir / f"judged_{predictions.name}.json",
        default_predictions_path=work_dir / f"hle_{_model_basename(model_id)}.json",
    )


def remaining_timeout_sec(
    deadline_monotonic: float,
    *,
    now_monotonic: float | None = None,
) -> int:
    """Seconds remaining until a cumulative wall-clock deadline (0 if exhausted)."""
    now = time.monotonic() if now_monotonic is None else now_monotonic
    left = deadline_monotonic - now
    if left <= 0:
        return 0
    return max(1, math.ceil(left))


def _materialize_hle_script_copies(
    scripts: tuple[Path, Path],
    copy_dir: Path,
) -> tuple[tuple[Path, Path], dict[str, str]]:
    """Copy the validated scripts into a BenchEval-owned run directory.

    Returns the copies and their expected sha256 digests. The harness
    executes the copies — never the mutable checkout pathnames — and a
    post-run digest check proves the executed bytes never changed mid-run.
    Writes are anchored to the copy dir's file descriptor with exclusive
    no-follow creates: a pre-planted symlink or hard link at a copy path is
    unlinked (never opened, truncated, or followed) and recreated as a fresh
    regular file.
    """
    copy_fd = open_owned_dir_fd(copy_dir, role="hle script copy directory")
    try:
        copies: list[Path] = []
        expected: dict[str, str] = {}
        for script in scripts:
            data = script.read_bytes()
            target = copy_dir / script.name
            write_bytes_at_exclusive(copy_fd, script.name, data)
            copies.append(target)
            expected[script.name] = hashlib.sha256(data).hexdigest()
    finally:
        os.close(copy_fd)
    return (copies[0], copies[1]), expected


def _hle_script_copies_digest_error(
    copies: tuple[Path, Path],
    expected: Mapping[str, str],
) -> str | None:
    """None while every executed copy still holds the launch-time bytes."""
    for copy in copies:
        try:
            digest = hashlib.sha256(copy.read_bytes()).hexdigest()
        except OSError:
            return f"hle script copy vanished during execution: {copy}"
        if digest != expected[copy.name]:
            return f"hle script copy changed during execution: {copy}"
    return None


def build_hle_run_commands(
    *,
    plan: RunPlan,
    max_samples: int,
    artifacts_dir: Path,
    run_id: str,
) -> tuple[tuple[str, ...], ...]:
    if plan.runtime_id is not None:
        raise BenchEvalError(
            f"hle adapter expects model-only (runtime_id=None), got {plan.runtime_id!r}",
        )
    if plan.agent_id is not None:
        raise BenchEvalError(
            f"hle adapter expects model-only (agent_id=None), got {plan.agent_id!r}",
        )
    if plan.judge_model_id is None:
        raise BenchEvalError("hle adapter requires a planned judge_model_id")
    root = _hle_root()
    scripts = _hle_scripts(root)
    if scripts is None:
        raise BenchEvalError(
            f"CAIS HLE scripts not found as plain in-checkout files under {_hle_eval_dir(root)} "
            f"(symlinked or out-of-checkout scripts are refused); "
            f"clone https://github.com/centerforaisafety/hle and set {_HLE_HOME_ENV}",
        )
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id=run_id,
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    return _build_hle_commands(
        plan=plan,
        scripts=scripts,
        paths=paths,
        max_samples=max_samples,
        dataset_name=_hle_dataset_name(),
    )


def _build_hle_commands(
    *,
    plan: RunPlan,
    scripts: tuple[Path, Path],
    paths: HleRunPaths,
    max_samples: int,
    dataset_name: str,
) -> tuple[tuple[str, ...], ...]:
    pred_script, judge_script = scripts
    n = max(max_samples, 1)
    workers = str(_MIN_HLE_WORKERS)
    pred_cmd = (
        "python",
        str(pred_script.resolve()),
        "--dataset",
        dataset_name,
        "--model",
        plan.model_id,
        "--max_completion_tokens",
        "8192",
        "--num_workers",
        workers,
        "--max_samples",
        str(n),
    )
    judge_cmd = (
        "python",
        str(judge_script.resolve()),
        "--dataset",
        dataset_name,
        "--predictions",
        str(paths.predictions_path),
        "--num_workers",
        workers,
        "--judge",
        plan.judge_model_id,
    )
    return (pred_cmd, judge_cmd)


def _clear_path(path: Path) -> None:
    if path.is_file():
        path.unlink()
    elif path.exists():
        raise BenchEvalError(f"refusing to reuse non-file HLE artifact path: {path}")


def prepare_hle_work_dir(paths: HleRunPaths) -> None:
    """Create run-local work dir and clear prior outputs for this run identity."""
    paths.work_dir.mkdir(parents=True, exist_ok=True)
    for path in (
        paths.predictions_path,
        paths.judged_path,
        paths.default_predictions_path,
        paths.work_dir / f"judged_{paths.default_predictions_path.name}.json",
    ):
        _clear_path(path)


def materialize_hle_predictions(paths: HleRunPaths) -> Path:
    """Map official basename output onto the run-isolated predictions path."""
    if paths.predictions_path.is_file():
        return paths.predictions_path
    if paths.default_predictions_path.is_file():
        paths.default_predictions_path.replace(paths.predictions_path)
        return paths.predictions_path
    raise AdapterFailureError(
        "hle predict finished without predictions file "
        f"(expected {paths.default_predictions_path.name} or {paths.predictions_path.name})",
        failure_label="runtime_output_unparseable",
        latency_sec=0.0,
        adapter_metadata={"hle_predictions": str(paths.predictions_path)},
    )


def parse_hle_official_score(
    *,
    eval_dir: Path,
    model_id: str,
    judge_stdout: str,
    max_samples: int,
    work_dir: Path | None = None,
    judged_path: Path | None = None,
    judged_dir_fd: int | None = None,
) -> HleOfficialScore | None:
    """Parse the current run's official judged artifact into accuracy.

    Authority is the judged JSON only (exact ``correct == "yes"``). Stdout
    metrics and BenchEval-authored summaries are never scoring authority.
    When ``work_dir`` is set, the judged file must resolve inside that tree.
    When ``judged_dir_fd`` is set, the judged file is read dirfd-relative and
    no-follow from that pinned inode: a rename-and-recreate swap of the work
    dir after the pin cannot substitute forged rows (the honest boundary is a
    same-uid mutator racing after the pin; writes before it are out of scope).
    """
    _ = judge_stdout  # retained for call-site symmetry; never scoring authority
    candidates: list[Path] = []
    if judged_path is not None:
        candidates.append(judged_path)
    elif eval_dir.is_dir():
        candidates.append(eval_dir / f"judged_hle_{_model_basename(model_id)}.json.json")

    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if work_dir is not None and not _path_is_under(resolved, work_dir):
            continue
        if judged_dir_fd is None and not path.is_file():
            continue
        try:
            if judged_dir_fd is not None and path == judged_path:
                judged_fd = os.open(
                    path.name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=judged_dir_fd,
                )
                with os.fdopen(judged_fd, encoding="utf-8") as handle:
                    parsed = json.load(handle)
            else:
                parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict) and parsed:
            correct = 0
            total = 0
            for row in parsed.values():
                if not isinstance(row, dict):
                    continue
                judge = row.get("judge_response")
                if not isinstance(judge, dict):
                    # Missing judge response shrinks the denominator → reject.
                    return None
                answer = judge.get("correct")
                # Official HLE judge literals are exactly "yes" / "no".
                if answer not in ("yes", "no"):
                    return None
                total += 1
                if answer == "yes":
                    correct += 1
            if total <= 0 or total != max_samples:
                return None
            return HleOfficialScore(
                accuracy=correct / total,
                correct=correct,
                total=total,
                source=str(resolved),
            )
    return None


def _is_known_post_artifact_small_slice_calibration_failure(
    *,
    cli: HleCliResult | None,
    max_samples: int,
    official: HleOfficialScore | None,
    harness_version: str | None,
) -> bool:
    """Recognize the pinned judge's metrics-only crash after complete judging.

    The pinned upstream judge writes ``judged_<predictions>.json`` before
    ``dump_metrics``. Its calibration code assumes at least one 100-row bin and
    raises the exact traceback below for smaller smoke slices. Only a captured
    harness, the judge command, a complete authoritative artifact, and all
    source-code-specific traceback markers may downgrade that nonzero exit.
    """
    if (
        cli is None
        or cli.returncode == 0
        or max_samples <= 0
        or max_samples >= _HLE_CALIBRATION_BIN_SIZE
        or official is None
        or official.total != max_samples
        or not is_captured_harness_version(harness_version)
        or len(cli.command) < 2
        or Path(cli.command[1]).name != "run_judge_results.py"
    ):
        return False
    return all(marker in cli.stderr for marker in _HLE_SMALL_SLICE_CALIBRATION_MARKERS)


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
    env: Mapping[str, str],
) -> HleCliResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_sec,
            env=dict(env),
        )
    except subprocess.TimeoutExpired as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"hle harness timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"hle_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"hle harness launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"hle_command": " ".join(command)},
        ) from e
    return HleCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def run_hle_slice(
    *,
    plan: RunPlan,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: HleProcessRunner | None = None,
    timeout_sec: int | None = None,
    run_id: str = "hle-run",
    monotonic_clock: Callable[[], float] | None = None,
    harness_pin: HleHarnessPin | None = None,
) -> list[HleInstanceOutcome]:
    if plan.adapter_id != HLE_ADAPTER_ID:
        raise BenchEvalError(f"hle adapter cannot run adapter_id={plan.adapter_id!r}")
    for inst in plan.instances:
        validate_control_plane_instance_id(inst.instance_id)
    launch = resolve_openai_compatible_launch(
        plan.provider_id,
        require_api_key=process_runner is None,
    )
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    # Pin the artifacts directory inode before launching the harness: every
    # BenchEval-owned write below is anchored to this descriptor, and the
    # post-run identity check proves the path still names the pinned inode.
    artifacts_fd = open_owned_dir_fd(artifacts_dir, role="hle artifacts directory")
    work_fd: int | None = None
    try:
        paths = hle_run_paths(
            artifacts_dir=artifacts_dir,
            run_id=run_id,
            provider_id=plan.provider_id,
            model_id=plan.model_id,
        )
        prepare_hle_work_dir(paths)
        work_fd = open_owned_dir_fd(paths.work_dir, role="hle work directory")
        root = _hle_root()
        scripts = _hle_scripts(root)
        if scripts is None:
            raise BenchEvalError(
                f"CAIS HLE scripts not found as plain in-checkout files under "
                f"{_hle_eval_dir(root)} "
                f"(symlinked or out-of-checkout scripts are refused); "
                f"clone https://github.com/centerforaisafety/hle and set {_HLE_HOME_ENV}",
            )
        # Bind execution to the validated bytes: the harness runs BenchEval-owned
        # copies, never the mutable checkout pathnames, and both the copies and
        # the stamped provenance are re-verified after the run.
        copies, expected_copy_digests = _materialize_hle_script_copies(
            scripts,
            artifacts_dir.resolve() / "hle-src",
        )
        dataset_name = _hle_dataset_name()
        commands = _build_hle_commands(
            plan=plan,
            scripts=copies,
            paths=paths,
            max_samples=len(plan.instances),
            dataset_name=dataset_name,
        )
        # Aggregate harness: prediction and judging for every sample run in one
        # subprocess chain, so the run-total envelope is the only honest bound;
        # no per-instance limit is enforceable inside the aggregate process.
        wall = timeout_sec if timeout_sec is not None else max(1, plan.max_wall_clock_sec)
        clock = monotonic_clock or time.monotonic
        deadline = clock() + wall
        runner = process_runner or _default_process_runner
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        total_latency = 0.0
        last_rc = 0
        last_cmd: tuple[str, ...] = ()
        last_cli: HleCliResult | None = None
        # Capture provenance before executing the harness; the post-run re-check
        # below proves the source identity never drifted while the harness ran.
        harness_version = _hle_harness_version(root, pin=harness_pin)
        eval_dir = _hle_eval_dir(root)
        cwd = paths.work_dir

        for index, command in enumerate(commands):
            remaining = remaining_timeout_sec(deadline, now_monotonic=clock())
            if remaining <= 0:
                raise AdapterFailureError(
                    f"hle harness timed out after {wall}s",
                    failure_label="runtime_budget_exceeded",
                    latency_sec=total_latency,
                    adapter_metadata={"hle_command": " ".join(command)},
                )
            cli = runner(command, cwd=cwd, timeout_sec=remaining, env=launch.environment)
            work_identity_error = dir_identity_error(
                work_fd,
                paths.work_dir,
                role="hle work directory",
            )
            if work_identity_error is not None:
                raise AdapterFailureError(
                    work_identity_error,
                    failure_label="evidence_corrupt",
                    latency_sec=total_latency + cli.latency_sec,
                    adapter_metadata={"hle_command": " ".join(cli.command)},
                )
            stdout_parts.append(cli.stdout)
            stderr_parts.append(cli.stderr)
            total_latency += cli.latency_sec
            last_rc = cli.returncode
            last_cmd = cli.command
            last_cli = cli
            if cli.returncode != 0:
                break
            if index == 0:
                materialize_hle_predictions(paths)

        copy_error = _hle_script_copies_digest_error(copies, expected_copy_digests)
        if copy_error is not None:
            # The executed bytes changed mid-run (same-uid mutator found the
            # copies): the produced outputs cannot be trusted as native evidence.
            raise AdapterFailureError(
                copy_error,
                failure_label="evidence_corrupt",
                latency_sec=total_latency,
                adapter_metadata={"hle_command": " ".join(last_cmd)},
            )
        if _hle_harness_version(root, pin=harness_pin) != harness_version:
            raise AdapterFailureError(
                "hle harness source identity drifted during execution",
                failure_label="evidence_corrupt",
                latency_sec=total_latency,
                adapter_metadata={"hle_command": " ".join(last_cmd)},
            )

        artifacts_identity_error = dir_identity_error(
            artifacts_fd,
            artifacts_dir,
            role="hle artifacts directory",
        )
        if artifacts_identity_error is not None:
            # The harness (cwd inside the artifacts tree) swapped the approved
            # directory mid-run; the dirfd-anchored writes stayed on the pinned
            # inode, so fail closed instead of publishing attacker content.
            raise AdapterFailureError(
                artifacts_identity_error,
                failure_label="evidence_corrupt",
                latency_sec=total_latency,
                adapter_metadata={"hle_command": " ".join(last_cmd)},
            )

        stdout_text = "\n".join(stdout_parts)
        stdout_file = artifacts_dir / "stdout.log"
        stderr_file = artifacts_dir / "stderr.log"
        # Anchored, no-follow, exclusive recreates: a symlink or hard link
        # planted at these paths by the harness is unlinked (never opened,
        # truncated, or followed) and replaced by a fresh regular file.
        write_text_at_exclusive(artifacts_fd, "stdout.log", stdout_text)
        write_text_at_exclusive(artifacts_fd, "stderr.log", "\n".join(stderr_parts))

        parsed_official = parse_hle_official_score(
            eval_dir=eval_dir,
            model_id=plan.model_id,
            judge_stdout=stdout_text,
            max_samples=len(plan.instances),
            work_dir=paths.work_dir,
            judged_path=paths.judged_path,
            judged_dir_fd=work_fd,
        )
        accepted_post_artifact_failure = _is_known_post_artifact_small_slice_calibration_failure(
            cli=last_cli,
            max_samples=len(plan.instances),
            official=parsed_official,
            harness_version=harness_version,
        )
        # A judged file from an arbitrary failed subprocess is not authority.
        # Publish it only after a clean judge exit or the exact pinned
        # post-artifact calibration failure recognized above.
        official = parsed_official if last_rc == 0 or accepted_post_artifact_failure else None
        if last_rc != 0 and not accepted_post_artifact_failure:
            primary_pass = False
            partial_score = 0.0
            counts = False
            failure: FailureLabel | None = "harness_failure"
        elif official is None:
            primary_pass = False
            partial_score = 0.0
            counts = False
            failure = "runtime_output_unparseable"
        else:
            partial_score = official.accuracy
            requested = len(plan.instances)
            complete = official.total == requested and official.correct <= official.total
            primary_pass = bool(
                complete and official.accuracy >= 1.0 and official.correct == official.total,
            )
            counts = complete
            if not complete:
                failure = "runtime_output_unparseable"
                primary_pass = False
            else:
                failure = None if primary_pass else "model_wrong_solution"

        summary_payload: dict[str, object] = {
            "returncode": last_rc,
            "max_samples": len(plan.instances),
            "work_dir": str(paths.work_dir),
            "predictions_path": str(paths.predictions_path),
            "judged_path": str(paths.judged_path),
            "judge_model_id": plan.judge_model_id,
            "official_score": (
                None
                if official is None
                else {
                    "accuracy": official.accuracy,
                    "correct": official.correct,
                    "total": official.total,
                    "source": official.source,
                }
            ),
            "primary_pass": primary_pass,
            "partial_score": partial_score,
            "counts_toward_pass_at_k": counts,
            "commands": [" ".join(c) for c in commands],
        }
        if accepted_post_artifact_failure:
            summary_payload["judge_exit_interpretation"] = (
                "known_post_artifact_small_slice_calibration_failure"
            )
        write_text_at_exclusive(
            artifacts_fd,
            "hle_summary.json",
            json.dumps(summary_payload, indent=2) + "\n",
        )
        meta = {
            "adapter_id": HLE_ADAPTER_ID,
            "harness_kind": "hle-native",
            "hle_command": " ".join(last_cmd),
            "interpretation": "adapter_smoke",
            "score_source": "official" if official is not None else "missing",
            "evidence_shape": "aggregate_slice",
            "effective_model_id": plan.model_id,
            "judge_model_id": plan.judge_model_id,
            # Honest dataset identity: default cais/hle, or the mirror/local source
            # selected via BENCHEVAL_HLE_DATASET (never hidden from evidence).
            "hle_dataset": dataset_name,
            "provider_config_hash": launch.config_hash,
            # One aggregate subprocess chain: per-instance wall is not enforceable.
            "per_instance_wall_enforcement": "unavailable_aggregate_harness",
        }
        if harness_version is not None:
            meta["harness_version"] = harness_version
        if accepted_post_artifact_failure:
            meta["judge_exit_interpretation"] = (
                "known_post_artifact_small_slice_calibration_failure"
            )
        native: dict[str, object] = {
            "returncode": last_rc,
            "planned_sample_slots": len(plan.instances),
            "work_dir": str(paths.work_dir),
            "effective_model_id": plan.model_id,
            "judge_model_id": plan.judge_model_id,
        }
        if official is not None:
            native.update(
                {
                    "accuracy": official.accuracy,
                    "correct": official.correct,
                    "total": official.total,
                    "score_source": official.source,
                },
            )
        if accepted_post_artifact_failure:
            native["judge_exit_interpretation"] = (
                "known_post_artifact_small_slice_calibration_failure"
            )
        _ = repo_root  # call-site symmetry; HLE scripts resolve under BENCHEVAL_HLE_HOME
        # cost_usd=0.0 below means "no provider metering captured", not zero spend.
        native["cost_basis"] = "unmeasured_no_provider_metering"
        # Official judged artifact is the only native verifier path; never hle_summary.json.
        verifier_log: str | None = None
        if official is not None and paths.judged_path.is_file():
            verifier_log = str(paths.judged_path.resolve())
        aggregate_id = f"{plan.benchmark_id}-{plan.slice_id}-aggregate"
        validate_control_plane_instance_id(aggregate_id)
        return [
            HleInstanceOutcome(
                instance_id=aggregate_id,
                primary_pass=primary_pass,
                partial_score=partial_score,
                cost_usd=0.0,
                latency_sec=total_latency,
                native_score=native,
                failure_class=failure,
                stdout_path=str(stdout_file.resolve()),
                stderr_path=str(stderr_file.resolve()),
                verifier_log_path=verifier_log,
                adapter_metadata={
                    **meta,
                    "cost_cap": "unenforced_estimate",
                    "reported_cost_usd": "unavailable",
                },
                counts_toward_pass_at_k=counts,
            ),
        ]
    finally:
        if work_fd is not None:
            os.close(work_fd)
        os.close(artifacts_fd)


__all__ = [
    "HLE_ADAPTER_ID",
    "HleCliResult",
    "HleHarnessPin",
    "HleInstanceOutcome",
    "HleOfficialScore",
    "HleProcessRunner",
    "HleRunPaths",
    "build_hle_run_commands",
    "hle_output_stem",
    "hle_run_paths",
    "hle_work_dir",
    "materialize_hle_predictions",
    "parse_hle_official_score",
    "prepare_hle_work_dir",
    "remaining_timeout_sec",
    "run_hle_slice",
]
