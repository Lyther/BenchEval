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
from dataclasses import dataclass, field, replace
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as distribution_version
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import yaml

from bencheval.access_evidence import EffectiveAccessEvidence, model_only_access
from bencheval.backends import INSPECT_BACKEND
from bencheval.benchmark_registry import BfclDerivedDataRef, BfclPackageDataIdentity
from bencheval.bfcl_package import BfclPackageSource, StagedPackage
from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.model_binding import ModelBinding, require_snapshot_endpoint
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.provider_registry import resolve_openai_compatible_launch
from bencheval.run_isolation import (
    AUTHORITATIVE_ARTIFACT_NAMES,
    dir_identity_error,
    open_owned_dir_fd,
    open_untrusted_regular_leaf,
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
_BFCL_CATEGORIES = (
    "live_parallel_multiple",
    "parallel_multiple",
    "live_irrelevance",
    "live_relevance",
    "live_multiple",
    "live_parallel",
    "simple_python",
    "irrelevance",
    "live_simple",
    "multiple",
    "parallel",
)
_TEST_IDS_FILE = "test_case_ids_to_generate.json"
# Run-level exposure-study artifacts. Both files are non-secret declarations of
# what this run actually bound: the verified package-data identity and the
# model-only effective-access state. ``study/private/`` is reserved for
# material that must never leave a private proof (retrieval transcripts).
STUDY_ARTIFACT_DIR = "study"
STUDY_IDENTITY_FILE = "benchmark-identity.json"
STUDY_ACCESS_FILE = "effective-access.json"

if TYPE_CHECKING:
    from bencheval.bfcl_study import DerivedRun, DerivedSource


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
    access_evidence: EffectiveAccessEvidence = field(default_factory=model_only_access)
    # Run-level study artifacts (`study/…` under the run root) referenced by
    # every scored row so private proof retains them with the generic role.
    study_artifact_paths: tuple[str, ...] = ()
    # The official generation record of an exact-id case (``results/…_result.json``),
    # retained with the generic artifact role so a proof keeps the typed
    # inference outcome and token usage next to the official score.
    generation_record_path: str | None = None


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


def _bfcl_category_for_instance(instance_id: str) -> tuple[str, bool]:
    """Return the official category and whether ``instance_id`` is one exact case."""
    validate_control_plane_instance_id(instance_id)
    if instance_id in _BFCL_CATEGORIES:
        return instance_id, False
    for category in _BFCL_CATEGORIES:
        if instance_id.startswith(f"{category}_"):
            return category, True
    raise BenchEvalError(f"unsupported BFCL category or case id: {instance_id!r}")


def build_bfcl_run_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    model_id: str | None = None,
) -> tuple[str, ...]:
    """``model_id`` is the BFCL registry key to launch; defaults to the plan's logical id."""
    validate_control_plane_instance_id(instance_id)
    _require_model_only(plan)
    category, exact_case = _bfcl_category_for_instance(instance_id)
    cmd: list[str] = [BFCL_COMMAND, "generate"]
    if exact_case:
        cmd.append("--run-ids")
    else:
        cmd.extend(["--test-category", category])
    cmd.extend(
        [
            "--result-dir",
            str(artifacts_dir.resolve()),
            "--allow-overwrite",
            "--num-threads",
            str(_bfcl_num_threads()),
        ],
    )
    name = model_id or plan.model_id
    if name != "runtime-default":
        cmd.extend(["--model", name])
    return tuple(cmd)


def build_bfcl_evaluate_command(
    *,
    plan: RunPlan,
    instance_id: str,
    result_dir: Path,
    score_dir: Path,
    model_id: str | None = None,
) -> tuple[str, ...]:
    """Official scoring phase: evaluate the generated output in ``result_dir``.

    ``--result-dir`` must match the generate phase's result directory exactly;
    ``--score-dir`` receives the official score artifacts that are the ONLY
    scoring authority for the instance outcome.
    """
    validate_control_plane_instance_id(instance_id)
    _require_model_only(plan)
    category, exact_case = _bfcl_category_for_instance(instance_id)
    cmd: list[str] = [
        BFCL_COMMAND,
        "evaluate",
        "--test-category",
        category,
        "--result-dir",
        str(result_dir.resolve()),
        "--score-dir",
        str(score_dir.resolve()),
    ]
    if exact_case:
        cmd.append("--partial-eval")
    name = model_id or plan.model_id
    if name != "runtime-default":
        cmd.extend(["--model", name])
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


def bfcl_registry_pin() -> str:
    """Reviewed ``sha256:<hex>`` of the pinned ``constants/model_config.py`` (manifest key)."""
    from bencheval.paths import repo_root as config_repo_root

    manifest_path = config_repo_root() / _SUPPORTED_MODELS_MANIFEST
    try:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, yaml.YAMLError) as e:
        raise BenchEvalError(f"cannot read {manifest_path}: {e}") from e
    pin = raw.get("registry_sha256") if isinstance(raw, dict) else None
    registry_file = raw.get("registry_file") if isinstance(raw, dict) else None
    if not isinstance(pin, str) or not pin.startswith("sha256:") or registry_file is None:
        raise BenchEvalError(
            f"{manifest_path.name}: configured BFCL registrations need the reviewed "
            "registry_file/registry_sha256 pin",
        )
    if registry_file != "constants/model_config.py":
        raise BenchEvalError(f"{manifest_path.name}: unexpected registry_file {registry_file!r}")
    return pin


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
    benchmark_id: str = "bfcl-v4",
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
    return bfcl_benchmark_identity(identity, benchmark_id=benchmark_id)


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
    if isinstance(identity, BfclDerivedDataRef):
        # A derived benchmark's version is content-bound to its materialized
        # overlay; the derived preparation step verifies the source pins itself.
        return None
    if not isinstance(identity, BfclPackageDataIdentity):
        raise BenchEvalError(f"bfcl benchmark identity kind drift: {identity.kind!r}")
    expected = bfcl_benchmark_identity(identity, benchmark_id=plan.benchmark_id)
    if process_runner is not None:
        if benchmark_identity is None:
            return None
        if benchmark_identity != expected:
            raise BenchEvalError(
                f"bfcl benchmark identity drift: expected {expected!r}, "
                f"supplied {benchmark_identity!r}",
            )
        return benchmark_identity
    return capture_bfcl_benchmark_identity(identity, benchmark_id=plan.benchmark_id)


@dataclass(frozen=True, slots=True)
class _ArtifactCandidate:
    """Located official artifact whose inode stays pinned by an open descriptor."""

    path: Path
    identity: tuple[int, int]
    descriptor: int


def _close_artifact_candidates(candidates: Sequence[_ArtifactCandidate]) -> None:
    for candidate in candidates:
        try:
            os.close(candidate.descriptor)
        except OSError:
            # Cleanup must not replace the evidence-integrity failure that led
            # here; the process will reclaim an already-invalid descriptor.
            pass


def _find_official_artifact_candidates(
    *,
    root_dir: Path,
    model_id: str,
    filename: str,
    role: str,
) -> list[_ArtifactCandidate]:
    """Locate and pin exact-name artifacts under a normalized model directory.

    Upstream resolves the directory as ``model_name.replace("/", "_")`` and the
    The intermediate directory group is category-derived, so callers supply the
    exact official filename instead of duplicating a hardcoded group path.
    """
    model_root = root_dir / model_id.replace("/", "_")
    if not model_root.is_dir():
        return []
    try:
        matches = sorted(p for p in model_root.rglob(filename) if p.is_file())
    except OSError as e:
        raise AdapterFailureError(
            f"bfcl {role} directory unreadable under {model_root}: {e}",
            failure_label="evidence_corrupt",
        ) from e
    candidates: list[_ArtifactCandidate] = []
    for path in matches:
        descriptor: int | None = None
        try:
            info = os.lstat(path)
            descriptor = open_untrusted_regular_leaf(str(path))
            opened = os.fstat(descriptor)
        except OSError as e:
            if descriptor is not None:
                os.close(descriptor)
            _close_artifact_candidates(candidates)
            raise AdapterFailureError(
                f"bfcl {role} artifact cannot be pinned after locate: {path}: {e}",
                failure_label="evidence_corrupt",
            ) from e
        identity = (info.st_dev, info.st_ino)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or (opened.st_dev, opened.st_ino) != identity
        ):
            os.close(descriptor)
            _close_artifact_candidates(candidates)
            raise AdapterFailureError(
                f"bfcl {role} artifact is not a stable plain file: {path}",
                failure_label="evidence_corrupt",
            )
        candidates.append(_ArtifactCandidate(path=path, identity=identity, descriptor=descriptor))
    return candidates


def _find_official_score_candidates(
    *,
    score_dir: Path,
    model_id: str,
    instance_id: str,
) -> list[_ArtifactCandidate]:
    return _find_official_artifact_candidates(
        root_dir=score_dir,
        model_id=model_id,
        filename=f"{_SCORE_FILE_PREFIX}_{instance_id}_score.json",
        role="score",
    )


def _open_nofollow_child_dir_fd(parent_fd: int, name: str, *, role: str) -> int:
    """Open the child directory ``name`` beneath ``parent_fd`` (no symlinks)."""
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as e:
        raise AdapterFailureError(
            f"bfcl artifact path component {name!r} unreadable ({role}): {e}",
            failure_label="evidence_corrupt",
        ) from e


def _read_artifact_candidate_bytes(
    *,
    root_fd: int,
    root_dir: Path,
    candidate: _ArtifactCandidate,
    role: str,
) -> bytes:
    """Read the located artifact through anchored, no-follow path resolution.

    The walk never leaves the pinned root descriptor and never follows a
    symlink; the opened inode must equal the identity recorded at locate time,
    and the pathname must still name that same inode after the read. Any
    mismatch means a same-uid mutator swapped the artifact and its bytes can
    never be scored.
    """
    rel = candidate.path.relative_to(root_dir)
    dir_fd = os.dup(root_fd)
    try:
        for part in rel.parts[:-1]:
            child_fd = _open_nofollow_child_dir_fd(dir_fd, part, role=f"bfcl {role} directory")
            os.close(dir_fd)
            dir_fd = child_fd
        try:
            file_fd = open_untrusted_regular_leaf(rel.parts[-1], dir_fd=dir_fd)
        except OSError as e:
            raise AdapterFailureError(
                f"bfcl {role} artifact unreadable: {candidate.path}: {e}",
                failure_label="evidence_corrupt",
            ) from e
        try:
            opened = os.fstat(file_fd)
        except OSError as e:
            os.close(file_fd)
            raise AdapterFailureError(
                f"bfcl {role} artifact unreadable: {candidate.path}: {e}",
                failure_label="evidence_corrupt",
            ) from e
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != candidate.identity:
            os.close(file_fd)
            raise AdapterFailureError(
                f"bfcl {role} artifact replaced after locate: {candidate.path}",
                failure_label="evidence_corrupt",
            )
        try:
            handle = os.fdopen(file_fd, "rb")
        except OSError as e:
            # fdopen failed before taking ownership: close fd so it never leaks.
            os.close(file_fd)
            raise AdapterFailureError(
                f"bfcl {role} artifact unreadable: {candidate.path}: {e}",
                failure_label="evidence_corrupt",
            ) from e
        try:
            with handle:
                data = handle.read()
        except OSError as e:
            raise AdapterFailureError(
                f"bfcl {role} artifact unreadable: {candidate.path}: {e}",
                failure_label="evidence_corrupt",
            ) from e
    finally:
        os.close(dir_fd)
    try:
        confirm = os.lstat(candidate.path)
    except OSError as e:
        raise AdapterFailureError(
            f"bfcl {role} artifact vanished during read: {candidate.path}: {e}",
            failure_label="evidence_corrupt",
        ) from e
    if (confirm.st_dev, confirm.st_ino) != candidate.identity:
        raise AdapterFailureError(
            f"bfcl {role} artifact replaced during read: {candidate.path}",
            failure_label="evidence_corrupt",
        )
    return data


def _read_exact_result_bytes(
    *,
    result_root_fd: int,
    result_dir: Path,
    model_id: str,
    test_category: str,
) -> tuple[bytes, Path]:
    """Read the one official category result (bytes, path) through the pinned result root."""
    target = f"{_SCORE_FILE_PREFIX}_{test_category}_result.json"
    candidates = _find_official_artifact_candidates(
        root_dir=result_dir,
        model_id=model_id,
        filename=target,
        role="result",
    )
    if len(candidates) != 1:
        _close_artifact_candidates(candidates)
        raise AdapterFailureError(
            f"bfcl exact-id run requires one official {target}, found {len(candidates)}",
            failure_label="evidence_corrupt",
        )
    candidate = candidates[0]
    try:
        data = _read_artifact_candidate_bytes(
            root_fd=result_root_fd,
            root_dir=result_dir,
            candidate=candidate,
            role="result",
        )
    finally:
        _close_artifact_candidates(candidates)
    return data, candidate.path


def _require_exact_result_id(data: bytes, *, instance_id: str) -> None:
    """Require one official generation row whose id is the requested case."""
    try:
        rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise AdapterFailureError(
            "bfcl exact-id result is not valid UTF-8 JSONL",
            failure_label="evidence_corrupt",
        ) from e
    if len(rows) != 1 or not isinstance(rows[0], dict) or rows[0].get("id") != instance_id:
        raise AdapterFailureError(
            f"bfcl exact-id result does not contain exactly {instance_id!r}",
            failure_label="evidence_corrupt",
        )


def _parse_official_score(
    text: bytes,
    *,
    expected_instance_id: str | None = None,
) -> tuple[bool, float] | None:
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
    if expected_instance_id is not None:
        if total_count != 1:
            return None
        if failure_rows and seen_ids != {expected_instance_id}:
            return None
    return correct_count == total_count, accuracy


# bfcl-eval 2026.3.23 ``evaluate`` writes every per-category score artifact in
# ``evaluate_task`` and only then builds the leaderboard CSV, where
# ``get_cost_latency_info`` calls ``statistics.stdev`` over the latency samples.
# An exact-id run has one sample per category, so that summary step always
# raises after scoring (upstream main is still unguarded). The official score
# artifact remains the only verdict authority; the crash stays in evidence.
POST_SCORE_SUMMARY_FAILURE = "leaderboard_latency_stdev_single_sample"
_STDEV_CRASH_FINAL_LINE = "StatisticsError: stdev requires at least two data points"
_STDEV_CRASH_FRAMES = ("generate_leaderboard_csv", "get_cost_latency_info")

# bfcl-eval 2026.3.23 ``generate`` catches handler exceptions and writes
# ``{"id", "result": "Error during inference: <message>", "traceback": …}`` in
# place of a model response; ``evaluate`` then scores that error string as a
# wrong answer. The official zero score stands, but the case never reached a
# model answer: it is a serving-path failure, classified apart from
# ``model_wrong_solution`` so it can never enter a native-eligible population.
INFERENCE_ERROR_PREFIX = "Error during inference: "
INFERENCE_FAILURE_CLASS: FailureLabel = "remote_infra_failure"


def _exact_generation_row(data: bytes) -> dict[str, object] | None:
    """The single official generation row of an exact-id case; None when unreadable."""
    try:
        rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    return rows[0]


def generation_inference_error(row: Mapping[str, object]) -> dict[str, str] | None:
    """The typed inference failure ``bfcl generate`` recorded instead of an answer, if any."""
    result = row.get("result")
    traceback_text = row.get("traceback")
    error_result = isinstance(result, str) and result.startswith(INFERENCE_ERROR_PREFIX)
    has_traceback = isinstance(traceback_text, str) and traceback_text.strip() != ""
    if not error_result and not has_traceback:
        return None
    error = {"result": result[:200] if isinstance(result, str) else ""}
    if has_traceback:
        lines = [line.strip() for line in str(traceback_text).splitlines() if line.strip()]
        error["exception"] = lines[-1][:200]
    return error


def generation_usage(row: Mapping[str, object]) -> dict[str, int | float] | None:
    """Token counts and latency the official generation row reports for a model answer."""
    usage: dict[str, int | float] = {}
    for key in ("input_token_count", "output_token_count"):
        value = row.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            usage[key] = value
    latency = row.get("latency")
    if isinstance(latency, (int, float)) and not isinstance(latency, bool) and latency >= 0:
        usage["latency"] = float(latency)
    return usage or None


def _is_post_score_summary_crash(cli: BfclCliResult, *, exact_case: bool) -> bool:
    """True only for the exact upstream post-scoring crash shape on an exact-id case."""
    if not exact_case or cli.returncode == 0:
        return False
    lines = [line.strip() for line in cli.stderr.splitlines() if line.strip()]
    if not lines or lines[-1] != _STDEV_CRASH_FINAL_LINE:
        return False
    return all(frame in cli.stderr for frame in _STDEV_CRASH_FRAMES)


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
    test_category: str | None = None,
    generation_record: bytes | None = None,
    generation_record_path: str | None = None,
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
    exact_case = test_category is not None and test_category != instance_id
    summary_crash = _is_post_score_summary_crash(cli, exact_case=exact_case)
    if summary_crash:
        native["post_score_summary_failure"] = POST_SCORE_SUMMARY_FAILURE

    if cli.returncode != 0 and not summary_crash:
        failure_class = "harness_failure"
    else:
        candidates: list[_ArtifactCandidate] = []
        try:
            candidates = _find_official_score_candidates(
                score_dir=score_dir,
                model_id=model_id,
                instance_id=test_category or instance_id,
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
                    score_bytes = _read_artifact_candidate_bytes(
                        root_fd=score_fd,
                        root_dir=score_dir,
                        candidate=candidate,
                        role="score",
                    )
                except AdapterFailureError:
                    # Locate→read swap: the bytes cannot be trusted, so no verdict.
                    failure_class = "evidence_corrupt"
                else:
                    verifier_path = str(candidate.path.resolve())
                    score = _parse_official_score(
                        score_bytes,
                        expected_instance_id=(
                            instance_id
                            if test_category is not None and test_category != instance_id
                            else None
                        ),
                    )
                    if score is None:
                        failure_class = "runtime_output_unparseable"
                    else:
                        primary_pass, partial_score = score
                        native["accuracy"] = partial_score
                        native["score_file"] = verifier_path
                finally:
                    os.close(score_fd)
        finally:
            _close_artifact_candidates(candidates)
        if summary_crash and failure_class not in (None, "evidence_corrupt"):
            # Without a coherent exact-id score artifact the crash is just a crash.
            failure_class = "harness_failure"
            native.pop("post_score_summary_failure", None)

    generation_row = (
        _exact_generation_row(generation_record) if generation_record is not None else None
    )
    if generation_row is not None:
        usage = generation_usage(generation_row)
        if usage is not None:
            native["generation_usage"] = usage
        inference_error = generation_inference_error(generation_row)
        if inference_error is not None and failure_class is None:
            # The official verdict is retained as data (``accuracy`` and
            # ``official_pass``; a non-call category may even score the error
            # string as correct), but the attempt never reached a model answer:
            # it is a serving-path failure, never a pass and never a wrong
            # solution. Stronger classes already assigned (corrupt, unparseable,
            # harness) keep precedence.
            native["generation_error"] = inference_error
            native["official_pass"] = primary_pass
            primary_pass = False
            partial_score = 0.0
            failure_class = INFERENCE_FAILURE_CLASS
        elif inference_error is not None:
            native["generation_error"] = inference_error

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
    if "post_score_summary_failure" in native:
        metadata["bfcl_post_score_summary_failure"] = POST_SCORE_SUMMARY_FAILURE

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
        generation_record_path=(
            _rel_path(generation_record_path, repo_root) if generation_record_path else None
        ),
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
    if identity is None or isinstance(identity, BfclDerivedDataRef):
        # Derived runs re-verify overlay and installed bytes through the overlay gate.
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


def _study_artifact_payloads(
    *,
    plan: RunPlan,
    benchmark_version: str | None,
    harness_version: str,
    access: EffectiveAccessEvidence,
    base_harness_version: str | None = None,
) -> dict[str, str]:
    """Canonical JSON texts for the run-level study artifacts."""
    from bencheval.identity_strings import catalog_benchmark_identity

    identity = catalog_benchmark_identity(plan.benchmark_id)
    identity_payload: dict[str, object] = {
        "schema_version": "bfcl-study-identity-v1",
        "benchmark_id": plan.benchmark_id,
        "benchmark_version": benchmark_version,
        "harness_version": harness_version,
        "adapter_id": plan.adapter_id,
        "harness_kind": plan.harness_kind,
        "identity": identity.model_dump(mode="json") if identity is not None else None,
    }
    if base_harness_version is not None:
        # Present only for configured-registration runs: the effective label
        # above names the extension; this keeps the unmodified base pin beside it.
        identity_payload["base_harness_version"] = base_harness_version
    access_payload = {
        "schema_version": "bfcl-study-access-v1",
        "basis": "official_bfcl_cli_model_only",
        "requested_network_policy": plan.network_policy,
        "access_control_source": access.access_control_source,
        "egress_control": access.egress_control,
        "repository_history": access.repository_history,
        "retrieval_audit": access.retrieval_audit,
    }
    return {
        STUDY_IDENTITY_FILE: json.dumps(identity_payload, sort_keys=True, indent=2) + "\n",
        STUDY_ACCESS_FILE: json.dumps(access_payload, sort_keys=True, indent=2) + "\n",
    }


def _write_or_verify_study_file(dir_fd: int, name: str, text: str) -> None:
    """First instance creates the file; later ones must see identical bytes.

    Both branches stay anchored to the study directory descriptor: an existing
    entry is read without following links and compared byte-for-byte, and a
    missing one is created through the attacker-entry-replacing exclusive
    writer, so a planted link or forged declaration can never be adopted.
    """
    try:
        existing_fd = open_untrusted_regular_leaf(name, dir_fd=dir_fd)
    except FileNotFoundError:
        write_text_at_exclusive(dir_fd, name, text)
        return
    except OSError as e:
        raise AdapterFailureError(
            f"study artifact {name} is not a plain single-link file: {e}",
            failure_label="evidence_corrupt",
        ) from e
    try:
        with os.fdopen(existing_fd, "rb") as handle:
            current = handle.read()
    except OSError as e:
        raise AdapterFailureError(
            f"study artifact {name} unreadable: {e}", failure_label="evidence_corrupt"
        ) from e
    if current != text.encode("utf-8"):
        raise AdapterFailureError(
            f"study artifact {name} drifted between instances of one run",
            failure_label="evidence_corrupt",
        )


def write_study_artifacts(
    *,
    artifacts_dir: Path,
    plan: RunPlan,
    benchmark_version: str | None,
    harness_version: str,
    repo_root: Path,
    access: EffectiveAccessEvidence | None = None,
    base_harness_version: str | None = None,
) -> tuple[str, ...]:
    """Materialize ``study/`` declarations under the run root and return their paths.

    Idempotent across the instances of one run: the bytes are canonical, so a
    second instance verifies rather than rewrites, and any drift fails closed
    as corrupt evidence before a charged call.
    """
    payloads = _study_artifact_payloads(
        plan=plan,
        benchmark_version=benchmark_version,
        harness_version=harness_version,
        access=access or model_only_access(),
        base_harness_version=base_harness_version,
    )
    study_dir = artifacts_dir / STUDY_ARTIFACT_DIR
    study_fd = open_owned_dir_fd(study_dir, role="bfcl study artifacts directory")
    try:
        for name, text in sorted(payloads.items()):
            _write_or_verify_study_file(study_fd, name, text)
    finally:
        os.close(study_fd)
    return tuple(_rel_path(str(study_dir / name), repo_root) for name in sorted(payloads))


@dataclass(frozen=True, slots=True)
class _Staging:
    """A configured registration staged once per run (architecture §23.4)."""

    staged: StagedPackage
    source: BfclPackageSource
    manifest_text: str
    artifact_paths: tuple[str, ...]


_EXECUTION_ARTIFACT_DIR = "execution"
_REGISTRATION_MANIFEST_NAME = "bfcl-registration.json"


def _resolve_package_source(plan: RunPlan) -> BfclPackageSource:
    """Installed pinned package + catalog data identity + reviewed registry pin."""
    from bencheval.bfcl_study import derived_ref_for
    from bencheval.identity_strings import catalog_benchmark_identity

    ref = derived_ref_for(plan.benchmark_id)
    source_id = ref.source_benchmark_id if ref is not None else plan.benchmark_id
    identity = catalog_benchmark_identity(source_id)
    if not isinstance(identity, BfclPackageDataIdentity):
        raise BenchEvalError(f"{source_id!r} has no pinned BFCL package-data identity")
    return BfclPackageSource(
        package_root=_bfcl_package_root(), identity=identity, registry_sha256=bfcl_registry_pin()
    )


def _prepare_staged_package(
    *,
    plan: RunPlan,
    artifacts_dir: Path,
    repo_root: Path,
    package_source: BfclPackageSource | None,
    base_version: str,
) -> _Staging | None:
    """Stage the configured registration once per run, or re-verify the retained one."""
    from bencheval.bfcl_package import (
        REGISTRATION_FILE,
        STAGED_PACKAGE_DIR,
        registration_spec_for,
        render_registration_manifest,
        restage_from_manifest,
        stage_bfcl_package,
    )

    snapshot = plan.model_binding_snapshot
    bfcl = snapshot.bfcl if snapshot is not None else None
    if snapshot is None or bfcl is None or bfcl.mode != "configured":
        if package_source is not None:
            raise BenchEvalError(
                f"model {plan.model_id!r} has no configured BFCL registration; "
                "a package source is invalid",
            )
        return None
    try:
        source = package_source or _resolve_package_source(plan)
        # Everything rendered comes from the confirmed snapshot; the shipped
        # registry is never re-read at execution time.
        spec = registration_spec_for(snapshot)
        execution_dir = artifacts_dir / _EXECUTION_ARTIFACT_DIR
        execution_fd = open_owned_dir_fd(execution_dir, role="bfcl execution artifacts directory")
        try:
            existing: bytes | None = None
            try:
                fd = open_untrusted_regular_leaf(_REGISTRATION_MANIFEST_NAME, dir_fd=execution_fd)
            except FileNotFoundError:
                fd = None
            except OSError as e:
                raise BenchEvalError(
                    f"registration manifest is not a plain single-link file: {e}"
                ) from e
            if fd is not None:
                with os.fdopen(fd, "rb") as handle:
                    existing = handle.read()
            overlay_root = artifacts_dir / STAGED_PACKAGE_DIR
            if existing is None:
                if overlay_root.exists() or overlay_root.is_symlink():
                    raise BenchEvalError(
                        "package copy exists without its retained registration manifest"
                    )
                staged = stage_bfcl_package(source=source, spec=spec, output_root=overlay_root)
                text = render_registration_manifest(staged, base_version=base_version)
                write_text_at_exclusive(execution_fd, _REGISTRATION_MANIFEST_NAME, text)
            else:
                text = existing.decode("utf-8")
                staged = restage_from_manifest(text, artifacts_dir=artifacts_dir, source=source)
                if staged.spec != spec:
                    raise BenchEvalError(
                        "retained registration manifest does not bind this run's model binding"
                    )
                if render_registration_manifest(staged, base_version=base_version) != text:
                    raise BenchEvalError("retained registration manifest bytes do not replay")
        finally:
            os.close(execution_fd)
    except BenchEvalError as e:
        raise AdapterFailureError(str(e), failure_label="runtime_config_drift") from e
    paths = (
        str(execution_dir / _REGISTRATION_MANIFEST_NAME),
        str(staged.package_dir / REGISTRATION_FILE),
    )
    return _Staging(
        staged=staged,
        source=source,
        manifest_text=text,
        artifact_paths=tuple(_rel_path(path, repo_root) for path in paths),
    )


def _reverify_staging(staging: _Staging | None, derived: DerivedRun | None) -> None:
    if staging is None:
        return
    from bencheval.bfcl_package import verify_staged_package

    declared = derived.overlay.derived_files if derived is not None else None
    try:
        verify_staged_package(staging.staged, source=staging.source, declared_changes=declared)
    except BenchEvalError as e:
        raise AdapterFailureError(str(e), failure_label="runtime_config_drift") from e


def _prepare_derived_run(
    *,
    plan: RunPlan,
    artifacts_dir: Path,
    repo_root: Path,
    derived_source: DerivedSource | None,
    staged: StagedPackage | None = None,
) -> DerivedRun | None:
    """Materialize or re-verify the run-owned overlay for a derived benchmark."""
    from bencheval.bfcl_study import derived_ref_for, prepare_tool_order_run, resolve_derived_source

    if derived_ref_for(plan.benchmark_id) is None:
        if derived_source is not None:
            raise BenchEvalError(
                f"{plan.benchmark_id!r} is not a derived benchmark; a derived source is invalid",
            )
        return None
    try:
        source = derived_source or resolve_derived_source(plan.benchmark_id)
        assert source is not None
        if source.ref.study_id != derived_ref_for(plan.benchmark_id).study_id:  # type: ignore[union-attr]
            raise BenchEvalError("derived source study does not match the catalog reference")
        return prepare_tool_order_run(
            artifacts_dir=artifacts_dir, source=source, repo_root=repo_root, staged=staged
        )
    except BenchEvalError as e:
        raise AdapterFailureError(str(e), failure_label="runtime_config_drift") from e


def _reverify_derived_overlay(derived: DerivedRun | None, source: DerivedSource | None) -> None:
    if derived is None or source is None:
        return
    from bencheval.bfcl_study import verify_tool_order_overlay

    try:
        verify_tool_order_overlay(
            derived.overlay, package_root=source.package_root, identity=source.source_identity
        )
    except BenchEvalError as e:
        raise AdapterFailureError(str(e), failure_label="runtime_config_drift") from e


def _verify_upstream_launch(
    snapshot: ModelBinding,
    *,
    package_source: BfclPackageSource | None,
    process_runner: BfclProcessRunner | None,
) -> None:
    from bencheval.bfcl_package import read_pinned_registry, verify_upstream_binding

    if package_source is None:
        if process_runner is not None:
            return
        identity = catalog_benchmark_identity_for_bfcl()
        package_source = BfclPackageSource(
            package_root=_bfcl_package_root(),
            identity=identity,
            registry_sha256=bfcl_registry_pin(),
        )
    verify_upstream_binding(snapshot, read_pinned_registry(package_source))


def catalog_benchmark_identity_for_bfcl() -> BfclPackageDataIdentity:
    from bencheval.identity_strings import catalog_benchmark_identity

    identity = catalog_benchmark_identity("bfcl-v4")
    if not isinstance(identity, BfclPackageDataIdentity):
        raise BenchEvalError("bfcl-v4 has no pinned BFCL package-data identity")
    return identity


def _finish_outcome(
    outcome: BfclInstanceOutcome, *, study_paths: tuple[str, ...], metadata: Mapping[str, str]
) -> BfclInstanceOutcome:
    return replace(
        outcome,
        adapter_metadata={**metadata, **outcome.adapter_metadata},
        study_artifact_paths=study_paths,
    )


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
    derived_source: DerivedSource | None = None,
    package_source: BfclPackageSource | None = None,
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
    # The confirmed snapshot fixed the public endpoint; a changed override is
    # a silent late substitution and fails before any charge.
    snapshot = plan.model_binding_snapshot
    require_snapshot_endpoint(snapshot, base_url=launch.base_url)
    supported_models, pinned_harness_version = _load_supported_models_manifest()
    # The BFCL registry key launched is the binding's registry id (legacy plans
    # without a snapshot keep the logical id). A configured registration is
    # generated in the run-owned copy; anything else must be a pinned key.
    bfcl_binding = snapshot.bfcl if snapshot is not None else None
    registry_id = bfcl_binding.registry_id if bfcl_binding is not None else plan.model_id
    configured = bfcl_binding is not None and bfcl_binding.mode == "configured"
    if not configured and snapshot is not None:
        # An allowlisted key must also launch the confirmed API model. The real
        # runner reads the pinned installed registry; an injected runner is a
        # controlled boundary and checks when it supplies the package source.
        _verify_upstream_launch(
            snapshot, package_source=package_source, process_runner=process_runner
        )
    binding_metadata: dict[str, str] = {}
    if snapshot is not None:
        binding_metadata = {
            "model_binding_sha256": snapshot.sha256,
            "api_model": snapshot.api_model,
            "bfcl_registry_id": registry_id,
        }
    if not configured and registry_id not in supported_models:
        raise BenchEvalError(
            f"bfcl model {plan.model_id!r} (registry key {registry_id!r}) is not supported by "
            f"the pinned upstream BFCL evaluate path (MODEL_CONFIG_MAPPING at gorilla "
            f"{_UPSTREAM_COMMIT}); supported models: {sorted(supported_models)}"
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
    if derived_source is None and process_runner is None:
        from bencheval.bfcl_study import derived_ref_for, resolve_derived_source

        if derived_ref_for(plan.benchmark_id) is not None:
            try:
                derived_source = resolve_derived_source(plan.benchmark_id)
            except BenchEvalError as e:
                raise AdapterFailureError(str(e), failure_label="runtime_config_drift") from e
    from bencheval.hle_adapter import remaining_timeout_sec

    test_category, exact_case = _bfcl_category_for_instance(instance_id)
    # Pin every run-owned directory by descriptor before the first subprocess:
    # each descriptor anchors the approved inode, and a swapped path fails
    # closed (never scored) at the phase boundaries below.
    pins: list[tuple[int, Path, str]] = []
    # The generate concurrency is known only once the launch command is built;
    # a failure before that point has no effective launch to describe.
    effective_num_threads: int | None = None
    try:
        staging = _prepare_staged_package(
            plan=plan,
            artifacts_dir=artifacts_dir,
            repo_root=repo_root,
            package_source=package_source,
            base_version=pinned_harness_version,
        )
        base_harness_version: str | None = None
        if staging is not None:
            from bencheval.bfcl_package import effective_harness_version as registration_label

            base_harness_version = effective_harness_version
            effective_harness_version = registration_label(
                pinned_harness_version, staging.staged.registration_sha256
            )
        derived = _prepare_derived_run(
            plan=plan,
            artifacts_dir=artifacts_dir,
            repo_root=repo_root,
            derived_source=derived_source,
            staged=staging.staged if staging is not None else None,
        )
        if derived is not None:
            benchmark_version = derived.benchmark_version
        study_paths = write_study_artifacts(
            artifacts_dir=artifacts_dir,
            plan=plan,
            benchmark_version=benchmark_version,
            harness_version=effective_harness_version,
            repo_root=repo_root,
            base_harness_version=base_harness_version,
        )
        if staging is not None:
            study_paths = (*study_paths, *staging.artifact_paths)
        if derived is not None:
            study_paths = (*study_paths, *derived.artifact_paths)
        if base_harness_version is not None:
            binding_metadata["base_harness_version"] = base_harness_version
        # The official score artifact is nested under run-owned roots; clear both so
        # a leftover score or generation from a prior use can never be re-scored.
        instance_dir = prepare_instance_artifacts_dir(
            artifacts_dir / instance_id,
            clear_names=AUTHORITATIVE_ARTIFACT_NAMES
            | frozenset({"results", "scores", "bfcl-project"}),
        )
        result_root = instance_dir / "results"
        score_root = instance_dir / "scores"
        project_root = instance_dir / "bfcl-project"
        for path, role in (
            (instance_dir, "bfcl instance artifacts directory"),
            (result_root, "bfcl generate result directory"),
            (score_root, "bfcl evaluate score directory"),
            (project_root, "bfcl project directory"),
        ):
            pins.append((open_owned_dir_fd(path, role=role), path, role))
        if exact_case:
            project_fd = next(fd for fd, path, _role in pins if path == project_root)
            write_text_at_exclusive(
                project_fd,
                _TEST_IDS_FILE,
                json.dumps({test_category: [instance_id]}, sort_keys=True) + "\n",
            )
        launch_environment = dict(launch.environment)
        launch_environment["BFCL_PROJECT_ROOT"] = str(project_root.resolve())
        if derived is not None:
            from bencheval.bfcl_study import launch_environment_for

            launch_environment = launch_environment_for(derived.overlay, launch_environment)
        elif staging is not None:
            from bencheval.bfcl_package import launch_environment as staged_environment

            launch_environment = staged_environment(staging.staged.pythonpath, launch_environment)
        generate_command = build_bfcl_run_command(
            plan=plan,
            instance_id=instance_id,
            artifacts_dir=result_root,
            model_id=registry_id,
        )
        effective_num_threads = int(
            generate_command[generate_command.index("--num-threads") + 1],
        )
        # Prelaunch overlay/installed-bytes proof; a drift here is preserved as
        # runtime_config_drift with the launch it would have made.
        _reverify_staging(staging, derived)
        _reverify_derived_overlay(derived, derived_source)
        evaluate_command = build_bfcl_evaluate_command(
            plan=plan,
            instance_id=instance_id,
            result_dir=result_root,
            score_dir=score_root,
            model_id=registry_id,
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
            env=launch_environment,
        )
        _raise_on_dir_drift(pins)
        if generate_cli.returncode != 0:
            return _finish_outcome(
                parse_bfcl_instance_outcome(
                    instance_id=instance_id,
                    cli=generate_cli,
                    artifacts_dir=instance_dir,
                    repo_root=repo_root,
                    harness_version=effective_harness_version,
                    score_dir=score_root,
                    model_id=registry_id,
                    benchmark_version=benchmark_version,
                    num_threads=effective_num_threads,
                    test_category=test_category,
                ),
                study_paths=study_paths,
                metadata=binding_metadata,
            )
        exact_result_bytes: bytes | None = None
        exact_result_path: Path | None = None
        if exact_case:
            result_root_fd = next(fd for fd, path, _role in pins if path == result_root)
            exact_result_bytes, exact_result_path = _read_exact_result_bytes(
                result_root_fd=result_root_fd,
                result_dir=result_root,
                model_id=registry_id,
                test_category=test_category,
            )
            _require_exact_result_id(exact_result_bytes, instance_id=instance_id)
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
        _reverify_staging(staging, derived)
        _reverify_derived_overlay(derived, derived_source)
        # Evaluate writes beneath the normalized per-model score subdirectory;
        # pin it too so a mid-phase swap cannot redirect the scoring authority.
        model_score_dir = score_root / registry_id.replace("/", "_")
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
            env=launch_environment,
        )
        _raise_on_dir_drift(pins)
        _reverify_bfcl_package_data(plan=plan, process_runner=process_runner)
        _reverify_staging(staging, derived)
        _reverify_derived_overlay(derived, derived_source)
        if exact_result_bytes is not None:
            current_result_bytes, _current_result_path = _read_exact_result_bytes(
                result_root_fd=result_root_fd,
                result_dir=result_root,
                model_id=registry_id,
                test_category=test_category,
            )
            _require_exact_result_id(current_result_bytes, instance_id=instance_id)
            if current_result_bytes != exact_result_bytes:
                raise AdapterFailureError(
                    "bfcl exact-id result changed during official evaluation",
                    failure_label="evidence_corrupt",
                )
        return _finish_outcome(
            parse_bfcl_instance_outcome(
                instance_id=instance_id,
                cli=evaluate_cli,
                artifacts_dir=instance_dir,
                repo_root=repo_root,
                harness_version=effective_harness_version,
                score_dir=score_root,
                model_id=registry_id,
                latency_sec=generate_cli.latency_sec + evaluate_cli.latency_sec,
                benchmark_version=benchmark_version,
                num_threads=effective_num_threads,
                test_category=test_category,
                generation_record=exact_result_bytes,
                generation_record_path=(
                    str(exact_result_path.resolve()) if exact_result_path is not None else None
                ),
            ),
            study_paths=study_paths,
            metadata=binding_metadata,
        )
    except AdapterFailureError as error:
        for key, value in binding_metadata.items():
            error.adapter_metadata.setdefault(key, value)
        # The generate concurrency remains part of the effective launch even
        # when evaluate, post-run verification, or a directory-integrity gate
        # fails after generation. Preserve it on every failure evidence row
        # that had a launch; never mask an earlier failure to attach it.
        if effective_num_threads is not None:
            error.adapter_metadata.setdefault("bfcl_num_threads", str(effective_num_threads))
        raise
    finally:
        for fd, _path, _role in pins:
            os.close(fd)


__all__ = [
    "BFCL_ADAPTER_ID",
    "BFCL_COMMAND",
    "POST_SCORE_SUMMARY_FAILURE",
    "STUDY_ACCESS_FILE",
    "STUDY_ARTIFACT_DIR",
    "STUDY_IDENTITY_FILE",
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
