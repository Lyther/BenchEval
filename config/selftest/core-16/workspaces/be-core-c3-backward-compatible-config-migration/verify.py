#!/usr/bin/env python3
"""Deterministic verifier for be-core-c3-backward-compatible-config-migration."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import py_compile
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_TESTS_DIR = Path("repo") / "tests"
_SETTINGS_PATH = Path("repo") / "config" / "settings.py"
_SCHEMA_PATH = Path("repo") / "schemas" / "normalized_schema.json"
_HIDDEN_FIXTURES = Path("hidden_fixtures")

_OLD_FIXTURES = (
    "old_minimal.yml",
    "old_debug.json",
    "old_custom_flags.yml",
    "old_sparse.yml",
    "legacy_env.json",
)
_NEW_FIXTURES = (
    "new_async_on.yml",
    "new_async_off.yml",
    "new_async_with_flags.yml",
)

_EXPECTED_NORMALIZED: dict[str, dict[str, Any]] = {
    "old_minimal.yml": {
        "app_name": "minimal",
        "debug": False,
        "enable_async": False,
        "feature_flags": {},
    },
    "old_debug.json": {
        "app_name": "debugapp",
        "debug": True,
        "enable_async": False,
        "feature_flags": {},
    },
    "old_custom_flags.yml": {
        "app_name": "flags",
        "debug": False,
        "enable_async": False,
        "feature_flags": {"beta_ui": True},
    },
    "old_sparse.yml": {
        "app_name": "app",
        "debug": False,
        "enable_async": False,
        "feature_flags": {},
    },
    "legacy_env.json": {
        "app_name": "legacy",
        "debug": False,
        "enable_async": False,
        "feature_flags": {},
    },
    "new_async_on.yml": {
        "app_name": "app",
        "debug": False,
        "enable_async": True,
        "feature_flags": {"async_pipeline": True},
    },
    "new_async_off.yml": {
        "app_name": "app",
        "debug": False,
        "enable_async": False,
        "feature_flags": {},
    },
    "new_async_with_flags.yml": {
        "app_name": "app",
        "debug": False,
        "enable_async": True,
        "feature_flags": {"other": True, "async_pipeline": True},
    },
}


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _snapshot_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_repo_tests_path(dest: Path, target: Path) -> bool:
    tests_root = (dest.resolve() / _TESTS_DIR).resolve()
    return target == tests_root or target.is_relative_to(tests_root)


def _resolve_candidate_target(dest: Path, rel_path: str) -> Path | None:
    dest_root = dest.resolve()
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    target = (dest_root / rel).resolve()
    if target == dest_root or not target.is_relative_to(dest_root):
        return None
    return target


def _apply_candidate(candidate: dict[str, object], dest: Path) -> bool:
    files = candidate.get("files")
    if not isinstance(files, dict):
        return False
    writes: list[tuple[Path, str]] = []
    for rel_path, content in files.items():
        if not isinstance(rel_path, str) or not isinstance(content, str):
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


def _load_settings_module(repo_root: Path) -> Any | None:
    module_path = repo_root / "config" / "settings.py"
    spec = importlib.util.spec_from_file_location("settings", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    if not hasattr(module, "load_config") or not hasattr(module, "normalize"):
        return None
    return module


def _run_visible_tests(repo_root: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return proc.returncode == 0


def _lint_typecheck_settings(repo_root: Path) -> bool:
    settings_path = repo_root / "config" / "settings.py"
    try:
        py_compile.compile(str(settings_path), doraise=True)
        tree = ast.parse(settings_path.read_text(encoding="utf-8"), filename=str(settings_path))
    except (OSError, SyntaxError, py_compile.PyCompileError):
        return False
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"normalize", "load_config", "_read_raw"}
    }
    if not {"normalize", "load_config"}.issubset(functions):
        return False
    for name in ("normalize", "load_config"):
        fn = functions[name]
        if fn.returns is None:
            return False
    return True


def _schema_snapshot_valid(repo_root: Path) -> bool:
    schema_path = repo_root / "schemas" / "normalized_schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if schema.get("schema_version") != "0.2":
        return False
    fields = schema.get("normalized_fields")
    if not isinstance(fields, dict):
        return False
    enable_async = fields.get("enable_async")
    if not isinstance(enable_async, dict):
        return False
    if enable_async.get("type") != "boolean":
        return False
    derivations = schema.get("feature_derivations")
    if not isinstance(derivations, dict):
        return False
    async_pipeline = derivations.get("async_pipeline")
    if not isinstance(async_pipeline, dict):
        return False
    return async_pipeline.get("source_field") == "enable_async"


def _evaluate_fixtures(
    workspace: Path,
    module: Any,
    *,
    fixture_names: tuple[str, ...],
) -> tuple[bool, bool]:
    fixtures_dir = workspace / _HIDDEN_FIXTURES
    parses = True
    unlocks = True
    for name in fixture_names:
        fixture_path = fixtures_dir / name
        expected = _EXPECTED_NORMALIZED.get(name)
        if expected is None:
            parses = False
            unlocks = False
            continue
        try:
            actual = module.load_config(fixture_path)
        except Exception:
            parses = False
            unlocks = False
            continue
        if _snapshot_hash(actual) != _snapshot_hash(expected):
            parses = False
            unlocks = False
            continue
        if name in _NEW_FIXTURES and name != "new_async_off.yml":
            flags = actual.get("feature_flags") or {}
            if flags.get("async_pipeline") is not True:
                unlocks = False
    return parses, unlocks


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="bencheval-c3-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(workspace / "repo", sandbox / "repo")
        patch_applies = _apply_candidate(candidate, sandbox)
        repo_root = sandbox / "repo"
        module = _load_settings_module(repo_root) if patch_applies else None
        lint_typecheck_pass = bool(module) and _lint_typecheck_settings(repo_root)
        schema_snapshot_valid = _schema_snapshot_valid(repo_root)
        visible_tests_pass = bool(module) and _run_visible_tests(repo_root)
        old_configs_parse = False
        new_configs_unlock_flag = False
        if module is not None:
            old_configs_parse, _ = _evaluate_fixtures(
                workspace,
                module,
                fixture_names=_OLD_FIXTURES,
            )
            _, new_configs_unlock_flag = _evaluate_fixtures(
                workspace,
                module,
                fixture_names=_NEW_FIXTURES,
            )
        no_test_modification = _tests_unchanged(workspace, sandbox)
        partial_metrics = {
            "patch_applies": 1.0 if patch_applies else 0.0,
            "no_test_modification": 1.0 if no_test_modification else 0.0,
            "visible_tests_pass": 1.0 if visible_tests_pass else 0.0,
            "old_configs_parse": 1.0 if old_configs_parse else 0.0,
            "new_configs_unlock_flag": 1.0 if new_configs_unlock_flag else 0.0,
            "schema_snapshot_valid": 1.0 if schema_snapshot_valid else 0.0,
            "lint_typecheck_pass": 1.0 if lint_typecheck_pass else 0.0,
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
