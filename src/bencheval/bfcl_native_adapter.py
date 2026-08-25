"""BFCL v4 model-only adapter (``bfcl generate`` → ``bfcl evaluate`` lifecycle).

Native scoring authority is the official ``bfcl evaluate`` score artifact at
``<score-dir>/<model>/non_live/BFCL_v4_<category>_score.json`` (JSONL: summary
header first, then one row per FAILED case); generation-side files
(``verdict.json``/``result.json``) are never consulted for the verdict.
BFCL is admitted (``executable: true``) since 2026-08-24, on the dev-box
lifecycle demonstration ``run-20260824-040631-228703-4756f857``
(diagnostic-labeled, operator-reviewed) plus the registered ``passed`` run
``run-20260824-045622-854659-a46ae44d``; the CLI
refuses ``--diagnostic`` for this now-executable row, and diagnostic-labeled
evidence never registers ``passed``.

Pinned upstream source of truth: gorilla commit
``6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`` (paths rooted at
``berkeley-function-call-leaderboard/bfcl_eval/``):

- ``utils.py:463-490`` ``write_list_of_dicts_to_file`` writes
  ``json.dumps(entry) + "\\n"`` per entry — JSONL, not a JSON array.
- ``eval_checker/eval_runner_helper.py:164-189`` ``save_eval_results`` inserts
  the header (``accuracy``/``correct_count``/``total_count``) at line 0 and
  names the file ``BFCL_v4_<category>_score.json``.
- ``eval_checker/eval_runner.py`` records ONLY failed cases after the header
  (a perfect run is a header-only one-line file), resolves model directories
  as ``model_name.replace("/", "_")``, and raises ``ValueError`` for models
  outside ``MODEL_CONFIG_MAPPING`` — mirrored here by the supported-model
  manifest gate in :func:`run_bfcl_instance`.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import stat
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import Protocol

import yaml

from bencheval.backends import INSPECT_BACKEND
from bencheval.benchmark_registry import BfclPackageDataIdentity
from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.provider_registry import resolve_openai_compatible_launch
from bencheval.run_isolation import (
    AUTHORITATIVE_ARTIFACT_NAMES,
    dir_identity_error,
    open_owned_dir_fd,
    prepare_instance_artifacts_dir,
    write_text_at_exclusive,
)

BFCL_ADAPTER_ID = "bfcl"
BFCL_COMMAND = "bfcl"
_BFCL_DIST_CANDIDATES = ("bfcl-eval", "bfcl")
_VERSION_TIMEOUT_SEC = 15
_UPSTREAM_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
_SCORE_FILE_PREFIX = "BFCL_v4"
_SUPPORTED_MODELS_MANIFEST = Path("config") / "bfcl-v4-supported-models.yaml"
# Hosted-model generation defaults to 1 thread upstream; bounded concurrency is
# required to finish a category inside the slice's per-instance wall cap. The
# effective value is stamped explicitly into evidence metadata.
_NUM_THREADS_ENV = "BENCHEVAL_BFCL_NUM_THREADS"
_DEFAULT_NUM_THREADS = 16
_MAX_NUM_THREADS = 48


def bfcl_harness_version() -> str | None:
    """Capture installed BFCL CLI/package revision; None when capture fails."""
    for dist in _BFCL_DIST_CANDIDATES:
        try:
            return f"{dist}@{distribution_version(dist)}"
        except PackageNotFoundError:
            continue
    if shutil.which(BFCL_COMMAND) is not None:
        try:
            proc = subprocess.run(
                [BFCL_COMMAND, "version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=_VERSION_TIMEOUT_SEC,
            )
        except (OSError, subprocess.TimeoutExpired):
            proc = None
        if proc is not None and proc.returncode == 0:
            line = (proc.stdout or proc.stderr).strip().splitlines()
            if line and line[0].strip():
                return line[0].strip()
    return None


@dataclass(frozen=True, slots=True)
class BfclCliResult:
    returncode: int
    stdout: str
    stderr: str
    latency_sec: float
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BfclInstanceOutcome:
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


class BfclProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult: ...


def _require_model_only(plan: RunPlan) -> None:
    if plan.runtime_id is not None:
        raise BenchEvalError(
            f"bfcl adapter expects model-only (runtime_id=None), got {plan.runtime_id!r}",
        )
    if plan.agent_id is not None:
        raise BenchEvalError(
            f"bfcl adapter expects model-only (agent_id=None), got {plan.agent_id!r}",
        )


def _bfcl_num_threads() -> int:
    raw = os.environ.get(_NUM_THREADS_ENV)
    if raw is None:
        return _DEFAULT_NUM_THREADS
    try:
        value = int(raw.strip())
    except ValueError as e:
        raise BenchEvalError(
            f"{_NUM_THREADS_ENV} must be an integer between 1 and "
            f"{_MAX_NUM_THREADS} inclusive, got {raw!r}",
        ) from e
    if not 1 <= value <= _MAX_NUM_THREADS:
        raise BenchEvalError(
            f"{_NUM_THREADS_ENV} must be an integer between 1 and "
            f"{_MAX_NUM_THREADS} inclusive, got {raw!r}",
        )
    return value


def build_bfcl_run_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[str, ...]:
    validate_control_plane_instance_id(instance_id)
    _require_model_only(plan)
    cmd: list[str] = [
        BFCL_COMMAND,
        "generate",
        "--test-category",
        instance_id,
        "--result-dir",
        str(artifacts_dir.resolve()),
        "--allow-overwrite",
        "--num-threads",
        str(_bfcl_num_threads()),
    ]
    if plan.model_id != "runtime-default":
        cmd.extend(["--model", plan.model_id])
    return tuple(cmd)


def build_bfcl_evaluate_command(
    *,
    plan: RunPlan,
    instance_id: str,
    result_dir: Path,
    score_dir: Path,
) -> tuple[str, ...]:
    """Official scoring phase: evaluate the generated output in ``result_dir``.

    ``--result-dir`` must match the generate phase's result directory exactly;
    ``--score-dir`` receives the official score artifacts that are the ONLY
    scoring authority for the instance outcome.
    """
    validate_control_plane_instance_id(instance_id)
    _require_model_only(plan)
    cmd: list[str] = [
        BFCL_COMMAND,
        "evaluate",
        "--test-category",
        instance_id,
        "--result-dir",
        str(result_dir.resolve()),
        "--score-dir",
        str(score_dir.resolve()),
    ]
    if plan.model_id != "runtime-default":
        cmd.extend(["--model", plan.model_id])
    return tuple(cmd)


def _bfcl_command_metadata(command: Sequence[str]) -> dict[str, str]:
    metadata = {"bfcl_command": " ".join(command)}
    try:
        num_threads = command[command.index("--num-threads") + 1]
    except (ValueError, IndexError):
        return metadata
    metadata["bfcl_num_threads"] = num_threads
    return metadata


def _default_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
    env: Mapping[str, str],
) -> BfclCliResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env),
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
            f"bfcl harness timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata=_bfcl_command_metadata(command),
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"bfcl harness launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata=_bfcl_command_metadata(command),
        ) from e
    return BfclCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(command),
    )


def _rel_path(path: str, repo_root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(repo_root))
    except ValueError:
        return path


def _load_supported_models_manifest() -> tuple[frozenset[str], str]:
    """Return supported models plus the exact allowed ``bfcl-eval`` version.

    Loaded from ``config/bfcl-v4-supported-models.yaml`` at the BenchEval
    config root (NOT the run's working directory): the manifest pins the
    upstream ``MODEL_CONFIG_MAPPING`` revision this gate mirrors.
    """
    from bencheval.paths import repo_root as config_repo_root

    manifest_path = config_repo_root() / _SUPPORTED_MODELS_MANIFEST
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8-sig"))
    except OSError as e:
        raise BenchEvalError(f"cannot read {manifest_path}: {e}") from e
    except yaml.YAMLError as e:
        raise BenchEvalError(f"{manifest_path.name}: invalid YAML: {e}") from e
    if not isinstance(raw, dict) or not isinstance(raw.get("models"), list):
        raise BenchEvalError(f"{manifest_path.name}: must map 'models' to a list of model ids")
    models = raw["models"]
    if not models or not all(isinstance(m, str) and m.strip() for m in models):
        raise BenchEvalError(f"{manifest_path.name}: 'models' must be non-empty model id strings")
    for pinned in ("upstream_commit", "bfcl_eval_version"):
        if not isinstance(raw.get(pinned), str) or not raw[pinned].strip():
            raise BenchEvalError(f"{manifest_path.name}: missing required pin {pinned!r}")
    upstream_commit = raw["upstream_commit"].strip()
    if upstream_commit != _UPSTREAM_COMMIT:
        raise BenchEvalError(
            f"{manifest_path.name}: upstream_commit {upstream_commit!r} does not match "
            f"the adapter source pin {_UPSTREAM_COMMIT!r}",
        )
    return frozenset(m.strip() for m in models), raw["bfcl_eval_version"].strip()


def bfcl_supported_models() -> frozenset[str]:
    """Model ids the pinned upstream BFCL evaluate path can score."""
    models, _ = _load_supported_models_manifest()
    return models


def bfcl_pinned_harness_version() -> str:
    """Manifest-pinned harness version label: ``bfcl-eval@<bfcl_eval_version>``."""
    _, pinned = _load_supported_models_manifest()
    return f"bfcl-eval@{pinned}"


def _require_pinned_harness_version(
    *,
    pinned_version: str,
    captured_version: str | None,
) -> str:
    effective = captured_version or bfcl_harness_version()
    expected = f"bfcl-eval@{pinned_version}"
    if effective != expected:
        raise BenchEvalError(
            "bfcl harness does not match the manifest bfcl_eval_version pin: "
            f"expected {expected!r}, captured {effective!r}",
        )
    return effective


# --- Pinned package-data identity (catalog ``identity:`` block) -------------


def _bfcl_package_root() -> Path:
    """Install location of the pinned ``bfcl_eval`` package (fail closed)."""
    import importlib.util

    spec = importlib.util.find_spec("bfcl_eval")
    locations = None if spec is None else spec.submodule_search_locations
    if not locations:
        raise BenchEvalError(
            "bfcl identity verification requires the bfcl-eval distribution to be installed",
        )
    return Path(locations[0])


def verify_bfcl_package_data(*, package_root: Path, files: Mapping[str, str]) -> None:
    """sha256-check every pinned data file inside the installed package.

    Pure verification core: local package root in, digest compare against the
    pin; a missing, symlinked, or drifted file fails closed.
    """
    from bencheval.identity_strings import file_sha256

    for relpath, pin in sorted(files.items()):
        target = package_root / relpath
        if target.is_symlink() or not target.is_file():
            raise BenchEvalError(f"bfcl package data file missing or not a plain file: {target}")
        actual = f"sha256:{file_sha256(target)}"
        if actual != pin:
            raise BenchEvalError(
                f"bfcl package data sha256 drift at {target}: expected {pin}, got {actual}",
            )


def capture_bfcl_benchmark_identity(
    identity: BfclPackageDataIdentity,
    *,
    package_root: Path | None = None,
) -> str:
    """Verify the pinned package data bytes, then return the identity string.

    The installed-distribution version check stays with
    ``_require_pinned_harness_version`` (already on the run path); this capture
    adds the data-file binding on top.
    """
    from bencheval.identity_strings import bfcl_benchmark_identity

    root = package_root if package_root is not None else _bfcl_package_root()
    verify_bfcl_package_data(package_root=root, files=identity.files)
    return bfcl_benchmark_identity(identity)


def _bfcl_prelaunch_benchmark_identity(
    *,
    plan: RunPlan,
    process_runner: BfclProcessRunner | None,
    benchmark_identity: str | None,
) -> str | None:
    """Fail closed before launch when the catalog pins a benchmark identity.

    The real/default runner always verifies the installed package data bytes
    against the pin. A supplied identity belongs to an injected runner's
    controlled test boundary and must equal the config-derived expectation.
    """
    from bencheval.identity_strings import bfcl_benchmark_identity, catalog_benchmark_identity

    identity = catalog_benchmark_identity(plan.benchmark_id)
    if identity is None:
        return None
    if not isinstance(identity, BfclPackageDataIdentity):
        raise BenchEvalError(f"bfcl benchmark identity kind drift: {identity.kind!r}")
    expected = bfcl_benchmark_identity(identity)
    if process_runner is not None:
        if benchmark_identity is None:
            return None
        if benchmark_identity != expected:
            raise BenchEvalError(
                f"bfcl benchmark identity drift: expected {expected!r}, "
                f"supplied {benchmark_identity!r}",
            )
        return benchmark_identity
    return capture_bfcl_benchmark_identity(identity)


@dataclass(frozen=True, slots=True)
class _ScoreCandidate:
    """Located score artifact whose inode stays pinned by an open descriptor."""

    path: Path
    identity: tuple[int, int]
    descriptor: int


def _close_score_candidates(candidates: Sequence[_ScoreCandidate]) -> None:
    for candidate in candidates:
        try:
            os.close(candidate.descriptor)
        except OSError:
            # Cleanup must not replace the evidence-integrity failure that led
            # here; the process will reclaim an already-invalid descriptor.
            pass


def _find_official_score_candidates(
    *,
    score_dir: Path,
    model_id: str,
    instance_id: str,
) -> list[_ScoreCandidate]:
    """Exact-name official artifacts under the normalized model directory.

    Upstream resolves the directory as ``model_name.replace("/", "_")`` and the
    filename as ``BFCL_v4_<category>_score.json``; the intermediate directory
    group (``non_live``/``live``/...) is category-derived, so the search is an
    exact-name walk instead of a hardcoded group. Each match is ``lstat``-bound:
    anything that is not a plain regular file (a symlink planted at the exact
    score name included) is rejected here instead of being followed.
    """
    model_root = score_dir / model_id.replace("/", "_")
    if not model_root.is_dir():
        return []
    target = f"{_SCORE_FILE_PREFIX}_{instance_id}_score.json"
    try:
        matches = sorted(p for p in model_root.rglob(target) if p.is_file())
    except OSError as e:
        raise AdapterFailureError(
            f"bfcl score directory unreadable under {model_root}: {e}",
            failure_label="evidence_corrupt",
        ) from e
    candidates: list[_ScoreCandidate] = []
    for path in matches:
        descriptor: int | None = None
        try:
            info = os.lstat(path)
            descriptor = os.open(
                path,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            )
            opened = os.fstat(descriptor)
        except OSError as e:
            if descriptor is not None:
                os.close(descriptor)
            _close_score_candidates(candidates)
            raise AdapterFailureError(
                f"bfcl score artifact cannot be pinned after locate: {path}: {e}",
                failure_label="evidence_corrupt",
            ) from e
        identity = (info.st_dev, info.st_ino)
        if (
            not stat.S_ISREG(info.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != identity
        ):
            os.close(descriptor)
            _close_score_candidates(candidates)
            raise AdapterFailureError(
                f"bfcl score artifact is not a stable plain file: {path}",
                failure_label="evidence_corrupt",
            )
        candidates.append(_ScoreCandidate(path=path, identity=identity, descriptor=descriptor))
    return candidates


def _open_nofollow_child_dir_fd(parent_fd: int, name: str, *, role: str) -> int:
    """Open the child directory ``name`` beneath ``parent_fd`` (no symlinks)."""
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as e:
        raise AdapterFailureError(
            f"bfcl score artifact path component {name!r} unreadable ({role}): {e}",
            failure_label="evidence_corrupt",
        ) from e


def _read_score_candidate_bytes(
    *,
    score_root_fd: int,
    score_dir: Path,
    candidate: _ScoreCandidate,
) -> bytes:
    """Read the located artifact through anchored, no-follow path resolution.

    The walk never leaves the pinned ``score_root_fd`` tree and never follows a
    symlink; the opened inode must equal the identity recorded at locate time,
    and the pathname must still name that same inode after the read. Any
    mismatch means a same-uid mutator swapped the artifact and its bytes can
    never be scored.
    """
    rel = candidate.path.relative_to(score_dir)
    dir_fd = os.dup(score_root_fd)
    try:
        for part in rel.parts[:-1]:
            child_fd = _open_nofollow_child_dir_fd(dir_fd, part, role="bfcl score directory")
            os.close(dir_fd)
            dir_fd = child_fd
        try:
            file_fd = os.open(rel.parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        except OSError as e:
            raise AdapterFailureError(
                f"bfcl score artifact unreadable: {candidate.path}: {e}",
                failure_label="evidence_corrupt",
            ) from e
        try:
            opened = os.fstat(file_fd)
        except OSError as e:
            os.close(file_fd)
            raise AdapterFailureError(
                f"bfcl score artifact unreadable: {candidate.path}: {e}",
                failure_label="evidence_corrupt",
            ) from e
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != candidate.identity:
            os.close(file_fd)
            raise AdapterFailureError(
                f"bfcl score artifact replaced after locate: {candidate.path}",
                failure_label="evidence_corrupt",
            )
        try:
            handle = os.fdopen(file_fd, "rb")
        except OSError as e:
            # fdopen failed before taking ownership: close fd so it never leaks.
            os.close(file_fd)
            raise AdapterFailureError(
                f"bfcl score artifact unreadable: {candidate.path}: {e}",
                failure_label="evidence_corrupt",
            ) from e
        try:
            with handle:
                data = handle.read()
        except OSError as e:
            raise AdapterFailureError(
                f"bfcl score artifact unreadable: {candidate.path}: {e}",
                failure_label="evidence_corrupt",
            ) from e
    finally:
        os.close(dir_fd)
    try:
        confirm = os.lstat(candidate.path)
    except OSError as e:
        raise AdapterFailureError(
            f"bfcl score artifact vanished during read: {candidate.path}: {e}",
            failure_label="evidence_corrupt",
        ) from e
    if (confirm.st_dev, confirm.st_ino) != candidate.identity:
        raise AdapterFailureError(
            f"bfcl score artifact replaced during read: {candidate.path}",
            failure_label="evidence_corrupt",
        )
    return data


def _parse_official_score(text: bytes) -> tuple[bool, float] | None:
    """Official BFCL v4 score artifact bytes → (primary_pass, partial_score); None when unparseable.

    Pinned upstream layout: JSONL, one object per line. Line 0 is the summary
    header (``{"accuracy": float, "correct_count": int, "total_count": int}``);
    every later line is one FAILED case (``{"id": str, "valid": false, ...}``).
    A perfect run is a header-only one-line file. The artifact is coherent only
    when the counts and accuracy agree and the failure rows number exactly
    ``total_count - correct_count`` with unique ids; anything else fails closed
    and can never grant a pass.
    """
    try:
        decoded = text.decode("utf-8")
    except UnicodeDecodeError:
        return None
    rows: list[object] = []
    for line in decoded.splitlines():
        if not line.strip():
            return None
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            return None
    if not rows:
        return None
    header, *failure_rows = rows
    if not isinstance(header, dict):
        return None
    accuracy = header.get("accuracy")
    correct_count = header.get("correct_count")
    total_count = header.get("total_count")
    if isinstance(accuracy, bool) or not isinstance(accuracy, (int, float)):
        return None
    accuracy = float(accuracy)
    if not math.isfinite(accuracy) or not 0.0 <= accuracy <= 1.0:
        return None
    for count in (correct_count, total_count):
        if isinstance(count, bool) or not isinstance(count, int):
            return None
    if total_count < 1 or not 0 <= correct_count <= total_count:
        return None
    if abs(accuracy - correct_count / total_count) > 1e-9:
        return None
    seen_ids: set[str] = set()
    for row in failure_rows:
        if not isinstance(row, dict):
            return None
        # Upstream records ONLY failed cases; a pass-bearing or mistyped row
        # is not the official artifact shape.
        if row.get("valid") is not False:
            return None
        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id or case_id in seen_ids:
            return None
        seen_ids.add(case_id)
    if len(failure_rows) != total_count - correct_count:
        return None
    return correct_count == total_count, accuracy


def parse_bfcl_instance_outcome(
    *,
    instance_id: str,
    cli: BfclCliResult,
    artifacts_dir: Path,
    repo_root: Path,
    harness_version: str | None,
    score_dir: Path,
    model_id: str,
    latency_sec: float | None = None,
    benchmark_version: str | None = None,
    num_threads: int | None = None,
) -> BfclInstanceOutcome:
    """Score one instance from the official ``bfcl evaluate`` artifact only.

    ``cli`` is the evaluate-phase process result (or the generate-phase result
    when generation failed before evaluate ran). Generation-side files under
    the result directory (``verdict.json``/``result.json``) are harness scratch
    output and are never consulted for the verdict.
    """
    instance_fd = open_owned_dir_fd(artifacts_dir, role="bfcl instance artifacts directory")
    try:
        # Anchored, attacker-entry-replacing writes: a planted stdout.log /
        # stderr.log symlink or hard link can never redirect these bytes.
        write_text_at_exclusive(instance_fd, "stdout.log", cli.stdout)
        write_text_at_exclusive(instance_fd, "stderr.log", cli.stderr)
    finally:
        os.close(instance_fd)
    stdout_file = artifacts_dir / "stdout.log"
    stderr_file = artifacts_dir / "stderr.log"
    stdout_rel = str(stdout_file.resolve())
    stderr_rel = str(stderr_file.resolve())

    native: dict[str, object] = {"returncode": cli.returncode, "backend": INSPECT_BACKEND}
    primary_pass = False
    partial_score = 0.0
    failure_class: FailureLabel | None = None
    cost_usd = 0.0
    # cost_usd=0.0 means "no provider metering captured" (the bfcl CLI reports
    # no cost), not zero spend — mirror of the hle stamp.
    native["cost_basis"] = "unmeasured_no_provider_metering"
    verifier_path: str | None = None

    if cli.returncode != 0:
        failure_class = "harness_failure"
    else:
        candidates: list[_ScoreCandidate] = []
        try:
            candidates = _find_official_score_candidates(
                score_dir=score_dir,
                model_id=model_id,
                instance_id=instance_id,
            )
        except AdapterFailureError:
            # A tampered or unreadable score tree can never grant a verdict;
            # it fails closed as corrupt evidence instead of propagating.
            candidates = []
            failure_class = "evidence_corrupt"
        try:
            if not candidates:
                # Evaluate exited 0 without writing the official score artifact.
                if failure_class is None:
                    failure_class = "harness_failure"
            elif len(candidates) > 1:
                # Duplicate exact-name artifacts cannot be disambiguated; scoring
                # either would be an invented verdict.
                failure_class = "runtime_output_unparseable"
            else:
                candidate = candidates[0]
                score_fd = open_owned_dir_fd(score_dir, role="bfcl evaluate score directory")
                try:
                    score_bytes = _read_score_candidate_bytes(
                        score_root_fd=score_fd,
                        score_dir=score_dir,
                        candidate=candidate,
                    )
                except AdapterFailureError:
                    # Locate→read swap: the bytes cannot be trusted, so no verdict.
                    failure_class = "evidence_corrupt"
                else:
                    verifier_path = str(candidate.path.resolve())
                    score = _parse_official_score(score_bytes)
                    if score is None:
                        failure_class = "runtime_output_unparseable"
                    else:
                        primary_pass, partial_score = score
                        native["accuracy"] = partial_score
                        native["score_file"] = verifier_path
                finally:
                    os.close(score_fd)
        finally:
            _close_score_candidates(candidates)

    if not primary_pass and failure_class is None:
        failure_class = "model_wrong_solution"

    metadata = _bfcl_command_metadata(cli.command)
    metadata.update(
        {
            "adapter_id": BFCL_ADAPTER_ID,
            "harness_kind": "bfcl-native",
        },
    )
    if harness_version:
        metadata["harness_version"] = harness_version
    if benchmark_version:
        metadata["benchmark_version"] = benchmark_version
    if num_threads is not None:
        metadata["bfcl_num_threads"] = str(num_threads)

    return BfclInstanceOutcome(
        instance_id=instance_id,
        primary_pass=primary_pass,
        partial_score=partial_score,
        cost_usd=cost_usd,
        latency_sec=cli.latency_sec if latency_sec is None else latency_sec,
        native_score=native,
        failure_class=failure_class,
        stdout_path=_rel_path(stdout_rel, repo_root),
        stderr_path=_rel_path(stderr_rel, repo_root),
        verifier_log_path=_rel_path(verifier_path, repo_root) if verifier_path else None,
        adapter_metadata=metadata,
    )


def _raise_on_dir_drift(pins: Sequence[tuple[int, Path, str]]) -> None:
    """Fail closed when any pinned directory path no longer names its inode."""
    for fd, path, role in pins:
        error = dir_identity_error(fd, path, role=role)
        if error is not None:
            raise AdapterFailureError(error, failure_label="evidence_corrupt")


def _reverify_bfcl_package_data(
    *,
    plan: RunPlan,
    process_runner: BfclProcessRunner | None,
) -> None:
    """Re-verify the pinned package data bytes around the evaluate phase.

    The evaluate phase consumes mutable ``possible_answer`` bytes from the
    installed package; a same-uid mutator rewriting them between the pre-launch
    gate and scoring must fail closed as ``runtime_config_drift``. An injected
    runner owns its controlled boundary and skips verification when the
    ``bfcl_eval`` package is not installed (the pre-launch gate already bound
    the supplied identity to the catalog pin).
    """
    from bencheval.identity_strings import catalog_benchmark_identity

    identity = catalog_benchmark_identity(plan.benchmark_id)
    if identity is None:
        return
    if not isinstance(identity, BfclPackageDataIdentity):
        raise AdapterFailureError(
            f"bfcl benchmark identity kind drift: {identity.kind!r}",
            failure_label="runtime_config_drift",
        )
    try:
        package_root = _bfcl_package_root()
    except BenchEvalError as e:
        if process_runner is not None:
            return
        raise AdapterFailureError(str(e), failure_label="runtime_config_drift") from e
    try:
        verify_bfcl_package_data(package_root=package_root, files=identity.files)
    except BenchEvalError as e:
        raise AdapterFailureError(str(e), failure_label="runtime_config_drift") from e


def run_bfcl_instance(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    repo_root: Path,
    process_runner: BfclProcessRunner | None = None,
    timeout_sec: int | None = None,
    harness_version: str | None = None,
    benchmark_identity: str | None = None,
) -> BfclInstanceOutcome:
    if plan.adapter_id != BFCL_ADAPTER_ID:
        raise BenchEvalError(f"bfcl adapter cannot run adapter_id={plan.adapter_id!r}")
    validate_control_plane_instance_id(instance_id)
    # Resolve the provider launch environment before any artifact or subprocess:
    # the real runner refuses to launch a charged call without the credential.
    launch = resolve_openai_compatible_launch(
        plan.provider_id,
        require_api_key=process_runner is None,
    )
    supported_models, pinned_harness_version = _load_supported_models_manifest()
    if plan.model_id not in supported_models:
        raise BenchEvalError(
            f"bfcl model {plan.model_id!r} is not supported by the pinned upstream BFCL "
            f"evaluate path (MODEL_CONFIG_MAPPING at gorilla {_UPSTREAM_COMMIT}); "
            f"supported models: {sorted(supported_models)}"
        )
    effective_harness_version = _require_pinned_harness_version(
        pinned_version=pinned_harness_version,
        # A supplied version belongs to an injected runner's controlled test
        # boundary. The real/default runner must always recapture the installed
        # distribution identity immediately before a potentially charged call.
        captured_version=harness_version if process_runner is not None else None,
    )
    # Pinned package-data identity gate, same boundary rule as the harness pin.
    benchmark_version = _bfcl_prelaunch_benchmark_identity(
        plan=plan,
        process_runner=process_runner,
        benchmark_identity=benchmark_identity,
    )
    from bencheval.hle_adapter import remaining_timeout_sec

    # The official score artifact is nested under run-owned roots; clear both so
    # a leftover score or generation from a prior use can never be re-scored.
    instance_dir = prepare_instance_artifacts_dir(
        artifacts_dir / instance_id,
        clear_names=AUTHORITATIVE_ARTIFACT_NAMES | frozenset({"results", "scores"}),
    )
    result_root = instance_dir / "results"
    score_root = instance_dir / "scores"
    # Pin every run-owned directory by descriptor before the first subprocess:
    # each descriptor anchors the approved inode, and a swapped path fails
    # closed (never scored) at the phase boundaries below.
    pins: list[tuple[int, Path, str]] = [
        (
            open_owned_dir_fd(instance_dir, role="bfcl instance artifacts directory"),
            instance_dir,
            "bfcl instance artifacts directory",
        ),
        (
            open_owned_dir_fd(result_root, role="bfcl generate result directory"),
            result_root,
            "bfcl generate result directory",
        ),
        (
            open_owned_dir_fd(score_root, role="bfcl evaluate score directory"),
            score_root,
            "bfcl evaluate score directory",
        ),
    ]
    try:
        generate_command = build_bfcl_run_command(
            plan=plan,
            instance_id=instance_id,
            artifacts_dir=result_root,
        )
        effective_num_threads = int(
            generate_command[generate_command.index("--num-threads") + 1],
        )
        evaluate_command = build_bfcl_evaluate_command(
            plan=plan,
            instance_id=instance_id,
            result_dir=result_root,
            score_dir=score_root,
        )
        wall = (
            timeout_sec if timeout_sec is not None else max(1, plan.max_wall_clock_sec_per_instance)
        )
        runner = process_runner or _default_process_runner
        deadline = time.monotonic() + wall
        generate_cli = runner(
            generate_command,
            cwd=repo_root,
            timeout_sec=wall,
            env=launch.environment,
        )
        _raise_on_dir_drift(pins)
        if generate_cli.returncode != 0:
            return parse_bfcl_instance_outcome(
                instance_id=instance_id,
                cli=generate_cli,
                artifacts_dir=instance_dir,
                repo_root=repo_root,
                harness_version=effective_harness_version,
                score_dir=score_root,
                model_id=plan.model_id,
                benchmark_version=benchmark_version,
                num_threads=effective_num_threads,
            )
        remaining = remaining_timeout_sec(deadline)
        if remaining <= 0:
            raise AdapterFailureError(
                f"bfcl harness timed out after {wall}s",
                failure_label="runtime_budget_exceeded",
                latency_sec=generate_cli.latency_sec,
                adapter_metadata=_bfcl_command_metadata(generate_command),
            )
        # The evaluate phase consumes mutable possible_answer bytes from the
        # installed package; re-verify the pin on both sides of the subprocess.
        _reverify_bfcl_package_data(plan=plan, process_runner=process_runner)
        # Evaluate writes beneath the normalized per-model score subdirectory;
        # pin it too so a mid-phase swap cannot redirect the scoring authority.
        model_score_dir = score_root / plan.model_id.replace("/", "_")
        pins.append(
            (
                open_owned_dir_fd(model_score_dir, role="bfcl evaluate model score directory"),
                model_score_dir,
                "bfcl evaluate model score directory",
            ),
        )
        evaluate_cli = runner(
            evaluate_command,
            cwd=repo_root,
            timeout_sec=remaining,
            env=launch.environment,
        )
        _raise_on_dir_drift(pins)
        _reverify_bfcl_package_data(plan=plan, process_runner=process_runner)
        return parse_bfcl_instance_outcome(
            instance_id=instance_id,
            cli=evaluate_cli,
            artifacts_dir=instance_dir,
            repo_root=repo_root,
            harness_version=effective_harness_version,
            score_dir=score_root,
            model_id=plan.model_id,
            latency_sec=generate_cli.latency_sec + evaluate_cli.latency_sec,
            benchmark_version=benchmark_version,
            num_threads=effective_num_threads,
        )
    except AdapterFailureError as error:
        # The generate concurrency remains part of the effective launch even
        # when evaluate, post-run verification, or a directory-integrity gate
        # fails after generation. Preserve it on every failure evidence row.
        error.adapter_metadata.setdefault("bfcl_num_threads", str(effective_num_threads))
        raise
    finally:
        for fd, _path, _role in pins:
            os.close(fd)


__all__ = [
    "BFCL_ADAPTER_ID",
    "BFCL_COMMAND",
    "BfclCliResult",
    "BfclInstanceOutcome",
    "BfclProcessRunner",
    "bfcl_harness_version",
    "bfcl_pinned_harness_version",
    "bfcl_supported_models",
    "build_bfcl_evaluate_command",
    "build_bfcl_run_command",
    "capture_bfcl_benchmark_identity",
    "parse_bfcl_instance_outcome",
    "run_bfcl_instance",
    "verify_bfcl_package_data",
]
