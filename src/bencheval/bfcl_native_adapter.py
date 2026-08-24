"""BFCL v4 model-only adapter (``bfcl generate`` → ``bfcl evaluate`` lifecycle).

Native scoring authority is the official ``bfcl evaluate`` score artifact at
``<score-dir>/<model>/non_live/BFCL_v4_<category>_score.json`` (JSONL: summary
header first, then one row per FAILED case); generation-side files
(``verdict.json``/``result.json``) are never consulted for the verdict.
BFCL is admitted (``executable: true``) since 2026-08-24, after the qualified
live dev-box lifecycle (``run-20260824-040631-228703-4756f857``); the CLI
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

BFCL_ADAPTER_ID = "bfcl"
BFCL_COMMAND = "bfcl"
_BFCL_DIST_CANDIDATES = ("bfcl-eval", "bfcl")
_VERSION_TIMEOUT_SEC = 15
_UPSTREAM_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
_SCORE_FILE_PREFIX = "BFCL_v4"
_SUPPORTED_MODELS_MANIFEST = Path("config") / "bfcl-v4-supported-models.yaml"
# Hosted-model generation defaults to 1 thread upstream; bounded concurrency is
# required to finish a category inside the slice's per-instance wall cap. The
# effective value is stamped into evidence via the logged command argv.
_NUM_THREADS_ENV = "BENCHEVAL_BFCL_NUM_THREADS"
_DEFAULT_NUM_THREADS = 16


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


def bfcl_benchmark_version() -> str | None:
    """BFCL dataset/category revision — not capturable from package version alone.

    Package/CLI output belongs in ``harness_version``. Until an upstream git
    commit plus dataset/category-map revision is captured, return None so the
    planner's provisional benchmark label is retained.
    """
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
            f"{_NUM_THREADS_ENV} must be a positive integer, got {raw!r}",
        ) from e
    if value < 1:
        raise BenchEvalError(
            f"{_NUM_THREADS_ENV} must be a positive integer, got {raw!r}",
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
            adapter_metadata={"bfcl_command": " ".join(command)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"bfcl harness launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"bfcl_command": " ".join(command)},
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


def _find_official_score_candidates(
    *,
    score_dir: Path,
    model_id: str,
    instance_id: str,
) -> list[Path]:
    """Exact-name official artifacts under the normalized model directory.

    Upstream resolves the directory as ``model_name.replace("/", "_")`` and the
    filename as ``BFCL_v4_<category>_score.json``; the intermediate directory
    group (``non_live``/``live``/...) is category-derived, so the search is an
    exact-name walk instead of a hardcoded group.
    """
    model_root = score_dir / model_id.replace("/", "_")
    if not model_root.is_dir():
        return []
    target = f"{_SCORE_FILE_PREFIX}_{instance_id}_score.json"
    try:
        return sorted(p for p in model_root.rglob(target) if p.is_file())
    except OSError as e:
        raise AdapterFailureError(
            f"bfcl score directory unreadable under {model_root}: {e}",
            failure_label="evidence_corrupt",
        ) from e


def _parse_official_score(score_file: Path) -> tuple[bool, float] | None:
    """Official BFCL v4 score artifact → (primary_pass, partial_score); None when unparseable.

    Pinned upstream layout: JSONL, one object per line. Line 0 is the summary
    header (``{"accuracy": float, "correct_count": int, "total_count": int}``);
    every later line is one FAILED case (``{"id": str, "valid": false, ...}``).
    A perfect run is a header-only one-line file. The artifact is coherent only
    when the counts and accuracy agree and the failure rows number exactly
    ``total_count - correct_count`` with unique ids; anything else fails closed
    and can never grant a pass.
    """
    try:
        text = score_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    rows: list[object] = []
    for line in text.splitlines():
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
) -> BfclInstanceOutcome:
    """Score one instance from the official ``bfcl evaluate`` artifact only.

    ``cli`` is the evaluate-phase process result (or the generate-phase result
    when generation failed before evaluate ran). Generation-side files under
    the result directory (``verdict.json``/``result.json``) are harness scratch
    output and are never consulted for the verdict.
    """
    stdout_file = artifacts_dir / "stdout.log"
    stderr_file = artifacts_dir / "stderr.log"
    stdout_file.parent.mkdir(parents=True, exist_ok=True)
    stdout_file.write_text(cli.stdout, encoding="utf-8")
    stderr_file.write_text(cli.stderr, encoding="utf-8")
    stdout_rel = str(stdout_file.resolve())
    stderr_rel = str(stderr_file.resolve())

    native: dict[str, object] = {"returncode": cli.returncode, "backend": INSPECT_BACKEND}
    primary_pass = False
    partial_score = 0.0
    failure_class: FailureLabel | None = None
    cost_usd = 0.0
    verifier_path: str | None = None

    if cli.returncode != 0:
        failure_class = "harness_failure"
    else:
        candidates = _find_official_score_candidates(
            score_dir=score_dir,
            model_id=model_id,
            instance_id=instance_id,
        )
        if not candidates:
            # Evaluate exited 0 without writing the official score artifact.
            failure_class = "harness_failure"
        elif len(candidates) > 1:
            # Duplicate exact-name artifacts cannot be disambiguated; scoring
            # either would be an invented verdict.
            failure_class = "runtime_output_unparseable"
        else:
            score_file = candidates[0]
            verifier_path = str(score_file.resolve())
            score = _parse_official_score(score_file)
            if score is None:
                failure_class = "runtime_output_unparseable"
            else:
                primary_pass, partial_score = score
                native["accuracy"] = partial_score
                native["score_file"] = verifier_path

    if not primary_pass and failure_class is None:
        failure_class = "model_wrong_solution"

    metadata = {
        "adapter_id": BFCL_ADAPTER_ID,
        "harness_kind": "bfcl-native",
        "bfcl_command": " ".join(cli.command),
    }
    if harness_version:
        metadata["harness_version"] = harness_version
    if benchmark_version:
        metadata["benchmark_version"] = benchmark_version

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
    from bencheval.run_isolation import (
        AUTHORITATIVE_ARTIFACT_NAMES,
        prepare_instance_artifacts_dir,
    )

    # The official score artifact is nested under run-owned roots; clear both so
    # a leftover score or generation from a prior use can never be re-scored.
    instance_dir = prepare_instance_artifacts_dir(
        artifacts_dir / instance_id,
        clear_names=AUTHORITATIVE_ARTIFACT_NAMES | frozenset({"results", "scores"}),
    )
    result_root = instance_dir / "results"
    score_root = instance_dir / "scores"
    result_root.mkdir(parents=True, exist_ok=True)
    score_root.mkdir(parents=True, exist_ok=True)
    generate_command = build_bfcl_run_command(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=result_root,
    )
    evaluate_command = build_bfcl_evaluate_command(
        plan=plan,
        instance_id=instance_id,
        result_dir=result_root,
        score_dir=score_root,
    )
    wall = timeout_sec if timeout_sec is not None else max(1, plan.max_wall_clock_sec_per_instance)
    runner = process_runner or _default_process_runner
    deadline = time.monotonic() + wall
    generate_cli = runner(generate_command, cwd=repo_root, timeout_sec=wall, env=launch.environment)
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
        )
    remaining = remaining_timeout_sec(deadline)
    if remaining <= 0:
        raise AdapterFailureError(
            f"bfcl harness timed out after {wall}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=generate_cli.latency_sec,
            adapter_metadata={"bfcl_command": " ".join(generate_command)},
        )
    evaluate_cli = runner(
        evaluate_command,
        cwd=repo_root,
        timeout_sec=remaining,
        env=launch.environment,
    )
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
    )


__all__ = [
    "BFCL_ADAPTER_ID",
    "BFCL_COMMAND",
    "BfclCliResult",
    "BfclInstanceOutcome",
    "BfclProcessRunner",
    "bfcl_benchmark_version",
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
