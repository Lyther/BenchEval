"""F004: GPQA must score from real Inspect eval logs, not nonexistent official_scores.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.gpqa_adapter import parse_gpqa_official_score

# SUBSTITUTE_JUSTIFICATION
# - substitute: disposable Inspect-shaped eval log fixture below
# - replaces: live `inspect eval` JSON log written under --log-dir
# - necessity: parser contract must discriminate Inspect results.scores without a live model run
# - real-option: live Inspect GPQA run needs credentials/dataset; not deterministic here
# - proof-limit: does not prove Inspect writes this exact filename on every host version
# - real-proof: BLOCKED until live GPQA pilot log artifact under results/raw/
_INSPECT_EVAL_LOG = {
    "version": 2,
    "status": "success",
    "eval": {
        "created": "2024-01-01T00:00:00+00:00",
        "task": "gpqa_diamond",
        "task_id": "fixture-task",
        "model": "openai/gpt-4",
    },
    "results": {
        "total_samples": 2,
        "completed_samples": 2,
        "scores": [
            {
                "name": "choice",
                "scorer": "choice",
                "metrics": {
                    "accuracy": {
                        "name": "accuracy",
                        "value": 0.5,
                    },
                },
            },
        ],
    },
}


def test_gpqa_parser_reads_inspect_eval_log_without_official_scores(tmp_path: Path) -> None:
    log_dir = tmp_path / "inspect-logs"
    log_dir.mkdir()
    log_path = log_dir / "2024-01-01T00-00-00-00Z_gpqa_diamond_openai-gpt-4.json"
    log_path.write_text(
        json.dumps(_INSPECT_EVAL_LOG),
        encoding="utf-8",
    )
    assert not (log_dir / "official_scores.json").exists()

    score = parse_gpqa_official_score(
        log_dir,
        expected_model="openai/gpt-4",
        stdout=f"Log: {log_path}\n",
    )
    assert score is not None
    assert score.accuracy == pytest.approx(0.5)
    assert "gpqa_diamond" in score.source or score.source.endswith(".json")


def test_gpqa_parser_rejects_log_location_outside_claimed_log_dir(tmp_path: Path) -> None:
    log_dir = tmp_path / "inspect-logs"
    log_dir.mkdir()
    log_path = tmp_path / "external" / "run.json"
    log_path.parent.mkdir()
    log_path.write_text(json.dumps(_INSPECT_EVAL_LOG), encoding="utf-8")

    score = parse_gpqa_official_score(
        log_dir,
        expected_model="openai/gpt-4",
        stdout=f"task complete\nLog: {log_path}\n",
    )
    assert score is None


def test_gpqa_parser_ignores_operator_official_scores_override(tmp_path: Path) -> None:
    log_dir = tmp_path / "inspect-logs"
    log_dir.mkdir()
    log_path = log_dir / "noise.json"
    log_path.write_text(json.dumps(_INSPECT_EVAL_LOG), encoding="utf-8")
    # SUBSTITUTE_JUSTIFICATION
    # - substitute: synthetic official_scores.json override fixture
    # - replaces: operator-authored score file that must not own pass authority
    # - necessity: prove Inspect log wins when a conflicting override is present
    # - real-option: operator-authored file on a live host; not available in CI
    # - proof-limit: parser-only diagnostic for override non-authority
    # - real-proof: not required for override reject path; Inspect-log path covered above
    (log_dir / "official_scores.json").write_text(
        json.dumps({"accuracy": 0.25, "correct": 1, "total": 4}),
        encoding="utf-8",
    )

    score = parse_gpqa_official_score(
        log_dir,
        expected_model="openai/gpt-4",
        stdout=f"Log: {log_path}\n",
    )
    assert score is not None
    assert score.accuracy == pytest.approx(0.5)
    assert "official_scores.json" not in score.source
