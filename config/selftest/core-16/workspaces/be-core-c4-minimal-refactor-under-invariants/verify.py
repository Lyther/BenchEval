#!/usr/bin/env python3
"""Deterministic verifier for be-core-c4-minimal-refactor-under-invariants."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import fields, is_dataclass
from pathlib import Path
from types import ModuleType

_ALLOWED_FILES = frozenset(
    {
        "repo/src/shipkit/rating.py",
        "repo/src/shipkit/zones.py",
        "repo/src/shipkit/_internal.py",
    },
)
_INIT_PATH = "repo/src/shipkit/__init__.py"
_MAX_LINES_PER_FILE = 80
_MAX_CYCLOMATIC_PER_FUNCTION = 12
_TESTS_DIR = Path("repo") / "tests"
_PUBLIC_EXPORTS = ("Parcel", "RateQuote", "ShipKitError", "compute_rate", "list_service_zones")


def _resolve_candidate_target(dest: Path, rel_path: str) -> Path | None:
    dest_root = dest.resolve()
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    target = (dest_root / rel).resolve()
    if target == dest_root or not target.is_relative_to(dest_root):
        return None
    return target


def _is_repo_tests_path(dest: Path, target: Path) -> bool:
    tests_root = (dest.resolve() / _TESTS_DIR).resolve()
    return target == tests_root or target.is_relative_to(tests_root)


def _apply_candidate(candidate: dict[str, object], dest: Path) -> bool:
    files = candidate.get("files")
    if not isinstance(files, dict):
        return False
    writes: list[tuple[Path, str]] = []
    for rel_path, content in files.items():
        if not isinstance(rel_path, str) or not isinstance(content, str):
            return False
        if rel_path not in _ALLOWED_FILES:
            return False
        target = _resolve_candidate_target(dest, rel_path)
        if target is None or _is_repo_tests_path(dest, target):
            return False
        writes.append((target, content))
    for target, content in writes:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return True


def _file_manifest(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    manifest: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if path.name.endswith((".pyc", ".pyo")) or "__pycache__/" in rel:
                continue
            manifest[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def _tests_unchanged(workspace: Path, sandbox: Path) -> bool:
    original = workspace / "repo" / "tests"
    copied = sandbox / "repo" / "tests"
    return _file_manifest(original) == _file_manifest(copied)


def _init_unchanged(workspace: Path, sandbox: Path) -> bool:
    original = workspace / _INIT_PATH
    copied = sandbox / _INIT_PATH
    if not original.is_file() or not copied.is_file():
        return False
    return original.read_bytes() == copied.read_bytes()


def _cyclomatic_complexity(node: ast.AST) -> int:
    complexity = 1
    for child in ast.walk(node):
        if isinstance(
            child,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.With,
                ast.AsyncWith,
                ast.Try,
                ast.ExceptHandler,
                ast.IfExp,
                ast.Assert,
                ast.comprehension,
            ),
        ):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += max(0, len(child.values) - 1)
    return complexity


def _function_complexities(source: str) -> dict[str, int]:
    tree = ast.parse(source)
    complexities: dict[str, int] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            complexities[node.name] = _cyclomatic_complexity(node)
    return complexities


def _invariants_ok(sandbox: Path, candidate: dict[str, object]) -> bool:
    files = candidate.get("files")
    if not isinstance(files, dict):
        return False
    for rel_path, content in files.items():
        if not isinstance(rel_path, str) or not isinstance(content, str):
            return False
        if rel_path not in _ALLOWED_FILES:
            return False
        line_count = len(content.splitlines())
        if line_count > _MAX_LINES_PER_FILE:
            return False
        try:
            complexities = _function_complexities(content)
        except SyntaxError:
            return False
        if any(cc > _MAX_CYCLOMATIC_PER_FUNCTION for cc in complexities.values()):
            return False
    return True


def _load_shipkit(repo_root: Path) -> ModuleType | None:
    src = (repo_root / "src").resolve()
    src_str = str(src)
    for mod_name in list(sys.modules):
        if mod_name == "shipkit" or mod_name.startswith("shipkit."):
            sys.modules.pop(mod_name, None)
    if src_str in sys.path:
        sys.path.remove(src_str)
    sys.path.insert(0, src_str)
    spec = importlib.util.spec_from_file_location(
        "shipkit",
        repo_root / "src" / "shipkit" / "__init__.py",
        submodule_search_locations=[str(repo_root / "src" / "shipkit")],
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    return module


def _public_api_snapshot(module: ModuleType) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    exports = getattr(module, "__all__", ())
    snapshot["__all__"] = json.dumps(list(exports), sort_keys=True)
    for name in _PUBLIC_EXPORTS:
        obj = getattr(module, name, None)
        if obj is None:
            snapshot[name] = "missing"
            continue
        if inspect.isclass(obj):
            if is_dataclass(obj):
                field_names = [field.name for field in fields(obj)]
                snapshot[name] = f"class:{','.join(field_names)}"
            elif issubclass(obj, Exception):
                snapshot[name] = "exception"
            else:
                snapshot[name] = "class"
        elif callable(obj):
            try:
                signature = str(inspect.signature(obj))
            except (TypeError, ValueError):
                signature = "(…)"
            snapshot[name] = f"callable:{signature}"
        else:
            snapshot[name] = type(obj).__name__
    return snapshot


def _public_api_unchanged(workspace: Path, sandbox: Path) -> bool:
    baseline = _load_shipkit(workspace / "repo")
    patched = _load_shipkit(sandbox / "repo")
    if baseline is None or patched is None:
        return False
    return _public_api_snapshot(baseline) == _public_api_snapshot(patched)


def _run_visible_tests(repo_root: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_visible.py", "-q"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return proc.returncode == 0


def _hidden_integration_pass(repo_root: Path) -> bool:
    shipkit = _load_shipkit(repo_root)
    if shipkit is None:
        return False
    try:
        parcel = shipkit.Parcel(weight_oz=5, length_in=20, width_in=20, height_in=20)
        quote = shipkit.compute_rate(parcel, "  REGIONAL ")
        if quote.zone != "regional":
            return False
        if quote.billable_weight_oz != 48:
            return False
        if quote.rate_cents != 3150:
            return False

        national = shipkit.compute_rate(
            shipkit.Parcel(weight_oz=12, length_in=10, width_in=8, height_in=6),
            "national",
        )
        if national.rate_cents != 1750:
            return False

        with _pytest_raises(shipkit.ShipKitError):
            shipkit.compute_rate(
                shipkit.Parcel(weight_oz=10, length_in=8, width_in=6, height_in=4),
                "invalid",
            )
    except Exception:
        return False
    return True


class _pytest_raises:
    def __init__(self, exc_type: type[BaseException]) -> None:
        self.exc_type = exc_type

    def __enter__(self) -> None:
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: object,
    ) -> bool:
        return exc_type is not None and issubclass(exc_type, self.exc_type)


def _diff_locality(candidate: dict[str, object]) -> bool:
    files = candidate.get("files")
    if not isinstance(files, dict) or not files:
        return False
    touched = {rel for rel in files if isinstance(rel, str)}
    return touched.issubset(_ALLOWED_FILES) and "repo/src/shipkit/rating.py" in touched


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="bencheval-c4-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(workspace / "repo", sandbox / "repo")
        patch_applies = _apply_candidate(candidate, sandbox)
        repo_root = sandbox / "repo"
        diff_locality = patch_applies and _diff_locality(candidate)
        no_test_modification = _tests_unchanged(workspace, sandbox)
        init_unchanged = _init_unchanged(workspace, sandbox)
        invariants_ok = patch_applies and _invariants_ok(sandbox, candidate)
        public_api_unchanged = (
            patch_applies and init_unchanged and _public_api_unchanged(workspace, sandbox)
        )
        visible_tests_pass = public_api_unchanged and _run_visible_tests(repo_root)
        hidden_integration_pass = visible_tests_pass and _hidden_integration_pass(repo_root)
        partial_metrics = {
            "patch_applies": 1.0 if patch_applies else 0.0,
            "diff_locality": 1.0 if diff_locality else 0.0,
            "no_test_modification": 1.0 if no_test_modification else 0.0,
            "public_api_unchanged": 1.0 if public_api_unchanged else 0.0,
            "invariants_ok": 1.0 if invariants_ok else 0.0,
            "visible_tests_pass": 1.0 if visible_tests_pass else 0.0,
            "hidden_integration_pass": 1.0 if hidden_integration_pass else 0.0,
        }
        primary_pass = all(metric == 1.0 for metric in partial_metrics.values())
        partial_score = sum(partial_metrics.values()) / len(partial_metrics)
        return {
            "primary_pass": primary_pass,
            "partial_score": partial_score,
            "partial_metrics": partial_metrics,
        }


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: verify.py <candidate.patch.json>\n")
        raise SystemExit(2)
    workspace = Path(__file__).resolve().parent
    try:
        candidate = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sys.stderr.write("error: candidate patch is not valid JSON\n")
        raise SystemExit(2) from None
    if not isinstance(candidate, dict):
        sys.stderr.write("error: candidate patch must be a JSON object\n")
        raise SystemExit(2)
    result = _score(workspace, candidate)
    sys.stdout.write(json.dumps(result) + "\n")
    return 0 if result["primary_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
