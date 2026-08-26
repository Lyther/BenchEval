"""GPQA Diamond model-only adapter via Inspect Evals (host pulls dataset)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Protocol

from bencheval.benchmark_registry import InspectEvalsCsvIdentity
from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.provider_registry import resolve_openai_compatible_launch
from bencheval.run_isolation import (
    dir_identity_error,
    open_owned_dir_fd,
    write_text_at_exclusive,
)

GPQA_ADAPTER_ID = "gpqa"
_INSPECT_TASK = "inspect_evals/gpqa_diamond"
_OFFICIAL_SCORES_NAME = "official_scores.json"
_INSPECT_EVALS_DIST = "inspect-evals"
# Inspect plain/rich panels print "Log: <path>"; strip optional rich markup around it.
_LOG_LOCATION_RE = re.compile(
    r"(?:^|\n)\s*(?:Log:\s+|log_location[\"']?\s*[:=]\s*[\"']?)([^\s\"'<>]+)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class GpqaCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GpqaOfficialScore:
    accuracy: float
    correct: int | None
    total: int | None
    source: str
    unique_samples: int | None = None
    epochs: int | None = None


@dataclass(frozen=True, slots=True)
class GpqaInstanceOutcome:
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


class GpqaProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> GpqaCliResult: ...


def _inspect_model_string(plan: RunPlan) -> str:
    expected = (
        f"openai/{plan.model_id}"
        if plan.provider_id == "bytellm"
        else f"{plan.provider_id}/{plan.model_id}"
    )
    override = os.environ.get("BENCHEVAL_INSPECT_MODEL")
    if override is not None and override.strip() != expected:
        raise BenchEvalError(
            f"BENCHEVAL_INSPECT_MODEL must match the provider-resolved planned model {expected!r}",
        )
    return expected


def build_gpqa_run_command(
    *,
    plan: RunPlan,
    sample_limit: int,
    log_dir: Path,
) -> tuple[str, ...]:
    if plan.runtime_id is not None:
        raise BenchEvalError(
            f"gpqa adapter expects model-only (runtime_id=None), got {plan.runtime_id!r}",
        )
    if plan.agent_id is not None:
        raise BenchEvalError(
            f"gpqa adapter expects model-only (agent_id=None), got {plan.agent_id!r}",
        )
    limit = max(sample_limit, 1)
    return (
        "inspect",
        "eval",
        _INSPECT_TASK,
        "--model",
        _inspect_model_string(plan),
        "--limit",
        str(limit),
        "--log-dir",
        str(log_dir.resolve()),
        "--log-format",
        "json",
        "--json",
    )


def _inspect_evals_harness_version() -> str | None:
    try:
        return f"{_INSPECT_EVALS_DIST}@{distribution_version(_INSPECT_EVALS_DIST)}"
    except PackageNotFoundError:
        return None


# --- Pinned dataset identity (catalog ``identity:`` block) ------------------

_GPQA_CACHE_EVAL_NAME = "gpqa"
_GPQA_CACHE_TAG = "gpqa_diamond"
# The real CSV is ~200 KB; the bound exists so a wrong-pinned URL cannot turn
# the buffered download into a memory blowup.
_MAX_GPQA_CSV_BYTES = 64 * 1024 * 1024


def gpqa_csv_cache_path(*, cache_root: Path, dataset_url: str) -> Path:
    """Cache file inspect_evals resolves for the pinned CSV URL.

    Mirrors ``inspect_evals.utils.load_dataset._get_cached_path``: the name is
    ``<tag>_<sha256(url)[:32]><ext>`` under ``<cache_root>/<eval>/``.
    """
    from urllib.parse import urlparse

    url_hash = hashlib.sha256(dataset_url.encode("utf-8")).hexdigest()[:32]
    suffix = Path(urlparse(dataset_url).path).suffix
    return cache_root / _GPQA_CACHE_EVAL_NAME / f"{_GPQA_CACHE_TAG}_{url_hash}{suffix}"


def verify_gpqa_csv_cache(*, cache_root: Path, dataset_url: str, sha256_pin: str) -> Path:
    """Return the cached CSV path iff its bytes sha256-match the pin.

    Pure verification core: local path in, digest compare against the pin.
    """
    from bencheval.identity_strings import file_sha256

    cached = gpqa_csv_cache_path(cache_root=cache_root, dataset_url=dataset_url)
    if cached.is_symlink() or not cached.is_file():
        raise BenchEvalError(f"gpqa dataset cache file missing or not a plain file: {cached}")
    actual = f"sha256:{file_sha256(cached)}"
    if actual != sha256_pin:
        raise BenchEvalError(
            f"gpqa dataset cache sha256 drift at {cached}: expected {sha256_pin}, got {actual}",
        )
    return cached


def _inspect_evals_cache_root() -> Path:
    """The cache root the harness subprocess resolves at its own import time."""
    from inspect_evals.constants import INSPECT_EVALS_CACHE_PATH

    return INSPECT_EVALS_CACHE_PATH


def _download_gpqa_csv(*, dataset_url: str, dest: Path) -> None:
    """Fetch the pinned CSV and anchor the write to the pinned cache dir fd.

    The payload is buffered whole (bounded) and written with one anchored,
    no-follow, exclusive create: a failed fetch never leaves a partial file,
    and an existing file is never overwritten.
    """
    import urllib.request

    from bencheval.run_isolation import write_bytes_at_exclusive

    try:
        with urllib.request.urlopen(dataset_url, timeout=120) as response:
            payload = response.read(_MAX_GPQA_CSV_BYTES + 1)
    except Exception as e:
        raise BenchEvalError(f"cannot download pinned gpqa dataset {dataset_url}: {e}") from e
    if len(payload) > _MAX_GPQA_CSV_BYTES:
        raise BenchEvalError(
            f"pinned gpqa dataset exceeds {_MAX_GPQA_CSV_BYTES} bytes: {dataset_url}",
        )
    dir_fd = open_owned_dir_fd(dest.parent, role="inspect_evals cache directory")
    try:
        write_bytes_at_exclusive(dir_fd, dest.name, payload)
    finally:
        os.close(dir_fd)


def capture_gpqa_benchmark_identity(
    identity: InspectEvalsCsvIdentity,
    *,
    cache_root: Path | None = None,
    fetcher: Callable[..., None] | None = None,
) -> str:
    """Verify the installed dist, eval metadata, and cached CSV bytes against
    the catalog pin, then return the capturable identity string.

    Fails closed on any drift. A missing cache file is fetched from the pinned
    URL (or the injected ``fetcher`` test seam); an existing mismatching file
    is never silently overwritten — drift aborts the run instead.
    """
    from inspect_evals.metadata import load_eval_metadata

    from bencheval.identity_strings import gpqa_benchmark_identity

    try:
        dist_version = distribution_version(identity.package)
    except PackageNotFoundError as e:
        raise BenchEvalError(
            f"gpqa identity requires the {identity.package!r} distribution to be installed",
        ) from e
    if dist_version != identity.package_version:
        raise BenchEvalError(
            f"{identity.package} distribution version drift: pinned "
            f"{identity.package_version}, installed {dist_version}",
        )
    eval_version = str(load_eval_metadata("gpqa").version)
    if eval_version != identity.eval_version:
        raise BenchEvalError(
            f"gpqa eval metadata version drift: pinned {identity.eval_version}, "
            f"installed {eval_version}",
        )
    root = cache_root if cache_root is not None else _inspect_evals_cache_root()
    cached = gpqa_csv_cache_path(cache_root=root, dataset_url=identity.dataset_url)
    downloaded = not cached.is_file()
    if downloaded:
        (fetcher or _download_gpqa_csv)(dataset_url=identity.dataset_url, dest=cached)
    try:
        verify_gpqa_csv_cache(
            cache_root=root,
            dataset_url=identity.dataset_url,
            sha256_pin=identity.sha256,
        )
    except BenchEvalError:
        if downloaded:
            # A just-fetched file that fails the pin is poison we created this
            # run; remove it so a later run cannot score drifted bytes.
            cached.unlink(missing_ok=True)
        raise
    return gpqa_benchmark_identity(identity)


def _gpqa_prelaunch_benchmark_identity(
    *,
    plan: RunPlan,
    process_runner: GpqaProcessRunner | None,
    benchmark_identity: str | None,
) -> str | None:
    """Fail closed before launch when the catalog pins a benchmark identity.

    The real/default runner always verifies local bytes against the pin. A
    supplied identity belongs to an injected runner's controlled test boundary
    and must equal the config-derived expectation.
    """
    from bencheval.identity_strings import catalog_benchmark_identity, gpqa_benchmark_identity

    identity = catalog_benchmark_identity(plan.benchmark_id)
    if identity is None:
        return None
    if not isinstance(identity, InspectEvalsCsvIdentity):
        raise AdapterFailureError(
            f"gpqa benchmark identity kind drift: {identity.kind!r}",
            failure_label="runtime_config_drift",
        )
    expected = gpqa_benchmark_identity(identity)
    if process_runner is not None:
        if benchmark_identity is None:
            return None
        if benchmark_identity != expected:
            raise AdapterFailureError(
                f"gpqa benchmark identity drift: expected {expected!r}, "
                f"supplied {benchmark_identity!r}",
                failure_label="runtime_config_drift",
            )
        return benchmark_identity
    try:
        return capture_gpqa_benchmark_identity(identity)
    except BenchEvalError as e:
        raise AdapterFailureError(str(e), failure_label="runtime_config_drift") from e


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _sample_totals(results: dict[str, object]) -> int | None:
    """Return a usable denominator only when completed and total agree."""
    completed_raw = results.get("completed_samples")
    total_raw = results.get("total_samples")
    completed = (
        completed_raw
        if isinstance(completed_raw, int) and not isinstance(completed_raw, bool)
        else None
    )
    total = total_raw if isinstance(total_raw, int) and not isinstance(total_raw, bool) else None
    if completed is None or total is None:
        return None
    if completed <= 0 or total <= 0 or completed != total:
        return None
    return total


def _counts_for_accuracy(accuracy: float, total: int | None) -> tuple[int | None, int | None]:
    if total is None:
        return None, None
    correct = round(accuracy * total)
    if total <= 0:
        return None, None
    if abs((correct / total) - accuracy) > 1e-9:
        return None, None
    return correct, total


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value


def _unique_sample_count(raw: dict[str, object]) -> int | None:
    eval_spec = raw.get("eval")
    if not isinstance(eval_spec, dict):
        return None
    dataset = eval_spec.get("dataset")
    if isinstance(dataset, dict):
        sample_ids = dataset.get("sample_ids")
        if isinstance(sample_ids, list) and sample_ids:
            names = [item.strip() for item in sample_ids if isinstance(item, str)]
            if len(names) == len(sample_ids) and all(names) and len(set(names)) == len(names):
                return len(names)
            return None
    config = eval_spec.get("config")
    if isinstance(config, dict):
        return _positive_int(config.get("limit"))
    return None


def _inspect_epochs(raw: dict[str, object]) -> int | None:
    eval_spec = raw.get("eval")
    if not isinstance(eval_spec, dict):
        return None
    for key in ("config", "task_args"):
        block = eval_spec.get(key)
        if not isinstance(block, dict):
            continue
        epochs = _positive_int(block.get("epochs"))
        if epochs is not None:
            return epochs
    return None


def _gpqa_official_complete(official: GpqaOfficialScore, requested: int) -> bool:
    if official.correct is None or official.total is None:
        return False
    if official.total <= 0 or official.correct > official.total:
        return False
    unique = official.unique_samples
    if unique is None:
        return official.total == requested
    if unique != requested:
        return False
    epochs = official.epochs
    if epochs is None:
        return official.total == unique
    return official.total == unique * epochs


def _score_from_inspect_results(raw: dict[str, object], *, source: str) -> GpqaOfficialScore | None:
    results = raw.get("results")
    if not isinstance(results, dict):
        return None
    scores = results.get("scores")
    if not isinstance(scores, list):
        return None
    sample_total = _sample_totals(results)
    for entry in scores:
        if not isinstance(entry, dict):
            continue
        metrics = entry.get("metrics")
        if isinstance(metrics, dict):
            for key in ("accuracy", "acc", "mean"):
                metric = metrics.get(key)
                if isinstance(metric, dict) and "value" in metric:
                    value = _as_float(metric.get("value"))
                    if value is not None and 0.0 <= value <= 1.0:
                        correct, total = _counts_for_accuracy(value, sample_total)
                        return _official_score(value, correct, total, source, raw)
                value = _as_float(metric)
                if value is not None and 0.0 <= value <= 1.0:
                    correct, total = _counts_for_accuracy(value, sample_total)
                    return _official_score(value, correct, total, source, raw)
        value = _as_float(entry.get("value"))
        if value is not None and 0.0 <= value <= 1.0:
            correct, total = _counts_for_accuracy(value, sample_total)
            return _official_score(value, correct, total, source, raw)
    return None


def _official_score(
    accuracy: float,
    correct: int | None,
    total: int | None,
    source: str,
    raw: dict[str, object],
) -> GpqaOfficialScore:
    return GpqaOfficialScore(
        accuracy,
        correct,
        total,
        source,
        unique_samples=_unique_sample_count(raw),
        epochs=_inspect_epochs(raw),
    )


def _looks_like_inspect_eval_log(
    raw: dict[str, object],
    *,
    expected_task: str,
    expected_model: str,
) -> bool:
    if raw.get("status") != "success":
        return False
    eval_spec = raw.get("eval")
    if not isinstance(eval_spec, dict):
        return False
    task = eval_spec.get("task")
    model = eval_spec.get("model")
    task_aliases = {expected_task, expected_task.rsplit("/", maxsplit=1)[-1]}
    if task not in task_aliases or model != expected_model:
        return False
    if not isinstance(raw.get("results"), dict):
        return False
    scores = raw["results"].get("scores") if isinstance(raw["results"], dict) else None
    return isinstance(scores, list)


def _load_json_object(
    path: Path,
    *,
    expected_task: str,
    expected_model: str,
    log_dir_fd: int | None = None,
) -> dict[str, object] | None:
    suffix = path.suffix.lower()
    if suffix == ".eval":
        try:
            from inspect_ai.log import read_eval_log
        except ImportError:
            return None
        try:
            log = read_eval_log(path, header_only=True)
        except (OSError, UnicodeDecodeError, ValueError, TypeError):
            return None
        dumped = json.loads(log.model_dump_json())
        return dumped if isinstance(dumped, dict) else None
    if log_dir_fd is not None:
        # Dirfd-relative, no-follow read from the pinned log-dir inode: a
        # rename-and-recreate swap of inspect-logs after the pin cannot
        # substitute a forged done-log (same-uid boundary, as in HLE).
        try:
            raw_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=log_dir_fd)
        except OSError:
            return None
        try:
            with os.fdopen(raw_fd, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            return None
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
    if suffix == ".jsonl":
        # Prefer the last JSON object that looks like an eval log.
        last: dict[str, object] | None = None
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict) and _looks_like_inspect_eval_log(
                parsed,
                expected_task=expected_task,
                expected_model=expected_model,
            ):
                last = parsed
        return last
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _log_locations_from_text(text: str) -> list[Path]:
    found: list[Path] = []
    for match in _LOG_LOCATION_RE.finditer(text):
        raw = match.group(1).strip().rstrip("]")
        if not raw:
            continue
        path = Path(raw).expanduser()
        found.append(path)
    return found


def _path_from_location(value: object) -> Path | None:
    if isinstance(value, str) and value.strip():
        return Path(value.strip()).expanduser()
    return None


def _done_log_locations(payload: dict[str, object]) -> list[Path]:
    found: list[Path] = []
    if payload.get("event") == "done":
        logs = payload.get("logs")
        if isinstance(logs, list):
            for entry in logs:
                if not isinstance(entry, dict):
                    continue
                location = _path_from_location(entry.get("location"))
                if location is not None:
                    found.append(location)
    if payload.get("type") == "done":
        tasks = payload.get("tasks")
        if isinstance(tasks, list):
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                location = _path_from_location(task.get("log_location"))
                if location is not None:
                    found.append(location)
    return found


def _log_locations_from_inspect_json(text: str) -> list[Path]:
    """Parse Inspect ``--json`` records; only done-event log locations win."""
    found: list[Path] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            found.extend(_done_log_locations(payload))
    if found:
        return found
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    return _done_log_locations(payload)


def _inspect_log_candidates(
    log_dir: Path,
    *,
    stdout: str,
    stderr: str,
) -> list[Path]:
    ordered: list[Path] = []
    seen: set[Path] = set()
    root = log_dir.resolve()

    def _add(path: Path) -> None:
        candidate = path if path.is_absolute() else log_dir / path
        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            return
        if resolved in seen or not resolved.is_file():
            return
        seen.add(resolved)
        ordered.append(resolved)

    # Machine-readable done records own scoring identity when present.
    json_owned = _log_locations_from_inspect_json(stdout)
    if json_owned:
        for path in json_owned:
            _add(path)
        return ordered

    for text in (stdout, stderr):
        for path in _log_locations_from_text(text):
            _add(path)
    # Live runs require Inspect to name the current log; never scan stale files.
    return ordered


def parse_gpqa_official_score(
    log_dir: Path,
    *,
    expected_model: str | None = None,
    expected_task: str = _INSPECT_TASK,
    stdout: str = "",
    stderr: str = "",
    log_dir_fd: int | None = None,
) -> GpqaOfficialScore | None:
    """Extract official accuracy from Inspect eval logs only.

    Operator-authored ``official_scores.json`` is never pass-authoritative.
    When ``log_dir_fd`` is set, direct-child log files are read dirfd-relative
    and no-follow from that pinned inode (the honest boundary is a same-uid
    mutator racing after the pin); nested or non-child candidates keep the
    pathname fallback. Carve-out: ``.eval`` candidates are always read via
    unpinned pathname because ``inspect_ai.read_eval_log`` requires a path —
    they are unreachable in the executor path (``build_gpqa_run_command``
    forces ``--log-format json``), so dirfd pinning applies to JSON
    candidates only.
    """
    if expected_model is None:
        return None
    pinned_root: Path | None = None
    if log_dir_fd is not None:
        try:
            pinned_root = log_dir.resolve()
        except OSError:
            pinned_root = None
    for path in _inspect_log_candidates(log_dir, stdout=stdout, stderr=stderr):
        candidate = path
        if not candidate.is_file() and not candidate.is_absolute():
            alt = log_dir / candidate
            if alt.is_file():
                candidate = alt
        if not candidate.is_file():
            continue
        # Never treat the operator override filename as an Inspect log.
        if candidate.name == _OFFICIAL_SCORES_NAME:
            continue
        candidate_fd = (
            log_dir_fd if pinned_root is not None and candidate.parent == pinned_root else None
        )
        parsed = _load_json_object(
            candidate,
            expected_task=expected_task,
            expected_model=expected_model,
            log_dir_fd=candidate_fd,
        )
        if parsed is None or not _looks_like_inspect_eval_log(
            parsed,
            expected_task=expected_task,
            expected_model=expected_model,
        ):
            continue
        score = _score_from_inspect_results(parsed, source=str(candidate))
        if score is not None:
            return score
    return None


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
    env: Mapping[str, str],
) -> GpqaCliResult:
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
            env=dict(env),
        )
    except subprocess.TimeoutExpired as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"inspect eval timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"gpqa_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"inspect eval launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"gpqa_command": " ".join(command)},
        ) from e
    return GpqaCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def run_gpqa_slice(
    *,
    plan: RunPlan,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: GpqaProcessRunner | None = None,
    timeout_sec: int | None = None,
    benchmark_identity: str | None = None,
) -> list[GpqaInstanceOutcome]:
    """Run one Inspect eval; score only from official log metrics, never exit code."""
    if plan.adapter_id != GPQA_ADAPTER_ID:
        raise BenchEvalError(f"gpqa adapter cannot run adapter_id={plan.adapter_id!r}")
    for inst in plan.instances:
        validate_control_plane_instance_id(inst.instance_id)
    log_dir = artifacts_dir / "inspect-logs"
    # Pin both directory inodes before launching Inspect (open_owned_dir_fd
    # also creates them): every BenchEval-owned write and the scored done-log
    # read below are anchored to these descriptors, and the post-run identity
    # checks prove the paths still name the pinned inodes. Both opens live
    # inside the try so a failing second open can never leak the first fd.
    artifacts_fd: int | None = None
    log_fd: int | None = None
    try:
        artifacts_fd = open_owned_dir_fd(artifacts_dir, role="gpqa artifacts directory")
        log_fd = open_owned_dir_fd(log_dir, role="gpqa inspect log directory")
        command = build_gpqa_run_command(
            plan=plan,
            sample_limit=len(plan.instances),
            log_dir=log_dir,
        )
        effective_model = command[command.index("--model") + 1]
        launch = resolve_openai_compatible_launch(
            plan.provider_id,
            require_api_key=process_runner is None,
        )
        # Identity gate BEFORE any launch: verify the pinned dist/eval/CSV bytes
        # (or validate a test-boundary-supplied identity); drift aborts here.
        benchmark_version = _gpqa_prelaunch_benchmark_identity(
            plan=plan,
            process_runner=process_runner,
            benchmark_identity=benchmark_identity,
        )
        # Aggregate harness: one Inspect eval covers every sample in a single
        # subprocess, so the run-total envelope is the only honest bound; no
        # per-instance limit is enforceable inside the aggregate process.
        wall = timeout_sec if timeout_sec is not None else max(1, plan.max_wall_clock_sec)
        runner = process_runner or _default_process_runner
        cli = runner(command, cwd=repo_root, timeout_sec=wall, env=launch.environment)

        artifacts_identity_error = dir_identity_error(
            artifacts_fd,
            artifacts_dir,
            role="gpqa artifacts directory",
        )
        if artifacts_identity_error is not None:
            # The launched subprocess (handed --log-dir under this tree)
            # swapped the approved directory mid-run; fail closed instead of
            # publishing attacker-controlled content.
            raise AdapterFailureError(
                artifacts_identity_error,
                failure_label="evidence_corrupt",
                latency_sec=cli.latency_sec,
                adapter_metadata={"gpqa_command": " ".join(cli.command)},
            )

        log_identity_error = dir_identity_error(
            log_fd,
            log_dir,
            role="gpqa inspect log directory",
        )
        if log_identity_error is not None:
            # The launched subprocess (handed --log-dir) swapped the log
            # directory mid-run; fail closed instead of scoring a planted
            # done-log.
            raise AdapterFailureError(
                log_identity_error,
                failure_label="evidence_corrupt",
                latency_sec=cli.latency_sec,
                adapter_metadata={"gpqa_command": " ".join(cli.command)},
            )

        stdout_file = artifacts_dir / "stdout.log"
        stderr_file = artifacts_dir / "stderr.log"
        # Anchored, no-follow, exclusive recreates: a symlink or hard link
        # planted at these paths by the subprocess is unlinked (never opened,
        # truncated, or followed) and replaced by a fresh regular file.
        write_text_at_exclusive(artifacts_fd, "stdout.log", cli.stdout)
        write_text_at_exclusive(artifacts_fd, "stderr.log", cli.stderr)

        # Re-verify immediately before the scored read: no subprocess runs
        # between the post-run check and parse, so this narrows the swap
        # window to the dirfd-pinned read itself.
        log_identity_error = dir_identity_error(
            log_fd,
            log_dir,
            role="gpqa inspect log directory",
        )
        if log_identity_error is not None:
            raise AdapterFailureError(
                log_identity_error,
                failure_label="evidence_corrupt",
                latency_sec=cli.latency_sec,
                adapter_metadata={"gpqa_command": " ".join(cli.command)},
            )
        official = (
            parse_gpqa_official_score(
                log_dir,
                expected_model=effective_model,
                stdout=cli.stdout,
                stderr=cli.stderr,
                log_dir_fd=log_fd,
            )
            if cli.returncode == 0
            else None
        )
        if cli.returncode != 0:
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
            complete = _gpqa_official_complete(official, requested)
            primary_pass = bool(
                complete and official.accuracy >= 1.0 and official.correct == official.total,
            )
            counts = complete
            if not complete:
                failure = "runtime_output_unparseable"
                primary_pass = False
            else:
                failure = None if primary_pass else "model_wrong_solution"

        write_text_at_exclusive(
            artifacts_fd,
            "gpqa_summary.json",
            json.dumps(
                {
                    "returncode": cli.returncode,
                    "limit": len(plan.instances),
                    "official_score": (
                        None
                        if official is None
                        else {
                            "accuracy": official.accuracy,
                            "correct": official.correct,
                            "total": official.total,
                            "unique_samples": official.unique_samples,
                            "epochs": official.epochs,
                            "source": official.source,
                        }
                    ),
                    "primary_pass": primary_pass,
                    "partial_score": partial_score,
                    "counts_toward_pass_at_k": counts,
                },
                indent=2,
            )
            + "\n",
        )
        # Final identity checks immediately before outcome stamping (F108
        # parity): the scored read was dirfd-pinned, but verifier/native paths
        # below stamp pathnames — fail closed if either pinned inode was
        # swapped anywhere in the post-parse window.
        log_identity_final = dir_identity_error(
            log_fd,
            log_dir,
            role="gpqa inspect log directory",
        )
        if log_identity_final is not None:
            raise AdapterFailureError(
                log_identity_final,
                failure_label="evidence_corrupt",
                latency_sec=cli.latency_sec,
                adapter_metadata={"gpqa_command": " ".join(cli.command)},
            )
        artifacts_identity_final = dir_identity_error(
            artifacts_fd,
            artifacts_dir,
            role="gpqa artifacts directory",
        )
        if artifacts_identity_final is not None:
            raise AdapterFailureError(
                artifacts_identity_final,
                failure_label="evidence_corrupt",
                latency_sec=cli.latency_sec,
                adapter_metadata={"gpqa_command": " ".join(cli.command)},
            )
        harness_version = _inspect_evals_harness_version()
        meta = {
            "adapter_id": GPQA_ADAPTER_ID,
            "harness_kind": "inspect-evals",
            "gpqa_command": " ".join(cli.command),
            "interpretation": "adapter_smoke",
            "score_source": official.source if official is not None else "missing",
            "evidence_shape": "aggregate_slice",
            "effective_model_id": effective_model,
            "provider_config_hash": launch.config_hash,
            # One aggregate subprocess: per-instance wall is not enforceable.
            "per_instance_wall_enforcement": "unavailable_aggregate_harness",
        }
        if harness_version is not None:
            meta["harness_version"] = harness_version
        if benchmark_version is not None:
            meta["benchmark_version"] = benchmark_version
        shared_native: dict[str, object] = {
            "returncode": cli.returncode,
            "inspect_task": _INSPECT_TASK,
            "effective_model_id": effective_model,
            "planned_sample_slots": len(plan.instances),
        }
        if official is not None:
            shared_native.update(
                {
                    "accuracy": official.accuracy,
                    "correct": official.correct,
                    "total": official.total,
                    "unique_samples": official.unique_samples,
                    "epochs": official.epochs,
                    "score_source": official.source,
                },
            )
        # Aggregate official metrics only: one evidence row (not N fake per-sample passes).
        # cost_usd=0.0 below means "no provider metering captured", not zero spend.
        shared_native["cost_basis"] = "unmeasured_no_provider_metering"
        aggregate_id = f"{plan.benchmark_id}-{plan.slice_id}-aggregate"
        validate_control_plane_instance_id(aggregate_id)
        # Summary alone is not a native verifier artifact — only Inspect log paths stamp.
        verifier_path = official.source if official is not None else None
        return [
            GpqaInstanceOutcome(
                instance_id=aggregate_id,
                primary_pass=primary_pass,
                partial_score=partial_score,
                cost_usd=0.0,
                latency_sec=cli.latency_sec,
                native_score=shared_native,
                failure_class=failure,
                stdout_path=str(stdout_file.resolve()),
                stderr_path=str(stderr_file.resolve()),
                verifier_log_path=verifier_path,
                adapter_metadata={
                    **meta,
                    "cost_cap": "unenforced_estimate",
                    "reported_cost_usd": "unavailable",
                },
                counts_toward_pass_at_k=counts,
            ),
        ]
    finally:
        if log_fd is not None:
            os.close(log_fd)
        if artifacts_fd is not None:
            os.close(artifacts_fd)


__all__ = [
    "GPQA_ADAPTER_ID",
    "GpqaCliResult",
    "GpqaInstanceOutcome",
    "GpqaOfficialScore",
    "GpqaProcessRunner",
    "build_gpqa_run_command",
    "capture_gpqa_benchmark_identity",
    "gpqa_csv_cache_path",
    "parse_gpqa_official_score",
    "run_gpqa_slice",
    "verify_gpqa_csv_cache",
]
