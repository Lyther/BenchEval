#!/usr/bin/env python3
"""Deterministic verifier for be-core-c2-regression-test-authoring."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_TESTS_PREFIX = Path("repo") / "tests"
_SRC_PREFIX = Path("repo") / "src"


def _resolve_target(dest: Path, rel_path: str) -> Path | None:
    dest_root = dest.resolve()
    rel = Path(rel_path)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    target = (dest_root / rel).resolve()
    if target == dest_root or not target.is_relative_to(dest_root):
        return None
    return target


def _is_under(prefix: Path, dest: Path, target: Path) -> bool:
    root = (dest.resolve() / prefix).resolve()
    return target == root or target.is_relative_to(root)


def _apply_files(
    dest: Path,
    files: dict[str, str],
    *,
    require_under: Path | None = None,
) -> bool:
    writes: list[tuple[Path, str]] = []
    for rel_path, content in files.items():
        target = _resolve_target(dest, rel_path)
        if target is None:
            return False
        if require_under is not None and not _is_under(require_under, dest, target):
            return False
        writes.append((target, content))
    for target, content in writes:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return True


def _run_pytest(repo_root: Path) -> bool:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    return proc.returncode == 0


def _load_candidate(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    files = candidate.get("files")
    if not isinstance(files, dict) or not files:
        return _result(
            False,
            0.0,
            {"test_fails_before_gold_patch": 0.0, "test_passes_after_gold_patch": 0.0},
        )

    with tempfile.TemporaryDirectory(prefix="bencheval-c2-") as tmp:
        sandbox = Path(tmp)
        shutil.copytree(workspace / "repo", sandbox / "repo")
        if not _apply_files(
            sandbox,
            {str(k): str(v) for k, v in files.items()},
            require_under=_TESTS_PREFIX,
        ):
            return _result(
                False,
                0.0,
                {"test_fails_before_gold_patch": 0.0, "test_passes_after_gold_patch": 0.0},
            )

        before_pass = _run_pytest(sandbox / "repo")
        test_fails_before = not before_pass

        gold = _load_candidate(workspace / "gold.patch.json")
        gold_files = gold.get("files")
        if not isinstance(gold_files, dict):
            return _result(
                False,
                sum([float(test_fails_before), 0.0]) / 2,
                {
                    "test_fails_before_gold_patch": float(test_fails_before),
                    "test_passes_after_gold_patch": 0.0,
                },
            )
        if not _apply_files(
            sandbox,
            {str(k): str(v) for k, v in gold_files.items()},
            require_under=_SRC_PREFIX,
        ):
            return _result(
                False,
                (float(test_fails_before) + 0.0) / 2,
                {
                    "test_fails_before_gold_patch": float(test_fails_before),
                    "test_passes_after_gold_patch": 0.0,
                },
            )

        after_pass = _run_pytest(sandbox / "repo")
        test_passes_after = after_pass

        metrics = {
            "test_fails_before_gold_patch": 1.0 if test_fails_before else 0.0,
            "test_passes_after_gold_patch": 1.0 if test_passes_after else 0.0,
        }
        primary = test_fails_before and test_passes_after
        partial = sum(metrics.values()) / len(metrics)
        return _result(primary, partial, metrics)


def _result(primary: bool, partial: float, metrics: dict[str, float]) -> dict[str, object]:
    return {
        "primary_pass": primary,
        "partial_score": partial,
        "partial_metrics": metrics,
    }


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: verify.py <candidate.test.json>\n")
        raise SystemExit(2)
    workspace = Path(__file__).resolve().parent
    try:
        candidate = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sys.stderr.write("error: candidate is not valid JSON\n")
        raise SystemExit(2) from None
    if not isinstance(candidate, dict):
        sys.stderr.write("error: candidate must be a JSON object\n")
        raise SystemExit(2)
    result = _score(workspace, candidate)
    sys.stdout.write(json.dumps(result) + "\n")
    return 0 if result["primary_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
