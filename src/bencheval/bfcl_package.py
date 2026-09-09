"""BFCL registration-only package staging (architecture §23.4, roadmap CF1.2).

Owns one shared run-owned package copy for configured-model runs: the installed
``bfcl_eval`` is copied with real files (link count 1), exactly one fixed-rendered
registration is appended to ``constants/model_config.py`` so the original bytes
remain an exact prefix, and every other file stays byte-identical. Nothing here
calls a model, launches the CLI, or scores.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from bencheval.benchmark_registry import BfclPackageDataIdentity
from bencheval.exceptions import BenchEvalError
from bencheval.model_binding import ModelBinding

REGISTRATION_SCHEMA = "bfcl-registration-v1"
REGISTRATION_FILE = "constants/model_config.py"
REGISTRATION_MANIFEST_FILE = "execution/bfcl-registration.json"
STAGED_PACKAGE_DIR = "overlay"  # shares the run-owned copy root with the tool-order variant
STAGED_PACKAGE_PARENT = "pkg"
STAGED_PACKAGE_NAME = "bfcl_eval"
UNKNOWN_PROVENANCE = "unknown"  # mirrored from model_binding for renderers
HANDLER_CLASS_BY_KEY: Mapping[str, str] = {"openai_completions_fc": "OpenAICompletionsHandler"}
_REGISTRATION_MARKER = (
    "# bencheval configured registration (bfcl-registration-v1); generated, do not edit."
)
# Primitive string values only: no quotes, backslashes, or line breaks can reach
# the generated Python; the renderer is a fixed template, never an f-string of code.
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9 ._:/@()+,\-]+$")
_SKIP_DIRS = frozenset({"__pycache__"})
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class RegistrationSpec:
    """Validated primitive values of one appended ``ModelConfig`` entry."""

    registry_id: str
    api_model: str
    display_name: str
    handler: Literal["openai_completions_fc"]
    underscore_to_dot: bool
    reference_url: str
    organization: str
    license: str


@dataclass(frozen=True, slots=True)
class BfclPackageSource:
    """The pinned installed package and the reviewed registry-file pin."""

    package_root: Path
    identity: BfclPackageDataIdentity
    registry_sha256: str  # sha256:<hex> of the pristine constants/model_config.py


@dataclass(frozen=True, slots=True)
class StagedPackage:
    root: Path
    package_dir: Path
    pythonpath: Path
    spec: RegistrationSpec
    base_registry_sha256: str
    staged_registry_sha256: str
    registration_sha256: str
    code_digests: dict[str, str]  # every unchanged rel -> hex digest


def _safe(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or _SAFE_VALUE.fullmatch(value) is None:
        raise BenchEvalError(
            f"registration {field_name} {value!r} is not a plain printable value "
            "(letters, digits, space, and . _ : / @ ( ) + , - only)",
        )
    return value


def registration_spec_for(binding: ModelBinding) -> RegistrationSpec:
    """Build the registration from a configured BFCL binding.

    Every value comes from the confirmed binding (provenance defaults were
    applied when it was resolved). Values are validated primitives (no quotes,
    backslashes, or line breaks); prices are always ``None``.
    """
    bfcl = binding.bfcl
    if bfcl is None or bfcl.mode != "configured":
        raise BenchEvalError(
            f"model {binding.model_id!r} has no configured BFCL binding; nothing to register",
        )
    if (
        bfcl.handler not in HANDLER_CLASS_BY_KEY
        or bfcl.underscore_to_dot is None
        or bfcl.display_name is None
        or bfcl.reference_url is None
        or bfcl.organization is None
        or bfcl.license is None
    ):
        raise BenchEvalError(f"model {binding.model_id!r}: incomplete configured BFCL binding")
    return _validated_spec(
        RegistrationSpec(
            registry_id=bfcl.registry_id,
            api_model=binding.api_model,
            display_name=bfcl.display_name,
            handler=bfcl.handler,
            underscore_to_dot=bool(bfcl.underscore_to_dot),
            reference_url=bfcl.reference_url,
            organization=bfcl.organization,
            license=bfcl.license,
        )
    )


_REGISTRY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


def _validated_spec(spec: RegistrationSpec) -> RegistrationSpec:
    for name in ("registry_id", "api_model", "display_name", "reference_url", "organization"):
        _safe(getattr(spec, name), field_name=name)
    _safe(spec.license, field_name="license")
    if _REGISTRY_ID.fullmatch(spec.registry_id) is None:
        raise BenchEvalError(
            f"registration registry_id {spec.registry_id!r} must be an identifier "
            "(letters, digits, . _ : -); it names the launched model and a result directory",
        )
    if spec.handler not in HANDLER_CLASS_BY_KEY:
        raise BenchEvalError(f"unknown registration handler key {spec.handler!r}")
    if not isinstance(spec.underscore_to_dot, bool):
        raise BenchEvalError("registration underscore_to_dot must be a boolean")
    return spec


def render_registration(spec: RegistrationSpec) -> str:
    """Fixed renderer for the appended entry; deterministic for equal specs."""
    spec = _validated_spec(spec)
    handler_class = HANDLER_CLASS_BY_KEY[spec.handler]
    return (
        "\n"
        f"{_REGISTRATION_MARKER}\n"
        f'MODEL_CONFIG_MAPPING["{spec.registry_id}"] = ModelConfig(\n'
        f'    model_name="{spec.api_model}",\n'
        f'    display_name="{spec.display_name}",\n'
        f'    url="{spec.reference_url}",\n'
        f'    org="{spec.organization}",\n'
        f'    license="{spec.license}",\n'
        f"    model_handler={handler_class},\n"
        "    input_price=None,\n"
        "    output_price=None,\n"
        "    is_fc_model=True,\n"
        f"    underscore_to_dot={'True' if spec.underscore_to_dot else 'False'},\n"
        ")\n"
    )


def registration_sha256(spec: RegistrationSpec) -> str:
    """Digest of the canonical registration payload (``sha256:<hex>``)."""
    payload = asdict(_validated_spec(spec))
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def upstream_registry_keys(registry_text: str) -> frozenset[str]:
    """Literal keys of the pinned registry file, read without importing it.

    Every module-level dict literal assignment contributes its string keys, and
    ``MODEL_CONFIG_MAPPING`` itself must be a dict literal (upstream merges the
    per-family maps with ``**``); anything else is not the pinned shape.
    """
    try:
        module = ast.parse(registry_text)
    except SyntaxError as e:
        raise BenchEvalError(f"registry file is not parseable Python: {e}") from e
    keys: set[str] = set()
    mapping_is_dict = False
    for node in module.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "MODEL_CONFIG_MAPPING" in names:
            mapping_is_dict = True
        for key in node.value.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                keys.add(key.value)
    if not mapping_is_dict:
        raise BenchEvalError("registry file does not define MODEL_CONFIG_MAPPING as a dict literal")
    return frozenset(keys)


@dataclass(frozen=True, slots=True)
class UpstreamRegistration:
    """The native properties of one pinned ``MODEL_CONFIG_MAPPING`` entry."""

    registry_id: str
    model_name: str
    handler_class: str
    is_fc_model: bool
    underscore_to_dot: bool


def upstream_registration(registry_text: str, registry_id: str) -> UpstreamRegistration:
    """Read one pinned entry's ``ModelConfig(...)`` keywords without importing the file."""
    try:
        module = ast.parse(registry_text)
    except SyntaxError as e:
        raise BenchEvalError(f"registry file is not parseable Python: {e}") from e
    for node in module.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            if not (isinstance(key, ast.Constant) and key.value == registry_id):
                continue
            is_config = isinstance(value, ast.Call) and (
                getattr(value.func, "id", None) == "ModelConfig"
            )
            if not is_config:
                raise BenchEvalError(f"pinned entry {registry_id!r} is not a ModelConfig literal")
            assert isinstance(value, ast.Call)
            kwargs: dict[str, object] = {}
            for keyword in value.keywords:
                if isinstance(keyword.value, ast.Constant):
                    kwargs[str(keyword.arg)] = keyword.value.value
                elif isinstance(keyword.value, ast.Name):
                    kwargs[str(keyword.arg)] = keyword.value.id
            model_name = kwargs.get("model_name")
            handler = kwargs.get("model_handler")
            if not isinstance(model_name, str) or not isinstance(handler, str):
                raise BenchEvalError(
                    f"pinned entry {registry_id!r} has no literal model_name/handler"
                )
            return UpstreamRegistration(
                registry_id=registry_id,
                model_name=model_name,
                handler_class=handler,
                is_fc_model=bool(kwargs.get("is_fc_model", True)),
                underscore_to_dot=bool(kwargs.get("underscore_to_dot", False)),
            )
    raise BenchEvalError(f"registry id {registry_id!r} is not a pinned registration")


def verify_upstream_binding(binding: ModelBinding, registry_text: str) -> UpstreamRegistration:
    """An upstream binding must name the API model the pinned registration launches.

    Shared by preflight (doctor) and launch: an allowlisted key alone says
    nothing about which vendor model BFCL will actually call.
    """
    registry_id = binding.bfcl.registry_id if binding.bfcl is not None else binding.model_id
    if binding.bfcl is not None and binding.bfcl.mode == "configured":
        raise BenchEvalError("configured bindings are generated, not looked up upstream")
    entry = upstream_registration(registry_text, registry_id)
    if entry.model_name != binding.api_model:
        raise BenchEvalError(
            f"model {binding.model_id!r} binds upstream key {registry_id!r}, whose pinned API "
            f"model is {entry.model_name!r}, not the confirmed api_model {binding.api_model!r}",
        )
    return entry


def read_pinned_registry(source: BfclPackageSource) -> str:
    """The pristine registry text, verified against the reviewed pin."""
    return _read_registry(source.package_root, source.registry_sha256).decode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_registry(package_root: Path, expected: str) -> bytes:
    target = package_root / REGISTRATION_FILE
    if target.is_symlink() or not target.is_file():
        raise BenchEvalError(f"registry file missing or not a plain file: {target}")
    data = target.read_bytes()
    actual = f"sha256:{_sha256_bytes(data)}"
    if actual != expected:
        raise BenchEvalError(
            f"registry file {REGISTRATION_FILE} drifted from the reviewed pin: "
            f"expected {expected}, got {actual}",
        )
    return data


def _require_single_links(root: Path) -> None:
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            path = Path(current) / name
            if os.lstat(path).st_nlink != 1:
                raise BenchEvalError(f"staged file is a hard link into another tree: {path}")


def stage_bfcl_package(
    *,
    source: BfclPackageSource,
    spec: RegistrationSpec,
    output_root: Path,
) -> StagedPackage:
    """Copy the installed package and append exactly one registration.

    Fails closed before writing when the registry pin, data pins, or link
    counts drift, or when ``spec.registry_id`` already exists upstream.
    """
    from bencheval.bfcl_native_adapter import verify_bfcl_package_data
    from bencheval.bfcl_study import tree_digests

    spec = _validated_spec(spec)
    verify_bfcl_package_data(package_root=source.package_root, files=source.identity.files)
    base = _read_registry(source.package_root, source.registry_sha256)
    if spec.registry_id in upstream_registry_keys(base.decode("utf-8")):
        raise BenchEvalError(
            f"registry id {spec.registry_id!r} is an existing pinned registration; "
            "a configured registration never replaces or relabels an upstream key",
        )
    source_digests = tree_digests(source.package_root)
    if output_root.is_symlink() or (output_root.exists() and any(output_root.iterdir())):
        raise BenchEvalError(f"staging root is not an exclusive empty directory: {output_root}")
    parent = output_root / STAGED_PACKAGE_PARENT
    package_dir = parent / STAGED_PACKAGE_NAME
    parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source.package_root,
        package_dir,
        symlinks=False,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    staged_bytes = base + render_registration(spec).encode("utf-8")
    target = package_dir / REGISTRATION_FILE
    target.unlink()
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(staged_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    _require_single_links(package_dir)
    staged_digests = tree_digests(package_dir)
    code_digests = {rel: d for rel, d in staged_digests.items() if rel != REGISTRATION_FILE}
    if code_digests != {rel: d for rel, d in source_digests.items() if rel != REGISTRATION_FILE}:
        raise BenchEvalError("staged copy does not match the installed package bytes")
    return StagedPackage(
        root=output_root,
        package_dir=package_dir,
        pythonpath=parent,
        spec=spec,
        base_registry_sha256=source.registry_sha256,
        staged_registry_sha256=f"sha256:{_sha256_bytes(staged_bytes)}",
        registration_sha256=registration_sha256(spec),
        code_digests=code_digests,
    )


def verify_staged_package(
    staged: StagedPackage,
    *,
    source: BfclPackageSource,
    declared_changes: Mapping[str, str] | None = None,
) -> None:
    """Re-prove the copy: prefix-bound registry, unchanged code, pinned installed tree.

    ``declared_changes`` maps additional rel paths (a variant's derived data
    files) to their expected ``sha256:<hex>``; any other difference fails.
    """
    from bencheval.bfcl_native_adapter import verify_bfcl_package_data
    from bencheval.bfcl_study import tree_digests

    verify_bfcl_package_data(package_root=source.package_root, files=source.identity.files)
    base = _read_registry(source.package_root, source.registry_sha256)
    installed = tree_digests(source.package_root)
    _require_single_links(staged.package_dir)
    current = tree_digests(staged.package_dir)
    declared = {rel: pin.removeprefix("sha256:") for rel, pin in (declared_changes or {}).items()}
    if REGISTRATION_FILE in declared:
        raise BenchEvalError("the registry file cannot be a declared data change")
    expected = {**staged.code_digests, **declared}
    expected[REGISTRATION_FILE] = staged.staged_registry_sha256.removeprefix("sha256:")
    missing = sorted(set(expected) - set(current))
    extra = sorted(set(current) - set(expected))
    if missing:
        raise BenchEvalError(f"staged package is missing files: {missing}")
    if extra:
        raise BenchEvalError(f"staged package contains extra files: {extra}")
    for rel in sorted(expected):
        if current[rel] != expected[rel]:
            raise BenchEvalError(f"staged file drifted from its materialized bytes: {rel}")
        if rel != REGISTRATION_FILE and rel not in declared and installed.get(rel) != current[rel]:
            raise BenchEvalError(f"staged file no longer matches the installed package: {rel}")
    if set(installed) != set(current):
        raise BenchEvalError("installed package file set differs from the staged copy")
    staged_registry = (staged.package_dir / REGISTRATION_FILE).read_bytes()
    if staged_registry != base + render_registration(staged.spec).encode("utf-8"):
        raise BenchEvalError("staged registry file is not the pinned base plus one registration")


def effective_harness_version(base_version: str, registration_digest: str) -> str:
    """``bfcl-eval@<base>+registration-<hex>``; the base stays retained separately."""
    digest = registration_digest.removeprefix("sha256:")
    if _HEX64.fullmatch(digest) is None or not base_version.strip():
        raise BenchEvalError("effective harness version needs a base version and a sha256 digest")
    return f"bfcl-eval@{base_version.strip()}+registration-{digest}"


def render_registration_manifest(staged: StagedPackage, *, base_version: str) -> str:
    """Canonical ``execution/bfcl-registration.json`` text."""
    payload = {
        "schema_version": REGISTRATION_SCHEMA,
        "base": {
            "bfcl_eval_version": base_version,
            "registry_file": REGISTRATION_FILE,
            "registry_sha256": staged.base_registry_sha256,
        },
        "staged": {
            "package_dir": f"{STAGED_PACKAGE_DIR}/{STAGED_PACKAGE_PARENT}/{STAGED_PACKAGE_NAME}",
            "pythonpath": f"{STAGED_PACKAGE_DIR}/{STAGED_PACKAGE_PARENT}",
            "registry_sha256": staged.staged_registry_sha256,
        },
        "registration": asdict(staged.spec),
        "registration_sha256": staged.registration_sha256,
        "harness_version": effective_harness_version(base_version, staged.registration_sha256),
    }
    return json.dumps(payload, sort_keys=True, indent=2) + "\n"


def parse_registration_manifest(text: str) -> tuple[RegistrationSpec, dict[str, object]]:
    """Validate a retained manifest; returns the spec and the parsed payload."""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise BenchEvalError(f"registration manifest is not JSON: {e}") from e
    if not isinstance(raw, dict) or raw.get("schema_version") != REGISTRATION_SCHEMA:
        raise BenchEvalError("registration manifest schema is not bfcl-registration-v1")
    registration = raw.get("registration")
    base = raw.get("base")
    staged = raw.get("staged")
    if (
        not isinstance(registration, dict)
        or not isinstance(base, dict)
        or not isinstance(staged, dict)
    ):
        raise BenchEvalError("registration manifest is missing its sections")
    try:
        spec = _validated_spec(RegistrationSpec(**{str(k): v for k, v in registration.items()}))
    except TypeError as e:
        raise BenchEvalError(f"registration manifest entry is malformed: {e}") from e
    digest = registration_sha256(spec)
    if raw.get("registration_sha256") != digest:
        raise BenchEvalError("registration manifest digest does not match its registration")
    version = base.get("bfcl_eval_version")
    if not isinstance(version, str) or base.get("registry_file") != REGISTRATION_FILE:
        raise BenchEvalError("registration manifest base section is malformed")
    if raw.get("harness_version") != effective_harness_version(version, digest):
        raise BenchEvalError("registration manifest harness_version does not match its digest")
    for section, key in ((base, "registry_sha256"), (staged, "registry_sha256")):
        value = section.get(key)
        if not isinstance(value, str) or _HEX64.fullmatch(value.removeprefix("sha256:")) is None:
            raise BenchEvalError("registration manifest registry digests are malformed")
    return spec, raw


def restage_from_manifest(
    text: str, *, artifacts_dir: Path, source: BfclPackageSource
) -> StagedPackage:
    """Rebuild the staged description from a retained manifest and re-verify the copy."""
    from bencheval.bfcl_study import tree_digests

    spec, payload = parse_registration_manifest(text)
    base = payload["base"]
    staged_section = payload["staged"]
    assert isinstance(base, dict) and isinstance(staged_section, dict)
    if base["registry_sha256"] != source.registry_sha256:
        raise BenchEvalError("retained registration manifest binds a different registry pin")
    installed = tree_digests(source.package_root)
    staged = StagedPackage(
        root=artifacts_dir / STAGED_PACKAGE_DIR,
        package_dir=artifacts_dir / str(staged_section["package_dir"]),
        pythonpath=artifacts_dir / str(staged_section["pythonpath"]),
        spec=spec,
        base_registry_sha256=source.registry_sha256,
        staged_registry_sha256=str(staged_section["registry_sha256"]),
        registration_sha256=str(payload["registration_sha256"]),
        code_digests={rel: d for rel, d in installed.items() if rel != REGISTRATION_FILE},
    )
    return staged


def launch_environment(pythonpath: Path, base: Mapping[str, str]) -> dict[str, str]:
    """The official CLI imports ``bfcl_eval`` from the copy; no bytecode is written."""
    env = dict(base)
    env["PYTHONPATH"] = str(pythonpath)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


__all__ = [
    "HANDLER_CLASS_BY_KEY",
    "REGISTRATION_FILE",
    "REGISTRATION_MANIFEST_FILE",
    "REGISTRATION_SCHEMA",
    "STAGED_PACKAGE_DIR",
    "UNKNOWN_PROVENANCE",
    "BfclPackageSource",
    "RegistrationSpec",
    "StagedPackage",
    "UpstreamRegistration",
    "effective_harness_version",
    "launch_environment",
    "parse_registration_manifest",
    "read_pinned_registry",
    "registration_sha256",
    "registration_spec_for",
    "render_registration",
    "render_registration_manifest",
    "restage_from_manifest",
    "stage_bfcl_package",
    "upstream_registration",
    "upstream_registry_keys",
    "verify_staged_package",
    "verify_upstream_binding",
]
