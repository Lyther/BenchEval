"""SWE-bench Verified adapter (control-plane P4, swebench-native harness)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from bencheval.backends import INSPECT_BACKEND
from bencheval.domain import FailureLabel, RunPlan
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.ids import new_run_id
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.paths import repo_root as _repo_root
from bencheval.run_isolation import (
    AUTHORITATIVE_ARTIFACT_NAMES,
    dir_identity_error,
    open_owned_dir_fd,
    open_untrusted_regular_leaf,
    prepare_instance_artifacts_dir,
    read_json_at_nofollow,
    write_bytes_at_exclusive,
    write_text_at_exclusive,
)
from bencheval.runtime_registry import load_runtime_catalog

SWEBENCH_ADAPTER_ID = "swebench"
_INSTANCE_DIR_ROLE = "swebench instance directory"
_OFFICIAL_REPORT_NAME = "report.json"
_WORKSPACE_DIFF_NAME = "workspace.diff"
_PREDICTIONS_NAME = "predictions.jsonl"
_SWE_VERIFIED_REPO = "SWE-bench/SWE-bench_Verified"
_SWE_VERIFIED_REVISION = "78f471bf655a3137b2e8a75af1501690ec009ec3"
_SWE_SOURCE_PARQUET = "data/test-00000-of-00001.parquet"
_SWE_SOURCE_PARQUET_SHA256 = (
    "sha256:030cfd7f2a704c4c0226e7f104c725a3b41230b1d3517f9c915ad7ea5be3fa25"
)
_INSPECT_DATASET_NAME = "inspect-dataset"
_OFFICIAL_DATASET_NAME = "official-dataset"
_EVAL_INPUT_NAME = "eval-input"
_TRANSFORM_MANIFEST_NAME = "transformation-manifest.json"
_DATASET_JSONL_NAME = "test.jsonl"
_JSON_LIST_FIELDS = ("PASS_TO_PASS", "FAIL_TO_PASS")
# Inspect Evals 0.8.0 formats {id}/{arch}/{org}/{repo}/{issue} only. Digest
# form forbids a :latest tag. The hex is still unbound until execution-time
# image-digest binding; do not invent one or add unknown braces.
_IMAGE_NAME_TEMPLATE = "ghcr.io/epoch-research/swe-bench.eval.x86_64.{id}@sha256:"
_INSTANCE_IMAGE_RE = re.compile(r"^(?P<org>.+?)__(?P<repo>.+)-(?P<issue>\d+)$")
_SWE_RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_INSPECT_SOLVER_BY_RUNTIME = {
    "codex-cli": "inspect_swe/codex_cli",
}
_SWE_CODEX_ONLY_MESSAGE = (
    "swe-bench-verified diagnostic is Codex-only for v1; "
    "claude-code is rejected until a pinned Inspect SWE + Claude lifecycle is proven"
)
# inspect-evals 0.8.0 scorers still import MAP_REPO_VERSION_TO_SPECS from
# swebench.harness.constants (removed in 5.0.1). Generation uses this pin in
# an isolated env only; official scoring stays swebench==5.0.1.
_INSPECT_GENERATION_SWEBENCH = "swebench==4.1.0"
_OFFICIAL_EVALUATOR_PACKAGE = "swebench==5.0.1"
_HUB_DATASET_ALIASES = frozenset(
    {
        "verified",
        "lite",
        "test",
        "full",
        "SWE-bench/SWE-bench_Verified",
        "princeton-nlp/SWE-bench_Verified",
    },
)


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
class SwebenchMaterialization:
    source_parquet: str
    source_sha256: str
    inspect_dataset: str
    official_dataset: str
    image_digest: str | None
    image_name_template: str


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
    predictions_path: str | None = None
    summary_path: str | None = None
    identity_artifact_paths: tuple[str, ...] = ()


class SwebenchProcessRunner(Protocol):
    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
    ) -> SwebenchCliResult: ...


def _inspect_model_string(plan: RunPlan) -> str:
    if plan.provider_id == "bytellm" or not plan.provider_id:
        return f"openai/{plan.model_id}"
    return f"{plan.provider_id}/{plan.model_id}"


def build_swebench_run_command(
    *,
    plan: RunPlan,
    instance_id: str,
    artifacts_dir: Path,
    image_name_template: str | None = None,
) -> tuple[str, ...]:
    """Inspect Evals generation command for the selected pinned runtime solver."""
    validate_control_plane_instance_id(instance_id)
    runtime_id = plan.runtime_id or ""
    if runtime_id == "claude-code":
        raise BenchEvalError(_SWE_CODEX_ONLY_MESSAGE)
    solver = _INSPECT_SOLVER_BY_RUNTIME.get(runtime_id)
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
    template = image_name_template if image_name_template is not None else _IMAGE_NAME_TEMPLATE
    return (
        "inspect",
        "eval",
        "inspect_evals/swe_bench",
        "--sample-id",
        instance_id,
        "--model",
        _inspect_model_string(plan),
        "--solver",
        solver,
        "-S",
        f"version={pin.strip()}",
        "-T",
        f"dataset={artifacts_dir / _INSPECT_DATASET_NAME}",
        "-T",
        f"revision={_SWE_VERIFIED_REVISION}",
        "-T",
        f"image_name_template={template}",
        "--log-dir",
        str(artifacts_dir),
    )


def _canonical_json_list(value: object) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as e:
            raise BenchEvalError(f"SWE list field is not JSON: {e}") from e
    elif isinstance(value, list):
        parsed = value
    else:
        raise BenchEvalError(f"SWE list field has unsupported type {type(value).__name__}")
    if not isinstance(parsed, list):
        raise BenchEvalError("SWE list field must decode to a JSON array")
    return json.dumps(parsed, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _inspect_compat_row(row: Mapping[str, object]) -> dict[str, object]:
    converted = dict(row)
    for field in _JSON_LIST_FIELDS:
        if field not in converted:
            raise BenchEvalError(f"official SWE row missing {field}")
        converted[field] = _canonical_json_list(converted[field])
    return converted


def _official_row(row: Mapping[str, object]) -> dict[str, object]:
    converted = dict(row)
    for field in _JSON_LIST_FIELDS:
        value = converted.get(field)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as e:
                raise BenchEvalError(f"official SWE {field} is not JSON: {e}") from e
            if not isinstance(parsed, list):
                raise BenchEvalError(f"official SWE {field} must decode to a JSON array")
            converted[field] = parsed
    return converted


def _hub_cache_root() -> Path:
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError as e:
        raise BenchEvalError("huggingface_hub is required to locate the SWE cache") from e
    return Path(HF_HUB_CACHE)


def _hub_parquet_path() -> Path:
    hub = _hub_cache_root()
    return (
        hub
        / "datasets--SWE-bench--SWE-bench_Verified"
        / "snapshots"
        / _SWE_VERIFIED_REVISION
        / _SWE_SOURCE_PARQUET
    )


def _path_is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (OSError, ValueError):
        return False
    return True


def _resolve_source_parquet(path: Path) -> Path:
    from bencheval.identity_strings import file_sha256

    read_path = path
    if path.is_symlink():
        hub_root = _hub_cache_root()
        try:
            resolved = path.resolve(strict=True)
        except OSError as e:
            raise BenchEvalError(f"SWE parquet symlink does not resolve: {path}") from e
        if not resolved.is_file() or not _path_is_under(resolved, hub_root):
            raise BenchEvalError(f"SWE parquet symlink escapes the hub cache: {path}")
        read_path = resolved
    elif not path.is_file():
        raise BenchEvalError(f"official SWE parquet missing: {path}")
    actual = f"sha256:{file_sha256(read_path)}"
    if actual != _SWE_SOURCE_PARQUET_SHA256:
        raise BenchEvalError(
            f"SWE parquet sha256 drift at {path}: expected {_SWE_SOURCE_PARQUET_SHA256}, "
            f"got {actual}",
        )
    return read_path


def _ensure_source_parquet(source_parquet: Path | None) -> Path:
    if source_parquet is not None:
        return _resolve_source_parquet(source_parquet)
    candidate = _hub_parquet_path()
    if candidate.exists():
        return _resolve_source_parquet(candidate)
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise BenchEvalError(
            "official SWE parquet is not cached and huggingface_hub is unavailable",
        ) from e
    snapshot = Path(
        snapshot_download(
            repo_id=_SWE_VERIFIED_REPO,
            repo_type="dataset",
            revision=_SWE_VERIFIED_REVISION,
        ),
    )
    return _resolve_source_parquet(snapshot / _SWE_SOURCE_PARQUET)


def _plain_value(value: object) -> object:
    to_list = getattr(value, "tolist", None)
    return to_list() if callable(to_list) else value


def _load_official_instance_row(parquet_path: Path, instance_id: str) -> dict[str, object]:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        try:
            from datasets import load_dataset
        except ImportError as e:
            raise BenchEvalError(
                "swebench materialization requires pyarrow or datasets",
            ) from e
        loaded = load_dataset("parquet", data_files=str(parquet_path), split="train")
        rows = [dict(row) for row in loaded if row.get("instance_id") == instance_id]
    else:
        rows = [
            row
            for row in pq.read_table(parquet_path).to_pylist()
            if row.get("instance_id") == instance_id
        ]
    if len(rows) != 1:
        raise BenchEvalError(
            f"official SWE snapshot must contain exactly one row for {instance_id!r}, "
            f"found {len(rows)}",
        )
    return {key: _plain_value(value) for key, value in rows[0].items()}


def _ensure_owned_subdir(parent_fd: int, name: str) -> int:
    try:
        os.mkdir(name, 0o755, dir_fd=parent_fd)
    except FileExistsError:
        pass
    except OSError as e:
        raise BenchEvalError(f"cannot create owned SWE directory {name}: {e}") from e
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError as e:
        raise BenchEvalError(f"cannot open owned SWE directory {name}: {e}") from e


def _write_jsonl_subdir(
    parent_fd: int,
    dir_name: str,
    row: Mapping[str, object],
) -> None:
    subdir_fd = _ensure_owned_subdir(parent_fd, dir_name)
    try:
        write_text_at_exclusive(
            subdir_fd,
            _DATASET_JSONL_NAME,
            json.dumps(row, ensure_ascii=True) + "\n",
        )
    finally:
        os.close(subdir_fd)


def _dockerhub_image_name(instance_id: str, *, arch: str = "x86_64") -> str:
    matched = _INSTANCE_IMAGE_RE.fullmatch(instance_id)
    if matched is None:
        raise BenchEvalError(f"cannot parse SWE instance image fields from {instance_id!r}")
    return f"swebench/sweb.eval.{arch}.{matched['org']}_1776_{matched['repo']}-{matched['issue']}"


def _docker_output(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _parse_repo_digest(image_name: str, raw: str) -> str:
    try:
        digests = json.loads(raw)
    except json.JSONDecodeError as e:
        raise BenchEvalError(f"docker RepoDigests were not JSON for {image_name}") from e
    if not isinstance(digests, list):
        raise BenchEvalError(f"docker RepoDigests were not a list for {image_name}")
    prefix = f"{image_name}@sha256:"
    matches = [
        item.removeprefix(prefix)
        for item in digests
        if isinstance(item, str) and item.startswith(prefix)
    ]
    if len(matches) != 1:
        raise BenchEvalError(f"expected one repo digest for {image_name}, found {len(matches)}")
    digest = matches[0]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise BenchEvalError(f"invalid SWE image digest for {image_name}")
    return digest


def _docker_repo_digest(image_name: str) -> str:
    tagged = f"{image_name}:latest"
    inspected = _docker_output(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", tagged],
    )
    if inspected.returncode != 0:
        pulled = _docker_output(["docker", "pull", tagged])
        if pulled.returncode != 0:
            raise BenchEvalError(f"cannot resolve SWE image {tagged}: {pulled.stderr.strip()}")
        inspected = _docker_output(
            ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", tagged],
        )
    if inspected.returncode != 0:
        raise BenchEvalError(f"docker inspect failed for {tagged}")
    return _parse_repo_digest(image_name, inspected.stdout)


def _bind_execution_image(instance_id: str) -> tuple[str, str]:
    image_name = _dockerhub_image_name(instance_id)
    digest = _docker_repo_digest(image_name)
    epoch_latest = f"ghcr.io/epoch-research/swe-bench.eval.x86_64.{instance_id}:latest"
    subprocess.run(
        ["docker", "tag", f"{image_name}:latest", epoch_latest],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    template = f"swebench/sweb.eval.{{arch}}.{{org}}_1776_{{repo}}-{{issue}}@sha256:{digest}"
    return digest, template


def materialize_swebench_diagnostic_inputs(
    *,
    instance_dir: Path,
    instance_id: str,
    instance_fd: int | None = None,
    source_parquet: Path | None = None,
    bind_image: bool = True,
) -> SwebenchMaterialization:
    """Derive Inspect and official one-row inputs from the pinned parquet."""
    validate_control_plane_instance_id(instance_id)
    parquet = _ensure_source_parquet(source_parquet)
    row = _load_official_instance_row(parquet, instance_id)
    owned_fd = instance_fd is None
    dir_fd = (
        instance_fd
        if instance_fd is not None
        else open_owned_dir_fd(
            instance_dir,
            role=_INSTANCE_DIR_ROLE,
        )
    )
    try:
        _write_jsonl_subdir(dir_fd, _INSPECT_DATASET_NAME, _inspect_compat_row(row))
        _write_jsonl_subdir(dir_fd, _OFFICIAL_DATASET_NAME, _official_row(row))
        digest: str | None = None
        template = _IMAGE_NAME_TEMPLATE
        if bind_image:
            digest, template = _bind_execution_image(instance_id)
        manifest = {
            "source_repo": _SWE_VERIFIED_REPO,
            "source_revision": _SWE_VERIFIED_REVISION,
            "source_file": _SWE_SOURCE_PARQUET,
            "source_sha256": _SWE_SOURCE_PARQUET_SHA256,
            "instance_id": instance_id,
            "pass_to_pass_encoding": "canonical-json-string",
            "fail_to_pass_encoding": "canonical-json-string",
            "image_digest": f"sha256:{digest}" if digest is not None else None,
            "image_name_template": template,
        }
        write_text_at_exclusive(
            dir_fd,
            _TRANSFORM_MANIFEST_NAME,
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
    finally:
        if owned_fd:
            os.close(dir_fd)
    return SwebenchMaterialization(
        source_parquet=str(parquet),
        source_sha256=_SWE_SOURCE_PARQUET_SHA256,
        inspect_dataset=str(instance_dir / _INSPECT_DATASET_NAME),
        official_dataset=str(instance_dir / _OFFICIAL_DATASET_NAME),
        image_digest=f"sha256:{digest}" if digest is not None else None,
        image_name_template=template,
    )


def resolve_swebench_subprocess(command: Sequence[str]) -> tuple[str, ...]:
    """Isolate Inspect generation from official swebench 5.0.1."""
    if not command:
        raise BenchEvalError("empty swebench process command")
    launched = tuple(str(part) for part in command)
    program = launched[0]
    if program == "inspect":
        return (
            "uv",
            "run",
            "--isolated",
            "--extra",
            "eval",
            "--with",
            _INSPECT_GENERATION_SWEBENCH,
            "--",
            *launched,
        )
    if program == "swebench":
        return (
            "uv",
            "run",
            "--isolated",
            "--project",
            str(_repo_root()),
            "--group",
            "swe",
            "--",
            *launched,
        )
    raise BenchEvalError(f"unsupported swebench process {program!r}")


def default_swebench_process_runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
    env: Mapping[str, str] | None = None,
) -> SwebenchCliResult:
    start = time.monotonic()
    argv = resolve_swebench_subprocess(command)
    if env is None:
        raise BenchEvalError(
            "default SWE process runner requires an explicit provider environment",
        )
    child_env = dict(env)
    try:
        proc = subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd is not None else None,
            env=child_env,
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
            f"swebench command timed out after {timeout_sec}s",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"swebench_command": " ".join(argv)},
        ) from e
    except OSError as e:
        elapsed = time.monotonic() - start
        raise AdapterFailureError(
            f"swebench command launch failed: {e}",
            failure_label="runtime_launch_failure",
            latency_sec=elapsed,
            adapter_metadata={"swebench_command": " ".join(argv)},
        ) from e
    return SwebenchCliResult(
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        latency_sec=time.monotonic() - start,
        command=tuple(argv),
    )


def _validate_swe_run_id(run_id: str) -> str:
    if not run_id or not _SWE_RUN_ID_PATTERN.fullmatch(run_id):
        raise BenchEvalError(
            f"invalid swebench run_id {run_id!r}: use alphanumeric, dot, underscore, hyphen",
        )
    return run_id


def _reject_eval_dataset_leaf(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as e:
        raise BenchEvalError(f"official SWE eval dataset is missing: {path}") from e
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise BenchEvalError(
            "official SWE eval dataset must be a real directory, not a symlink",
        )
    leaf = path / _DATASET_JSONL_NAME
    try:
        leaf_info = os.lstat(leaf)
    except OSError as e:
        raise BenchEvalError(f"official SWE eval dataset leaf is missing: {leaf}") from e
    if not stat.S_ISREG(leaf_info.st_mode) or leaf_info.st_nlink != 1:
        raise BenchEvalError(
            "official SWE eval dataset leaf is not a single-link regular file",
        )


def build_swebench_eval_command(
    *,
    instance_id: str,
    predictions_path: Path,
    run_id: str,
    report_dir: Path,
    dataset_path: Path,
) -> tuple[str, ...]:
    validate_control_plane_instance_id(instance_id)
    owned = Path(os.path.abspath(str(Path(report_dir) / _EVAL_INPUT_NAME)))
    actual = Path(os.path.abspath(str(dataset_path)))
    if actual != owned:
        raise BenchEvalError(
            "official SWE eval dataset must be the run-owned eval-input directory",
        )
    if actual.name in _HUB_DATASET_ALIASES or str(dataset_path) in _HUB_DATASET_ALIASES:
        raise BenchEvalError(
            f"official SWE eval rejects Hub alias {dataset_path!s}",
        )
    _reject_eval_dataset_leaf(actual)
    return (
        "swebench",
        "eval",
        str(owned),
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


def _swe_identity_metadata() -> dict[str, str]:
    from bencheval.benchmark_registry import HfDatasetSnapshotIdentity
    from bencheval.identity_strings import catalog_benchmark_identity, swebench_benchmark_identity

    metadata = {
        "evaluator_package": _OFFICIAL_EVALUATOR_PACKAGE,
        "source_repo": _SWE_VERIFIED_REPO,
        "source_revision": _SWE_VERIFIED_REVISION,
        "source_sha256": _SWE_SOURCE_PARQUET_SHA256,
    }
    identity = catalog_benchmark_identity("swe-bench-verified")
    if isinstance(identity, HfDatasetSnapshotIdentity):
        metadata["benchmark_version"] = swebench_benchmark_identity(identity)
    return metadata


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
        file_fd = open_untrusted_regular_leaf(name, dir_fd=instance_fd)
    except OSError:
        return None
    os.close(file_fd)
    return os.path.abspath(artifacts_dir / name)


def _owned_nested_regular_file_path(
    instance_fd: int,
    parts: tuple[str, ...],
    artifacts_dir: Path,
) -> str | None:
    if not parts or any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in parts):
        return None
    current_fd = instance_fd
    opened: list[int] = []
    try:
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)
            if index < len(parts) - 1:
                flags |= os.O_DIRECTORY
            try:
                next_fd = os.open(part, flags, dir_fd=current_fd)
            except OSError:
                return None
            opened.append(next_fd)
            opened_stat = os.fstat(next_fd)
            if index < len(parts) - 1:
                if not stat.S_ISDIR(opened_stat.st_mode):
                    return None
            elif not stat.S_ISREG(opened_stat.st_mode) or opened_stat.st_nlink != 1:
                return None
            current_fd = next_fd
        return os.path.abspath(artifacts_dir.joinpath(*parts))
    finally:
        for file_fd in reversed(opened):
            os.close(file_fd)


@dataclass(frozen=True, slots=True)
class _BoundLeaf:
    digest: str
    dev: int
    ino: int
    data: bytes


def _bind_owned_leaf(instance_fd: int, parts: tuple[str, ...]) -> _BoundLeaf:
    if not parts or any(part in {"", ".", ".."} or "/" in part or "\\" in part for part in parts):
        raise AdapterFailureError(
            "unsafe SWE eval input path",
            failure_label="evidence_corrupt",
        )
    current_fd = instance_fd
    opened: list[int] = []
    try:
        for index, part in enumerate(parts):
            if index < len(parts) - 1:
                flags = (
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | os.O_NONBLOCK
                    | getattr(os, "O_CLOEXEC", 0)
                )
                next_fd = os.open(part, flags, dir_fd=current_fd)
            else:
                next_fd = open_untrusted_regular_leaf(part, dir_fd=current_fd)
            opened.append(next_fd)
            current_fd = next_fd
        info = os.fstat(current_fd)
        data = _read_fd_bytes(current_fd)
        return _BoundLeaf(
            digest=f"sha256:{hashlib.sha256(data).hexdigest()}",
            dev=info.st_dev,
            ino=info.st_ino,
            data=data,
        )
    except OSError as e:
        raise AdapterFailureError(
            f"SWE eval input cannot be bound: {'/'.join(parts)}: {e}",
            failure_label="evidence_corrupt",
        ) from e
    finally:
        for file_fd in reversed(opened):
            os.close(file_fd)


def _materialize_eval_input(instance_fd: int, official: _BoundLeaf) -> _BoundLeaf:
    eval_fd = _ensure_owned_subdir(instance_fd, _EVAL_INPUT_NAME)
    try:
        write_bytes_at_exclusive(eval_fd, _DATASET_JSONL_NAME, official.data)
    finally:
        os.close(eval_fd)
    bound = _bind_owned_leaf(instance_fd, (_EVAL_INPUT_NAME, _DATASET_JSONL_NAME))
    if bound.digest != official.digest:
        raise AdapterFailureError(
            "eval-input bytes drifted from the bound official SWE row",
            failure_label="evidence_corrupt",
        )
    return bound


def _assert_same_leaf(first: _BoundLeaf, second: _BoundLeaf, *, role: str) -> None:
    if first.digest != second.digest or (first.dev, first.ino) != (second.dev, second.ino):
        raise AdapterFailureError(
            f"{role} changed between generation and official evaluation",
            failure_label="evidence_corrupt",
        )


def _swe_identity_artifact_relpaths(
    instance_fd: int,
    instance_dir: Path,
    repo_root: Path,
) -> tuple[str, ...]:
    found: list[str] = []
    nested = (
        (_OFFICIAL_DATASET_NAME, _DATASET_JSONL_NAME),
        (_INSPECT_DATASET_NAME, _DATASET_JSONL_NAME),
    )
    for parts in nested:
        abs_path = _owned_nested_regular_file_path(instance_fd, parts, instance_dir)
        if abs_path is not None:
            found.append(_rel_path(abs_path, repo_root))
    manifest = _owned_regular_file_path(instance_fd, _TRANSFORM_MANIFEST_NAME, instance_dir)
    if manifest is not None:
        found.append(_rel_path(manifest, repo_root))
    eval_names = [name for name in _owned_eval_log_names(instance_fd) if name.startswith(".bound-")]
    if not eval_names:
        eval_names = list(_owned_eval_log_names(instance_fd))
    for name in eval_names:
        found.append(_rel_path(os.path.abspath(instance_dir / name), repo_root))
    return tuple(found)


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


_CODEX_SANDBOX_VERSION = re.compile(r"codex-(\d+\.\d+\.\d+)-")


def _codex_binary_version_from_events(log: object) -> str | None:
    found: set[str] = set()
    for sample in getattr(log, "samples", None) or []:
        for event in getattr(sample, "events", None) or []:
            for text in (getattr(event, "file", None), getattr(event, "cmd", None)):
                if isinstance(text, str):
                    found.update(_CODEX_SANDBOX_VERSION.findall(text))
    if len(found) == 1:
        return found.pop()
    return None


def _inspect_log_solver_version(log: object) -> str | None:
    executed = _codex_binary_version_from_events(log)
    if executed is not None:
        return executed
    eval_obj = getattr(log, "eval", None)
    for args_name in ("solver_args", "solver_args_passed"):
        args = getattr(eval_obj, args_name, None)
        if isinstance(args, Mapping):
            value = args.get("version")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _inspect_runtime_version_from_owned_logs(
    instance_fd: int,
    instance_dir: Path,
) -> str | None:
    try:
        from inspect_ai.log import read_eval_log
    except ImportError:
        return None
    names = [name for name in _owned_eval_log_names(instance_fd) if name.startswith(".bound-")]
    if not names:
        names = list(_owned_eval_log_names(instance_fd))
    for name in names:
        try:
            log = read_eval_log(str(instance_dir / name))
        except (OSError, UnicodeDecodeError, ValueError, TypeError):
            continue
        version = _inspect_log_solver_version(log)
        if version is not None:
            return version
    return None


def _configured_solver_pin(plan: RunPlan) -> str | None:
    if not plan.runtime_id:
        return None
    try:
        runtime = load_runtime_catalog().by_id(plan.runtime_id)
    except (KeyError, BenchEvalError):
        return None
    pin = runtime.versioning.agent_version_pin
    return pin.strip() if pin and pin.strip() else None


def _stamp_swe_runtime_metadata(
    outcome: SwebenchInstanceOutcome,
    *,
    plan: RunPlan,
) -> SwebenchInstanceOutcome:
    extras: dict[str, str] = {}
    pin = _configured_solver_pin(plan)
    if pin:
        extras["configured_solver_version"] = pin
    if not extras:
        return outcome
    return replace(outcome, adapter_metadata={**outcome.adapter_metadata, **extras})


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
            file_fd = open_untrusted_regular_leaf(name, dir_fd=instance_fd)
        except OSError:
            continue
        os.close(file_fd)
        owned.append(name)
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
        source_fd = open_untrusted_regular_leaf(name, dir_fd=instance_fd)
        try:
            bound = _read_fd_bytes(source_fd)
        finally:
            os.close(source_fd)
        bound_name = f".bound-{name}"
        write_bytes_at_exclusive(instance_fd, bound_name, bound)
        row = _prediction_row_from_inspect_log(
            instance_dir / bound_name,
            instance_id=instance_id,
            model_name_or_path=model_name_or_path,
        )
        if row is not None:
            rows.append(row)
    if len(rows) != 1:
        return None
    write_text_at_exclusive(instance_fd, _PREDICTIONS_NAME, json.dumps(rows[0]) + "\n")
    return _owned_regular_file_path(instance_fd, _PREDICTIONS_NAME, instance_dir)


def _standard_prediction_row(row: object, instance_id: str) -> bool:
    if not isinstance(row, dict):
        return False
    model_name = row.get("model_name_or_path")
    model_patch = row.get("model_patch")
    return (
        row.get("instance_id") == instance_id
        and isinstance(model_name, str)
        and bool(model_name)
        and isinstance(model_patch, str)
    )


def _read_standard_prediction(
    *,
    instance_fd: int,
    instance_id: str,
) -> dict[str, object] | None:
    descriptor = -1
    try:
        descriptor = open_untrusted_regular_leaf(_PREDICTIONS_NAME, dir_fd=instance_fd)
        handle = os.fdopen(descriptor, encoding="utf-8")
        descriptor = -1
        with handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    rows: list[object] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            return None
    if len(rows) != 1 or not _standard_prediction_row(rows[0], instance_id):
        return None
    row = rows[0]
    return row if isinstance(row, dict) else None


def _has_exactly_one_standard_prediction(*, instance_fd: int, instance_id: str) -> bool:
    return _read_standard_prediction(instance_fd=instance_fd, instance_id=instance_id) is not None


def _schema_v2_incoherent(
    summary: dict[str, object],
    *,
    instance_id: str,
    resolved: bool | None,
) -> bool:
    if summary.get("schema_version") != 2:
        return True
    resolved_ids = summary.get("resolved_ids")
    unresolved_ids = summary.get("unresolved_ids")
    empty_patch_ids = summary.get("empty_patch_ids")
    if not isinstance(resolved_ids, list) or not isinstance(unresolved_ids, list):
        return True
    in_resolved = instance_id in resolved_ids
    in_unresolved = instance_id in unresolved_ids
    in_empty = isinstance(empty_patch_ids, list) and instance_id in empty_patch_ids
    if in_resolved and in_unresolved:
        return True
    invalid_ids = summary.get("error_ids")
    infra_ids = summary.get("infra_failure_ids")
    ambiguous_ids = summary.get("ambiguous_failure_ids")
    for bucket in (invalid_ids, infra_ids, ambiguous_ids):
        if isinstance(bucket, list) and instance_id in bucket:
            return True
    if in_empty:
        return resolved is True or in_resolved
    if resolved is None:
        return True
    if resolved:
        return not in_resolved or in_unresolved
    return not in_unresolved or in_resolved


def _schema_v2_report_name(model_name_or_path: str, run_id: str) -> str | None:
    """Official swebench 5.0.1 replaces ``/`` with ``__`` in the summary filename."""
    sanitized = model_name_or_path.replace("/", "__")
    name = f"{sanitized}.{run_id}.json"
    if "/" in name or name in ("", ".", ".."):
        return None
    return name


def _apply_schema_v2_coherence(
    outcome: SwebenchInstanceOutcome,
    *,
    instance_fd: int,
    instance_dir: Path,
    repo_root: Path,
    instance_id: str,
    model_name_or_path: str,
    run_id: str,
) -> SwebenchInstanceOutcome:
    resolved = outcome.native_score.get("resolved")
    resolved_bool = resolved if isinstance(resolved, bool) else None
    report_name = _schema_v2_report_name(model_name_or_path, run_id)
    if report_name is None:
        return replace(
            outcome,
            primary_pass=False,
            partial_score=0.0,
            failure_class="runtime_output_unparseable",
        )
    present, parsed = read_json_at_nofollow(instance_fd, report_name)
    if not present:
        if resolved_bool is not None:
            return replace(
                outcome,
                primary_pass=False,
                partial_score=0.0,
                failure_class="runtime_output_unparseable",
            )
        return outcome
    summary_path = _rel_path(os.path.abspath(instance_dir / report_name), repo_root)
    if isinstance(parsed, dict) and not _schema_v2_incoherent(
        parsed,
        instance_id=instance_id,
        resolved=resolved_bool,
    ):
        if resolved_bool is None:
            return replace(
                outcome,
                primary_pass=False,
                partial_score=0.0,
                failure_class="model_wrong_solution",
                native_score={**outcome.native_score, "empty_patch": True},
                summary_path=summary_path,
            )
        return replace(outcome, summary_path=summary_path)
    return replace(
        outcome,
        primary_pass=False,
        partial_score=0.0,
        failure_class="runtime_output_unparseable",
        summary_path=summary_path,
    )


def _read_fd_bytes(file_fd: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(file_fd, 1024 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _read_nested_eval_report_bytes(
    instance_fd: int,
    *,
    instance_id: str,
    run_id: str,
) -> bytes | None:
    owned: list[int] = []
    current = instance_fd
    try:
        for part in ("logs", "run_evaluation", run_id):
            try:
                nxt = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current,
                )
            except OSError:
                return None
            owned.append(nxt)
            current = nxt
        try:
            model_names = os.listdir(current)
        except OSError:
            return None
        matches: list[bytes] = []
        for model_name in model_names:
            model_fd = -1
            inst_fd = -1
            report_fd = -1
            try:
                model_fd = os.open(
                    model_name,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current,
                )
                inst_fd = os.open(
                    instance_id,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=model_fd,
                )
                report_fd = os.open(
                    _OFFICIAL_REPORT_NAME,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=inst_fd,
                )
                opened = os.fstat(report_fd)
                if not stat.S_ISREG(opened.st_mode):
                    raise AdapterFailureError(
                        "official SWE report is not a regular file",
                        failure_label="evidence_corrupt",
                    )
                if opened.st_nlink != 1:
                    raise AdapterFailureError(
                        "official SWE report is hardlinked",
                        failure_label="evidence_corrupt",
                    )
                matches.append(_read_fd_bytes(report_fd))
            except AdapterFailureError:
                raise
            except OSError:
                continue
            finally:
                for handle in (report_fd, inst_fd, model_fd):
                    if handle >= 0:
                        os.close(handle)
        if len(matches) != 1:
            return None
        return matches[0]
    finally:
        for handle in reversed(owned):
            os.close(handle)


def _materialize_official_instance_report(
    *,
    instance_dir: Path,
    instance_fd: int,
    instance_id: str,
    run_id: str,
) -> None:
    if _owned_regular_file_path(instance_fd, _OFFICIAL_REPORT_NAME, instance_dir):
        return
    data = _read_nested_eval_report_bytes(
        instance_fd,
        instance_id=instance_id,
        run_id=run_id,
    )
    if data is None:
        return
    write_bytes_at_exclusive(instance_fd, _OFFICIAL_REPORT_NAME, data)
    owned = _owned_regular_file_path(instance_fd, _OFFICIAL_REPORT_NAME, instance_dir)
    if owned is None:
        raise AdapterFailureError(
            "retained official SWE report is missing after copy",
            failure_label="evidence_corrupt",
        )
    written_fd = open_untrusted_regular_leaf(_OFFICIAL_REPORT_NAME, dir_fd=instance_fd)
    try:
        written = _read_fd_bytes(written_fd)
    finally:
        os.close(written_fd)
    if written != data:
        raise AdapterFailureError(
            "retained official SWE report bytes do not match the scored bytes",
            failure_label="evidence_corrupt",
        )


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
        **_swe_identity_metadata(),
    }
    metadata["harness_version"] = harness_version or _OFFICIAL_EVALUATOR_PACKAGE
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
        identity_artifact_paths=_swe_identity_artifact_relpaths(
            instance_fd,
            instance_dir,
            repo_root,
        ),
    )


def _official_instance_report(
    instance_fd: int,
    instance_id: str,
    artifacts_dir: Path,
) -> tuple[bool, dict[str, object], str] | None:
    if _owned_regular_file_path(instance_fd, _OFFICIAL_REPORT_NAME, artifacts_dir) is None:
        return None
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
        predictions_path = _owned_regular_file_path(
            instance_fd,
            _PREDICTIONS_NAME,
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
            **_swe_identity_metadata(),
        }
        metadata["harness_version"] = harness_version or _OFFICIAL_EVALUATOR_PACKAGE
        observed = _inspect_runtime_version_from_owned_logs(instance_fd, artifacts_dir)
        if observed:
            metadata["inspect_runtime_version"] = observed
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
            predictions_path=_rel_path(predictions_path, repo_root) if predictions_path else None,
            identity_artifact_paths=_swe_identity_artifact_relpaths(
                instance_fd,
                artifacts_dir,
                repo_root,
            ),
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
    materialize_inputs: bool,
) -> SwebenchInstanceOutcome:
    template = _IMAGE_NAME_TEMPLATE
    if materialize_inputs:
        materialized = materialize_swebench_diagnostic_inputs(
            instance_dir=instance_dir,
            instance_id=instance_id,
            instance_fd=instance_fd,
        )
        template = materialized.image_name_template
    generate = build_swebench_run_command(
        plan=plan,
        instance_id=instance_id,
        artifacts_dir=instance_dir,
        image_name_template=template,
    )
    started = time.monotonic()
    generation = runner(generate, cwd=repo_root, timeout_sec=wall)
    _reject_instance_swap(instance_dir=instance_dir, instance_fd=instance_fd, cli=generation)
    elapsed = max(generation.latency_sec, time.monotonic() - started)
    remaining = wall - elapsed
    if generation.returncode != 0:
        return _score_swe_phase(
            instance_id=instance_id,
            cli=generation,
            instance_dir=instance_dir,
            repo_root=repo_root,
            harness_version=harness_version,
            instance_fd=instance_fd,
        )
    if remaining < 1:
        raise AdapterFailureError(
            "no remaining wall budget for official SWE-bench evaluation",
            failure_label="runtime_budget_exceeded",
            latency_sec=elapsed,
            adapter_metadata={"swebench_command": " ".join(generate)},
        )
    predictions = _ensure_official_predictions(
        instance_dir=instance_dir,
        instance_fd=instance_fd,
        instance_id=instance_id,
        model_name_or_path=plan.model_id,
    )
    prediction = _read_standard_prediction(
        instance_fd=instance_fd,
        instance_id=instance_id,
    )
    if predictions is None or prediction is None:
        return _missing_predictions_outcome(
            instance_id=instance_id,
            cli=generation,
            instance_dir=instance_dir,
            repo_root=repo_root,
            harness_version=harness_version,
            instance_fd=instance_fd,
        )
    model_name = prediction.get("model_name_or_path")
    if not isinstance(model_name, str) or not model_name:
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
        remaining=remaining,
        harness_version=harness_version,
        run_id=run_id,
        model_name_or_path=model_name,
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
    remaining: float,
    harness_version: str | None,
    run_id: str,
    model_name_or_path: str,
    generation: SwebenchCliResult,
    predictions: str,
) -> SwebenchInstanceOutcome:
    _clear_owned_name(instance_fd, _OFFICIAL_REPORT_NAME)
    official = _bind_owned_leaf(instance_fd, (_OFFICIAL_DATASET_NAME, _DATASET_JSONL_NAME))
    bound_predictions = _bind_owned_leaf(instance_fd, (_PREDICTIONS_NAME,))
    eval_input = _materialize_eval_input(instance_fd, official)
    evaluate = build_swebench_eval_command(
        instance_id=instance_id,
        predictions_path=Path(predictions),
        run_id=run_id,
        report_dir=instance_dir,
        dataset_path=instance_dir / _EVAL_INPUT_NAME,
    )
    if remaining < 1:
        raise AdapterFailureError(
            "no remaining wall budget for official SWE-bench evaluation",
            failure_label="runtime_budget_exceeded",
            latency_sec=generation.latency_sec,
            adapter_metadata={"swebench_command": " ".join(evaluate)},
        )
    scored = runner(evaluate, cwd=instance_dir, timeout_sec=int(remaining))
    _assert_same_leaf(
        official,
        _bind_owned_leaf(instance_fd, (_OFFICIAL_DATASET_NAME, _DATASET_JSONL_NAME)),
        role="official-dataset",
    )
    _assert_same_leaf(
        eval_input,
        _bind_owned_leaf(instance_fd, (_EVAL_INPUT_NAME, _DATASET_JSONL_NAME)),
        role="eval-input",
    )
    _assert_same_leaf(
        bound_predictions,
        _bind_owned_leaf(instance_fd, (_PREDICTIONS_NAME,)),
        role="predictions",
    )
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
    outcome = _score_swe_phase(
        instance_id=instance_id,
        cli=scored,
        instance_dir=instance_dir,
        repo_root=repo_root,
        harness_version=harness_version,
        instance_fd=instance_fd,
    )
    return _apply_schema_v2_coherence(
        outcome,
        instance_fd=instance_fd,
        instance_dir=instance_dir,
        repo_root=repo_root,
        instance_id=instance_id,
        model_name_or_path=model_name_or_path,
        run_id=run_id,
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
    materialize_inputs: bool = False,
) -> SwebenchInstanceOutcome:
    if plan.adapter_id != SWEBENCH_ADAPTER_ID:
        raise BenchEvalError(f"swebench adapter cannot run adapter_id={plan.adapter_id!r}")
    if process_runner is None:
        raise BenchEvalError(
            "swebench default process runner is disabled until the diagnostic "
            "can be charged with a materialized dataset; inject a process_runner",
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
        return _stamp_swe_runtime_metadata(
            _run_generation_then_eval(
                plan=plan,
                instance_id=instance_id,
                instance_dir=instance_dir,
                instance_fd=instance_fd,
                repo_root=repo_root,
                runner=process_runner,
                wall=wall,
                harness_version=harness_version,
                run_id=_validate_swe_run_id(run_id) if run_id is not None else new_run_id(),
                materialize_inputs=materialize_inputs,
            ),
            plan=plan,
        )
    finally:
        os.close(instance_fd)


__all__ = [
    "SWEBENCH_ADAPTER_ID",
    "SwebenchCliResult",
    "SwebenchInstanceOutcome",
    "SwebenchMaterialization",
    "SwebenchProcessRunner",
    "build_swebench_eval_command",
    "build_swebench_run_command",
    "default_swebench_process_runner",
    "materialize_swebench_diagnostic_inputs",
    "parse_swebench_instance_outcome",
    "resolve_swebench_subprocess",
    "run_swebench_instance",
]
