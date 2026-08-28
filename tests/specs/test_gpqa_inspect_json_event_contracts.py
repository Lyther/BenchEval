"""RED contracts for inspect-ai 0.3.x GPQA done-log discovery and epoch completeness.

Live inspect-ai 0.3.252 --json stdout names the official log as
``{"event": "done", "logs": [{"location": ...}]}``. The older
``{"type": "done", "tasks": [{"log_location": ...}]}`` shape remains valid.
inspect-evals ``gpqa_diamond`` defaults to ``epochs: 4``, so a two-slot smoke
completes 8 epoch rows while still requesting exactly two unique samples.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.gpqa_adapter import (
    GpqaCliResult,
    parse_gpqa_official_score,
    run_gpqa_slice,
)

# SUBSTITUTE_JUSTIFICATION
# - substitute: disposable inspect-ai 0.3.252-shaped stdout + eval-log fixtures
#   used by injected ``process_runner`` callables
# - replaces: a second charged live Inspect GPQA run
# - necessity: assert exact done-event and epoch-row completeness without
#   re-calling the provider; the live 2026-08-25 smoke already proved the
#   official schema and cannot be replayed deterministically
# - real-option: re-run `inspect eval inspect_evals/gpqa_diamond` on
#   dev-box-cpu; that charges tokens and is not a parser-discrimination oracle
# - proof-limit: does not prove Inspect will keep this event key forever
# - real-proof: registered operator-host run
#   ``run-20260825-160511-036214-304c2cee`` (private proof
#   ``sha256:aa19d02b7d1457d0f43d9588b3d08c042e967a981ed8537068412e1797ff0eda``)
#   remains externally retained
# - covered tests: test_gpqa_parser_reads_inspect_ai_event_done_logs_location,
#   test_gpqa_parser_rejects_event_done_location_outside_log_dir,
#   test_gpqa_parser_still_reads_legacy_type_done_task_log_location,
#   test_gpqa_epoch_expanded_official_rows_remain_complete_for_requested_limit,
#   test_gpqa_rejects_epoch_row_count_that_is_not_unique_samples_times_epochs,
#   test_gpqa_duplicate_sample_ids_are_not_a_unique_sample_count


def _gpqa_plan():
    return plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )


def _inspect_eval_log(
    *,
    model: str,
    accuracy: float,
    unique_ids: tuple[str, ...] = ("rec06pnAkLOr2t2mp", "rec0Arme2jcXQZnAW"),
    epochs: int = 4,
) -> dict[str, object]:
    unique = len(unique_ids)
    epoch_rows = unique * epochs
    return {
        "status": "success",
        "eval": {
            "task": "inspect_evals/gpqa_diamond",
            "task_registry_name": "inspect_evals/gpqa_diamond",
            "model": model,
            "dataset": {
                "name": "gpqa_diamond_fixture",
                "samples": 198,
                "sample_ids": list(unique_ids),
                "shuffled": False,
            },
            "task_args": {"cot": True, "epochs": epochs},
            "config": {"limit": unique, "epochs": epochs},
        },
        "results": {
            "total_samples": epoch_rows,
            "completed_samples": epoch_rows,
            "scores": [
                {
                    "name": "choice",
                    "scorer": "choice",
                    "metrics": {
                        "accuracy": {
                            "name": "accuracy",
                            "value": accuracy,
                            "params": {},
                        }
                    },
                }
            ],
        },
    }


def _write_log(log_dir: Path, payload: dict[str, object]) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "2026-08-25T15-46-52-00-00_gpqa-diamond_fixture.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_gpqa_parser_reads_inspect_ai_event_done_logs_location(tmp_path: Path) -> None:
    log_dir = tmp_path / "inspect-logs"
    log_path = _write_log(
        log_dir,
        _inspect_eval_log(model="openai/kimi-k2.7-code", accuracy=1.0),
    )
    stdout = (
        json.dumps(
            {
                "event": "launch",
                "run_id": "fixture-run",
                "log_dir": str(log_dir),
            }
        )
        + "\n"
        + json.dumps(
            {
                "event": "done",
                "run_id": "fixture-run",
                "logs": [
                    {
                        "task": "inspect_evals/gpqa_diamond",
                        "status": "success",
                        "location": str(log_path),
                    }
                ],
            }
        )
        + "\n"
    )

    score = parse_gpqa_official_score(
        log_dir,
        expected_model="openai/kimi-k2.7-code",
        stdout=stdout,
    )

    assert score is not None
    assert score.accuracy == pytest.approx(1.0)
    assert score.total == 8
    assert score.correct == 8
    assert score.unique_samples == 2
    assert score.epochs == 4
    assert Path(score.source).resolve() == log_path.resolve()


def test_gpqa_parser_rejects_event_done_location_outside_log_dir(
    tmp_path: Path,
) -> None:
    log_dir = tmp_path / "inspect-logs"
    log_dir.mkdir()
    outside = tmp_path / "external" / "escaped.json"
    outside.parent.mkdir()
    outside.write_text(
        json.dumps(_inspect_eval_log(model="openai/kimi-k2.7-code", accuracy=1.0)),
        encoding="utf-8",
    )
    stdout = json.dumps(
        {
            "event": "done",
            "logs": [{"status": "success", "location": str(outside)}],
        }
    )

    score = parse_gpqa_official_score(
        log_dir,
        expected_model="openai/kimi-k2.7-code",
        stdout=stdout,
    )
    assert score is None


def test_gpqa_parser_still_reads_legacy_type_done_task_log_location(
    tmp_path: Path,
) -> None:
    log_dir = tmp_path / "inspect-logs"
    log_path = _write_log(
        log_dir,
        _inspect_eval_log(model="openai/kimi-k2.7-code", accuracy=0.5, epochs=1),
    )
    stdout = json.dumps(
        {
            "type": "done",
            "status": "success",
            "tasks": [{"status": "success", "log_location": str(log_path)}],
        }
    )

    score = parse_gpqa_official_score(
        log_dir,
        expected_model="openai/kimi-k2.7-code",
        stdout=stdout,
    )

    assert score is not None
    assert score.accuracy == pytest.approx(0.5)
    assert score.total == 2


def test_gpqa_epoch_expanded_official_rows_remain_complete_for_requested_limit(
    tmp_path: Path,
) -> None:
    plan = _gpqa_plan()
    assert len(plan.instances) == 2
    selected_log: Path | None = None

    def inspect_runner(
        command,
        *,
        cwd: Path | None,
        timeout_sec: int,
        env=None,
    ) -> GpqaCliResult:
        nonlocal selected_log
        log_dir = Path(command[command.index("--log-dir") + 1])
        model = command[command.index("--model") + 1]
        selected_log = _write_log(
            log_dir,
            _inspect_eval_log(model=model, accuracy=1.0, epochs=4),
        )
        stdout = json.dumps(
            {
                "event": "done",
                "logs": [
                    {
                        "task": "inspect_evals/gpqa_diamond",
                        "status": "success",
                        "location": str(selected_log),
                    }
                ],
            }
        )
        return GpqaCliResult(0, stdout + "\n", "", 0.2, tuple(command))

    outcome = run_gpqa_slice(
        plan=plan,
        artifacts_dir=tmp_path / "run",
        repo_root=tmp_path,
        process_runner=inspect_runner,
        timeout_sec=5,
    )[0]

    assert selected_log is not None
    assert outcome.partial_score == pytest.approx(1.0)
    assert outcome.primary_pass is True
    assert outcome.failure_class is None
    assert outcome.counts_toward_pass_at_k is True
    assert outcome.native_score["total"] == 8
    assert outcome.native_score["unique_samples"] == 2
    assert outcome.native_score["epochs"] == 4
    retained = Path(outcome.verifier_log_path or "")
    assert retained.name == "gpqa-official-log.json"
    assert retained.read_bytes() == selected_log.read_bytes()
    assert outcome.native_score["score_source"] == str(selected_log)


def test_gpqa_rejects_epoch_row_count_that_is_not_unique_samples_times_epochs(
    tmp_path: Path,
) -> None:
    plan = _gpqa_plan()

    def inspect_runner(
        command,
        *,
        cwd: Path | None,
        timeout_sec: int,
        env=None,
    ) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        model = command[command.index("--model") + 1]
        payload = _inspect_eval_log(model=model, accuracy=1.0, epochs=4)
        results = payload["results"]
        assert isinstance(results, dict)
        results["total_samples"] = 7
        results["completed_samples"] = 7
        log_path = _write_log(log_dir, payload)
        stdout = json.dumps(
            {
                "event": "done",
                "logs": [{"status": "success", "location": str(log_path)}],
            }
        )
        return GpqaCliResult(0, stdout + "\n", "", 0.2, tuple(command))

    outcome = run_gpqa_slice(
        plan=plan,
        artifacts_dir=tmp_path / "run",
        repo_root=tmp_path,
        process_runner=inspect_runner,
        timeout_sec=5,
    )[0]

    assert outcome.primary_pass is False
    assert outcome.counts_toward_pass_at_k is False
    assert outcome.failure_class == "runtime_output_unparseable"


def test_gpqa_duplicate_sample_ids_are_not_a_unique_sample_count(
    tmp_path: Path,
) -> None:
    plan = _gpqa_plan()

    def inspect_runner(
        command,
        *,
        cwd: Path | None,
        timeout_sec: int,
        env=None,
    ) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        model = command[command.index("--model") + 1]
        payload = _inspect_eval_log(
            model=model,
            accuracy=1.0,
            unique_ids=("rec06pnAkLOr2t2mp", "rec06pnAkLOr2t2mp"),
            epochs=4,
        )
        log_path = _write_log(log_dir, payload)
        stdout = json.dumps(
            {
                "event": "done",
                "logs": [{"status": "success", "location": str(log_path)}],
            }
        )
        return GpqaCliResult(0, stdout + "\n", "", 0.2, tuple(command))

    outcome = run_gpqa_slice(
        plan=plan,
        artifacts_dir=tmp_path / "run",
        repo_root=tmp_path,
        process_runner=inspect_runner,
        timeout_sec=5,
    )[0]

    assert outcome.primary_pass is False
    assert outcome.counts_toward_pass_at_k is False
    assert outcome.failure_class == "runtime_output_unparseable"
