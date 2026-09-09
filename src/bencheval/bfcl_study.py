"""BFCL tool-order materializer and run-owned package-data overlay.

One deterministic, balanced, non-identity rotation of each row's ``function``
list for the declared ``multiple``/``parallel_multiple`` files, staged as a
byte-identical copy of the pinned ``bfcl_eval`` package whose only differences
are those two data files. The unchanged official CLI then runs from the copy
via ``PYTHONPATH``; nothing here scores, mutates site-packages, or generalizes
into a transform framework (X0.2 proved the loader route on 2026-09-07).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from bencheval.benchmark_registry import BfclDerivedDataRef, BfclPackageDataIdentity
from bencheval.exceptions import BenchEvalError

if TYPE_CHECKING:
    from bencheval.bfcl_package import StagedPackage
from bencheval.exposure_selection import ExposureSelection
from bencheval.exposure_study import BfclDerivedDataIdentity, ExposureStudyManifest

TOOL_ORDER_TRANSFORM_ID = "bfcl-tool-order"
TOOL_ORDER_TRANSFORM_VERSION = "1"
BALANCE_ALGORITHM = "sha256_rotate_v1"
TOOL_ORDER_CATEGORIES: tuple[str, ...] = ("multiple", "parallel_multiple")
OVERLAY_PACKAGE_PARENT = "pkg"
OVERLAY_PACKAGE_NAME = "bfcl_eval"
OVERLAY_DIR = "overlay"
VARIANT_MANIFEST_FILE = "variant-manifest.json"
VARIANT_MANIFEST_SCHEMA = "bfcl-variant-manifest-v1"
_QUESTION_FILE = "data/BFCL_v4_{category}.json"
_ROW_KEYS = frozenset({"id", "question", "function"})
_SKIP_DIRS = frozenset({"__pycache__"})


# --- balanced rotation -----------------------------------------------------------


def rotation_offset(*, seed: str, instance_id: str, function_count: int) -> int:
    """Frozen ``sha256_rotate_v1``: ``1 + sha256([algo, seed, id]) mod (k-1)``."""
    if function_count < 2:
        raise BenchEvalError(
            f"{instance_id}: a balanced rotation needs at least two functions "
            f"(got {function_count})",
        )
    payload = json.dumps(
        [BALANCE_ALGORITHM, seed, instance_id], separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return 1 + int(hashlib.sha256(payload).hexdigest(), 16) % (function_count - 1)


def permute_functions[T](functions: Sequence[T], offset: int) -> list[T]:
    """Rotate left by ``offset`` (a non-identity rotation for ``0 < offset < len``)."""
    if not 0 < offset < len(functions):
        raise BenchEvalError(
            f"rotation offset {offset} is not a non-identity rotation of {len(functions)} tools",
        )
    return [*functions[offset:], *functions[:offset]]


def derive_tool_order_text(text: str, *, seed: str, category: str) -> tuple[str, dict[str, int]]:
    """Rewrite every row's ``function`` order; everything else stays byte-identical.

    Returns the derived JSONL text and the offset applied per instance id. Rows
    are validated strictly: exactly ``id``/``question``/``function`` keys, ids of
    the declared category, unique ids, at least two uniquely named tools.
    """
    rows: list[dict[str, object]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as e:
            raise BenchEvalError(f"{category}: line {number} is not JSON: {e}") from e
        if not isinstance(row, dict):
            raise BenchEvalError(f"{category}: line {number} is not a JSON object")
        rows.append(row)
    if not rows:
        raise BenchEvalError(f"{category}: source file holds no rows")
    seen: set[str] = set()
    out: list[str] = []
    offsets: dict[str, int] = {}
    for row in rows:
        instance_id = row.get("id")
        if not isinstance(instance_id, str) or not instance_id:
            raise BenchEvalError(f"{category}: a row has no string id")
        functions = row.get("function")
        if not isinstance(functions, list):
            raise BenchEvalError(f"{instance_id}: row has no function list")
        if set(row) != _ROW_KEYS:
            raise BenchEvalError(
                f"{instance_id}: row keys {sorted(row)} are not exactly {sorted(_ROW_KEYS)}",
            )
        if not instance_id.startswith(f"{category}_"):
            raise BenchEvalError(f"{instance_id}: id is not in category {category!r}")
        if instance_id in seen:
            raise BenchEvalError(f"{category}: duplicate instance id {instance_id!r}")
        seen.add(instance_id)
        names = [f.get("name") if isinstance(f, dict) else None for f in functions]
        if any(not isinstance(n, str) or not n for n in names) or len(set(names)) != len(names):
            raise BenchEvalError(f"{instance_id}: tool names must be unique non-empty strings")
        offset = rotation_offset(seed=seed, instance_id=instance_id, function_count=len(functions))
        offsets[instance_id] = offset
        derived = {**row, "function": permute_functions(functions, offset)}
        out.append(json.dumps(derived, ensure_ascii=False))
    return "\n".join(out) + "\n", offsets


# --- tree digests ------------------------------------------------------------------


def tree_digests(root: Path) -> dict[str, str]:
    """sha256 hex per regular file under ``root`` (lstat walk; links fail closed)."""
    if root.is_symlink() or not root.is_dir():
        raise BenchEvalError(f"package tree {root} is a symlink or not a directory")
    out: dict[str, str] = {}
    for current, dirs, files in os.walk(root):
        base = Path(current)
        dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
        for name in dirs:
            if (base / name).is_symlink():
                raise BenchEvalError(f"package tree contains a symlink: {base / name}")
        for name in sorted(files):
            path = base / name
            info = os.lstat(path)
            if os.path.islink(path):
                raise BenchEvalError(f"package tree contains a symlink: {path}")
            if not os.path.isfile(path):
                raise BenchEvalError(f"package tree contains a non-regular file: {path}")
            del info
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            out[path.relative_to(root).as_posix()] = digest.hexdigest()
    return out


def _require_single_links(root: Path) -> None:
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            path = Path(current) / name
            if os.lstat(path).st_nlink != 1:
                raise BenchEvalError(f"overlay file is a hard link into another tree: {path}")


def derived_data_sha256(derived_files: Mapping[str, str]) -> str:
    from bencheval.identity_strings import combined_data_sha256

    return f"sha256:{combined_data_sha256(dict(derived_files))}"


# --- overlay -----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ToolOrderOverlay:
    """A materialized run-owned copy of the pinned package with derived data."""

    root: Path
    package_dir: Path
    pythonpath: Path
    seed: str
    derived_files: dict[str, str]  # rel -> sha256:<hex>
    offsets: dict[str, dict[str, int]]  # category -> instance id -> offset
    code_digests: dict[str, str]  # every non-derived rel -> hex digest
    # Files a configured registration changed in the shared staged copy
    # (rel -> hex); pinned to the staging digest, exempt from installed equality.
    registered_files: dict[str, str] = field(default_factory=dict)

    @property
    def derived_data_sha256(self) -> str:
        return derived_data_sha256(self.derived_files)


def _declared_rel(category: str) -> str:
    return _QUESTION_FILE.format(category=category)


def question_file_for(instance_id: str) -> str:
    """Package-relative data file a tool-order derived instance must be read from."""
    category = instance_id.rsplit("_", 1)[0]
    if category not in TOOL_ORDER_CATEGORIES:
        raise BenchEvalError(
            f"{instance_id!r} is not in a tool-order category {sorted(TOOL_ORDER_CATEGORIES)}"
        )
    return _declared_rel(category)


def materialize_tool_order_overlay(
    *,
    package_root: Path,
    identity: BfclPackageDataIdentity,
    seed: str,
    output_root: Path,
    staged: StagedPackage | None = None,
) -> ToolOrderOverlay:
    """Copy the pinned package to ``output_root/pkg/bfcl_eval`` and derive the data.

    Fails closed before writing anything when the installed pins drift, the
    source tree carries links, or the output root is not exclusively ours.
    With ``staged`` (a configured registration already copied by
    ``bfcl_package``), the derived data is written into that same copy and the
    registry file is pinned to its staged digest instead of the installed one.
    """
    from bencheval.bfcl_native_adapter import verify_bfcl_package_data

    verify_bfcl_package_data(package_root=package_root, files=identity.files)
    for category in TOOL_ORDER_CATEGORIES:
        if _declared_rel(category) not in identity.files:
            raise BenchEvalError(
                f"{_declared_rel(category)} is not pinned by the catalog identity; refusing to "
                "derive from unpinned data",
            )
    source_digests = tree_digests(package_root)
    registered_files: dict[str, str] = {}
    if staged is None:
        if output_root.is_symlink() or (output_root.exists() and any(output_root.iterdir())):
            raise BenchEvalError(f"overlay root is not an exclusive empty directory: {output_root}")
        parent = output_root / OVERLAY_PACKAGE_PARENT
        package_dir = parent / OVERLAY_PACKAGE_NAME
        parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            package_root, package_dir, symlinks=False, ignore=shutil.ignore_patterns("__pycache__")
        )
    else:
        from bencheval.bfcl_package import REGISTRATION_FILE

        if staged.root != output_root:
            raise BenchEvalError("staged package root is not the overlay root")
        parent, package_dir = staged.pythonpath, staged.package_dir
        registered_files[REGISTRATION_FILE] = staged.staged_registry_sha256.removeprefix("sha256:")
        source_digests = {**source_digests, **registered_files}
    derived_files: dict[str, str] = {}
    offsets: dict[str, dict[str, int]] = {}
    for category in TOOL_ORDER_CATEGORIES:
        rel = _declared_rel(category)
        target = package_dir / rel
        derived, per_row = derive_tool_order_text(
            target.read_text(encoding="utf-8"), seed=seed, category=category
        )
        target.unlink()
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(derived)
            handle.flush()
            os.fsync(handle.fileno())
        derived_files[rel] = "sha256:" + hashlib.sha256(derived.encode("utf-8")).hexdigest()
        offsets[category] = per_row
    _require_single_links(package_dir)
    overlay_digests = tree_digests(package_dir)
    code_digests = {rel: d for rel, d in overlay_digests.items() if rel not in derived_files}
    if code_digests != {rel: d for rel, d in source_digests.items() if rel not in derived_files}:
        raise BenchEvalError("overlay copy does not match the installed package bytes")
    return ToolOrderOverlay(
        root=output_root,
        package_dir=package_dir,
        pythonpath=parent,
        seed=seed,
        derived_files=derived_files,
        offsets=offsets,
        code_digests=code_digests,
        registered_files=registered_files,
    )


def verify_tool_order_overlay(
    overlay: ToolOrderOverlay,
    *,
    package_root: Path,
    identity: BfclPackageDataIdentity,
) -> None:
    """Re-prove the overlay and the installed tree before and after each phase."""
    from bencheval.bfcl_native_adapter import verify_bfcl_package_data

    verify_bfcl_package_data(package_root=package_root, files=identity.files)
    installed = tree_digests(package_root)
    _require_single_links(overlay.package_dir)
    current = tree_digests(overlay.package_dir)
    expected = {**overlay.code_digests}
    for rel, pin in overlay.derived_files.items():
        expected[rel] = pin.removeprefix("sha256:")
    missing = sorted(set(expected) - set(current))
    extra = sorted(set(current) - set(expected))
    if missing:
        raise BenchEvalError(f"overlay is missing files: {missing}")
    if extra:
        raise BenchEvalError(f"overlay contains extra files: {extra}")
    for rel in sorted(expected):
        if current[rel] != expected[rel]:
            raise BenchEvalError(f"overlay file drifted from its materialized bytes: {rel}")
        if rel in overlay.registered_files:
            if current[rel] != overlay.registered_files[rel]:
                raise BenchEvalError(f"registered file drifted from its staged bytes: {rel}")
            continue
        if rel not in overlay.derived_files and installed.get(rel) != current[rel]:
            raise BenchEvalError(f"overlay file no longer matches the installed package: {rel}")
    if set(installed) != set(current):
        raise BenchEvalError("installed package file set differs from the overlay copy")


# --- run-owned derived execution -------------------------------------------------


@dataclass(frozen=True, slots=True)
class DerivedSource:
    """Everything a derived BFCL run needs, resolved from the catalog and installed package.

    Tests may construct one directly for an injected process runner; the real
    path always resolves it through :func:`resolve_derived_source`.
    """

    ref: BfclDerivedDataRef
    source_identity: BfclPackageDataIdentity
    study: ExposureStudyManifest
    selection: ExposureSelection
    package_root: Path


@dataclass(frozen=True, slots=True)
class DerivedRun:
    overlay: ToolOrderOverlay
    identity: BfclDerivedDataIdentity
    benchmark_version: str
    artifact_paths: tuple[str, ...]
    variant_manifest_text: str


def derived_ref_for(benchmark_id: str) -> BfclDerivedDataRef | None:
    from bencheval.identity_strings import catalog_benchmark_identity

    identity = catalog_benchmark_identity(benchmark_id)
    return identity if isinstance(identity, BfclDerivedDataRef) else None


def resolve_derived_source(
    benchmark_id: str, *, package_root: Path | None = None
) -> DerivedSource | None:
    """Bind a derived benchmark to its source pins, study, and selection; None if not derived."""
    from bencheval.exposure_selection import (
        load_exposure_selection,
        verify_selection_against_catalog,
        verify_selection_for_study,
    )
    from bencheval.exposure_study import default_studies_dir, load_exposure_study
    from bencheval.identity_strings import catalog_benchmark_identity

    ref = derived_ref_for(benchmark_id)
    if ref is None:
        return None
    if (
        ref.transform_id != TOOL_ORDER_TRANSFORM_ID
        or ref.transform_version != TOOL_ORDER_TRANSFORM_VERSION
    ):
        raise BenchEvalError(
            f"{benchmark_id}: unsupported transform {ref.transform_id}@{ref.transform_version}"
        )
    source_identity = catalog_benchmark_identity(ref.source_benchmark_id)
    if not isinstance(source_identity, BfclPackageDataIdentity):
        raise BenchEvalError(
            f"{benchmark_id}: source {ref.source_benchmark_id!r} has no package-data identity"
        )
    study = load_exposure_study(ref.study_id)
    _require_study_matches_ref(study, ref, benchmark_id=benchmark_id)
    selection = load_exposure_selection(default_studies_dir() / f"{study.id}.selection.json")
    verify_selection_for_study(study, selection)
    verify_selection_against_catalog(selection)
    if package_root is None:
        from bencheval.bfcl_native_adapter import _bfcl_package_root

        package_root = _bfcl_package_root()
    return DerivedSource(
        ref=ref,
        source_identity=source_identity,
        study=study,
        selection=selection,
        package_root=package_root,
    )


def _require_study_matches_ref(
    study: ExposureStudyManifest, ref: BfclDerivedDataRef, *, benchmark_id: str
) -> None:
    variant = study.variant
    if study.kind != "representation_pair" or variant is None:
        raise BenchEvalError(f"{benchmark_id}: study {study.id!r} is not a representation pair")
    if (
        study.candidate.benchmark_id != benchmark_id
        or study.canonical.benchmark_id != ref.source_benchmark_id
        or variant.transform_id != ref.transform_id
        or variant.transform_version != ref.transform_version
        or variant.balance_algorithm != BALANCE_ALGORITHM
        or tuple(variant.source_categories) != TOOL_ORDER_CATEGORIES
    ):
        raise BenchEvalError(
            f"{benchmark_id}: study {study.id!r} does not declare this derived benchmark's "
            "source, transform, balance algorithm, and categories",
        )


def _derived_identity(source: DerivedSource, overlay: ToolOrderOverlay) -> BfclDerivedDataIdentity:
    from bencheval.exposure_study import build_bfcl_derived_data_identity

    selected = source.selection.candidate.selected_ids
    return build_bfcl_derived_data_identity(
        study=source.study,
        source_identity=source.source_identity,
        source_mapping={instance_id: instance_id for instance_id in selected},
        derived_data_sha256=overlay.derived_data_sha256,
    )


def render_variant_manifest(identity: BfclDerivedDataIdentity, overlay: ToolOrderOverlay) -> str:
    from bencheval.identity_strings import bfcl_derived_benchmark_identity

    payload = {
        "schema_version": VARIANT_MANIFEST_SCHEMA,
        "benchmark_version": bfcl_derived_benchmark_identity(identity),
        "identity": identity.model_dump(mode="json"),
        "overlay": {
            "pythonpath": f"{OVERLAY_DIR}/{OVERLAY_PACKAGE_PARENT}",
            "package_dir": f"{OVERLAY_DIR}/{OVERLAY_PACKAGE_PARENT}/{OVERLAY_PACKAGE_NAME}",
            "seed": overlay.seed,
            "balance_algorithm": BALANCE_ALGORITHM,
            "derived_files": dict(sorted(overlay.derived_files.items())),
            "offsets": {k: dict(sorted(v.items())) for k, v in sorted(overlay.offsets.items())},
            "code_digests": dict(sorted(overlay.code_digests.items())),
        },
    }
    if overlay.registered_files:
        # Only present when the copy also carries a configured registration.
        payload["overlay"]["registered_files"] = dict(sorted(overlay.registered_files.items()))  # type: ignore[index]
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def parse_variant_manifest(
    text: str, *, artifacts_dir: Path
) -> tuple[BfclDerivedDataIdentity, ToolOrderOverlay]:
    """Rebuild the identity and overlay description from a retained manifest."""
    from pydantic import ValidationError

    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise BenchEvalError(f"variant manifest is not JSON: {e}") from e
    if not isinstance(raw, dict) or raw.get("schema_version") != VARIANT_MANIFEST_SCHEMA:
        raise BenchEvalError("variant manifest schema is not bfcl-variant-manifest-v1")
    try:
        identity = BfclDerivedDataIdentity.model_validate(raw.get("identity"))
    except ValidationError as e:
        raise BenchEvalError(f"variant manifest identity is invalid: {e}") from e
    ov = raw.get("overlay")
    if not isinstance(ov, dict):
        raise BenchEvalError("variant manifest has no overlay section")
    try:
        overlay = ToolOrderOverlay(
            root=artifacts_dir / OVERLAY_DIR,
            package_dir=artifacts_dir / str(ov["package_dir"]),
            pythonpath=artifacts_dir / str(ov["pythonpath"]),
            seed=str(ov["seed"]),
            derived_files={str(k): str(v) for k, v in dict(ov["derived_files"]).items()},
            offsets={
                str(k): {str(i): int(o) for i, o in dict(v).items()}
                for k, v in dict(ov["offsets"]).items()
            },
            code_digests={str(k): str(v) for k, v in dict(ov["code_digests"]).items()},
            registered_files={
                str(k): str(v) for k, v in dict(ov.get("registered_files") or {}).items()
            },
        )
    except (KeyError, TypeError, ValueError) as e:
        raise BenchEvalError(f"variant manifest overlay section is malformed: {e}") from e
    if overlay.derived_data_sha256 != identity.derived_data_sha256:
        raise BenchEvalError("variant manifest derived data digest does not match its identity")
    return identity, overlay


def prepare_tool_order_run(
    *,
    artifacts_dir: Path,
    source: DerivedSource,
    repo_root: Path,
    staged: StagedPackage | None = None,
) -> DerivedRun:
    """Materialize the run-owned overlay once per run, or re-verify an existing one.

    The first instance creates ``overlay/`` and ``study/variant-manifest.json``;
    every later instance rebuilds the description from the retained manifest,
    re-verifies overlay and installed bytes, and requires the manifest bytes to
    replay exactly. Nothing here launches or scores.
    """
    from bencheval.identity_strings import bfcl_derived_benchmark_identity
    from bencheval.run_isolation import (
        open_owned_dir_fd,
        open_untrusted_regular_leaf,
        write_text_at_exclusive,
    )

    overlay_root = artifacts_dir / OVERLAY_DIR
    study_dir = artifacts_dir / "study"
    study_fd = open_owned_dir_fd(study_dir, role="bfcl study artifacts directory")
    try:
        existing: bytes | None = None
        try:
            fd = open_untrusted_regular_leaf(VARIANT_MANIFEST_FILE, dir_fd=study_fd)
        except FileNotFoundError:
            fd = None
        except OSError as e:
            raise BenchEvalError(f"variant manifest is not a plain single-link file: {e}") from e
        if fd is not None:
            with os.fdopen(fd, "rb") as handle:
                existing = handle.read()
        if existing is None:
            if staged is None and (overlay_root.exists() or overlay_root.is_symlink()):
                raise BenchEvalError("overlay exists without its retained variant manifest")
            overlay = materialize_tool_order_overlay(
                package_root=source.package_root,
                identity=source.source_identity,
                seed=source.study.population.seed,
                output_root=overlay_root,
                staged=staged,
            )
            identity = _derived_identity(source, overlay)
            text = render_variant_manifest(identity, overlay)
            write_text_at_exclusive(study_fd, VARIANT_MANIFEST_FILE, text)
        else:
            text = existing.decode("utf-8")
            identity, overlay = parse_variant_manifest(text, artifacts_dir=artifacts_dir)
            if identity != _derived_identity(source, overlay):
                raise BenchEvalError(
                    "retained variant manifest does not bind this run's source, study, "
                    "and selection"
                )
            expected_registered = (
                {}
                if staged is None
                else {"constants/model_config.py": staged.staged_registry_sha256[7:]}
            )
            if overlay.registered_files != expected_registered:
                raise BenchEvalError(
                    "retained variant manifest does not bind this run's configured registration"
                )
            if render_variant_manifest(identity, overlay) != text:
                raise BenchEvalError("retained variant manifest bytes do not replay")
            verify_tool_order_overlay(
                overlay, package_root=source.package_root, identity=source.source_identity
            )
    finally:
        os.close(study_fd)
    rel = _relative_artifact_paths(repo_root, artifacts_dir, overlay)
    return DerivedRun(
        overlay=overlay,
        identity=identity,
        benchmark_version=bfcl_derived_benchmark_identity(identity),
        artifact_paths=rel,
        variant_manifest_text=text,
    )


def _relative_artifact_paths(
    repo_root: Path, artifacts_dir: Path, overlay: ToolOrderOverlay
) -> tuple[str, ...]:
    from bencheval.bfcl_native_adapter import _rel_path

    paths = [str(artifacts_dir / "study" / VARIANT_MANIFEST_FILE)]
    paths.extend(str(overlay.package_dir / rel) for rel in sorted(overlay.derived_files))
    return tuple(_rel_path(path, repo_root) for path in paths)


def launch_environment_for(overlay: ToolOrderOverlay, base: Mapping[str, str]) -> dict[str, str]:
    """The official CLI imports ``bfcl_eval`` from the overlay; no bytecode is written."""
    env = dict(base)
    env["PYTHONPATH"] = str(overlay.pythonpath)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


__all__ = [
    "BALANCE_ALGORITHM",
    "OVERLAY_DIR",
    "OVERLAY_PACKAGE_NAME",
    "OVERLAY_PACKAGE_PARENT",
    "TOOL_ORDER_CATEGORIES",
    "TOOL_ORDER_TRANSFORM_ID",
    "TOOL_ORDER_TRANSFORM_VERSION",
    "VARIANT_MANIFEST_FILE",
    "VARIANT_MANIFEST_SCHEMA",
    "DerivedRun",
    "DerivedSource",
    "ToolOrderOverlay",
    "derive_tool_order_text",
    "derived_data_sha256",
    "derived_ref_for",
    "launch_environment_for",
    "materialize_tool_order_overlay",
    "parse_variant_manifest",
    "permute_functions",
    "prepare_tool_order_run",
    "question_file_for",
    "render_variant_manifest",
    "resolve_derived_source",
    "rotation_offset",
    "tree_digests",
    "verify_tool_order_overlay",
]
