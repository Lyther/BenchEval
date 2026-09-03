"""Round-12 regressions for Harbor result selection.

SUBSTITUTE_JUSTIFICATION
- substitute: the two JSON files created by
  ``test_f001_harbor_selects_the_instance_trial_not_the_job_aggregate``
- replaces: Harbor's aggregate ``JobResult`` and nested per-instance
  ``TrialResult`` artifacts
- necessity: the regression requires both authority-conflicting artifacts to
  exist deterministically in one jobs tree; a live charged Harbor run cannot
  safely guarantee a chosen model result or exact output layout on demand
- real-option: a provisioned Docker/Harbor/provider dev-box run; it cannot
  deterministically manufacture the conflicting pass/aggregate state
- proof-limit: proves BenchEval's result selection and official reward parser,
  not Harbor execution, verifier correctness, model quality, or live readiness
- real-proof: BLOCKED until the dev-box Terminal-Bench lane is rerun through
  docs/ops/dev-box-pilot.md
"""

from __future__ import annotations

import json
from pathlib import Path

from bencheval.terminal_bench_harbor import HarborCliResult, parse_harbor_instance_outcome


def test_f001_harbor_selects_the_instance_trial_not_the_job_aggregate(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "jobs"
    job = artifacts / "2026-08-19__12-00-00"
    trial = job / "rstan-to-pystan__ABC123"
    trial.mkdir(parents=True)
    (job / "result.json").write_text(
        json.dumps({"stats": {"n_errors": 0}, "trials": ["rstan-to-pystan"]}),
        encoding="utf-8",
    )
    (trial / "result.json").write_text(
        json.dumps(
            {
                "task_name": "rstan-to-pystan",
                "exception_info": None,
                "verifier_result": {"rewards": {"reward": 1.0}},
            }
        ),
        encoding="utf-8",
    )

    outcome = parse_harbor_instance_outcome(
        instance_id="rstan-to-pystan",
        cli=HarborCliResult(0, "", "", 0.1, ("harbor", "run")),
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        harness_version="harbor@test",
    )

    assert outcome.primary_pass is True
    assert outcome.failure_class is None
    assert outcome.native_score["verdict_provenance"] == "harbor_verifier_result"
    assert outcome.raw_result_path is not None
    assert "rstan-to-pystan__ABC123/result.json" in outcome.raw_result_path
