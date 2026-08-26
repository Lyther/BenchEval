"""RED contracts for the legacy evidence-comparison eligibility boundary.

SUBSTITUTE_JUSTIFICATION
- substitute: constructed ``EvidenceRecord`` populations and disposable JSONL
  files in every test in this module
- replaces: historical evidence from two charged benchmark/provider runs
- necessity: exact infrastructure-pass, explicit-invalid, and asymmetric
  eligibility populations cannot be produced safely and deterministically by
  a real benchmark while the production comparison implementation is exercised
- real-option: live runs cannot guarantee these exact mutually contradictory
  score/validity combinations and would incur external charges
- proof-limit: diagnostic proof of local filtering, validity, reporting, and
  CLI exit behavior only; it does not prove benchmark execution or score truth
- real-proof: a publishable comparison still requires two qualified native
  evidence sets with constant non-varied provenance axes
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import get_args

from bencheval.domain import InterpretationLabel
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink
from bencheval.evidence_compare import compare_evidence_runs

_TS = datetime(2026, 8, 25, tzinfo=UTC)


def _row(
    task_id: str,
    *,
    passed: bool,
    failure_labels: list[str] | None = None,
    attempt_validity: str | None = None,
    counts_toward_pass_at_k: bool | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        run_id=f"run-{task_id}",
        task_id=task_id,
        model_id="legacy/model",
        execution_profile="E0",
        backend="local",
        primary_pass=passed,
        partial_score=1.0 if passed else 0.0,
        cost_usd=0.0,
        latency_sec=0.1,
        failure_labels=failure_labels or ([] if passed else ["wrong_solution"]),
        attempt_validity=attempt_validity,
        counts_toward_pass_at_k=counts_toward_pass_at_k,
        created_at=_TS,
    )


def test_infrastructure_pass_cannot_improve_legacy_headline_rates() -> None:
    baseline = [
        _row("ordinary", passed=False),
        _row("infra", passed=True, failure_labels=["runtime_launch_failure"]),
    ]
    current = [
        _row("ordinary", passed=True),
        _row("infra", passed=True, failure_labels=["runtime_launch_failure"]),
    ]

    report = compare_evidence_runs(baseline, current)

    assert report.baseline_pass_rate == 0.0
    assert report.current_pass_rate == 1.0
    assert report.pass_rate_delta == 1.0
    assert len(report.task_deltas) == 2


def test_asymmetric_shared_eligibility_invalidates_legacy_comparison() -> None:
    baseline = [_row("shared", passed=True)]
    current = [
        _row(
            "shared",
            passed=True,
            attempt_validity="invalid",
            counts_toward_pass_at_k=False,
        ),
    ]

    payload = compare_evidence_runs(baseline, current).to_dict()

    assert payload["comparison_valid"] is False
    assert payload["interpretation_label"] == "contaminated_or_legacy"
    assert any("asymmetric" in reason for reason in payload["validity_reasons"])


def test_v02_ordinary_rows_remain_eligible() -> None:
    baseline = [_row("shared", passed=False)]
    current = [_row("shared", passed=True)]

    payload = compare_evidence_runs(baseline, current).to_dict()

    assert payload["comparison_valid"] is True
    assert payload["baseline_pass_rate"] == 0.0
    assert payload["current_pass_rate"] == 1.0


def test_valid_legacy_comparison_uses_closed_interpretation_label() -> None:
    baseline = [_row("shared", passed=False)]
    current = [_row("shared", passed=True)]

    payload = compare_evidence_runs(baseline, current).to_dict()

    assert payload["comparison_valid"] is True
    assert payload["interpretation_label"] == "contaminated_or_legacy"
    assert payload["interpretation_label"] in get_args(InterpretationLabel)


def test_cli_returns_nonzero_and_reports_invalid_legacy_comparison(
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "baseline.jsonl"
    current_path = tmp_path / "current.jsonl"
    output = tmp_path / "comparison.json"
    sink = JsonlEvidenceSink()
    sink.append_jsonl(baseline_path, _row("shared", passed=True))
    sink.append_jsonl(
        current_path,
        _row(
            "shared",
            passed=True,
            failure_labels=["remote_infra_failure"],
        ),
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "bencheval.cli",
            "compare",
            str(baseline_path),
            str(current_path),
            "--format",
            "json",
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    cli_payload = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert cli_payload["mode"] == "legacy"
    assert cli_payload["comparison_valid"] is False
    assert cli_payload["interpretation_label"] == "contaminated_or_legacy"
