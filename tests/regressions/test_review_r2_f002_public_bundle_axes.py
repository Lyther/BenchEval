"""F002: public bundles must redact secrets in SUMMARY.md and manifest.json."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from bencheval.evidence import EvidenceRecord
from bencheval.run_bundle import export_run_bundle

# SUBSTITUTE_JUSTIFICATION
# - substitute: monkeypatched test-only proxy key in
#   test_public_summary_and_manifest_redact_axis_secrets
# - replaces: a real provider credential used as a redaction canary
# - necessity: the assertion needs a known literal secret without exposing a real one
# - real-option: real credentials must not be written into test artifacts
# - proof-limit: proves local public-bundle redaction only
# - real-proof: live public-bundle inspection follows a credentialed dev-box pilot

_SECRET = "super-secret-axis-token-value-9f3a"


def test_public_summary_and_manifest_redact_axis_secrets(
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    monkeypatch.setenv("BYTELLM_PROXY_API_KEY", _SECRET)
    evidence = tmp_path / "evidence.jsonl"
    record = EvidenceRecord(
        run_id="public-bundle-secret",
        task_id="task-1",
        model_id=f"provider/{_SECRET}",
        execution_profile="E0",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.0,
        latency_sec=0.1,
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        adapter_id="gpqa",
        harness_kind="inspect-evals",
        provider_id="bytellm",
        provider_config_hash="sha256:public-provider-config",
        judge_model_id="gpt-5.4-2026-03-05",
    )
    evidence.write_text(record.model_dump_json() + "\n", encoding="utf-8")

    bundle_dir = tmp_path / "bundle"
    export_run_bundle(
        evidence_path=evidence,
        output_dir=bundle_dir,
        redaction="public",
    )

    summary = (bundle_dir / "SUMMARY.md").read_text(encoding="utf-8")
    report = (bundle_dir / "report.md").read_text(encoding="utf-8")
    manifest = (bundle_dir / "manifest.json").read_text(encoding="utf-8")
    evidence_out = (bundle_dir / "evidence.jsonl").read_text(encoding="utf-8")

    assert _SECRET not in evidence_out
    assert _SECRET not in summary
    assert _SECRET not in manifest
    parsed = json.loads(manifest)
    assert parsed["redaction"] == "public"
    assert parsed["axes"]["provider_config_hash"] == "sha256:public-provider-config"
    assert parsed["axes"]["judge_model_id"] == "gpt-5.4-2026-03-05"
    public_record = json.loads(evidence_out)
    assert public_record["provider_config_hash"] == "sha256:public-provider-config"
    assert public_record["judge_model_id"] == "gpt-5.4-2026-03-05"
    assert "provider_config_hash: `sha256:public-provider-config`" in summary
    assert "judge_model_id: `gpt-5.4-2026-03-05`" in summary
    assert "Provider config hash: `sha256:public-provider-config`" in report
    assert "Judge model: `gpt-5.4-2026-03-05`" in report
    assert os.environ.get("BYTELLM_PROXY_API_KEY") == _SECRET
