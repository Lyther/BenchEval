#!/usr/bin/env python3
"""Deterministic verifier for be-core-a3-dependency-api-bump."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ACCEPTED_MIGRATIONS = {"strutil-v2-field-parser"}
_EXPECTED_PIN = "strutil==2.0.0"
_FORBIDDEN_PIN = "strutil==1.0.0"
_EXPECTED_FILES = {
    "repo/src/loader.py",
    "repo/src/reporting.py",
    "repo/requirements.txt",
}
_TESTS_DIR = Path("repo") / "tests"
_STRUTIL_V2_DIR = Path("vendor") / "strutil-2.0.0"


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


def _lockfile_pin_correct(sandbox: Path) -> bool:
    req_path = sandbox / "repo" / "requirements.txt"
    if not req_path.is_file():
        return False
    text = req_path.read_text(encoding="utf-8")
    return _EXPECTED_PIN in text and _FORBIDDEN_PIN not in text


def _run_pytest(repo_root: Path, *, strutil_vendor: Path) -> bool:
    env = os.environ.copy()
    env["STRUTIL_VENDOR"] = str(strutil_vendor.resolve())
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=env,
    )
    return proc.returncode == 0


def _run_compatibility_fixtures(sandbox: Path, *, strutil_vendor: Path) -> bool:
    env = os.environ.copy()
    env["STRUTIL_VENDOR"] = str(strutil_vendor.resolve())
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str((sandbox / "repo" / "src").resolve()),
            str(strutil_vendor.resolve()),
        ],
    )
    script = sandbox / "compatibility" / "check_imports.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        env=env,
    )
    return proc.returncode == 0


def _hidden_integration_pass(repo_root: Path, *, strutil_vendor: Path) -> bool:
    env = os.environ.copy()
    env["STRUTIL_VENDOR"] = str(strutil_vendor.resolve())
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str((repo_root / "src").resolve()),
            str(strutil_vendor.resolve()),
        ],
    )
    code = (
        "from reporting import field_count\n"
        "assert field_count('a|b|c') == 3\n"
        "assert field_count('solo') == 1\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
        env=env,
    )
    return proc.returncode == 0


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    migration_id = candidate.get("migration_id")
    files_obj = candidate.get("files")
    if not isinstance(files_obj, dict):
        files_obj = {}
    files = {str(k): str(v) for k, v in files_obj.items()}

    migration_identified = isinstance(migration_id, str) and migration_id in _ACCEPTED_MIGRATIONS
    patch_localized = bool(files) and set(files.keys()).issubset(_EXPECTED_FILES)
    patch_minimality = set(files.keys()) == _EXPECTED_FILES

    with tempfile.TemporaryDirectory(prefix="bencheval-a3-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(workspace / "repo", sandbox / "repo")
        shutil.copytree(workspace / "vendor", sandbox / "vendor")
        shutil.copytree(workspace / "compatibility", sandbox / "compatibility")
        patch_applies = _apply_patch(sandbox, files)
        repo_root = sandbox / "repo"
        strutil_vendor = sandbox / _STRUTIL_V2_DIR
        tests_ok = _tests_unchanged(workspace, sandbox)
        lockfile_ok = patch_applies and _lockfile_pin_correct(sandbox)
        compatibility_ok = (
            patch_applies
            and tests_ok
            and lockfile_ok
            and _run_compatibility_fixtures(sandbox, strutil_vendor=strutil_vendor)
        )
        visible_tests_pass = compatibility_ok and _run_pytest(
            repo_root, strutil_vendor=strutil_vendor
        )
        hidden_pass = visible_tests_pass and _hidden_integration_pass(
            repo_root,
            strutil_vendor=strutil_vendor,
        )

        metrics = {
            "migration_identified": 1.0 if migration_identified else 0.0,
            "lockfile_pin_correct": 1.0 if lockfile_ok else 0.0,
            "compatibility_fixes_apply": 1.0 if compatibility_ok else 0.0,
            "visible_tests_pass": 1.0 if visible_tests_pass else 0.0,
            "hidden_integration_pass": 1.0 if hidden_pass else 0.0,
            "patch_minimality": 1.0 if patch_minimality else 0.0,
            "no_unrelated_changes": 1.0 if patch_localized else 0.0,
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
