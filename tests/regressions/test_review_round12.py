"""Round-12 regressions for Harbor result selection and operator-facing docs.

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
import re
import subprocess
import sys
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


def test_f002_dev_box_docs_do_not_put_provider_secrets_on_curl_argv() -> None:
    repo = Path(__file__).resolve().parents[2]
    text = (repo / "docs" / "ops" / "dev-box-pilot.md").read_text(encoding="utf-8")
    credentialed_curl = re.compile(
        r"^.*curl\b.*(?:authorization|x-api-key).*[\$][A-Z0-9_]*(?:KEY|TOKEN).*$",
        re.IGNORECASE | re.MULTILINE,
    )
    assert credentialed_curl.search(text) is None


def test_f007_bfcl_docs_describe_the_implemented_diagnostic_lifecycle() -> None:
    repo = Path(__file__).resolve().parents[2]
    ops = (repo / "docs" / "ops" / "benchmarks" / "bfcl-v4.md").read_text(encoding="utf-8")
    contracts = (repo / "docs" / "context" / "runtime-invocation-contracts.md").read_text(
        encoding="utf-8"
    )
    assert "`bfcl generate`" in ops and "`bfcl evaluate`" in ops
    assert "official score" in ops.lower()
    assert "generation-only" not in ops
    assert "official BFCL evaluate score parsing **not wired**" not in contracts

    command = (
        "from bencheval.cli import main; raise SystemExit(main(['benchmark', 'show', 'bfcl-v4']))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", command],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert '"id": "bfcl-v4"' in proc.stdout
