"""Immutable benchmark identity contracts for GPQA / HLE / BFCL.

Feature scope:
- catalog ``identity:`` blocks (shape + validation, additive; no flag changes),
- captured identity strings (exact, never provisional),
- pre-launch runtime verification cores on real local bytes,
- run-level fail-closed gating (drift blocks launch, identity is stamped),
- executor ``benchmark_version`` stamping preference,
- the opt-in ``--diagnostic`` route and the passed-registration executable gate.

Only the network-fetch seam (HF snapshot/download, CSV download) and the
injected process-runner boundary are substituted; every digest comparison runs
against real bytes on disk. Each substituted seam carries its justification at
the call site.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

import datasets
import huggingface_hub
import pytest
import yaml

import bencheval.hle_adapter as hle_adapter
from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import (
    BfclPackageDataIdentity,
    HfDatasetSnapshotIdentity,
    load_benchmark_catalog,
)
from bencheval.cli import _qualify_passed_registration, main
from bencheval.config_cache import clear_config_loader_caches
from bencheval.control_plane_executor import (
    _evidence_benchmark_version,
    _require_executable_benchmark,
    control_plane_interpretation_label,
    execute_control_plane_run,
)
from bencheval.domain import InterpretationLabel
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink, read_evidence_jsonl
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.gpqa_adapter import GpqaCliResult, run_gpqa_slice
from bencheval.hle_adapter import HleCliResult, hle_run_paths, run_hle_slice
from bencheval.live_proof import qualify_lane
from bencheval.provenance_gates import is_provisional_benchmark_version
from tests.factories import make_control_plane_evidence_record

_REPO_ROOT = Path(__file__).resolve().parents[2]

_GPQA_CSV_URL = "https://openaipublic.blob.core.windows.net/simple-evals/gpqa_diamond.csv"
_GPQA_CSV_SHA = "sha256:41d1213cd7a4998605a26c2798500652572007161b3a92817ba46b35befcd305"
_GPQA_IDENTITY = "gpqa-diamond@inspect-evals-0.8.0+eval-2-B+csv-41d1213cd7a49986"

_HLE_REPO = "cais/hle"
_HLE_REVISION = "5a81a4c7271a2a2a312b9a690f0c2fde837e4c29"
_HLE_PARQUET_RELPATH = "data/test-00000-of-00001.parquet"
_HLE_PARQUET_SHA = "sha256:6d0ee0602e8aea6b159509577e884f48ecac7b8e3f6822a35f51335a446c726a"
_HLE_IDENTITY = "hle@5a81a4c7271a2a2a+data-6d0ee0602e8aea6b"

_BFCL_EVAL_VERSION = "2026.3.23"
_BFCL_UPSTREAM_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
_BFCL_FILES = {
    "data/BFCL_v4_irrelevance.json": (
        "sha256:2b6ed4c2e992cdcf5f1678a701851f944bef7550ee026ed1ddb89efed5be01a6"
    ),
    "data/BFCL_v4_multiple.json": (
        "sha256:aef168155ebd74b7ac2401198b201343bc7d16d7a3d7e0d4e6d8ee82c6969b2a"
    ),
    "data/BFCL_v4_parallel.json": (
        "sha256:19f51a82eff42e5d62541aa500115a056eb78f437c2ba1f10415fd7c8e5dda84"
    ),
    "data/BFCL_v4_parallel_multiple.json": (
        "sha256:8863ea8433239f55c5f016154cf0830853c89f693c6ea270396a2fa121960579"
    ),
    "data/BFCL_v4_simple_python.json": (
        "sha256:82dd63ba502eb2520c6b5d1d9a5c4b590e03ff261565175561f6228a367d1991"
    ),
    "data/possible_answer/BFCL_v4_multiple.json": (
        "sha256:244e00ce9395df948bcafc7bee64e8f9c87ef70887587d83cae45b13699f3047"
    ),
    "data/possible_answer/BFCL_v4_parallel.json": (
        "sha256:8a6aa19c1adddc6a5a2f7e40f9dbf30cc7e95815e7b830c90589ab318229e0f0"
    ),
    "data/possible_answer/BFCL_v4_parallel_multiple.json": (
        "sha256:5ebf24f458c1f16300c05505d83d6f0a1b68b79be273a033febd0d4f840507e3"
    ),
    "data/possible_answer/BFCL_v4_simple_python.json": (
        "sha256:90cd5bc653690ee8e459b5b3f3fc9458606f7f3fcbf795bb51b7dc581f8c86dc"
    ),
}
# sha256 over the sorted "<relpath>:<sha256>\n" lines of the nine pinned files
# (all five smoke-5 categories; irrelevance has no possible_answer file in v4).
_BFCL_COMBINED_DATA_SHA = "79bb46df7e8c7d7bbbf9f6c0db3c3fde16b332aa51e3cea296499f1296302e9a"
_BFCL_IDENTITY = "bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b"


def _gpqa_plan(**kwargs):
    return plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
        **kwargs,
    )


def _hle_plan(**kwargs):
    return plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
        **kwargs,
    )


def _plain_hle_home(tmp_path: Path) -> Path:
    home = tmp_path / "hle-home"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# stub predict\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# stub judge\n", encoding="utf-8")
    return home


def _write_gpqa_done_log(command: tuple[str, ...], log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "2026-08-19T040000_gpqa_diamond.json"
    log_path.write_text(
        json.dumps(
            {
                "status": "success",
                "eval": {
                    "task": "gpqa_diamond",
                    "model": command[command.index("--model") + 1],
                },
                "results": {
                    "total_samples": 2,
                    "completed_samples": 2,
                    "scores": [{"name": "choice", "metrics": {"accuracy": {"value": 1.0}}}],
                },
            },
        )
        + "\n",
        encoding="utf-8",
    )
    return log_path


def _sha256_pin(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


# ---------------------------------------------------------------------------
# A. Catalog identity config surface
# ---------------------------------------------------------------------------


def test_catalog_exposes_pinned_identities_for_gpqa_hle_bfcl() -> None:
    catalog = load_benchmark_catalog()

    gpqa = catalog.by_id_or_alias("gpqa-diamond").identity
    assert gpqa is not None
    assert gpqa.kind == "inspect-evals-csv"
    assert gpqa.package == "inspect-evals"
    assert gpqa.package_version == "0.8.0"
    assert gpqa.eval_version == "2-B"
    assert gpqa.dataset_url == _GPQA_CSV_URL
    assert gpqa.sha256 == _GPQA_CSV_SHA

    # HLE pins the OFFICIAL CAIS dataset (product decision: option (a) after the
    # review-F002 mirror revert). The pinned repo must be exactly ``cais/hle`` —
    # never the third-party mirror that silently rebound the benchmark.
    hle = catalog.by_id_or_alias("hle").identity
    assert hle is not None
    assert hle.kind == "hf-dataset-snapshot"
    assert hle.repo == _HLE_REPO == "cais/hle"
    assert hle.repo != "macabdul9/hle_text_only"
    assert hle.revision == _HLE_REVISION
    assert hle.files == {_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA}

    bfcl = catalog.by_id_or_alias("bfcl-v4").identity
    assert bfcl is not None
    assert bfcl.kind == "bfcl-package-data"
    assert bfcl.bfcl_eval_version == _BFCL_EVAL_VERSION
    assert bfcl.upstream_commit == _BFCL_UPSTREAM_COMMIT
    assert bfcl.files == _BFCL_FILES


def test_identity_binding_does_not_change_catalog_admission() -> None:
    """Identity binding is orthogonal to admission: 8 benchmarks, 4 executable."""
    catalog = load_benchmark_catalog()
    assert len(catalog.benchmarks) == 8
    executable = sorted(b.id for b in catalog.benchmarks if b.executable)
    assert executable == ["bfcl-v4", "gpqa-diamond", "hle", "terminal-bench"]


def _minimal_entry(identity: object) -> dict[str, object]:
    return {
        "id": "identity-test-bench",
        "name": "Identity Test Bench",
        "category": "reasoning",
        "tier": "calibration",
        "adapter_status": "manifest_available",
        "recommended_backend": "inspect",
        "recommended_profile": "E3",
        "public_indexed": True,
        "contamination_risk": "medium",
        "single_mode_required": False,
        "notes": "validation fixture",
        "identity": identity,
    }


def _load_catalog_with(tmp_path: Path, entry: dict[str, object]):
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "benchmarks.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": 1, "benchmarks": [entry]}),
        encoding="utf-8",
    )
    return load_benchmark_catalog(path)


def test_unknown_identity_kind_is_a_catalog_load_error(tmp_path: Path) -> None:
    entry = _minimal_entry({"kind": "git-commit", "repo": "x/y"})
    # The discriminated-union error names the expected tags; the pre-feature
    # extra-forbidden error (which echoes the input) must not satisfy this.
    with pytest.raises(BenchEvalError, match="expected tags"):
        _load_catalog_with(tmp_path, entry)


@pytest.mark.parametrize(
    "bad_sha",
    [
        "41d1213cd7a4998605a26c2798500652572007161b3a92817ba46b35befcd305",  # no sha256: prefix
        "sha256:41d1213c",  # too short
        "sha256:Z" + "1" * 63,  # non-hex character in digest
    ],
)
def test_gpqa_identity_sha256_must_be_prefixed_64_hex(tmp_path: Path, bad_sha: str) -> None:
    entry = _minimal_entry(
        {
            "kind": "inspect-evals-csv",
            "package": "inspect-evals",
            "package_version": "0.8.0",
            "eval_version": "2-B",
            "dataset_url": _GPQA_CSV_URL,
            "sha256": bad_sha,
        },
    )
    with pytest.raises(BenchEvalError, match="sha256"):
        _load_catalog_with(tmp_path, entry)


@pytest.mark.parametrize("bad_revision", ["e3e9cb5a", "Z" * 40])
def test_hle_identity_revision_must_be_40_hex(tmp_path: Path, bad_revision: str) -> None:
    entry = _minimal_entry(
        {
            "kind": "hf-dataset-snapshot",
            "repo": _HLE_REPO,
            "revision": bad_revision,
            "files": {_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA},
        },
    )
    with pytest.raises(BenchEvalError, match="revision"):
        _load_catalog_with(tmp_path, entry)


def test_hle_identity_requires_files_and_revision(tmp_path: Path) -> None:
    no_revision = _minimal_entry(
        {
            "kind": "hf-dataset-snapshot",
            "repo": _HLE_REPO,
            "files": {_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA},
        },
    )
    with pytest.raises(BenchEvalError, match="revision"):
        _load_catalog_with(tmp_path / "a", no_revision)
    empty_files = _minimal_entry(
        {"kind": "hf-dataset-snapshot", "repo": _HLE_REPO, "revision": _HLE_REVISION, "files": {}},
    )
    with pytest.raises(BenchEvalError, match="files"):
        _load_catalog_with(tmp_path / "b", empty_files)


def test_hle_identity_file_digests_must_be_prefixed_64_hex(tmp_path: Path) -> None:
    entry = _minimal_entry(
        {
            "kind": "hf-dataset-snapshot",
            "repo": _HLE_REPO,
            "revision": _HLE_REVISION,
            "files": {_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA.removeprefix("sha256:")},
        },
    )
    with pytest.raises(BenchEvalError, match="sha256"):
        _load_catalog_with(tmp_path, entry)


def test_gpqa_identity_requires_eval_version(tmp_path: Path) -> None:
    entry = _minimal_entry(
        {
            "kind": "inspect-evals-csv",
            "package": "inspect-evals",
            "package_version": "0.8.0",
            "dataset_url": _GPQA_CSV_URL,
            "sha256": _GPQA_CSV_SHA,
        },
    )
    with pytest.raises(BenchEvalError, match="eval_version"):
        _load_catalog_with(tmp_path, entry)


def test_bfcl_identity_requires_commit_version_and_files(tmp_path: Path) -> None:
    bad_commit = _minimal_entry(
        {
            "kind": "bfcl-package-data",
            "bfcl_eval_version": _BFCL_EVAL_VERSION,
            "upstream_commit": "6ea57973",
            "files": _BFCL_FILES,
        },
    )
    with pytest.raises(BenchEvalError, match="upstream_commit"):
        _load_catalog_with(tmp_path / "a", bad_commit)
    missing_files = _minimal_entry(
        {
            "kind": "bfcl-package-data",
            "bfcl_eval_version": _BFCL_EVAL_VERSION,
            "upstream_commit": _BFCL_UPSTREAM_COMMIT,
        },
    )
    with pytest.raises(BenchEvalError, match="files"):
        _load_catalog_with(tmp_path / "b", missing_files)


def test_bfcl_catalog_identity_pins_all_smoke_category_files() -> None:
    # The smoke-5 slice runs five categories; every question and answer data
    # file behind them must be pinned. irrelevance has no possible_answer file
    # in v4 by design (it scores on "no function called"), so the pin set is
    # nine files, not ten.
    identity = load_benchmark_catalog().by_id_or_alias("bfcl-v4").identity
    assert isinstance(identity, BfclPackageDataIdentity)
    assert dict(identity.files) == _BFCL_FILES


# ---------------------------------------------------------------------------
# B. Captured identity strings
# ---------------------------------------------------------------------------


def test_captured_identity_strings_match_pinned_values() -> None:
    from bencheval.identity_strings import (
        bfcl_benchmark_identity,
        gpqa_benchmark_identity,
        hle_benchmark_identity,
    )

    catalog = load_benchmark_catalog()
    gpqa_entry = catalog.by_id_or_alias("gpqa-diamond")
    assert gpqa_benchmark_identity(gpqa_entry.identity) == _GPQA_IDENTITY
    assert hle_benchmark_identity(catalog.by_id_or_alias("hle").identity) == _HLE_IDENTITY
    assert bfcl_benchmark_identity(catalog.by_id_or_alias("bfcl-v4").identity) == _BFCL_IDENTITY


def test_combined_data_sha256_is_sorted_and_stable() -> None:
    from bencheval.identity_strings import combined_data_sha256

    assert combined_data_sha256(_BFCL_FILES) == _BFCL_COMBINED_DATA_SHA
    reversed_files = dict(reversed(list(_BFCL_FILES.items())))
    assert combined_data_sha256(reversed_files) == _BFCL_COMBINED_DATA_SHA
    # A single-file pin binds that file's own digest directly (HLE shape).
    hle_single_file = {_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA}
    assert combined_data_sha256(hle_single_file) == _HLE_PARQUET_SHA.removeprefix("sha256:")


def test_captured_identities_are_not_provisional() -> None:
    for value in (_GPQA_IDENTITY, _HLE_IDENTITY, _BFCL_IDENTITY):
        assert not is_provisional_benchmark_version(value)
    assert is_provisional_benchmark_version("provisional:gpqa-diamond/inspect-evals")
    assert is_provisional_benchmark_version("provisional:hle/cais")
    assert is_provisional_benchmark_version("provisional:bfcl-v4/generate-smoke")


def _gpqa_qualifying_row(tmp_path: Path, *, benchmark_version: str) -> EvidenceRecord:
    verifier = tmp_path / "verifier.json"
    verifier.write_text('{"accuracy": 1.0}\n', encoding="utf-8")
    return EvidenceRecord(
        run_id="identity-qualify",
        task_id="gpqa-aggregate",
        model_id="kimi-k2.7-code",
        execution_profile="E0",
        backend="inspect",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.1,
        latency_sec=1.0,
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
        benchmark_id="gpqa-diamond",
        benchmark_version=benchmark_version,
        slice_id="smoke",
        adapter_id="gpqa",
        harness_kind="inspect-evals",
        harness_version="inspect-evals@0.8.0",
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm-test",
        instance_id="gpqa-aggregate",
        interpretation_label="adapter_smoke",
        artifact_paths=[str(verifier)],
        verifier_log_path=str(verifier),
        verifier_integrity_label="native",
        counts_toward_pass_at_k=True,
    )


def test_qualify_lane_accepts_captured_gpqa_identity(tmp_path: Path) -> None:
    row = _gpqa_qualifying_row(tmp_path, benchmark_version=_GPQA_IDENTITY)
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, row)

    q = qualify_lane(
        evidence,
        expected_instances=1,
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        require_runtime=False,
        repo_root=tmp_path,
    )

    assert q.ok, "; ".join(q.reasons)


def test_qualify_lane_still_rejects_provisional_gpqa_identity(tmp_path: Path) -> None:
    row = _gpqa_qualifying_row(
        tmp_path,
        benchmark_version="provisional:gpqa-diamond/inspect-evals",
    )
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, row)

    q = qualify_lane(
        evidence,
        expected_instances=1,
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        require_runtime=False,
        repo_root=tmp_path,
    )

    assert not q.ok
    assert "provisional" in " ".join(q.reasons).lower()


def _hle_qualifying_row(tmp_path: Path, *, benchmark_version: str) -> EvidenceRecord:
    verifier = tmp_path / "hle_summary.json"
    verifier.write_text('{"accuracy": 1.0}\n', encoding="utf-8")
    return EvidenceRecord(
        run_id="identity-qualify-hle",
        task_id="hle-aggregate",
        model_id="kimi-k2.7-code",
        execution_profile="E3",
        backend="inspect",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.1,
        latency_sec=1.0,
        created_at=datetime(2026, 8, 19, tzinfo=UTC),
        benchmark_id="hle",
        benchmark_version=benchmark_version,
        slice_id="smoke",
        adapter_id="hle",
        harness_kind="hle-native",
        harness_version="hle@5a81a4c",
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm-test",
        judge_model_id="gpt-5.3-chat-2026-03-03",
        instance_id="hle-aggregate",
        interpretation_label="adapter_smoke",
        artifact_paths=[str(verifier)],
        verifier_log_path=str(verifier),
        verifier_integrity_label="native",
        counts_toward_pass_at_k=True,
    )


def test_qualify_lane_accepts_captured_hle_identity(tmp_path: Path) -> None:
    """Pinned-official hle evidence with the captured identity is eligible."""
    row = _hle_qualifying_row(tmp_path, benchmark_version=_HLE_IDENTITY)
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, row)

    q = qualify_lane(
        evidence,
        expected_instances=1,
        benchmark_id="hle",
        slice_id="smoke",
        require_runtime=False,
        repo_root=tmp_path,
    )

    assert q.ok, "; ".join(q.reasons)


def test_qualify_lane_rejects_provisional_hle_identity(tmp_path: Path) -> None:
    """A provisional-LABELED hle row stays unregistrable even with the pin restored.

    The disqualifier is label-based: it protects any benchmark whose evidence
    carries a ``provisional:*`` fallback, hle included.
    """
    row = _hle_qualifying_row(tmp_path, benchmark_version="provisional:hle/cais")
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, row)

    q = qualify_lane(
        evidence,
        expected_instances=1,
        benchmark_id="hle",
        slice_id="smoke",
        require_runtime=False,
        repo_root=tmp_path,
    )

    assert not q.ok
    assert "provisional" in " ".join(q.reasons).lower()


# ---------------------------------------------------------------------------
# C1. GPQA runtime verification
# ---------------------------------------------------------------------------


def test_gpqa_csv_cache_verifier_accepts_real_pinned_bytes(tmp_path: Path) -> None:
    from bencheval.gpqa_adapter import gpqa_csv_cache_path, verify_gpqa_csv_cache

    payload = b"Question,Correct Answer\nq?,a\n"
    pin = _sha256_pin(payload)
    cache_root = tmp_path / "inspect-cache"
    cached = gpqa_csv_cache_path(cache_root=cache_root, dataset_url=_GPQA_CSV_URL)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(payload)

    assert (
        verify_gpqa_csv_cache(cache_root=cache_root, dataset_url=_GPQA_CSV_URL, sha256_pin=pin)
        == cached
    )


def test_gpqa_csv_cache_verifier_rejects_mismatching_bytes(tmp_path: Path) -> None:
    from bencheval.gpqa_adapter import gpqa_csv_cache_path, verify_gpqa_csv_cache

    cache_root = tmp_path / "inspect-cache"
    cached = gpqa_csv_cache_path(cache_root=cache_root, dataset_url=_GPQA_CSV_URL)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"drifted\n")

    with pytest.raises(BenchEvalError, match="sha256"):
        verify_gpqa_csv_cache(
            cache_root=cache_root,
            dataset_url=_GPQA_CSV_URL,
            sha256_pin=_GPQA_CSV_SHA,
        )


def test_gpqa_csv_cache_verifier_fails_closed_when_missing(tmp_path: Path) -> None:
    from bencheval.gpqa_adapter import verify_gpqa_csv_cache

    with pytest.raises(BenchEvalError, match=r"(?i)(missing|absent|not found)"):
        verify_gpqa_csv_cache(
            cache_root=tmp_path / "inspect-cache",
            dataset_url=_GPQA_CSV_URL,
            sha256_pin=_GPQA_CSV_SHA,
        )


def _test_gpqa_identity(*, package_version: str = "0.8.0", sha256: str):
    from bencheval.benchmark_registry import InspectEvalsCsvIdentity

    return InspectEvalsCsvIdentity(
        kind="inspect-evals-csv",
        package="inspect-evals",
        package_version=package_version,
        eval_version="2-B",
        dataset_url=_GPQA_CSV_URL,
        sha256=sha256,
    )


def test_capture_gpqa_identity_binds_dist_eval_and_csv_bytes(tmp_path: Path) -> None:
    """Real installed inspect-evals dist + eval metadata; only the download is substituted.

    SUBSTITUTE_JUSTIFICATION
    - substitute: ``fetcher`` callable writing pinned bytes to the cache path
    - replaces: HTTPS download of the pinned CSV from ``dataset_url``
    - necessity: the network fetch is an external service effect; the assertion
      targets local digest verification and capture, not TLS/download behavior
    - real-option: live download from openaipublic.blob.core.windows.net — a
      charged external fetch, nondeterministic inside a unit test
    - proof-limit: does not prove the remote object matches the pin today
    - real-proof: dev-box live lane (docs/ops/dev-box-pilot.md) downloads and
      verifies the real CSV before launch
    """
    from bencheval.gpqa_adapter import capture_gpqa_benchmark_identity

    payload = b"Question,Correct Answer\nq?,a\n"
    pin = _sha256_pin(payload)
    identity = _test_gpqa_identity(sha256=pin)
    cache_root = tmp_path / "inspect-cache"

    def fetcher(*, dataset_url: str, dest: Path) -> None:
        assert dataset_url == _GPQA_CSV_URL
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)

    captured = capture_gpqa_benchmark_identity(identity, cache_root=cache_root, fetcher=fetcher)

    csv_tag = pin.removeprefix("sha256:")[:16]
    assert captured == f"gpqa-diamond@inspect-evals-0.8.0+eval-2-B+csv-{csv_tag}"

    def refetch_boom(*, dataset_url: str, dest: Path) -> None:
        raise AssertionError("verified cache must be reused, never refetched")

    assert (
        capture_gpqa_benchmark_identity(identity, cache_root=cache_root, fetcher=refetch_boom)
        == captured
    )


def test_capture_gpqa_identity_fails_closed_on_csv_drift_and_never_overwrites(
    tmp_path: Path,
) -> None:
    from bencheval.gpqa_adapter import capture_gpqa_benchmark_identity, gpqa_csv_cache_path

    identity = _test_gpqa_identity(sha256=_GPQA_CSV_SHA)
    cache_root = tmp_path / "inspect-cache"
    cached = gpqa_csv_cache_path(cache_root=cache_root, dataset_url=_GPQA_CSV_URL)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"poisoned existing cache\n")

    def overwriting_fetcher(*, dataset_url: str, dest: Path) -> None:
        dest.write_bytes(b"replacement\n")

    with pytest.raises(BenchEvalError, match="sha256"):
        capture_gpqa_benchmark_identity(
            identity, cache_root=cache_root, fetcher=overwriting_fetcher
        )
    assert cached.read_bytes() == b"poisoned existing cache\n"


def test_capture_gpqa_identity_fails_closed_on_dist_version_drift(tmp_path: Path) -> None:
    """The dist-version check runs against the real installed inspect-evals."""
    from bencheval.gpqa_adapter import capture_gpqa_benchmark_identity

    identity = _test_gpqa_identity(package_version="0.0.0-not-installed", sha256=_GPQA_CSV_SHA)

    def fetcher(*, dataset_url: str, dest: Path) -> None:
        raise AssertionError("dist drift must fail before any fetch")

    with pytest.raises(BenchEvalError, match="inspect-evals"):
        capture_gpqa_benchmark_identity(identity, cache_root=tmp_path / "c", fetcher=fetcher)


# ---------------------------------------------------------------------------
# C2. HLE runtime verification
# ---------------------------------------------------------------------------


def test_verify_hle_snapshot_files_accepts_real_bytes(tmp_path: Path) -> None:
    from bencheval.hle_adapter import verify_hle_snapshot_files

    payload = b"parquet-bytes\n"
    snapshot = tmp_path / "snapshot"
    target = snapshot / _HLE_PARQUET_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    verify_hle_snapshot_files(
        snapshot_dir=snapshot,
        files={_HLE_PARQUET_RELPATH: _sha256_pin(payload)},
    )


def test_verify_hle_snapshot_files_accepts_hub_cache_blob_symlink(tmp_path: Path) -> None:
    """Real HF hub caches store snapshot entries as symlinks into the repo's
    own blobs/ store (observed on the dev-box pre-warm of cais/hle). A link
    that resolves strictly inside the same repo cache root to a plain file
    with the pinned bytes must verify."""
    from bencheval.hle_adapter import verify_hle_snapshot_files

    payload = b"parquet-bytes\n"
    repo_cache = tmp_path / "datasets--cais--hle"
    blob = repo_cache / "blobs" / "6d0ee0602e8aea6b"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)
    snapshot = repo_cache / "snapshots" / ("5" * 40)
    target = snapshot / _HLE_PARQUET_RELPATH
    target.parent.mkdir(parents=True)
    target.symlink_to(Path("../../../blobs") / blob.name)

    verify_hle_snapshot_files(
        snapshot_dir=snapshot,
        files={_HLE_PARQUET_RELPATH: _sha256_pin(payload)},
    )


def test_verify_hle_snapshot_files_rejects_symlink_escaping_cache_root(tmp_path: Path) -> None:
    """A snapshot symlink resolving OUTSIDE the repo cache root is a foreign
    target and fails closed — even when the pointed-to bytes match the pin."""
    from bencheval.hle_adapter import verify_hle_snapshot_files

    payload = b"parquet-bytes\n"
    outside = tmp_path / "outside.parquet"
    outside.write_bytes(payload)
    repo_cache = tmp_path / "datasets--cais--hle"
    snapshot = repo_cache / "snapshots" / ("5" * 40)
    target = snapshot / _HLE_PARQUET_RELPATH
    target.parent.mkdir(parents=True)
    target.symlink_to(outside)

    with pytest.raises(BenchEvalError):
        verify_hle_snapshot_files(
            snapshot_dir=snapshot,
            files={_HLE_PARQUET_RELPATH: _sha256_pin(payload)},
        )


def test_verify_hle_snapshot_files_rejects_in_cache_symlink_with_drifted_bytes(
    tmp_path: Path,
) -> None:
    """An intra-cache link still hashes the real resolved bytes."""
    from bencheval.hle_adapter import verify_hle_snapshot_files

    repo_cache = tmp_path / "datasets--cais--hle"
    blob = repo_cache / "blobs" / "deadbeef"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"drifted\n")
    snapshot = repo_cache / "snapshots" / ("5" * 40)
    target = snapshot / _HLE_PARQUET_RELPATH
    target.parent.mkdir(parents=True)
    target.symlink_to(Path("../../../blobs") / blob.name)

    with pytest.raises(BenchEvalError, match="sha256"):
        verify_hle_snapshot_files(
            snapshot_dir=snapshot, files={_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA}
        )


def test_verify_hle_snapshot_files_fails_closed_on_drift_and_absence(tmp_path: Path) -> None:
    from bencheval.hle_adapter import verify_hle_snapshot_files

    snapshot = tmp_path / "snapshot"
    target = snapshot / _HLE_PARQUET_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"drifted\n")
    with pytest.raises(BenchEvalError, match="sha256"):
        verify_hle_snapshot_files(
            snapshot_dir=snapshot, files={_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA}
        )

    target.unlink()
    with pytest.raises(BenchEvalError, match=r"(?i)(missing|absent|not found)"):
        verify_hle_snapshot_files(
            snapshot_dir=snapshot, files={_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA}
        )


def test_hle_datasets_cache_must_contain_exactly_the_pinned_revision(tmp_path: Path) -> None:
    from bencheval.hle_adapter import hle_datasets_cache_error

    cache = tmp_path / "datasets"
    pinned = cache / "cais___hle" / "default" / "0.0.0" / _HLE_REVISION
    pinned.mkdir(parents=True)
    assert (
        hle_datasets_cache_error(datasets_cache=cache, repo=_HLE_REPO, revision=_HLE_REVISION)
        is None
    )

    # A second cached revision means a drifted dataset was once materialized.
    (pinned.parent / ("0" * 40)).mkdir()
    assert hle_datasets_cache_error(datasets_cache=cache, repo=_HLE_REPO, revision=_HLE_REVISION)

    missing = tmp_path / "empty"
    assert hle_datasets_cache_error(datasets_cache=missing, repo=_HLE_REPO, revision=_HLE_REVISION)


def test_capture_hle_identity_binds_snapshot_and_cache(tmp_path: Path) -> None:
    """Real snapshot bytes on disk; only the HF download/pre-warm seam is substituted.

    SUBSTITUTE_JUSTIFICATION
    - substitute: ``fetcher`` callable materializing a local snapshot dir
    - replaces: ``huggingface_hub.snapshot_download`` + ``datasets.load_dataset``
      pre-warm against huggingface.co (or HF_ENDPOINT mirror)
    - necessity: external service effect; the assertion targets local digest
      verification, cache singleness, and identity capture
    - real-option: live snapshot_download of cais/hle — external fetch (and the
      dataset is access-gated), nondeterministic inside a unit test
    - proof-limit: does not prove the remote revision matches the pin today
    - real-proof: dev-box live lane downloads, verifies, and pre-warms the real
      snapshot before an offline launch
    """
    from bencheval.benchmark_registry import HfDatasetSnapshotIdentity
    from bencheval.hle_adapter import capture_hle_benchmark_identity

    payload = b"parquet-bytes\n"
    revision = "1" * 40
    identity = HfDatasetSnapshotIdentity(
        kind="hf-dataset-snapshot",
        repo=_HLE_REPO,
        revision=revision,
        files={_HLE_PARQUET_RELPATH: _sha256_pin(payload)},
    )
    snapshot = tmp_path / "snapshot"
    cache = tmp_path / "datasets"

    def fetcher(*, repo: str, revision: str, datasets_cache: Path) -> Path:
        assert repo == _HLE_REPO
        target = snapshot / _HLE_PARQUET_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        assert datasets_cache == cache
        (datasets_cache / "cais___hle" / "default" / "0.0.0" / revision).mkdir(
            parents=True,
        )
        return snapshot

    captured = capture_hle_benchmark_identity(identity, fetcher=fetcher, datasets_cache=cache)

    data_tag = _sha256_pin(payload).removeprefix("sha256:")[:16]
    assert captured == f"hle@{revision[:16]}+data-{data_tag}"


def test_hle_fetcher_rejects_hostile_exact_revision_ambient_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An exact-revision ambient cache with altered bytes must fail before launch.

    SUBSTITUTE_JUSTIFICATION
    - substitute: monkeypatched ``huggingface_hub.snapshot_download`` and
      ``datasets.load_dataset`` that fail the pre-warm after a local snapshot
    - replaces: a real datasets materialization of the pinned cais/hle revision
    - necessity: the removed ambient-copy fallback fired only when pre-warm
      failed; that failure must be forced without corrupting the operator cache
    - real-option: a live load_dataset of cais/hle cannot safely be made to fail
      after the official snapshot is present
    - proof-limit: proves fail-closed pre-warm and no ambient copy, not Hub bytes
    - real-proof: post-fix live HLE smoke on the operator host
    """
    from bencheval.hle_adapter import _fetch_hle_snapshot_and_prewarm

    assert not hasattr(hle_adapter, "_copy_ambient_hle_datasets_cache")

    planted = (
        tmp_path / "ambient" / "cais___hle" / "default" / "0.0.0" / _HLE_REVISION / "hle-test.arrow"
    )
    planted.parent.mkdir(parents=True)
    planted.write_bytes(b"not-official-hle-data")
    monkeypatch.setenv("HF_DATASETS_CACHE", str(tmp_path / "ambient"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf-home"))

    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda **kwargs: str(snapshot))

    def fail_load(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("prewarm failed")

    monkeypatch.setattr(datasets, "load_dataset", fail_load)

    run_owned = tmp_path / "run-owned-cache"
    with pytest.raises(BenchEvalError, match="pre-warm"):
        _fetch_hle_snapshot_and_prewarm(
            repo=_HLE_REPO,
            revision=_HLE_REVISION,
            datasets_cache=run_owned,
        )
    leaked = list(run_owned.rglob("*")) if run_owned.exists() else []
    assert not any(
        path.read_bytes() == b"not-official-hle-data" for path in leaked if path.is_file()
    )


def test_capture_hle_identity_rejects_preexisting_materialized_cache(tmp_path: Path) -> None:
    """An ambient cache with plausible directory names is never trusted."""
    from bencheval.hle_adapter import _prepare_fresh_hle_datasets_cache

    cache = tmp_path / "datasets"
    corrupt = cache / "cais___hle" / "default" / "0.0.0" / _HLE_REVISION / "hle-test.arrow"
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"corrupted materialized rows\n")

    with pytest.raises(BenchEvalError, match=r"(?i)(empty|pre-existing|fresh)"):
        _prepare_fresh_hle_datasets_cache(cache)


def test_capture_hle_identity_fails_closed_on_snapshot_drift(tmp_path: Path) -> None:
    """Drifted bytes fail the real verifier after a controlled network seam.

    SUBSTITUTE_JUSTIFICATION
    - substitute: ``fetcher`` callable materializing the returned snapshot dir
    - replaces: gated Hugging Face snapshot download and datasets pre-warm
    - necessity: deterministically supplying a wrong pinned file without a
      charged external fetch is required to exercise the digest failure
    - real-option: a real pinned snapshot cannot safely be made to return
      corrupt bytes, and changing the remote revision would test another input
    - proof-limit: proves local digest rejection, not Hub transport integrity
    - real-proof: the retained dev-box HLE lane verified the real official pin
    """
    from bencheval.benchmark_registry import HfDatasetSnapshotIdentity
    from bencheval.hle_adapter import capture_hle_benchmark_identity

    revision = "1" * 40
    identity = HfDatasetSnapshotIdentity(
        kind="hf-dataset-snapshot",
        repo=_HLE_REPO,
        revision=revision,
        files={_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA},
    )
    snapshot = tmp_path / "snapshot"

    def fetcher(*, repo: str, revision: str, datasets_cache: Path) -> Path:
        del repo, revision, datasets_cache
        target = snapshot / _HLE_PARQUET_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"drifted\n")
        return snapshot

    with pytest.raises(BenchEvalError, match="sha256"):
        capture_hle_benchmark_identity(identity, fetcher=fetcher, datasets_cache=tmp_path / "d")


def test_default_fetcher_addresses_the_dataset_repo_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The default network seam must address the HF dataset endpoint.

    ``huggingface_hub.snapshot_download`` defaults ``repo_type`` to ``model``,
    and the model endpoint 404s dataset repos — verified against the live hub
    on 2026-08-24 (``model_info("cais/hle")`` → RepositoryNotFoundError while
    ``dataset_info`` resolves the pinned revision). The pinned dataset must
    therefore be requested explicitly as a dataset.

    SUBSTITUTE_JUSTIFICATION
    - substitute: monkeypatched ``huggingface_hub.snapshot_download`` and
      ``datasets.load_dataset`` recording their call arguments
    - replaces: the real HF hub download and datasets pre-warm
    - necessity: the assertion is the exact request shape the production
      fetcher emits; a real call is an external fetch of an access-gated
      dataset and cannot run inside a deterministic unit test
    - real-option: live snapshot_download of cais/hle — exercised by the
      dev-box live lane pre-warm instead
    - proof-limit: proves only the request shape, not the remote bytes
    - real-proof: dev-box live lane downloads and digest-verifies the real
      pinned snapshot before launch
    """

    from bencheval.hle_adapter import _fetch_hle_snapshot_and_prewarm

    calls: dict[str, object] = {}

    def fake_snapshot_download(**kwargs: object) -> str:
        calls["snapshot_download"] = kwargs
        return str(tmp_path)

    def fake_load_dataset(*args: object, **kwargs: object) -> None:
        calls["load_dataset"] = (args, kwargs)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    monkeypatch.setattr(datasets, "load_dataset", fake_load_dataset)

    datasets_cache = tmp_path / "datasets-cache"
    snapshot = _fetch_hle_snapshot_and_prewarm(
        repo=_HLE_REPO,
        revision=_HLE_REVISION,
        datasets_cache=datasets_cache,
    )

    assert snapshot == tmp_path
    download_kwargs = calls["snapshot_download"]
    assert isinstance(download_kwargs, dict)
    assert download_kwargs["repo_id"] == _HLE_REPO
    assert download_kwargs["revision"] == _HLE_REVISION
    assert download_kwargs["repo_type"] == "dataset"
    assert download_kwargs["local_files_only"] is True
    load_args, load_kwargs = calls["load_dataset"]
    assert load_args == (_HLE_REPO,)
    assert load_kwargs["revision"] == _HLE_REVISION
    assert load_kwargs["cache_dir"] == str(datasets_cache)


def test_hle_prewarm_builds_from_local_hub_snapshot_without_datasets_offline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A cached hub snapshot must become Arrow without a gated Hub round-trip.

    SUBSTITUTE_JUSTIFICATION
    - substitute: monkeypatched ``huggingface_hub.snapshot_download`` and
      ``datasets.load_dataset`` that record the first pre-warm environment
    - replaces: converting a local cais/hle hub snapshot into a run-owned
      datasets cache
    - necessity: the assertion is the exact offline/build flags; a real
      load_dataset of the gated dataset cannot run in this unit test
    - real-option: operator-host pre-warm against the already cached snapshot
    - proof-limit: proves env flags only, not official parquet bytes
    - real-proof: post-fix live HLE smoke on the operator host
    """
    from bencheval.hle_adapter import _fetch_hle_snapshot_and_prewarm

    seen: dict[str, str | None] = {}

    def fake_load_dataset(*args: object, **kwargs: object) -> None:
        del args, kwargs
        seen["HF_HUB_OFFLINE"] = os.environ.get("HF_HUB_OFFLINE")
        seen["HF_DATASETS_OFFLINE"] = os.environ.get("HF_DATASETS_OFFLINE")

    monkeypatch.setattr(huggingface_hub, "snapshot_download", lambda **kwargs: str(tmp_path))
    monkeypatch.setattr(datasets, "load_dataset", fake_load_dataset)

    _fetch_hle_snapshot_and_prewarm(
        repo=_HLE_REPO,
        revision=_HLE_REVISION,
        datasets_cache=tmp_path / "datasets-cache",
    )

    assert seen["HF_HUB_OFFLINE"] == "1"
    assert seen["HF_DATASETS_OFFLINE"] is None


def test_default_fetcher_retries_online_when_local_snapshot_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A gated hub login is only required when the pinned snapshot is absent.

    SUBSTITUTE_JUSTIFICATION
    - substitute: monkeypatched ``huggingface_hub.snapshot_download`` that
      rejects the local-only request, then succeeds online
    - replaces: a missing local HF hub snapshot plus a real gated download
    - necessity: the retry order must be forced without a live hub login
    - real-option: delete the cached snapshot and download cais/hle live
    - proof-limit: proves request order only, not remote bytes
    - real-proof: dev-box live lane uses the cached snapshot or a real token
    """

    from bencheval.hle_adapter import _fetch_hle_snapshot_and_prewarm

    calls: list[dict[str, object]] = []

    def fake_snapshot_download(**kwargs: object) -> str:
        calls.append(kwargs)
        if kwargs.get("local_files_only") is True:
            raise OSError("not in local cache")
        return str(tmp_path)

    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    monkeypatch.setattr(datasets, "load_dataset", lambda *args, **kwargs: None)

    snapshot = _fetch_hle_snapshot_and_prewarm(
        repo=_HLE_REPO,
        revision=_HLE_REVISION,
        datasets_cache=tmp_path / "datasets-cache",
    )

    assert snapshot == tmp_path
    assert calls[0]["local_files_only"] is True
    assert "local_files_only" not in calls[1]
    assert calls[1]["repo_type"] == "dataset"


def test_default_hle_runner_uses_run_owned_datasets_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The production runner never sees the ambient materialized cache.

    SUBSTITUTE_JUSTIFICATION
    - substitute: patched identity gate and default HLE subprocess runner
    - replaces: gated Hugging Face download plus charged candidate/judge calls
    - necessity: the assertion targets environment wiring on the real
      default-runner branch; live provider calls are charged and cannot be
      deterministic, while the isolated cache path must be observed in-process
    - real-option: official dev-box HLE run with provider credentials
    - proof-limit: proves cache-path ownership and propagation, not dataset
      materialization correctness or live scoring
    - real-proof: dev-box-cpu run hle-isolated-cache-live-20260825T072129Z;
      real candidate and official judge calls used the fresh run-owned cache,
      qualified as one eligible native attempt, and cleanup removed the cache
    """
    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    monkeypatch.setenv("BYTELLM_API_KEY", "test-credential-placeholder")
    monkeypatch.delenv("BENCHEVAL_HLE_DATASET", raising=False)
    plan = _hle_plan()
    artifacts_dir = tmp_path / "artifacts"
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id="hle-cache",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    identity = HfDatasetSnapshotIdentity(
        kind="hf-dataset-snapshot",
        repo=_HLE_REPO,
        revision=_HLE_REVISION,
        files={_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA},
    )
    observed_cache: list[Path] = []
    observed_envs: list[dict[str, str]] = []

    def capture_for_default_runner(
        *,
        plan,
        process_runner,
        benchmark_identity,
        datasets_cache: Path,
    ):
        del plan, benchmark_identity
        assert process_runner is None
        observed_cache.append(datasets_cache)
        pinned = datasets_cache / "cais___hle" / "default" / "0.0.0" / _HLE_REVISION
        pinned.mkdir(parents=True)
        (pinned / "hle-test.arrow").write_bytes(b"materialized rows\n")
        return _HLE_IDENTITY, identity

    def default_runner(command, *, cwd, timeout_sec, env=None) -> HleCliResult:
        del cwd, timeout_sec
        observed_envs.append(dict(env or {}))
        if len(observed_envs) == 1:
            paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
        else:
            judged = {
                f"row-{index}": {"judge_response": {"correct": "yes"}}
                for index in range(len(plan.instances))
            }
            paths.judged_path.write_text(json.dumps(judged), encoding="utf-8")
        return HleCliResult(0, "", "", 0.1, tuple(command))

    monkeypatch.setattr(
        hle_adapter,
        "_hle_prelaunch_benchmark_identity",
        capture_for_default_runner,
    )
    monkeypatch.setattr(hle_adapter, "_default_process_runner", default_runner)

    outcomes = run_hle_slice(
        plan=plan,
        artifacts_dir=artifacts_dir,
        repo_root=tmp_path,
        run_id="hle-cache",
    )

    expected_cache = artifacts_dir.resolve() / "hle-datasets-cache"
    assert observed_cache == [expected_cache]
    assert observed_envs
    assert all(env["HF_DATASETS_CACHE"] == str(expected_cache) for env in observed_envs)
    assert all(env["HF_DATASETS_OFFLINE"] == "1" for env in observed_envs)
    assert outcomes


def test_default_hle_runner_rejects_materialized_cache_file_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-root Arrow replacement invalidates the run after subprocess use.

    SUBSTITUTE_JUSTIFICATION
    - substitute: patched identity gate and default HLE subprocess runner
    - replaces: gated Hugging Face pre-warm plus charged candidate/judge calls
    - necessity: the assertion requires a deterministic mutation between
      pre-launch capture and post-command verification; a real charged run
      cannot safely or reliably expose that race
    - real-option: official dev-box HLE run, which proves the normal lifecycle
      but not a deliberately concurrent cache mutation
    - proof-limit: proves local mutation detection, not the remote dataset or
      model/judge behavior
    - real-proof: dev-box-cpu run hle-isolated-cache-live-20260825T072129Z;
      real candidate and official judge calls used the fresh run-owned cache,
      qualified as one eligible native attempt, and cleanup removed the cache
    """
    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    monkeypatch.setenv("BYTELLM_API_KEY", "test-credential-placeholder")
    monkeypatch.delenv("BENCHEVAL_HLE_DATASET", raising=False)
    plan = _hle_plan()
    artifacts_dir = tmp_path / "artifacts"
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id="hle-cache-mutation",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    identity = HfDatasetSnapshotIdentity(
        kind="hf-dataset-snapshot",
        repo=_HLE_REPO,
        revision=_HLE_REVISION,
        files={_HLE_PARQUET_RELPATH: _HLE_PARQUET_SHA},
    )
    materialized = (
        artifacts_dir.resolve()
        / "hle-datasets-cache"
        / "cais___hle"
        / "default"
        / "0.0.0"
        / _HLE_REVISION
        / "hle-test.arrow"
    )

    def capture_for_default_runner(
        *,
        plan,
        process_runner,
        benchmark_identity,
        datasets_cache: Path,
    ):
        del plan, benchmark_identity
        assert process_runner is None
        assert datasets_cache == artifacts_dir.resolve() / "hle-datasets-cache"
        materialized.parent.mkdir(parents=True)
        materialized.write_bytes(b"official materialized rows\n")
        return _HLE_IDENTITY, identity

    calls = 0

    def mutating_runner(command, *, cwd, timeout_sec, env=None) -> HleCliResult:
        nonlocal calls
        del cwd, timeout_sec, env
        calls += 1
        paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
        materialized.write_bytes(b"forged materialized rows\n")
        return HleCliResult(0, "", "", 0.1, tuple(command))

    monkeypatch.setattr(
        hle_adapter,
        "_hle_prelaunch_benchmark_identity",
        capture_for_default_runner,
    )
    monkeypatch.setattr(hle_adapter, "_default_process_runner", mutating_runner)

    with pytest.raises(AdapterFailureError) as excinfo:
        run_hle_slice(
            plan=plan,
            artifacts_dir=artifacts_dir,
            repo_root=tmp_path,
            run_id="hle-cache-mutation",
        )

    assert excinfo.value.failure_label == "evidence_corrupt"
    assert "datasets cache" in str(excinfo.value).lower()
    assert calls == 1


# ---------------------------------------------------------------------------
# C3. Run-level fail-closed gating and identity stamping
# ---------------------------------------------------------------------------


def test_run_gpqa_slice_stamps_captured_identity(tmp_path: Path) -> None:
    """Supplied identity at the injected-runner boundary is validated then stamped.

    SUBSTITUTE_JUSTIFICATION
    - substitute: injected ``process_runner`` writing a run-local inspect log and
      caller-supplied ``benchmark_identity``
    - replaces: the ``inspect eval`` subprocess and the real CSV/dist capture
    - necessity: a real launch is a charged external effect; the assertion is
      that a validated identity is stamped onto the outcome, and (in the
      mismatch case) that the runner is never invoked
    - real-option: live inspect eval against the provider API
    - proof-limit: wiring only; real byte verification is covered by the pure
      capture/verifier tests above
    - real-proof: dev-box live lane
    """
    plan = _gpqa_plan()

    def fake(command, *, cwd, timeout_sec, env=None) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_path = _write_gpqa_done_log(tuple(command), log_dir)
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.05, tuple(command))

    outcomes = run_gpqa_slice(
        plan=plan,
        artifacts_dir=tmp_path / "art",
        repo_root=tmp_path,
        process_runner=fake,
        benchmark_identity=_GPQA_IDENTITY,
    )

    assert outcomes
    assert outcomes[0].adapter_metadata["benchmark_version"] == _GPQA_IDENTITY


def test_run_gpqa_slice_refuses_mismatched_supplied_identity(tmp_path: Path) -> None:
    plan = _gpqa_plan()
    calls: list[tuple[str, ...]] = []

    def runner(command, *, cwd, timeout_sec, env=None) -> GpqaCliResult:
        calls.append(tuple(command))
        return GpqaCliResult(0, "", "", 0.0, tuple(command))

    with pytest.raises(AdapterFailureError) as excinfo:
        run_gpqa_slice(
            plan=plan,
            artifacts_dir=tmp_path / "art",
            repo_root=tmp_path,
            process_runner=runner,
            benchmark_identity="gpqa-diamond@inspect-evals-0.8.0+eval-2-B+csv-0000000000000000",
        )

    assert excinfo.value.failure_label == "runtime_config_drift"
    assert calls == []


def test_run_hle_slice_launches_pinned_dataset_and_stamps_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pinned official dataset decides ``--dataset``; the identity is stamped."""
    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    monkeypatch.delenv("BENCHEVAL_HLE_DATASET", raising=False)
    plan = _hle_plan()
    artifacts_dir = tmp_path / "artifacts"
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id="hle-id",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    argv_datasets: list[str] = []

    def fake(command, *, cwd, timeout_sec, env=None) -> HleCliResult:
        argv_datasets.append(command[command.index("--dataset") + 1])
        if len(argv_datasets) == 1:
            paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
        else:
            judged = {
                f"row-{index}": {"judge_response": {"correct": "yes"}}
                for index in range(len(plan.instances))
            }
            paths.judged_path.write_text(json.dumps(judged), encoding="utf-8")
        return HleCliResult(0, "", "", 0.1, tuple(command))

    outcomes = run_hle_slice(
        plan=plan,
        artifacts_dir=artifacts_dir,
        repo_root=tmp_path,
        process_runner=fake,
        run_id="hle-id",
        benchmark_identity=_HLE_IDENTITY,
    )

    # Anti-mirror discrimination: the launched dataset is exactly the official
    # pinned repo, never the reverted third-party mirror.
    assert argv_datasets == ["cais/hle", "cais/hle"]
    assert outcomes
    assert outcomes[0].adapter_metadata["hle_dataset"] == "cais/hle"
    assert outcomes[0].adapter_metadata["benchmark_version"] == _HLE_IDENTITY


def test_run_hle_slice_accepts_env_restating_pinned_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``BENCHEVAL_HLE_DATASET=cais/hle`` restates the pin exactly: accepted."""
    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    monkeypatch.setenv("BENCHEVAL_HLE_DATASET", "cais/hle")
    plan = _hle_plan()
    artifacts_dir = tmp_path / "artifacts"
    paths = hle_run_paths(
        artifacts_dir=artifacts_dir,
        run_id="hle-restated",
        provider_id=plan.provider_id,
        model_id=plan.model_id,
    )
    argv_datasets: list[str] = []

    def fake(command, *, cwd, timeout_sec, env=None) -> HleCliResult:
        argv_datasets.append(command[command.index("--dataset") + 1])
        if len(argv_datasets) == 1:
            paths.default_predictions_path.write_text("{}\n", encoding="utf-8")
        else:
            judged = {
                f"row-{index}": {"judge_response": {"correct": "yes"}}
                for index in range(len(plan.instances))
            }
            paths.judged_path.write_text(json.dumps(judged), encoding="utf-8")
        return HleCliResult(0, "", "", 0.1, tuple(command))

    outcomes = run_hle_slice(
        plan=plan,
        artifacts_dir=artifacts_dir,
        repo_root=tmp_path,
        process_runner=fake,
        run_id="hle-restated",
        benchmark_identity=_HLE_IDENTITY,
    )

    assert argv_datasets == ["cais/hle", "cais/hle"]
    assert outcomes


def test_run_hle_slice_refuses_mirror_dataset_env_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reverted third-party mirror is source drift against the official pin."""
    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    monkeypatch.setenv("BENCHEVAL_HLE_DATASET", "macabdul9/hle_text_only")
    calls: list[tuple[str, ...]] = []

    def runner(command, *, cwd, timeout_sec, env=None) -> HleCliResult:
        calls.append(tuple(command))
        return HleCliResult(0, "", "", 0.0, tuple(command))

    with pytest.raises(AdapterFailureError) as excinfo:
        run_hle_slice(
            plan=_hle_plan(),
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=runner,
            run_id="hle-drift",
        )

    assert excinfo.value.failure_label == "runtime_config_drift"
    assert calls == []


def test_run_hle_slice_refuses_mismatched_supplied_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _plain_hle_home(tmp_path)
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    monkeypatch.delenv("BENCHEVAL_HLE_DATASET", raising=False)
    calls: list[tuple[str, ...]] = []

    def runner(command, *, cwd, timeout_sec, env=None) -> HleCliResult:
        calls.append(tuple(command))
        return HleCliResult(0, "", "", 0.0, tuple(command))

    with pytest.raises(AdapterFailureError) as excinfo:
        run_hle_slice(
            plan=_hle_plan(),
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=runner,
            run_id="hle-drift",
            benchmark_identity="hle@0000000000000000+data-0000000000000000",
        )

    assert excinfo.value.failure_label == "runtime_config_drift"
    assert calls == []


# ---------------------------------------------------------------------------
# C4. Executor benchmark_version stamping preference
# ---------------------------------------------------------------------------


def test_evidence_benchmark_version_prefers_adapter_captured_identity() -> None:
    plan = _gpqa_plan()
    assert (
        _evidence_benchmark_version(plan, {"benchmark_version": _GPQA_IDENTITY}) == _GPQA_IDENTITY
    )
    assert _evidence_benchmark_version(plan, {}) == plan.benchmark_version
    assert _evidence_benchmark_version(plan, None) == plan.benchmark_version
    assert plan.benchmark_version == "provisional:gpqa-diamond/inspect-evals"


def test_execute_gpqa_stamps_captured_identity_on_evidence(tmp_path: Path) -> None:
    plan = _gpqa_plan()
    evidence = tmp_path / "evidence.jsonl"

    def fake(command, *, cwd, timeout_sec, env=None) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_path = _write_gpqa_done_log(tuple(command), log_dir)
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.05, tuple(command))

    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        gpqa_process_runner=fake,
        gpqa_benchmark_identity=_GPQA_IDENTITY,
        run_id="gpqa-identity",
    )

    assert summary.passed_count == 1
    rows = read_evidence_jsonl(evidence)
    assert len(rows) == 1
    assert rows[0].benchmark_version == _GPQA_IDENTITY


def test_execute_gpqa_falls_back_to_provisional_label_without_capture(tmp_path: Path) -> None:
    plan = _gpqa_plan()
    evidence = tmp_path / "evidence.jsonl"

    def fake(command, *, cwd, timeout_sec, env=None) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_path = _write_gpqa_done_log(tuple(command), log_dir)
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.05, tuple(command))

    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        gpqa_process_runner=fake,
        run_id="gpqa-provisional",
    )

    rows = read_evidence_jsonl(evidence)
    assert rows[0].benchmark_version == "provisional:gpqa-diamond/inspect-evals"
    assert is_provisional_benchmark_version(rows[0].benchmark_version)


# ---------------------------------------------------------------------------
# D. Diagnostic route and passed-registration executable gate
# ---------------------------------------------------------------------------


@pytest.fixture
def _demoted_gpqa_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A real config copy with gpqa-diamond demoted to executable: false."""
    home = tmp_path / "home"
    shutil.copytree(_REPO_ROOT / "config", home / "config")
    catalog_path = home / "config" / "benchmarks.yaml"
    text = catalog_path.read_text(encoding="utf-8")
    needle = "adapter_id: gpqa\n    executable: true"
    assert needle in text
    catalog_path.write_text(
        text.replace(needle, "adapter_id: gpqa\n    executable: false"),
        encoding="utf-8",
    )
    monkeypatch.setenv("BENCHEVAL_HOME", str(home))
    clear_config_loader_caches()
    yield home
    clear_config_loader_caches()


def test_run_plan_carries_diagnostic_flag_default_false() -> None:
    assert _gpqa_plan().diagnostic is False
    assert _gpqa_plan(diagnostic=True).diagnostic is True
    assert "diagnostic" in get_args(InterpretationLabel)


def test_diagnostic_plan_maps_to_diagnostic_interpretation_label() -> None:
    assert control_plane_interpretation_label(_gpqa_plan()) == "adapter_smoke"
    assert control_plane_interpretation_label(_gpqa_plan(diagnostic=True)) == "diagnostic"


@pytest.mark.usefixtures("_demoted_gpqa_home")
def test_run_diagnostic_allows_demoted_wired_benchmark(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "run",
            "gpqa-diamond/smoke",
            "--model",
            "kimi-k2.7-code",
            "--provider",
            "bytellm",
            "--diagnostic",
            "--dry-run",
        ],
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["benchmark_id"] == "gpqa-diamond"
    assert payload["diagnostic"] is True


@pytest.mark.usefixtures("_demoted_gpqa_home")
def test_run_without_diagnostic_still_rejects_demoted_benchmark(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "run",
            "gpqa-diamond/smoke",
            "--model",
            "kimi-k2.7-code",
            "--provider",
            "bytellm",
            "--dry-run",
        ],
    )
    assert code == 1
    assert "executable" in capsys.readouterr().err


def test_run_diagnostic_admits_demoted_wired_swe_without_promoting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # SWE is catalog-demoted but now has diagnostic-capable dispatch. Dry-run
    # may plan; it still cannot register passed (see passed-registration tests).
    code = main(
        [
            "run",
            "swe-bench-verified/swe-bench-verified-smoke-10",
            "--runtime",
            "codex-cli",
            "--model",
            "kimi-k2.7-code",
            "--provider",
            "bytellm",
            "--diagnostic",
            "--dry-run",
        ],
    )
    assert code == 0
    assert "executable" not in capsys.readouterr().err


@pytest.mark.usefixtures("_demoted_gpqa_home")
def test_executor_gates_demoted_benchmark_without_diagnostic() -> None:
    plan = _gpqa_plan()
    with pytest.raises(BenchEvalError, match="executable"):
        _require_executable_benchmark(plan)


@pytest.mark.usefixtures("_demoted_gpqa_home")
def test_executor_admits_demoted_wired_benchmark_with_diagnostic() -> None:
    plan = _gpqa_plan(diagnostic=True)
    _require_executable_benchmark(plan)


def test_executor_rejects_diagnostic_for_unwired_adapter() -> None:
    plan = _gpqa_plan(diagnostic=True).model_copy(
        update={"adapter_id": "cybergym", "benchmark_id": "cybergym"},
    )
    with pytest.raises(BenchEvalError, match="executable"):
        _require_executable_benchmark(plan)


def test_passed_registration_rejects_demoted_benchmark_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, make_control_plane_evidence_record(instance_id="x"))

    err = _qualify_passed_registration(
        evidence=evidence,
        benchmark="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        run_id="run-x",
        model_id="kimi-k2.7-code",
        runtime_id=None,
        allow_missing=False,
    )

    assert err is not None
    assert "executable" in err


def test_passed_registration_keeps_qualify_path_for_executable_benchmark(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, make_control_plane_evidence_record(instance_id="x"))

    err = _qualify_passed_registration(
        evidence=evidence,
        benchmark="terminal-bench",
        slice_id="smoke-5",
        run_id="run-x",
        model_id="kimi-k2.7-code",
        runtime_id="claude-code",
        allow_missing=False,
    )

    assert err is not None
    assert "executable" not in err
    assert "qualified" in err


@pytest.mark.parametrize(
    ("target", "extra"),
    [
        ("terminal-bench/smoke-5", ["--runtime", "claude-code"]),
        ("gpqa-diamond/smoke", []),
        ("hle/smoke", []),
    ],
)
def test_run_diagnostic_rejects_executable_benchmark(
    target: str,
    extra: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    # --diagnostic exists solely for demoted benchmarks. On an executable one it
    # would mint diagnostic-labeled evidence that could register passed.
    code = main(
        [
            "run",
            target,
            *extra,
            "--model",
            "kimi-k2.7-code",
            "--provider",
            "bytellm",
            "--diagnostic",
            "--dry-run",
        ],
    )
    assert code == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--diagnostic" in captured.err
    assert "executable" in captured.err


def test_passed_registration_rejects_diagnostic_rows_on_executable_benchmark(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(
        evidence,
        make_control_plane_evidence_record(instance_id="x").model_copy(
            update={"interpretation_label": "diagnostic"},
        ),
    )

    err = _qualify_passed_registration(
        evidence=evidence,
        benchmark="terminal-bench",
        slice_id="smoke-5",
        run_id="run-x",
        model_id="kimi-k2.7-code",
        runtime_id="claude-code",
        allow_missing=False,
    )

    assert err is not None
    assert "diagnostic" in err
