"""Behavioral contracts for the BFCL tool-order materializer and run-owned overlay.

SUBSTITUTE_JUSTIFICATION
- substitute: a disposable ``bfcl_eval``-shaped package tree (code, config,
  scorer, and question/answer files with synthetic rows) plus a matching pin
  identity (`_substitute_package`)
- replaces: the installed pinned bfcl-eval distribution and its official data
- necessity: symlinks, hardlinks, replaced directories, mutated code/scorer,
  mutated derived data, pin drift, malformed rows, and single-function rows
  must be forced deterministically without mutating the installed package
- real-option: none; the installed package cannot be corrupted safely and the
  real loader probe (X0.2, dev-box-cpu 2026-09-07) already proved the overlay
  route against pinned bytes
- proof-limit: proves permutation determinism, byte containment, digest
  binding, and fail-closed verification only; nothing about model behavior
- real-proof: X0.2 overlay spike and the X3.5 dev-box tool-order plumbing run
- covered tests: every test in this module
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from bencheval.benchmark_registry import BfclPackageDataIdentity, BfclPopulationPin
from bencheval.bfcl_study import (
    BALANCE_ALGORITHM,
    TOOL_ORDER_CATEGORIES,
    ToolOrderOverlay,
    derive_tool_order_text,
    derived_data_sha256,
    materialize_tool_order_overlay,
    permute_functions,
    rotation_offset,
    tree_digests,
    verify_tool_order_overlay,
)
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_selection import population_ids_sha256

_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
_SEED = "bencheval-bfcl-tool-order-v1"


def _row(category: str, index: int, k: int) -> dict[str, object]:
    return {
        "id": f"{category}_{index}",
        "question": [[{"role": "user", "content": f"question {index}"}]],
        "function": [
            {
                "name": f"tool_{index}_{j}.get",
                "description": f"tool {j}",
                "parameters": {"type": "dict", "properties": {}, "required": []},
            }
            for j in range(k)
        ],
    }


def _jsonl(rows: list[dict[str, object]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _substitute_package(
    root: Path, *, rows: dict[str, list[dict[str, object]]] | None = None
) -> BfclPackageDataIdentity:
    """A bfcl_eval-shaped tree: code, config, scorer, data, and possible answers."""
    pkg = root / "bfcl_eval"
    (pkg / "constants").mkdir(parents=True)
    (pkg / "eval_checker").mkdir()
    (pkg / "data" / "possible_answer").mkdir(parents=True)
    (pkg / "__init__.py").write_text("VERSION = '2026.3.23'\n", encoding="utf-8")
    (pkg / "constants" / "eval_config.py").write_text(
        "from pathlib import Path\nPACKAGE_ROOT = Path(__file__).resolve().parents[1]\n"
        "PROMPT_PATH = PACKAGE_ROOT / 'data'\n",
        encoding="utf-8",
    )
    (pkg / "eval_checker" / "eval_runner.py").write_text("def runner():\n    return 1\n")
    (pkg / "eval_checker" / "checker.json").write_text('{"tolerance": 0}\n')
    rows = rows or {
        "multiple": [_row("multiple", i, 2 + i % 3) for i in range(12)],
        "parallel_multiple": [_row("parallel_multiple", i, 2 + i % 2) for i in range(8)],
        "simple_python": [
            {**_row("simple_python", i, 1), "function": _row("simple_python", i, 1)["function"]}
            for i in range(3)
        ],
    }
    files: dict[str, str] = {}
    populations: dict[str, BfclPopulationPin] = {}
    for category, entries in rows.items():
        rel = f"data/BFCL_v4_{category}.json"
        text = _jsonl(entries)
        (pkg / rel).write_text(text, encoding="utf-8")
        files[rel] = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        ids = [str(e["id"]) for e in entries]
        populations[rel] = BfclPopulationPin(count=len(ids), ids_sha256=population_ids_sha256(ids))
        answer = f"data/possible_answer/BFCL_v4_{category}.json"
        answer_text = _jsonl([{"id": e["id"], "ground_truth": [{}]} for e in entries])
        (pkg / answer).write_text(answer_text, encoding="utf-8")
        files[answer] = "sha256:" + hashlib.sha256(answer_text.encode("utf-8")).hexdigest()
    return BfclPackageDataIdentity(
        kind="bfcl-package-data",
        bfcl_eval_version="2026.3.23",
        upstream_commit=_COMMIT,
        files=files,
        populations=populations,
    )


def _overlay(
    tmp_path: Path, *, seed: str = _SEED
) -> tuple[Path, BfclPackageDataIdentity, ToolOrderOverlay]:
    package = tmp_path / "site" / "bfcl_eval"
    identity = _substitute_package(tmp_path / "site")
    overlay = materialize_tool_order_overlay(
        package_root=package, identity=identity, seed=seed, output_root=tmp_path / "run" / "overlay"
    )
    return package, identity, overlay


# --- balanced rotation ------------------------------------------------------------


def test_rotation_is_the_frozen_seeded_non_identity_offset() -> None:
    expected = 1 + (
        int(
            hashlib.sha256(
                json.dumps([BALANCE_ALGORITHM, _SEED, "multiple_7"], separators=(",", ":")).encode()
            ).hexdigest(),
            16,
        )
        % 3
    )
    assert rotation_offset(seed=_SEED, instance_id="multiple_7", function_count=4) == expected
    offsets = {
        rotation_offset(seed=_SEED, instance_id=f"multiple_{i}", function_count=4)
        for i in range(400)
    }
    assert offsets == {1, 2, 3}
    assert rotation_offset(
        seed="other", instance_id="multiple_7", function_count=4
    ) != expected or (
        rotation_offset(seed="other", instance_id="multiple_8", function_count=4)
        != rotation_offset(seed=_SEED, instance_id="multiple_8", function_count=4)
    )
    for k in (0, 1):
        with pytest.raises(BenchEvalError, match="two"):
            rotation_offset(seed=_SEED, instance_id="multiple_1", function_count=k)
    assert permute_functions(["a", "b", "c"], 1) == ["b", "c", "a"]
    assert permute_functions(["a", "b", "c"], 2) == ["c", "a", "b"]
    with pytest.raises(BenchEvalError, match="offset"):
        permute_functions(["a", "b", "c"], 0)
    with pytest.raises(BenchEvalError, match="offset"):
        permute_functions(["a", "b", "c"], 3)


def test_derived_text_changes_only_function_order_and_is_deterministic() -> None:
    rows = [_row("multiple", i, 2 + i % 3) for i in range(60)]
    text = _jsonl(rows)
    derived, offsets = derive_tool_order_text(text, seed=_SEED, category="multiple")
    assert derive_tool_order_text(text, seed=_SEED, category="multiple") == (derived, offsets)
    derived_rows = [json.loads(line) for line in derived.splitlines()]
    assert [r["id"] for r in derived_rows] == [r["id"] for r in rows]
    for source, out in zip(rows, derived_rows, strict=True):
        assert set(out) == set(source) == {"id", "question", "function"}
        assert out["question"] == source["question"]
        assert sorted(f["name"] for f in out["function"]) == sorted(
            f["name"] for f in source["function"]
        )
        assert [f["name"] for f in out["function"]] != [f["name"] for f in source["function"]]
        assert out["function"] == permute_functions(source["function"], offsets[str(source["id"])])
        assert all(
            a == b
            for a, b in zip(
                sorted(out["function"], key=lambda f: f["name"]),
                sorted(source["function"], key=lambda f: f["name"]),
                strict=True,
            )
        )
    assert set(offsets) == {r["id"] for r in rows}
    other, _ = derive_tool_order_text(text, seed="another-seed", category="multiple")
    assert other != derived

    def _rejects(bad_rows: list[dict[str, object]], match: str, *, raw: str | None = None) -> None:
        with pytest.raises(BenchEvalError, match=match):
            derive_tool_order_text(
                raw if raw is not None else _jsonl(bad_rows), seed=_SEED, category="multiple"
            )

    _rejects([_row("multiple", 0, 1)], "two")
    _rejects([_row("multiple", 0, 2), _row("multiple", 0, 3)], "duplicate")
    dup_names = _row("multiple", 0, 2)
    dup_names["function"][1]["name"] = dup_names["function"][0]["name"]  # type: ignore[index]
    _rejects([dup_names], "name")
    _rejects([{"question": [], "function": _row("multiple", 0, 2)["function"]}], "id")
    _rejects([{"id": "multiple_0", "question": []}], "function")
    _rejects([_row("parallel_multiple", 0, 2)], "category")
    _rejects([], "no rows")
    _rejects([], "JSON", raw="{not json}\n")
    extra = {**_row("multiple", 0, 2), "answer": "leak"}
    _rejects([extra], "keys")


# --- overlay materialization -----------------------------------------------------


def test_materialized_overlay_differs_from_the_source_only_in_declared_data(
    tmp_path: Path,
) -> None:
    package, identity, overlay = _overlay(tmp_path)
    assert overlay.package_dir == tmp_path / "run" / "overlay" / "pkg" / "bfcl_eval"
    assert overlay.pythonpath == tmp_path / "run" / "overlay" / "pkg"
    source = tree_digests(package)
    out = tree_digests(overlay.package_dir)
    declared = {f"data/BFCL_v4_{c}.json" for c in TOOL_ORDER_CATEGORIES}
    assert set(out) == set(source)
    assert {rel for rel in out if out[rel] != source[rel]} == declared
    assert set(overlay.derived_files) == declared
    for rel, digest in overlay.derived_files.items():
        assert digest == "sha256:" + out[rel]
        text = (overlay.package_dir / rel).read_text(encoding="utf-8")
        expected, offsets = derive_tool_order_text(
            (package / rel).read_text(encoding="utf-8"),
            seed=_SEED,
            category=rel[len("data/BFCL_v4_") : -len(".json")],
        )
        assert text == expected
        assert overlay.offsets[rel[len("data/BFCL_v4_") : -len(".json")]] == offsets
    # Ground truth and every code/config/scorer byte are the source bytes.
    for rel in source:
        if rel not in declared:
            assert out[rel] == source[rel], rel
    # Fresh copies only: nothing links back into the installed tree.
    for path in overlay.package_dir.rglob("*"):
        assert not path.is_symlink()
        if path.is_file():
            assert os.lstat(path).st_nlink == 1
    assert overlay.derived_data_sha256 == derived_data_sha256(overlay.derived_files)
    verify_tool_order_overlay(overlay, package_root=package, identity=identity)

    # Determinism: an independent materialization is byte-identical.
    again = materialize_tool_order_overlay(
        package_root=package, identity=identity, seed=_SEED, output_root=tmp_path / "again"
    )
    assert again.derived_files == overlay.derived_files
    assert again.derived_data_sha256 == overlay.derived_data_sha256
    assert tree_digests(again.package_dir) == out
    reseeded = materialize_tool_order_overlay(
        package_root=package, identity=identity, seed="other-seed", output_root=tmp_path / "reseed"
    )
    assert reseeded.derived_data_sha256 != overlay.derived_data_sha256


def test_materialization_fails_closed_on_pin_drift_and_occupied_output(tmp_path: Path) -> None:
    package = tmp_path / "site" / "bfcl_eval"
    identity = _substitute_package(tmp_path / "site")
    drifted = identity.model_copy(
        update={"files": {**identity.files, "data/BFCL_v4_multiple.json": "sha256:" + "0" * 64}}
    )
    with pytest.raises(BenchEvalError, match="drift"):
        materialize_tool_order_overlay(
            package_root=package, identity=drifted, seed=_SEED, output_root=tmp_path / "o1"
        )
    assert not (tmp_path / "o1").exists()
    occupied = tmp_path / "o2"
    (occupied / "pkg").mkdir(parents=True)
    (occupied / "pkg" / "stale").write_text("x")
    with pytest.raises(BenchEvalError, match="exclusive"):
        materialize_tool_order_overlay(
            package_root=package, identity=identity, seed=_SEED, output_root=occupied
        )
    linked_source = tmp_path / "linked"
    shutil.copytree(tmp_path / "site", linked_source)
    victim = linked_source / "bfcl_eval" / "eval_checker" / "eval_runner.py"
    victim.unlink()
    victim.symlink_to(package / "eval_checker" / "eval_runner.py")
    with pytest.raises(BenchEvalError, match="symlink"):
        materialize_tool_order_overlay(
            package_root=linked_source / "bfcl_eval",
            identity=identity,
            seed=_SEED,
            output_root=tmp_path / "o3",
        )
    single = _substitute_package(
        tmp_path / "single",
        rows={
            "multiple": [_row("multiple", 0, 1)],
            "parallel_multiple": [_row("parallel_multiple", 0, 2)],
        },
    )
    with pytest.raises(BenchEvalError, match="two"):
        materialize_tool_order_overlay(
            package_root=tmp_path / "single" / "bfcl_eval",
            identity=single,
            seed=_SEED,
            output_root=tmp_path / "o4",
        )


@pytest.mark.parametrize(
    ("label", "mutate", "match"),
    [
        (
            "symlinked data file",
            lambda o, p: (
                (o / "data/BFCL_v4_simple_python.json").unlink()
                or (o / "data/BFCL_v4_simple_python.json").symlink_to(
                    p / "data/BFCL_v4_simple_python.json"
                )
            ),
            "symlink",
        ),
        (
            "hardlinked scorer",
            lambda o, p: (
                (o / "eval_checker/eval_runner.py").unlink()
                or os.link(p / "eval_checker/eval_runner.py", o / "eval_checker/eval_runner.py")
            ),
            "link",
        ),
        (
            "replaced answer directory",
            lambda o, p: (
                shutil.rmtree(o / "data/possible_answer")
                or (o / "data/possible_answer").symlink_to(p / "data/possible_answer")
            ),
            "symlink",
        ),
        (
            "mutated scorer",
            lambda o, p: (o / "eval_checker/eval_runner.py").write_text(
                "def runner():\n    return 0\n"
            ),
            "eval_checker/eval_runner.py",
        ),
        (
            "mutated config",
            lambda o, p: (o / "eval_checker/checker.json").write_text('{"tolerance": 1}\n'),
            "eval_checker/checker.json",
        ),
        (
            "mutated derived data",
            lambda o, p: (o / "data/BFCL_v4_multiple.json").write_text(
                (o / "data/BFCL_v4_multiple.json").read_text().replace("question 1", "question X")
            ),
            "data/BFCL_v4_multiple.json",
        ),
        (
            "mutated ground truth",
            lambda o, p: (o / "data/possible_answer/BFCL_v4_multiple.json").write_text("{}\n"),
            "possible_answer",
        ),
        ("extra file", lambda o, p: (o / "eval_checker/extra.py").write_text("x = 1\n"), "extra"),
        ("missing file", lambda o, p: (o / "constants/eval_config.py").unlink(), "missing"),
    ],
)
def test_overlay_verification_rejects_every_tamper(
    tmp_path: Path, label: str, mutate: Callable[[Path, Path], object], match: str
) -> None:
    package, identity, overlay = _overlay(tmp_path)
    mutate(overlay.package_dir, package)
    with pytest.raises(BenchEvalError, match=match):
        verify_tool_order_overlay(overlay, package_root=package, identity=identity)
    # The installed tree was never touched by the overlay or the probe.
    assert tree_digests(package) == tree_digests(tmp_path / "site" / "bfcl_eval")


def test_overlay_verification_rejects_installed_tree_drift(tmp_path: Path) -> None:
    package, identity, overlay = _overlay(tmp_path)
    answer = package / "data" / "possible_answer" / "BFCL_v4_multiple.json"
    answer.write_text(answer.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(BenchEvalError, match="drift"):
        verify_tool_order_overlay(overlay, package_root=package, identity=identity)


def test_tree_digests_refuse_links_and_skip_bytecode(tmp_path: Path) -> None:
    package = tmp_path / "site" / "bfcl_eval"
    _substitute_package(tmp_path / "site")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    digests = tree_digests(package)
    assert not any(rel.startswith("__pycache__") for rel in digests)
    link = package / "data" / "link.json"
    link.symlink_to(package / "data" / "BFCL_v4_multiple.json")
    with pytest.raises(BenchEvalError, match="symlink"):
        tree_digests(package)
