#!/usr/bin/env python3
"""Deterministic verifier for be-core-s2-authorization-matrix-regression."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_EXPECTED_FILES = {"repo/src/authz.py"}
_TESTS_DIR = Path("repo") / "tests"
_MATRIX_PATH = Path("matrix") / "hidden_gold.json"


def _resolve_target(dest: Path, rel_path: str) -> Path | None:
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


def _apply_patch(dest: Path, files: dict[str, str]) -> bool:
    writes: list[tuple[Path, str]] = []
    for rel_path, content in files.items():
        target = _resolve_target(dest, rel_path)
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
            manifest[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def _tests_unchanged(workspace: Path, sandbox: Path) -> bool:
    return _file_manifest(workspace / "repo" / "tests") == _file_manifest(
        sandbox / "repo" / "tests",
    )


def _load_authz(repo_root: Path):
    src = (repo_root / "src").resolve()
    src_str = str(src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)
    module_path = repo_root / "src" / "authz.py"
    spec = importlib.util.spec_from_file_location("authz", module_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
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


def _load_gold_matrix(workspace: Path) -> list[dict[str, object]]:
    path = workspace / _MATRIX_PATH
    payload = json.loads(path.read_text(encoding="utf-8"))
    tuples = payload.get("tuples")
    if not isinstance(tuples, list):
        return []
    rows: list[dict[str, object]] = []
    for item in tuples:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        action = item.get("action")
        resource = item.get("resource")
        allow = item.get("allow")
        if (
            isinstance(role, str)
            and isinstance(action, str)
            and isinstance(resource, str)
            and isinstance(allow, bool)
        ):
            rows.append(
                {
                    "role": role,
                    "action": action,
                    "resource": resource,
                    "allow": allow,
                },
            )
    return rows


def _authorization_matrix_match(authz_mod, gold_rows: list[dict[str, object]]) -> bool:
    if not gold_rows:
        return False
    for row in gold_rows:
        role = str(row["role"])
        action = str(row["action"])
        resource = str(row["resource"])
        expected = bool(row["allow"])
        try:
            actual = authz_mod.can(role, action, resource)
        except Exception:
            return False
        if actual is not expected:
            return False
    return True


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    files_obj = candidate.get("files")
    if not isinstance(files_obj, dict):
        files_obj = {}
    files = {str(k): str(v) for k, v in files_obj.items()}
    patch_minimality = set(files.keys()) == _EXPECTED_FILES

    with tempfile.TemporaryDirectory(prefix="bencheval-s2-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(workspace / "repo", sandbox / "repo")
        patch_ok = _apply_patch(sandbox, files)
        repo_root = sandbox / "repo"
        tests_ok = _tests_unchanged(workspace, sandbox)
        authz_mod = _load_authz(repo_root) if patch_ok and tests_ok else None
        valid_behavior = authz_mod is not None and _run_visible_tests(repo_root)
        gold_rows = _load_gold_matrix(workspace)
        matrix_match = (
            valid_behavior
            and authz_mod is not None
            and _authorization_matrix_match(authz_mod, gold_rows)
        )

        metrics = {
            "authorization_matrix_match": 1.0 if matrix_match else 0.0,
            "valid_behavior_preserved": 1.0 if valid_behavior else 0.0,
            "patch_minimality": 1.0 if patch_minimality else 0.0,
        }
        primary = all(v == 1.0 for v in metrics.values())
        partial = sum(metrics.values()) / len(metrics)
        return {
            "primary_pass": primary,
            "partial_score": partial,
            "partial_metrics": metrics,
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
