#!/usr/bin/env python3
"""Deterministic verifier for be-core-a2-build-log-triage."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ACCEPTED_CAUSES = {"missing-greet-export"}
_EXPECTED_FILES = {"repo/src/greeter.py"}
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


def _run_pytest(repo_root: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return proc.returncode == 0


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    diagnosis = candidate.get("diagnosis")
    cause_id = None
    if isinstance(diagnosis, dict):
        raw = diagnosis.get("cause_id")
        if isinstance(raw, str):
            cause_id = raw
    files_obj = candidate.get("files")
    if not isinstance(files_obj, dict):
        files_obj = {}
    files = {str(k): str(v) for k, v in files_obj.items()}

    log_cause_identified = cause_id in _ACCEPTED_CAUSES
    minimal_diff = set(files.keys()) == _EXPECTED_FILES
    no_unrelated = bool(files) and set(files.keys()).issubset(_EXPECTED_FILES)

    with tempfile.TemporaryDirectory(prefix="bencheval-a2-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(workspace / "repo", sandbox / "repo")
        patch_ok = _apply_patch(sandbox, files)
        repo_root = sandbox / "repo"
        tests_ok = _tests_unchanged(workspace, sandbox)
        build_passes = patch_ok and tests_ok and _run_pytest(repo_root)

        metrics = {
            "build_passes": 1.0 if build_passes else 0.0,
            "minimal_diff": 1.0 if minimal_diff else 0.0,
            "no_unrelated_changes": 1.0 if no_unrelated else 0.0,
            "log_cause_identified": 1.0 if log_cause_identified else 0.0,
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
