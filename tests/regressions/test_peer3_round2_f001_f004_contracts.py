"""Peer#3 round-2 F001–F004 regressions.

SUBSTITUTE_JUSTIFICATION
- substitute: real FIFOs/symlinks/hardlinks, injected SWE runners, a
  ``snapshot_download`` boundary returning an on-disk custom-cache snapshot,
  and planted evidence rows
- replaces: a same-UID harness helper that leaves a FIFO or swapped dataset
  after the bounded subprocess exits, a charged Claude SWE launch, and a live
  Hugging Face download into a non-default cache
- necessity: FIFO hang, directory symlink swap, unknown-producer qualification,
  evaluator working-directory selection, and custom-cache return-path handling
  must be forced without charging a provider or mutating the operator cache
- real-option: a live helper cannot safely or deterministically plant those
  filesystem states after wall-limited harness exit; the real configured-cache
  contract is independently defined by ``huggingface_hub.constants``
- proof-limit: local reader/planner/qualification/cache/launch contracts only;
  not live score truth, network download behavior, or catalog admission
- real-proof: prior imported HLE/SWE proofs remain historical; new passed
  registration requires a canonical ``sha256:[0-9a-f]{64}`` producer digest
- covered tests: every test in this module
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.cli import _qualify_passed_registration, main
from bencheval.control_plane_executor import _producer_identity
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.exceptions import AdapterFailureError, BenchEvalError
from bencheval.live_proof import producer_content_ok, qualify_lane
from bencheval.swebench_adapter import (
    SwebenchCliResult,
    _ensure_source_parquet,
    build_swebench_eval_command,
    run_swebench_instance,
)

_INSTANCE_ID = "django__django-11099"
_TS = datetime(2026, 8, 27, tzinfo=UTC)


def _fifo_script(tmp_path: Path, body: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", body, str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=1.0,
    )


def test_harbor_retained_copy_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "harbor-official-result.json")
    result = _fifo_script(
        tmp_path,
        """
import os, sys
from pathlib import Path
from bencheval.exceptions import BenchEvalError
from bencheval.run_isolation import open_owned_dir_fd
from bencheval.terminal_bench_harbor import _read_direct_child_bytes

root = Path(sys.argv[1])
fd = open_owned_dir_fd(root, role="harbor fifo")
try:
    try:
        _read_direct_child_bytes(fd, "harbor-official-result.json")
    except (OSError, BenchEvalError):
        raise SystemExit(0)
    raise SystemExit("FIFO was accepted")
finally:
    os.close(fd)
""",
    )
    assert result.returncode == 0, result.stderr


def test_swe_nested_report_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    nested = tmp_path / "logs" / "run_evaluation" / "rid" / "kimi-k2.7-code" / _INSTANCE_ID
    nested.mkdir(parents=True)
    os.mkfifo(nested / "report.json")
    result = _fifo_script(
        tmp_path,
        f"""
import os, sys
from pathlib import Path
from bencheval.exceptions import AdapterFailureError
from bencheval.run_isolation import open_owned_dir_fd
from bencheval.swebench_adapter import _read_nested_eval_report_bytes

root = Path(sys.argv[1])
fd = open_owned_dir_fd(root, role="swe fifo")
try:
    try:
        data = _read_nested_eval_report_bytes(fd, instance_id="{_INSTANCE_ID}", run_id="rid")
    except AdapterFailureError:
        raise SystemExit(0)
    if data is None:
        raise SystemExit(0)
    raise SystemExit("FIFO report was scored")
finally:
    os.close(fd)
""",
    )
    assert result.returncode == 0, result.stderr


def test_hle_judged_artifact_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "judged.json")
    result = _fifo_script(
        tmp_path,
        """
import os, sys
from pathlib import Path
from bencheval.hle_adapter import parse_hle_official_score
from bencheval.run_isolation import open_owned_dir_fd

root = Path(sys.argv[1])
judged = root / "judged.json"
fd = open_owned_dir_fd(root, role="hle fifo")
try:
    score = parse_hle_official_score(
        eval_dir=root,
        model_id="kimi-k2.7-code",
        judge_stdout="",
        max_samples=1,
        work_dir=root,
        judged_path=judged,
        judged_dir_fd=fd,
    )
    if score is not None:
        raise SystemExit("FIFO judged artifact was scored")
finally:
    os.close(fd)
""",
    )
    assert result.returncode == 0, result.stderr


def test_bfcl_score_read_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "BFCL_v4_simple_score.json")
    result = _fifo_script(
        tmp_path,
        """
import os, sys
from pathlib import Path
from bencheval.bfcl_native_adapter import _ScoreCandidate, _read_score_candidate_bytes
from bencheval.exceptions import AdapterFailureError
from bencheval.run_isolation import open_owned_dir_fd

root = Path(sys.argv[1])
leaf = root / "BFCL_v4_simple_score.json"
fd = open_owned_dir_fd(root, role="bfcl fifo")
candidate = _ScoreCandidate(path=leaf, identity=(0, 0), descriptor=-1)
try:
    try:
        _read_score_candidate_bytes(score_root_fd=fd, score_dir=root, candidate=candidate)
    except AdapterFailureError:
        raise SystemExit(0)
    raise SystemExit("FIFO score was accepted")
finally:
    os.close(fd)
""",
    )
    assert result.returncode == 0, result.stderr


def test_external_agent_capture_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "stdout.log")
    result = _fifo_script(
        tmp_path,
        """
import os, sys
from pathlib import Path
from bencheval.exceptions import BenchEvalError
from bencheval.external_agent_adapter import _read_text_at
from bencheval.run_isolation import open_owned_dir_fd

root = Path(sys.argv[1])
fd = open_owned_dir_fd(root, role="agent fifo")
try:
    try:
        _read_text_at(fd, "stdout.log")
    except (OSError, BenchEvalError):
        raise SystemExit(0)
    raise SystemExit("FIFO capture was accepted")
finally:
    os.close(fd)
""",
    )
    assert result.returncode == 0, result.stderr


def test_producer_identity_is_content_bound_and_stable() -> None:
    first = _producer_identity()
    second = _producer_identity()
    assert first["producer_content_sha256"] == second["producer_content_sha256"]
    assert producer_content_ok(first["producer_content_sha256"])
    assert first["producer_package_version"] != "unknown"
    assert first.get("producer_git_commit") != "unknown"
    assert first.get("producer_dirty") != "unknown"


def test_producer_digest_includes_uv_style_hardlinked_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bencheval
    import bencheval.control_plane_executor as executor

    package = tmp_path / "site-packages" / "bencheval"
    config = tmp_path / "checkout" / "config"
    cache = tmp_path / "uv-cache"
    package.mkdir(parents=True)
    config.mkdir(parents=True)
    cache.mkdir()

    cached_init = cache / "__init__.py"
    cached_module = cache / "worker.py"
    cached_config = cache / "benchmarks.yaml"
    cached_init.write_text('VERSION = "1"\n', encoding="utf-8")
    cached_module.write_text('VALUE = "before"\n', encoding="utf-8")
    cached_config.write_text("benchmarks: []\n", encoding="utf-8")
    os.link(cached_init, package / "__init__.py")
    os.link(cached_module, package / "worker.py")
    os.link(cached_config, config / "benchmarks.yaml")

    monkeypatch.setattr(bencheval, "__file__", str(package / "__init__.py"))
    monkeypatch.setattr(executor, "_repo_root", lambda: tmp_path / "checkout")

    before = executor._producer_content_digest()
    cached_module.write_text('VALUE = "after"\n', encoding="utf-8")
    after = executor._producer_content_digest()

    assert before != after


def test_swe_download_uses_returned_snapshot_in_configured_hub_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import huggingface_hub
    from huggingface_hub import constants as hf_constants

    import bencheval.swebench_adapter as adapter

    configured_hub = tmp_path / "configured-hub"
    returned_snapshot = configured_hub / "returned-snapshot"
    blob = configured_hub / "blobs" / "official-parquet"
    payload = b"configured-cache-official-parquet"
    calls: list[dict[str, object]] = []

    def download(**kwargs: object) -> str:
        calls.append(kwargs)
        blob.parent.mkdir(parents=True)
        blob.write_bytes(payload)
        source = returned_snapshot / adapter._SWE_SOURCE_PARQUET
        source.parent.mkdir(parents=True)
        source.symlink_to(blob)
        return str(returned_snapshot)

    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.setenv("HF_HUB_CACHE", str(configured_hub))
    monkeypatch.setattr(hf_constants, "HF_HUB_CACHE", str(configured_hub))
    monkeypatch.setattr(huggingface_hub, "snapshot_download", download)
    monkeypatch.setattr(
        adapter,
        "_SWE_SOURCE_PARQUET_SHA256",
        f"sha256:{hashlib.sha256(payload).hexdigest()}",
    )

    resolved = _ensure_source_parquet(None)

    assert calls == [
        {
            "repo_id": adapter._SWE_VERIFIED_REPO,
            "repo_type": "dataset",
            "revision": adapter._SWE_VERIFIED_REVISION,
        },
    ]
    assert resolved == blob.resolve()


def _qualifying_row(*, producer: dict[str, str], artifact: Path) -> EvidenceRecord:
    return EvidenceRecord(
        run_id="lane-run",
        task_id="fix-git",
        model_id="kimi-k2.7-code",
        execution_profile="E2",
        backend="harbor",
        primary_pass=False,
        partial_score=0.0,
        cost_usd=0.1,
        latency_sec=1.0,
        created_at=_TS,
        benchmark_id="terminal-bench",
        benchmark_version="terminal-bench@2.1",
        slice_id="tier1-one",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@1",
        runtime_id="codex-cli",
        runtime_kind="cli_agent",
        runtime_version="0.148.0",
        runtime_config_hash="sha256:runtime",
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm",
        instance_id="fix-git",
        interpretation_label="runtime_comparison",
        attempt_validity="valid",
        counts_toward_pass_at_k=True,
        verifier_integrity_label="native",
        artifact_paths=(str(artifact),),
        adapter_metadata=producer,
    )


def test_qualify_lane_rejects_unknown_git_without_content_identity(tmp_path: Path) -> None:
    artifact = tmp_path / "result.json"
    artifact.write_text("{}", encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(
        evidence,
        _qualifying_row(producer={"producer_git_commit": "unknown"}, artifact=artifact),
    )
    qualification = qualify_lane(
        evidence,
        expected_instances=1,
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        require_runtime=True,
        repo_root=tmp_path,
    )
    assert qualification.ok is False
    assert any("unknown-producer" in reason for reason in qualification.reasons)


def test_passed_registration_requires_producer_content_identity(tmp_path: Path) -> None:
    artifact = tmp_path / "result.json"
    artifact.write_text("{}", encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(
        evidence,
        _qualifying_row(producer={}, artifact=artifact),
    )
    err = _qualify_passed_registration(
        evidence=evidence,
        benchmark="terminal-bench",
        slice_id="tier1-one",
        run_id="lane-run",
        model_id="kimi-k2.7-code",
        runtime_id="codex-cli",
        allow_missing=False,
    )
    assert err is not None
    assert "producer_content_sha256" in err


@pytest.mark.parametrize(
    "digest",
    [
        "sha256:" + ("z" * 64),
        "sha256:" + ("/" * 64),
        "sha256:" + ("A" * 64),
        "sha256:" + ("a" * 63),
        "sha256:" + ("a" * 65),
        "sha256:unknown",
        "sha256:unknown" + ("0" * 50),
    ],
)
def test_passed_registration_rejects_malformed_producer_digest(
    tmp_path: Path,
    digest: str,
) -> None:
    artifact = tmp_path / "result.json"
    artifact.write_text("{}", encoding="utf-8")
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(
        evidence,
        _qualifying_row(
            producer={"producer_content_sha256": digest},
            artifact=artifact,
        ),
    )
    manifest = tmp_path / "runs.jsonl"
    code = main(
        [
            "evidence",
            "register",
            "--run-id",
            "lane-run",
            "--model",
            "kimi-k2.7-code",
            "--status",
            "passed",
            "--host",
            "dev-box",
            "--manifest-path",
            str(manifest),
            "--runtime",
            "codex-cli",
            "--benchmark",
            "terminal-bench",
            "--slice",
            "tier1-one",
            "--evidence",
            str(evidence),
        ],
    )
    assert code != 0
    assert not manifest.exists()
    assert producer_content_ok(digest) is False


def test_passed_registration_accepts_canonical_producer_digest(tmp_path: Path) -> None:
    artifact = tmp_path / "result.json"
    artifact.write_text("{}", encoding="utf-8")
    digest = "sha256:" + ("a" * 64)
    evidence = tmp_path / "evidence.jsonl"
    JsonlEvidenceSink().append_jsonl(
        evidence,
        _qualifying_row(
            producer={"producer_content_sha256": digest},
            artifact=artifact,
        ),
    )
    manifest = tmp_path / "runs.jsonl"
    code = main(
        [
            "evidence",
            "register",
            "--run-id",
            "lane-run",
            "--model",
            "kimi-k2.7-code",
            "--status",
            "passed",
            "--host",
            "dev-box",
            "--manifest-path",
            str(manifest),
            "--runtime",
            "codex-cli",
            "--benchmark",
            "terminal-bench",
            "--slice",
            "tier1-one",
            "--evidence",
            str(evidence),
        ],
    )
    assert code == 0
    assert manifest.is_file()
    assert "status" in manifest.read_text(encoding="utf-8")
    assert producer_content_ok(digest)


def test_swe_eval_rejects_symlinked_eval_input(tmp_path: Path) -> None:
    report_dir = tmp_path / "run"
    report_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test.jsonl").write_text("{}\n", encoding="utf-8")
    eval_input = report_dir / "eval-input"
    eval_input.symlink_to(outside, target_is_directory=True)
    with pytest.raises(BenchEvalError, match="symlink"):
        build_swebench_eval_command(
            instance_id=_INSTANCE_ID,
            predictions_path=report_dir / "predictions.jsonl",
            run_id="swe-symlink",
            report_dir=report_dir,
            dataset_path=eval_input,
        )


def test_swe_eval_rejects_hardlinked_eval_leaf(tmp_path: Path) -> None:
    report_dir = tmp_path / "run"
    eval_input = report_dir / "eval-input"
    eval_input.mkdir(parents=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("{}\n", encoding="utf-8")
    os.link(outside, eval_input / "test.jsonl")
    with pytest.raises(BenchEvalError, match="single-link"):
        build_swebench_eval_command(
            instance_id=_INSTANCE_ID,
            predictions_path=report_dir / "predictions.jsonl",
            run_id="swe-hardlink",
            report_dir=report_dir,
            dataset_path=eval_input,
        )


def test_swe_generation_symlink_swap_is_rejected_before_eval(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "test.jsonl").write_text('{"swapped": true}\n', encoding="utf-8")
    commands: list[tuple[str, ...]] = []

    def runner(command, *, cwd, timeout_sec) -> SwebenchCliResult:
        del cwd, timeout_sec
        argv = tuple(str(part) for part in command)
        commands.append(argv)
        root = artifacts / _INSTANCE_ID
        root.mkdir(parents=True, exist_ok=True)
        (root / "predictions.jsonl").write_text(
            json.dumps(
                {
                    "instance_id": _INSTANCE_ID,
                    "model_name_or_path": "kimi-k2.7-code",
                    "model_patch": "diff --git a/a b/a\n",
                },
            )
            + "\n",
            encoding="utf-8",
        )
        official = root / "official-dataset"
        official.mkdir()
        (official / "test.jsonl").write_text("{}\n", encoding="utf-8")
        os.rename(official, tmp_path / "original-official")
        official.symlink_to(outside, target_is_directory=True)
        return SwebenchCliResult(0, "", "", 0.1, argv)

    with pytest.raises(AdapterFailureError, match=r"cannot be bound|eval input"):
        run_swebench_instance(
            plan=plan_control_plane(
                benchmark_id="swe-bench-verified",
                slice_id="swe-bench-verified-diagnostic-1",
                runtime_id="codex-cli",
                model_id="kimi-k2.7-code",
                diagnostic=True,
            ),
            instance_id=_INSTANCE_ID,
            artifacts_dir=artifacts,
            repo_root=tmp_path,
            process_runner=runner,
            timeout_sec=30,
            run_id="swe-swap",
        )
    assert len(commands) == 1
    assert commands[0][:2] == ("inspect", "eval")


def test_swe_official_evaluator_keeps_the_run_owned_working_directory(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "checkout"
    repo_root.mkdir()
    artifacts = tmp_path / "external-artifacts"
    working_directories: list[Path] = []

    def runner(command, *, cwd, timeout_sec) -> SwebenchCliResult:
        del timeout_sec
        argv = tuple(str(part) for part in command)
        working_directories.append(Path(cwd))
        root = artifacts / _INSTANCE_ID
        root.mkdir(parents=True, exist_ok=True)
        if len(working_directories) == 1:
            (root / "predictions.jsonl").write_text(
                json.dumps(
                    {
                        "instance_id": _INSTANCE_ID,
                        "model_name_or_path": "kimi-k2.7-code",
                        "model_patch": "diff --git a/a b/a\n",
                    },
                )
                + "\n",
                encoding="utf-8",
            )
            official = root / "official-dataset"
            official.mkdir()
            (official / "test.jsonl").write_text("{}\n", encoding="utf-8")
        return SwebenchCliResult(
            0 if len(working_directories) == 1 else 1,
            "",
            "",
            0.1,
            argv,
        )

    run_swebench_instance(
        plan=plan_control_plane(
            benchmark_id="swe-bench-verified",
            slice_id="swe-bench-verified-diagnostic-1",
            runtime_id="codex-cli",
            model_id="kimi-k2.7-code",
            diagnostic=True,
        ),
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=repo_root,
        process_runner=runner,
        timeout_sec=30,
        run_id="swe-project-root",
    )

    assert working_directories == [repo_root, artifacts / _INSTANCE_ID]


def test_swe_planning_rejects_claude_code() -> None:
    with pytest.raises(BenchEvalError, match="Codex-only"):
        plan_control_plane(
            benchmark_id="swe-bench-verified",
            slice_id="swe-bench-verified-diagnostic-1",
            runtime_id="claude-code",
            model_id="kimi-k2.7-code",
            diagnostic=True,
        )


def test_swe_claude_diagnostic_dry_run_is_rejected() -> None:
    code = main(
        [
            "run",
            "swe-bench-verified/swe-bench-verified-diagnostic-1",
            "--runtime",
            "claude-code",
            "--model",
            "kimi-k2.7-code",
            "--diagnostic",
            "--dry-run",
        ],
    )
    assert code != 0
