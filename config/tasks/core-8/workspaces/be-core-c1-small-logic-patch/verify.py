#!/usr/bin/env python3
"""Deterministic verifier for be-core-c1-small-logic-patch."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_TESTS_DIR = Path("repo") / "tests"


def _load_module(repo_root: Path) -> bool:
    module_path = repo_root / "src" / "counter.py"
    spec = importlib.util.spec_from_file_location("counter", module_path)
    if spec is None or spec.loader is None:
        return False
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return False
    try:
        if module.increment(0) != 1:
            return False
        if module.increment(-1) != 0:
            return False
        if module.increment(5) != 6:
            return False
    except Exception:
        return False
    return True


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
            manifest[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return manifest


def _tests_unchanged(workspace: Path, sandbox: Path) -> bool:
    original = workspace / "repo" / "tests"
    copied = sandbox / "repo" / "tests"
    return _file_manifest(original) == _file_manifest(copied)


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="bencheval-c1-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(workspace / "repo", sandbox / "repo")
        patch_applies = _apply_candidate(candidate, sandbox)
        repo_root = sandbox / "repo"
        compile_success = patch_applies and _load_module(repo_root)
        hidden_tests_pass = compile_success
        visible_tests_pass = compile_success and _run_visible_tests(repo_root)
        no_test_modification = _tests_unchanged(workspace, sandbox)
        partial_metrics = {
            "compile_success": 1.0 if compile_success else 0.0,
            "visible_tests_pass": 1.0 if visible_tests_pass else 0.0,
            "hidden_tests_pass": 1.0 if hidden_tests_pass else 0.0,
            "patch_applies": 1.0 if patch_applies else 0.0,
            "no_test_modification": 1.0 if no_test_modification else 0.0,
        }
        primary_pass = (
            patch_applies
            and compile_success
            and visible_tests_pass
            and hidden_tests_pass
            and no_test_modification
        )
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
