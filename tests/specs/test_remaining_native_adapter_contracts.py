"""RED contracts for model-only native adapter result integrity.

These tests parse real filesystem artifacts through the production parsers.
They do not replace Inspect Evals or CAIS HLE execution and therefore make no
live-harness or end-to-end claim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.gpqa_adapter import parse_gpqa_official_score
from bencheval.hle_adapter import parse_hle_official_score
from bencheval.slice_manifest import default_slices_dir, load_slice_manifest


def _inspect_log(*, accuracy: float) -> dict[str, object]:
    return {
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
                    "metrics": {"accuracy": {"name": "accuracy", "value": accuracy}},
                },
            ],
        },
    }


def test_gpqa_parser_accepts_inspect_log_but_ignores_unrelated_json(
    tmp_path: Path,
) -> None:
    official_dir = tmp_path / "official"
    official_dir.mkdir()
    # SUBSTITUTE_JUSTIFICATION
    # - substitute: synthetic Inspect eval log fixture
    # - replaces: live Inspect eval log on disk
    # - necessity: parser-only contract for Inspect acceptance vs unrelated JSON
    # - real-option: live Inspect GPQA log; requires eval extra + credentials
    # - proof-limit: diagnostic only — not production Inspect proof
    # - real-proof: BLOCKED until live GPQA pilot artifact is available
    (official_dir / "done.json").write_text(
        json.dumps(_inspect_log(accuracy=0.5)),
        encoding="utf-8",
    )
    official = parse_gpqa_official_score(
        official_dir,
        expected_model="openai/gpt-4",
        stdout=f"Log: {official_dir / 'done.json'}\n",
    )
    assert official is not None
    assert official.accuracy == pytest.approx(0.5)

    unrelated_dir = tmp_path / "unrelated"
    unrelated_dir.mkdir()
    (unrelated_dir / "run_metadata.json").write_text(
        json.dumps({"accuracy": 1.0, "correct": 99, "total": 99}),
        encoding="utf-8",
    )
    assert parse_gpqa_official_score(unrelated_dir) is None
    # Operator override alone is never pass-authoritative.
    override_only = tmp_path / "override-only"
    override_only.mkdir()
    (override_only / "official_scores.json").write_text(
        json.dumps({"accuracy": 0.5, "correct": 1, "total": 2}),
        encoding="utf-8",
    )
    assert parse_gpqa_official_score(override_only) is None


def test_gpqa_parser_rejects_out_of_range_accuracy_instead_of_clamping(
    tmp_path: Path,
) -> None:
    valid_dir = tmp_path / "valid"
    valid_dir.mkdir()
    # SUBSTITUTE_JUSTIFICATION
    # - substitute: synthetic Inspect eval log fixtures (valid + out-of-range)
    # - replaces: live Inspect metrics
    # - necessity: prove reject-not-clamp without inventing live out-of-range Inspect metrics
    # - real-option: cannot safely force Inspect to emit accuracy > 1.0
    # - proof-limit: parser-only diagnostic for range gate
    # - real-proof: not applicable for this negative path
    (valid_dir / "done.json").write_text(
        json.dumps(_inspect_log(accuracy=0.25)),
        encoding="utf-8",
    )
    assert (
        parse_gpqa_official_score(
            valid_dir,
            expected_model="openai/gpt-4",
            stdout=f"Log: {valid_dir / 'done.json'}\n",
        )
        is not None
    )

    invalid_dir = tmp_path / "invalid"
    invalid_dir.mkdir()
    invalid_path = invalid_dir / "done.json"
    invalid_path.write_text(
        json.dumps(_inspect_log(accuracy=1.25)),
        encoding="utf-8",
    )
    assert (
        parse_gpqa_official_score(
            invalid_dir,
            expected_model="openai/gpt-4",
            stdout=f"Log: {invalid_path}\n",
        )
        is None
    )


def test_hle_parser_uses_exact_judge_decisions_not_substring_matches(tmp_path: Path) -> None:
    model_id = "provider/model-under-test"
    judged = tmp_path / "judged_hle_model-under-test.json.json"
    judged.write_text(
        json.dumps(
            {
                "correct": {"judge_response": {"correct": "yes"}},
                "incorrect": {"judge_response": {"correct": "no"}},
                "negated": {"judge_response": {"correct": "not yes"}},
                "uppercase": {"judge_response": {"correct": "YES"}},
            },
        ),
        encoding="utf-8",
    )

    score = parse_hle_official_score(
        eval_dir=tmp_path,
        model_id=model_id,
        judge_stdout="Accuracy: 33.333% | n = 3",
        max_samples=3,
        work_dir=tmp_path,
    )

    # Noncanonical judge literals (substring/case variants) fail the whole artifact.
    assert score is None


def test_hle_parser_rejects_stdout_only_accuracy(tmp_path: Path) -> None:
    """Stdout metrics are never scoring authority once the judged artifact is missing."""
    assert (
        parse_hle_official_score(
            eval_dir=tmp_path,
            model_id="provider/valid-model",
            judge_stdout="Accuracy: 25.0% | n = 4",
            max_samples=4,
            work_dir=tmp_path,
        )
        is None
    )
    assert (
        parse_hle_official_score(
            eval_dir=tmp_path,
            model_id="provider/invalid-model",
            judge_stdout="Accuracy: 125.0% | n = 4",
            max_samples=4,
            work_dir=tmp_path,
        )
        is None
    )


@pytest.mark.parametrize(
    "filename",
    ["gpqa-diamond-smoke.yaml", "hle-smoke.yaml"],
)
def test_limit_based_model_only_smokes_do_not_claim_fixed_instance_identity(
    filename: str,
) -> None:
    manifest = load_slice_manifest(default_slices_dir() / filename)

    assert manifest.slice.selection_policy != "fixed_instance_ids"
    assert not any(instance.startswith("sample-") for instance in manifest.slice.instances)
