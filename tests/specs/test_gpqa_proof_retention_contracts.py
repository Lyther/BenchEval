"""RED contracts binding GPQA's scored bytes through private-proof retention.

SUBSTITUTE_JUSTIFICATION
- substitute: injected ``GpqaProcessRunner`` writing an Inspect-shaped done log
- replaces: the charged provider-backed ``inspect eval`` subprocess
- necessity: the retention invariant requires deterministic mutation after the
  official parser returns; a live charged run cannot safely or reliably expose
  that exact post-score state
- real-option: rerun the registered GPQA smoke on dev-box-cpu after this contract
  is implemented; that proves Inspect/provider integration but not the hostile
  post-score mutation deterministically
- proof-limit: proves only adapter-owned byte retention and filesystem behavior;
  it does not prove Inspect scoring truth, provider behavior, or Tier-2 readiness
- real-proof: imported GPQA private proofs
  ``sha256:90978d9e161419aba7ca9c48ceedabc1a009403a7e36deeee861b22a7c21c032``
  (post-retention refresh) and
  ``sha256:a8f17d90cd44dea3f6a032f7db406ec8061f878626c8b2a7615552fe4c6da2f8``
  (cleanup replay). This module still does not prove Inspect scoring truth.
- covered tests: every test in this module, including retain-held-bytes,
  source-symlink, and source-outside-log-dir negatives
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import AdapterFailureError
from bencheval.gpqa_adapter import (
    GpqaCliResult,
    GpqaOfficialScore,
    _retain_scored_gpqa_log,
    run_gpqa_slice,
)

_GPQA_IDENTITY = "gpqa-diamond@inspect-evals-0.8.0+eval-2-B+csv-41d1213cd7a49986"


def _plan():
    return plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )


def _official_log(model: str) -> bytes:
    payload = {
        "status": "success",
        "eval": {
            "task": "inspect_evals/gpqa_diamond",
            "model": model,
            "dataset": {
                "name": "gpqa_diamond",
                "samples": 198,
                "sample_ids": ["rec06pnAkLOr2t2mp", "rec0Arme2jcXQZnAW"],
            },
            "task_args": {"epochs": 4},
            "config": {"limit": 2, "epochs": 4},
        },
        "results": {
            "total_samples": 8,
            "completed_samples": 8,
            "scores": [
                {
                    "name": "choice",
                    "scorer": "choice",
                    "metrics": {"accuracy": {"name": "accuracy", "value": 0.5, "params": {}}},
                }
            ],
        },
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _run_with_log(artifacts: Path) -> tuple[object, Path, bytes]:
    source_path: Path | None = None
    source_bytes: bytes | None = None

    def runner(command, *, cwd, timeout_sec, env=None) -> GpqaCliResult:
        nonlocal source_path, source_bytes
        log_dir = Path(command[command.index("--log-dir") + 1])
        model = command[command.index("--model") + 1]
        source_bytes = _official_log(model)
        source_path = log_dir / "inspect-done.json"
        source_path.write_bytes(source_bytes)
        done = {
            "event": "done",
            "logs": [{"status": "success", "location": str(source_path)}],
        }
        return GpqaCliResult(0, json.dumps(done) + "\n", "", 0.1, tuple(command))

    outcome = run_gpqa_slice(
        plan=_plan(),
        artifacts_dir=artifacts,
        repo_root=artifacts.parent,
        process_runner=runner,
        benchmark_identity=_GPQA_IDENTITY,
    )[0]
    assert source_path is not None
    assert source_bytes is not None
    return outcome, source_path, source_bytes


def test_gpqa_retains_the_exact_scored_bytes_under_an_owned_direct_child(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    outcome, source_path, scored_bytes = _run_with_log(artifacts)

    retained = Path(outcome.verifier_log_path or "")
    assert retained.resolve() == (artifacts / "gpqa-official-log.json").resolve()
    assert retained.name == "gpqa-official-log.json"
    assert retained.is_file()
    assert not retained.is_symlink()
    assert retained.read_bytes() == scored_bytes
    expected_digest = "sha256:" + hashlib.sha256(scored_bytes).hexdigest()
    assert outcome.adapter_metadata["score_artifact_sha256"] == expected_digest
    assert outcome.native_score["score_artifact_sha256"] == expected_digest

    source_path.write_bytes(b'{"forged":true}\n')
    assert retained.read_bytes() == scored_bytes


def test_gpqa_retention_replaces_a_planted_symlink_without_touching_its_target(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text("KEEP\n", encoding="utf-8")
    (artifacts / "gpqa-official-log.json").symlink_to(victim)

    outcome, _, scored_bytes = _run_with_log(artifacts)

    retained = Path(outcome.verifier_log_path or "")
    assert victim.read_text(encoding="utf-8") == "KEEP\n"
    assert retained.resolve() == (artifacts / "gpqa-official-log.json").resolve()
    assert not (artifacts / "gpqa-official-log.json").is_symlink()
    assert retained.read_bytes() == scored_bytes


def test_gpqa_retain_writes_held_scored_bytes_not_a_later_pathname_read(
    tmp_path: Path,
) -> None:
    log_dir = tmp_path / "inspect-logs"
    artifacts = tmp_path / "artifacts"
    log_dir.mkdir()
    artifacts.mkdir()
    source = log_dir / "inspect-done.json"
    scored = b'{"scored":true,"status":"success"}\n'
    source.write_bytes(b'{"forged":true}\n')
    official = GpqaOfficialScore(
        0.5,
        4,
        8,
        str(source),
        unique_samples=2,
        epochs=4,
        scored_bytes=scored,
    )
    log_fd = os.open(log_dir, os.O_RDONLY)
    artifacts_fd = os.open(artifacts, os.O_RDONLY)
    try:
        retained_path, digest = _retain_scored_gpqa_log(
            official=official,
            log_dir=log_dir,
            log_fd=log_fd,
            artifacts_dir=artifacts,
            artifacts_fd=artifacts_fd,
            latency_sec=0.1,
            command=("inspect", "eval"),
        )
    finally:
        os.close(log_fd)
        os.close(artifacts_fd)
    assert Path(retained_path).read_bytes() == scored
    assert digest == "sha256:" + hashlib.sha256(scored).hexdigest()
    assert source.read_bytes() == b'{"forged":true}\n'


def test_gpqa_retain_rejects_a_source_symlink(tmp_path: Path) -> None:
    log_dir = tmp_path / "inspect-logs"
    artifacts = tmp_path / "artifacts"
    log_dir.mkdir()
    artifacts.mkdir()
    victim = tmp_path / "victim.json"
    victim.write_bytes(b'{"keep":true}\n')
    source = log_dir / "inspect-done.json"
    source.symlink_to(victim)
    official = GpqaOfficialScore(
        0.5,
        4,
        8,
        str(source),
        scored_bytes=b'{"scored":true}\n',
    )
    log_fd = os.open(log_dir, os.O_RDONLY)
    artifacts_fd = os.open(artifacts, os.O_RDONLY)
    try:
        with pytest.raises(AdapterFailureError, match="single-link regular file"):
            _retain_scored_gpqa_log(
                official=official,
                log_dir=log_dir,
                log_fd=log_fd,
                artifacts_dir=artifacts,
                artifacts_fd=artifacts_fd,
                latency_sec=0.1,
                command=("inspect", "eval"),
            )
    finally:
        os.close(log_fd)
        os.close(artifacts_fd)
    assert victim.read_bytes() == b'{"keep":true}\n'
    assert not (artifacts / "gpqa-official-log.json").exists()


def test_gpqa_retain_rejects_a_source_outside_the_pinned_log_dir(tmp_path: Path) -> None:
    log_dir = tmp_path / "inspect-logs"
    other = tmp_path / "other"
    artifacts = tmp_path / "artifacts"
    log_dir.mkdir()
    other.mkdir()
    artifacts.mkdir()
    source = other / "inspect-done.json"
    source.write_bytes(b'{"outside":true}\n')
    official = GpqaOfficialScore(
        0.5,
        4,
        8,
        str(source),
        scored_bytes=b'{"scored":true}\n',
    )
    log_fd = os.open(log_dir, os.O_RDONLY)
    artifacts_fd = os.open(artifacts, os.O_RDONLY)
    try:
        with pytest.raises(AdapterFailureError, match="direct child"):
            _retain_scored_gpqa_log(
                official=official,
                log_dir=log_dir,
                log_fd=log_fd,
                artifacts_dir=artifacts,
                artifacts_fd=artifacts_fd,
                latency_sec=0.1,
                command=("inspect", "eval"),
            )
    finally:
        os.close(log_fd)
        os.close(artifacts_fd)
    assert not (artifacts / "gpqa-official-log.json").exists()
