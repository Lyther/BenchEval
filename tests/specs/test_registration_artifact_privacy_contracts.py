"""X4.2 contracts: a registration-bound run keeps its artifacts private and portable.

CF1 gave a BFCL run two artifacts no earlier run had: the registration manifest
the launch was bound to, and the copied upstream registry file that registration
came from. Both are retained evidence — a proof without them cannot show which
model identity was actually registered — and both describe the operator's host.
So they must travel inside a private proof and a private bundle byte for byte,
stay bound to the inventory that verifies them, and never reach a public bundle,
along with the absolute paths the run recorded.

The study-artifact side of this contract is X1.6's
(`test_exposure_artifact_retention_contracts.py`); the registration side had no
committed coverage until this module.

SUBSTITUTE_JUSTIFICATION
- substitute: a disposable copy of the retained CF1 candidate proof used as a
  run tree (its evidence, raw artifacts, and live-run history), plus disposable
  bundle/proof/store destinations under ``tmp_path``
- replaces: a charged BFCL run on the operator host and that host's permanent
  proof store
- necessity: export, import, verification, and public omission must be exercised
  end to end without charging a provider or writing the operator's store
- real-option: the artifacts, evidence rows, history, digests, and every
  production code path are real retained bytes from the dev-box CF1 run; nothing
  is synthesized or patched
- proof-limit: proves BenchEval-side retention, portability, and public omission
  for registration and derived study artifacts; it proves nothing about BFCL
  execution, scores, or the registration's upstream truth
- real-proof: the retained CF1.3 dev-box proofs in ``tests/fixtures/exposure/cf13``
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bencheval.exceptions import BenchEvalError
from bencheval.proof_bundle import (
    export_private_proof,
    import_private_proof,
    verify_private_proof,
)
from bencheval.run_bundle import export_run_bundle

_CF13 = Path(__file__).resolve().parents[1] / "fixtures" / "exposure" / "cf13" / "candidate"
_REGISTRATION = Path("execution/bfcl-registration.json")
_OVERLAY = Path("overlay/pkg/bfcl_eval/constants/model_config.py")
_DERIVED_STUDY = Path("study/benchmark-identity.json")


@pytest.fixture
def run(tmp_path: Path) -> Path:
    """A disposable copy of the retained run: evidence, raw artifacts, history."""
    destination = tmp_path / "run"
    shutil.copytree(_CF13, destination)
    return destination


def _rows(run: Path) -> list[dict[str, object]]:
    text = (run / "evidence.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _recorded_host_paths(rows: list[dict[str, object]]) -> tuple[str, ...]:
    """Absolute paths the retained run recorded, which no public output may carry."""
    found: set[str] = set()

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for token in value.split():
                if token.startswith("/") and len(token) > 20:
                    found.add(token)

    walk(rows)
    return tuple(sorted(found))


def _files(root: Path) -> list[Path]:
    return [path for path in sorted(root.rglob("*")) if path.is_file()]


def test_a_public_bundle_omits_the_raw_tree_and_every_recorded_host_path(run: Path) -> None:
    rows = _rows(run)
    host_paths = _recorded_host_paths(rows)
    assert host_paths, "the retained rows must contain the host paths this test looks for"
    bundle = run.parent / "public"

    export_run_bundle(
        evidence_path=run / "evidence.jsonl",
        output_dir=bundle,
        raw_dir=run / "artifacts" / "raw",
        redaction="public",
    )

    # The registration manifest, the copied upstream registry, and everything
    # else under raw/ stay on the operator's host.
    assert not (bundle / "raw").exists()
    assert not (bundle / "capture").exists()
    published = _files(bundle)
    assert published, "a public bundle must still publish the evidence and its report"
    for path in published:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for recorded in host_paths:
            assert recorded not in text, f"{path.name} published {recorded}"
    # The redacted evidence keeps no local locators at all.
    for row in (json.loads(line) for line in (bundle / "evidence.jsonl").read_text().splitlines()):
        assert row["artifact_paths"] == []
        assert row["native_score"] == {}
        assert row["verifier_log_path"] is None


def test_a_private_bundle_retains_the_registration_manifest_and_its_registry_copy(
    run: Path,
) -> None:
    raw = run / "artifacts" / "raw"
    bundle = run.parent / "private"

    export_run_bundle(
        evidence_path=run / "evidence.jsonl",
        output_dir=bundle,
        raw_dir=raw,
        redaction="private",
    )

    for relative in (_REGISTRATION, _OVERLAY, _DERIVED_STUDY):
        retained = bundle / "raw" / relative
        assert retained.is_file(), f"private bundle dropped {relative}"
        assert retained.read_bytes() == (raw / relative).read_bytes()
    # A second export cannot overwrite the first.
    with pytest.raises(BenchEvalError, match="empty or missing"):
        export_run_bundle(
            evidence_path=run / "evidence.jsonl",
            output_dir=bundle,
            raw_dir=raw,
            redaction="private",
        )


def test_a_private_proof_inventories_and_restores_the_registration_artifacts(
    run: Path, tmp_path: Path
) -> None:
    raw = run / "artifacts" / "raw"
    exported = export_private_proof(
        run_id=str(_rows(run)[0]["run_id"]),
        evidence_path=run / "evidence.jsonl",
        artifacts_dir=raw,
        manifest_path=run / "history.jsonl",
        output_dir=tmp_path / "proof",
    )

    inventory = json.loads((exported.root / "inventory.json").read_text(encoding="utf-8"))
    inventoried = {entry["path"]: entry for entry in inventory["files"]}
    for relative in (_REGISTRATION, _OVERLAY, _DERIVED_STUDY):
        key = f"artifacts/raw/{relative.as_posix()}"
        assert key in inventoried, f"proof inventory omits {key}"
        assert inventoried[key]["size"] == (raw / relative).stat().st_size
    assert verify_private_proof(exported.root) == exported.proof_id

    installed = import_private_proof(exported.root, store_root=tmp_path / "store")
    for relative in (_REGISTRATION, _OVERLAY, _DERIVED_STUDY):
        assert (installed / "artifacts" / "raw" / relative).read_bytes() == (
            raw / relative
        ).read_bytes()


def test_the_shipped_commands_still_read_the_retained_proof_and_lock(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Legacy read: proofs and locks retained before this packet still verify.

    The fixtures are read in place, exactly as an operator would point the
    commands at their permanent store.
    """
    from bencheval.cli import main

    x24fc = _CF13.parent.parent / "x24fc"
    store = tmp_path / "store"

    assert main(["proof", "verify", str(_CF13)]) == 0
    verified = json.loads(capsys.readouterr().out)
    assert verified["ok"] is True

    assert main(["proof", "import", str(_CF13), "--store", str(store)]) == 0
    installed = Path(json.loads(capsys.readouterr().out)["installed"])
    assert (installed / "artifacts" / "raw" / _REGISTRATION).read_bytes() == (
        _CF13 / "artifacts" / "raw" / _REGISTRATION
    ).read_bytes()

    reproduced = tmp_path / "reproduced.json"
    assert (
        main(
            [
                "study",
                "verify",
                "--lock",
                str(x24fc / "x24fc-exposure-report.lock.json"),
                "--canonical-proof",
                str(x24fc / "canonical"),
                "--candidate-proof",
                str(x24fc / "candidate"),
                "--output",
                str(reproduced),
            ],
        )
        == 0
    )
    assert reproduced.read_bytes() == (x24fc / "x24fc-exposure-report.json").read_bytes()


def test_a_changed_registration_artifact_fails_verification_and_import(
    run: Path, tmp_path: Path
) -> None:
    """The registration manifest is inventory-bound, not merely carried along."""
    exported = export_private_proof(
        run_id=str(_rows(run)[0]["run_id"]),
        evidence_path=run / "evidence.jsonl",
        artifacts_dir=run / "artifacts" / "raw",
        manifest_path=run / "history.jsonl",
        output_dir=tmp_path / "proof",
    )
    planted = exported.root / "artifacts" / "raw" / _REGISTRATION
    original = json.loads(planted.read_text(encoding="utf-8"))
    tampered = dict(original)
    tampered["model_name"] = "some-other-model"
    planted.write_text(json.dumps(tampered), encoding="utf-8")

    with pytest.raises(BenchEvalError):
        verify_private_proof(exported.root)
    with pytest.raises(BenchEvalError):
        import_private_proof(exported.root, store_root=tmp_path / "store")
    assert not (tmp_path / "store").exists() or not any((tmp_path / "store").rglob("proof.json"))
