"""RED contracts for BFCL v4's official generation/evaluation lifecycle."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import BfclCliResult, run_bfcl_instance
from bencheval.slice_manifest import load_slice_manifest, slice_instance_ids

# SUBSTITUTE_JUSTIFICATION
# - substitute: _official_lifecycle_runner and _generation_verdict_runner in this file
# - replaces: the external BFCL CLI process and its charged provider calls
# - necessity: these assertions require deterministic control of the exact generate/evaluate
#   transition and a forged generation-side verdict; a real provider run cannot safely and
#   deterministically expose those orchestration fault states
# - real-option: an official bfcl-eval install plus a supported registered model and provider
#   credentials; those prerequisites are not available in the local Tier-0 environment
# - proof-limit: these tests prove only BenchEval command sequencing and score-artifact authority,
#   not BFCL execution, scorer correctness, model quality, or live readiness
# - real-proof: BLOCKED until the BFCL dev-box lifecycle is provisioned and its native score
#   artifact qualifies through BenchEval live proof


def _plan():
    return plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        # The only config/models.yaml entry the pinned upstream
        # MODEL_CONFIG_MAPPING supports (see test_bfcl_official_score_contracts.py).
        model_id="gpt-5.2-2025-12-11",
    )


def _option_path(command: Sequence[str], option: str) -> Path:
    index = command.index(option)
    return Path(command[index + 1])


def test_bfcl_smoke_slice_uses_current_v4_category_name() -> None:
    path = Path("config/slices/bfcl-v4-smoke-5.yaml")
    manifest = load_slice_manifest(path)
    instances = slice_instance_ids(manifest, path)

    assert "simple" not in instances
    assert "simple_python" in instances


def test_bfcl_runs_generate_then_evaluate_and_scores_only_official_output(
    tmp_path: Path,
) -> None:
    plan = _plan()
    calls: list[tuple[str, ...]] = []

    def _official_lifecycle_runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        call = tuple(command)
        calls.append(call)
        if len(call) > 1 and call[1] == "evaluate":
            score_root = _option_path(call, "--score-dir")
            # Pinned upstream format: JSONL, header-only on a perfect run,
            # named BFCL_v4_<category>_score.json (see the sibling
            # test_bfcl_official_score_contracts.py module docstring).
            score_file = (
                score_root / plan.model_id / "non_live" / "BFCL_v4_simple_python_score.json"
            )
            score_file.parent.mkdir(parents=True, exist_ok=True)
            score_file.write_text(
                json.dumps({"accuracy": 1.0, "correct_count": 1, "total_count": 1}) + "\n",
                encoding="utf-8",
            )
        return BfclCliResult(0, "", "", 0.1, call)

    outcome = run_bfcl_instance(
        plan=plan,
        instance_id="simple_python",
        artifacts_dir=tmp_path / "artifacts",
        repo_root=tmp_path,
        process_runner=_official_lifecycle_runner,
        harness_version="bfcl-eval@2026.3.23",
    )

    assert [command[1] for command in calls] == ["generate", "evaluate"]
    generate, evaluate = calls
    assert _option_path(generate, "--result-dir") == _option_path(evaluate, "--result-dir")
    assert "--score-dir" in evaluate
    assert outcome.primary_pass is True
    assert outcome.failure_class is None
    assert outcome.verifier_log_path is not None
    assert outcome.verifier_log_path.endswith("BFCL_v4_simple_python_score.json")


def test_bfcl_generation_side_verdict_cannot_grant_pass(tmp_path: Path) -> None:
    plan = _plan()

    def _generation_verdict_runner(
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        call = tuple(command)
        if len(call) > 1 and call[1] == "generate":
            result_root = _option_path(call, "--result-dir")
            result_root.mkdir(parents=True, exist_ok=True)
            (result_root / "verdict.json").write_text(
                json.dumps({"primary_pass": True}),
                encoding="utf-8",
            )
        return BfclCliResult(0, "", "", 0.1, call)

    outcome = run_bfcl_instance(
        plan=plan,
        instance_id="simple_python",
        artifacts_dir=tmp_path / "artifacts",
        repo_root=tmp_path,
        process_runner=_generation_verdict_runner,
        harness_version="bfcl-eval@2026.3.23",
    )

    assert outcome.primary_pass is False
    assert outcome.failure_class == "harness_failure"
    assert outcome.verifier_log_path is None
