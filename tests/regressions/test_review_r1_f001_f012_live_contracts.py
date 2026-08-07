"""Round-1 reject regressions: producer→qualifier, score ownership, compare, paths."""

from __future__ import annotations

import json
import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import EvidenceRecord, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.external_agent_adapter import run_external_agent_instance
from bencheval.gpqa_adapter import GpqaCliResult, parse_gpqa_official_score
from bencheval.hle_adapter import parse_hle_official_score
from bencheval.live_proof import qualify_lane
from bencheval.path_safety import validate_control_plane_instance_id
from bencheval.run_bundle import export_run_bundle
from bencheval.runtime_compare import assess_runtime_comparison_validity
from bencheval.terminal_bench_harbor import HarborCliResult, build_harbor_run_command
from tests.factories import make_control_plane_evidence_record

_INSPECT_LOG = {
    "version": 2,
    "status": "success",
    "eval": {
        "created": "2024-01-01T00:00:00+00:00",
        "task": "gpqa_diamond",
        "task_id": "fixture-task",
        "model": "openai/kimi-k2.7-code",
    },
    "results": {
        "total_samples": 2,
        "completed_samples": 2,
        "scores": [
            {
                "name": "choice",
                "scorer": "choice",
                "metrics": {"accuracy": {"name": "accuracy", "value": 0.0}},
            },
        ],
    },
}


def test_f001_harbor_producer_stamps_native_label(tmp_path: Path) -> None:
    """SUBSTITUTE_JUSTIFICATION
    - substitute: injected Harbor CLI runner that writes result.json
    - replaces: live Harbor + Docker + provider credentials
    - necessity: prove evidence constructors stamp verifier_integrity_label from
      adapter verifier artifacts without writing that field in the test
    - real-option: live pilot matrix on dev-box
    - proof-limit: does not prove Docker/Harbor isolation or provider auth
    - real-proof: BLOCKED until Harbor doctor + live matrix
    """
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    one = plan.model_copy(update={"instances": plan.instances[:1]})
    evidence = tmp_path / "e.jsonl"
    arts = tmp_path / "raw"

    def fake(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        dirs = [p for p in arts.iterdir() if p.is_dir()]
        assert dirs, "instance dir must exist before Harbor launch"
        (dirs[0] / "result.json").write_text(
            json.dumps({"verifier": {"rewards": {"reward": 1.0}}}),
            encoding="utf-8",
        )
        return HarborCliResult(0, "ok", "", 0.05, tuple(command))

    execute_control_plane_run(
        plan=one,
        output_path=evidence,
        artifacts_dir=arts,
        harbor_process_runner=fake,
        run_id="f001-harbor",
    )
    rows = read_evidence_jsonl(evidence)
    assert len(rows) == 1
    assert rows[0].verifier_integrity_label == "native"
    assert rows[0].verifier_log_path
    q = qualify_lane(
        evidence,
        expected_instances=1,
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        require_runtime=False,
        repo_root=tmp_path,
    )
    assert "no-native-verifier-result" not in " ".join(q.reasons)


def test_f002_gpqa_inspect_log_wins_over_operator_override(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_path = log_dir / "done.json"
    log_path.write_text(json.dumps(_INSPECT_LOG), encoding="utf-8")
    (log_dir / "official_scores.json").write_text(
        json.dumps({"accuracy": 1.0, "correct": 2, "total": 2}),
        encoding="utf-8",
    )
    score = parse_gpqa_official_score(
        log_dir,
        expected_model="openai/kimi-k2.7-code",
        stdout=f"Log: {log_path}\n",
    )
    assert score is not None
    assert score.accuracy == pytest.approx(0.0)
    assert "official_scores.json" not in score.source


def test_f002_gpqa_execute_uses_inspect_not_override(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    evidence = tmp_path / "e.jsonl"

    def fake(command, *, cwd: Path | None, timeout_sec: int, env=None) -> GpqaCliResult:
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "official_scores.json").write_text(
            json.dumps({"accuracy": 1.0, "correct": 2, "total": 2}),
            encoding="utf-8",
        )
        (log_dir / "done.json").write_text(json.dumps(_INSPECT_LOG), encoding="utf-8")
        log_path = log_dir / "done.json"
        return GpqaCliResult(0, f"Log: {log_path}\n", "", 0.05, tuple(command))

    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        gpqa_process_runner=fake,
        run_id="f002-gpqa",
    )
    rows = read_evidence_jsonl(evidence)
    assert rows[0].partial_score == pytest.approx(0.0)
    assert rows[0].primary_pass is False
    assert rows[0].verifier_integrity_label == "native"


def test_f003_hle_ignores_stale_judged_glob(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "judged_hle_stale.json").write_text(
        json.dumps({"x": {"judge_response": {"correct": "yes"}}}),
        encoding="utf-8",
    )
    expected = work / "judged_hle_current.json"
    score = parse_hle_official_score(
        eval_dir=tmp_path,
        model_id="provider/current",
        judge_stdout="",
        max_samples=1,
        work_dir=work,
        judged_path=expected,
    )
    assert score is None


def test_f004_asymmetric_eligible_populations_invalid() -> None:
    baseline = [
        make_control_plane_evidence_record(
            instance_id="a",
            runtime_id="claude-code",
            counts_toward_pass_at_k=True,
        ),
        make_control_plane_evidence_record(
            instance_id="b",
            runtime_id="claude-code",
            counts_toward_pass_at_k=True,
        ),
    ]
    current = [
        make_control_plane_evidence_record(
            instance_id="a",
            runtime_id="codex-cli",
            counts_toward_pass_at_k=True,
        ),
        make_control_plane_evidence_record(
            instance_id="b",
            runtime_id="codex-cli",
            counts_toward_pass_at_k=False,
        ),
    ]
    verdict = assess_runtime_comparison_validity(baseline, current)
    assert verdict.valid is False
    assert any("asymmetric" in r for r in verdict.reasons)


def test_f005_private_bundle_denies_proxy_env(tmp_path: Path) -> None:
    evidence = tmp_path / "e.jsonl"
    evidence.write_text(
        EvidenceRecord(
            run_id="r",
            task_id="t",
            model_id="kimi-k2.7-code",
            execution_profile="E0",
            backend="local",
            primary_pass=False,
            partial_score=0.0,
            cost_usd=0.0,
            latency_sec=0.0,
            failure_labels=[],
            artifact_paths=[],
            adapter_metadata={},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / ".bencheval-harbor-proxy.env").write_text(
        "https_proxy=http://user:s3cr3t@proxy:1\n",
        encoding="utf-8",
    )
    out = tmp_path / "bundle"
    archive = export_run_bundle(
        evidence_path=evidence,
        output_dir=out,
        raw_dir=raw,
        redaction="private",
    )
    assert not (out / "raw" / ".bencheval-harbor-proxy.env").exists()
    with tarfile.open(archive, "r:gz") as tf:
        names = tf.getnames()
    assert not any(".bencheval-harbor-proxy.env" in n for n in names)
    assert "s3cr3t" not in archive.read_bytes().decode("latin-1", errors="ignore")


def test_f013_build_harbor_command_does_not_orphan_proxy_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BENCHEVAL_HARBOR_FORWARD_PROXY", "1")
    monkeypatch.setenv("https_proxy", "http://user:s3cr3t@proxy.example:8118")
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    cmd = build_harbor_run_command(
        plan=plan,
        instance_id="fix-git",
        artifacts_dir=tmp_path,
    )
    assert "--env-file" not in cmd


def test_f007_harbor_deny_network_policy_rejected(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    ).model_copy(update={"network_policy": "deny"})
    with pytest.raises(BenchEvalError, match="cannot enforce network_policy=deny"):
        build_harbor_run_command(
            plan=plan,
            instance_id="fix-git",
            artifacts_dir=tmp_path,
        )


def test_f008_external_agent_rejects_traversal_instance_id(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="instance"):
        validate_control_plane_instance_id("../escaped")
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="kimi-k2.7-code",
        agent_id="momo",
    )

    def boom(*_a: object, **_k: object) -> None:
        raise AssertionError("should not launch")

    with pytest.raises(Exception, match="instance"):
        run_external_agent_instance(
            plan=plan,
            instance_id="../escaped",
            artifacts_dir=tmp_path / "art",
            repo_root=tmp_path,
            process_runner=boom,  # type: ignore[arg-type]
        )


def test_f011_bundle_rejects_nested_output_under_raw(tmp_path: Path) -> None:
    evidence = tmp_path / "e.jsonl"
    evidence.write_text(
        EvidenceRecord(
            run_id="r",
            task_id="t",
            model_id="kimi-k2.7-code",
            execution_profile="E0",
            backend="local",
            primary_pass=False,
            partial_score=0.0,
            cost_usd=0.0,
            latency_sec=0.0,
            failure_labels=[],
            artifact_paths=[],
            adapter_metadata={},
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    raw = tmp_path / "raw"
    raw.mkdir()
    with pytest.raises(BenchEvalError, match="must not equal or nest"):
        export_run_bundle(
            evidence_path=evidence,
            output_dir=raw / "bundle-out",
            raw_dir=raw,
            redaction="private",
        )
