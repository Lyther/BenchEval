#!/usr/bin/env python3
"""Deterministic verifier for be-core-a1-multi-file-repo-fix."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ACCEPTED_ROOT_CAUSES = {"whitespace-tokenization"}
_ALLOWED_CLAIMS: set[str] = set()
_EXPECTED_FILES = {
    "repo/src/tokenizer.py",
    "repo/src/evaluator.py",
}
_TESTS_DIR = Path("repo") / "tests"


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


def _load_module(repo_root: Path, rel: str, name: str):
    src = (repo_root / "src").resolve()
    src_str = str(src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)
    module_path = repo_root / rel
    spec = importlib.util.spec_from_file_location(name, module_path)
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


def _hidden_tests_pass(repo_root: Path) -> bool:
    evaluator = _load_module(repo_root, "src/evaluator.py", "evaluator")
    if evaluator is None:
        return False
    try:
        if evaluator.sum_tokens("1  2") != 3:
            return False
        if evaluator.sum_tokens("10\t5") != 15:
            return False
        if evaluator.sum_tokens("0 0 0") != 0:
            return False
    except Exception:
        return False
    return True


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    root_cause_id = candidate.get("root_cause_id")
    files_obj = candidate.get("files")
    claims = candidate.get("claims", [])
    if not isinstance(files_obj, dict):
        files_obj = {}
    files = {str(k): str(v) for k, v in files_obj.items()}
    if not isinstance(claims, list):
        claims = []

    root_cause_identified = (
        isinstance(root_cause_id, str) and root_cause_id in _ACCEPTED_ROOT_CAUSES
    )
    no_unsupported_claims = all(isinstance(c, str) and c in _ALLOWED_CLAIMS for c in claims)
    file_localized = bool(files) and set(files.keys()).issubset(_EXPECTED_FILES)
    patch_minimality = set(files.keys()) == _EXPECTED_FILES

    with tempfile.TemporaryDirectory(prefix="bencheval-a1-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(workspace / "repo", sandbox / "repo")
        patch_applies = _apply_patch(sandbox, files)
        repo_root = sandbox / "repo"
        tests_ok = _tests_unchanged(workspace, sandbox)
        patch_compiles = (
            patch_applies
            and tests_ok
            and _load_module(
                repo_root,
                "src/evaluator.py",
                "evaluator",
            )
            is not None
        )
        visible_tests_pass = patch_compiles and _run_visible_tests(repo_root)
        hidden_pass = visible_tests_pass and _hidden_tests_pass(repo_root)

        metrics = {
            "file_localized": 1.0 if file_localized else 0.0,
            "root_cause_identified": 1.0 if root_cause_identified else 0.0,
            "patch_compiles": 1.0 if patch_compiles else 0.0,
            "hidden_tests_pass": 1.0 if hidden_pass else 0.0,
            "patch_minimality": 1.0 if patch_minimality else 0.0,
            "no_unsupported_claims": 1.0 if no_unsupported_claims else 0.0,
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
