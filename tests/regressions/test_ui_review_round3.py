"""Regressions for proof-store isolation and sibling output ownership.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed evidence/history/artifact source from
  ``tests.specs.test_private_proof_v1_contracts._write_source`` and a disposable
  ``BENCHEVAL_HOME`` containing a byte-copy of the real checked-in config bundle
- replaces: a charged native benchmark run, its private raw artifact tree, and the
  operator's permanent proof store/config root
- necessity: the tests must deterministically add un-inventoried residue and symlink redirects
  without corrupting the operator's permanent proof store or real evidence
- real-option: the operator store cannot safely be corrupted for a repeatable negative test;
  the copied config is required so the real readiness projection can target the disposable store
- proof-limit: proves proof-list fault isolation and output-path ownership only; it does not prove
  native harness execution, scoring truth, or live readiness
- real-proof: the retained HLE proof and disposable real-browser action matrix documented in the
  operator-console readiness handoff
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bencheval.application import OperatorOperations, proof_inventory_counts
from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root
from bencheval.proof_bundle import (
    default_proofs_dir,
    export_private_proof,
    import_private_proof,
    list_private_proofs,
)
from tests.specs.test_private_proof_v1_contracts import _RUN_ID, _write_source


def _export_source(
    tmp_path: Path,
    *,
    name: str = "proof",
    with_plan: bool = True,
):
    source = _write_source(tmp_path / f"source-{name}", with_plan=with_plan)
    exported = export_private_proof(
        run_id=_RUN_ID,
        evidence_path=source["evidence"],
        artifacts_dir=source["raw"],
        manifest_path=source["manifest"],
        output_dir=tmp_path / name,
    )
    return source, exported


def _write_console_output(
    operations: OperatorOperations,
    operation: str,
    source: dict[str, Path],
    link: Path,
) -> None:
    if operation == "report":
        operations.report(source["evidence"], link / "report.md")
    elif operation == "compare":
        operations.compare(
            source["evidence"],
            source["evidence"],
            link / "compare.md",
            output_format="markdown",
        )
    elif operation == "bundle":
        operations.bundle(
            source["evidence"],
            link,
            raw_dir=None,
            redaction="public",
        )
    else:
        operations.proof_export(
            run_id=_RUN_ID,
            evidence_path=source["evidence"],
            artifacts_dir=source["raw"],
            manifest_path=source["manifest"],
            output_dir=link / "proof",
        )


def test_proof_inventory_isolates_one_corrupt_object(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / "home"
    shutil.copytree(repo_root() / "config", home / "config")
    monkeypatch.setenv("BENCHEVAL_HOME", str(home))
    _, healthy = _export_source(tmp_path, name="healthy")
    _, corrupt = _export_source(tmp_path, name="corrupt", with_plan=False)
    store = default_proofs_dir()
    import_private_proof(healthy.root, store_root=store)
    corrupt_root = import_private_proof(corrupt.root, store_root=store)
    (corrupt_root / "history.jsonl.lock").touch()

    operations = OperatorOperations()
    views = operations.proofs(store)
    by_id = {row.proof_id: row for row in views}
    assert len(views) == 2
    assert by_id[healthy.proof_id].verified is True
    assert by_id[corrupt.proof_id].verified is False
    assert "history.jsonl.lock" in str(by_id[corrupt.proof_id].classification_reason)
    assert proof_inventory_counts(views) == (1, 1)
    terminal_bench = next(
        row for row in operations.readiness() if row.benchmark_id == "terminal-bench"
    )
    assert terminal_bench.tier1_state == "proof-present-not-tier1"

    with pytest.raises(BenchEvalError, match=corrupt.proof_id.removeprefix("sha256:")):
        list_private_proofs(store)

    (store / "proofs.jsonl").write_text("{bad\n", encoding="utf-8")
    with pytest.raises(BenchEvalError, match="corrupt proof index"):
        operations.proofs(store)


@pytest.mark.parametrize("operation", ["report", "compare", "bundle", "proof"])
def test_console_writes_reject_symlink_redirects(tmp_path: Path, operation: str) -> None:
    source, _ = _export_source(tmp_path)
    redirect = tmp_path / "redirect"
    redirect.mkdir()
    link = tmp_path / "link"
    link.symlink_to(redirect, target_is_directory=True)
    operations = OperatorOperations()

    with pytest.raises(BenchEvalError, match="symlink"):
        _write_console_output(operations, operation, source, link)

    assert list(redirect.iterdir()) == []
