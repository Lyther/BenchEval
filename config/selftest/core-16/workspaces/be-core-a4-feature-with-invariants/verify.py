#!/usr/bin/env python3
"""Deterministic verifier for be-core-a4-feature-with-invariants."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_ACCEPTED_FEATURE_FLAGS = {"comma_grouping"}
_ALLOWED_CLAIMS: set[str] = set()
_ALLOWED_FILES = {
    "repo/src/flags.py",
    "repo/src/normalize.py",
    "repo/src/summarizer.py",
}
_EXPECTED_FILES = {
    "repo/src/flags.py",
    "repo/src/normalize.py",
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


def _load_invariants(workspace: Path) -> dict[str, object]:
    path = workspace / "invariants.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return data


def _purge_src_modules() -> None:
    for name in list(sys.modules):
        if name in {"flags", "normalize", "summarizer"}:
            del sys.modules[name]


def _load_repo_modules(repo_root: Path) -> tuple[object | None, object | None, object | None]:
    src = (repo_root / "src").resolve()
    src_str = str(src)
    if src_str not in sys.path:
        sys.path.insert(0, src_str)
    _purge_src_modules()
    modules: dict[str, object | None] = {}
    for rel, name in (
        ("src/flags.py", "flags"),
        ("src/normalize.py", "normalize"),
        ("src/summarizer.py", "summarizer"),
    ):
        module_path = repo_root / rel
        spec = importlib.util.spec_from_file_location(name, module_path)
        if spec is None or spec.loader is None:
            modules[name] = None
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(name, None)
            module = None
        modules[name] = module
    return (
        sys.modules.get("flags"),
        sys.modules.get("normalize"),
        sys.modules.get("summarizer"),
    )


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


def _sum_line_with_flag(
    flags_mod: object,
    summarizer_mod: object,
    *,
    flag_value: bool,
    line: str,
) -> int:
    flags_mod.comma_grouping = flag_value
    return summarizer_mod.sum_line(line)


def _legacy_invariants_pass(
    flags_mod: object,
    summarizer_mod: object,
    invariants: dict[str, object],
) -> bool:
    legacy_cases = invariants.get("legacy_flag_off", [])
    reject_cases = invariants.get("legacy_rejects_commas_flag_off", [])
    if not isinstance(legacy_cases, list) or not isinstance(reject_cases, list):
        return False
    try:
        for case in legacy_cases:
            if not isinstance(case, dict):
                return False
            line = case.get("input")
            expect = case.get("expect")
            if not isinstance(line, str) or not isinstance(expect, int):
                return False
            if (
                _sum_line_with_flag(flags_mod, summarizer_mod, flag_value=False, line=line)
                != expect
            ):
                return False
        for case in reject_cases:
            if not isinstance(case, dict):
                return False
            line = case.get("input")
            if not isinstance(line, str):
                return False
            try:
                _sum_line_with_flag(flags_mod, summarizer_mod, flag_value=False, line=line)
            except (ValueError, TypeError):
                continue
            else:
                return False
    except Exception:
        return False
    return True


def _feature_functional_pass(
    flags_mod: object,
    summarizer_mod: object,
    invariants: dict[str, object],
) -> bool:
    feature_cases = invariants.get("feature_flag_on", [])
    if not isinstance(feature_cases, list):
        return False
    try:
        for case in feature_cases:
            if not isinstance(case, dict):
                return False
            line = case.get("input")
            expect = case.get("expect")
            if not isinstance(line, str) or not isinstance(expect, int):
                return False
            if _sum_line_with_flag(flags_mod, summarizer_mod, flag_value=True, line=line) != expect:
                return False
    except Exception:
        return False
    return True


def _feature_flag_enabled(flags_mod: object) -> bool:
    try:
        return bool(flags_mod.comma_grouping)
    except Exception:
        return False


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    feature_flag_id = candidate.get("feature_flag_id")
    files_obj = candidate.get("files")
    claims = candidate.get("claims", [])
    if not isinstance(files_obj, dict):
        files_obj = {}
    files = {str(k): str(v) for k, v in files_obj.items()}
    if not isinstance(claims, list):
        claims = []

    feature_flag_identified = (
        isinstance(feature_flag_id, str) and feature_flag_id in _ACCEPTED_FEATURE_FLAGS
    )
    no_unsupported_claims = all(isinstance(c, str) and c in _ALLOWED_CLAIMS for c in claims)
    file_localized = bool(files) and set(files.keys()).issubset(_ALLOWED_FILES)
    patch_minimality = set(files.keys()) == _EXPECTED_FILES

    invariants = _load_invariants(workspace)

    with tempfile.TemporaryDirectory(prefix="bencheval-a4-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(workspace / "repo", sandbox / "repo")
        patch_applies = _apply_patch(sandbox, files)
        repo_root = sandbox / "repo"
        tests_ok = _tests_unchanged(workspace, sandbox)
        flags_mod, _normalize_mod, summarizer_mod = _load_repo_modules(repo_root)
        patch_compiles = (
            patch_applies and tests_ok and flags_mod is not None and summarizer_mod is not None
        )
        visible_tests_pass = patch_compiles and _run_visible_tests(repo_root)
        flag_enabled = patch_compiles and _feature_flag_enabled(flags_mod)
        legacy_pass = (
            visible_tests_pass
            and flag_enabled
            and _legacy_invariants_pass(flags_mod, summarizer_mod, invariants)
        )
        feature_pass = legacy_pass and _feature_functional_pass(
            flags_mod,
            summarizer_mod,
            invariants,
        )

        metrics = {
            "feature_flag_identified": 1.0 if feature_flag_identified else 0.0,
            "file_localized": 1.0 if file_localized else 0.0,
            "patch_compiles": 1.0 if patch_compiles else 0.0,
            "visible_tests_pass": 1.0 if visible_tests_pass else 0.0,
            "feature_flag_enabled": 1.0 if flag_enabled else 0.0,
            "legacy_invariants_pass": 1.0 if legacy_pass else 0.0,
            "feature_functional_pass": 1.0 if feature_pass else 0.0,
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
