"""BFCL v4 official score-artifact contracts at the pinned upstream format.

Upstream pin: gorilla commit ``6ea57973c7a6097fd7c5915698c54c17c5b1b6c8``
(paths rooted at ``berkeley-function-call-leaderboard/bfcl_eval/``):

- ``utils.py:463-490`` ``write_list_of_dicts_to_file`` writes
  ``json.dumps(entry) + "\\n"`` per entry — the score artifact is JSONL,
  one object per line, not a JSON array.
- ``eval_checker/eval_runner_helper.py:164-189`` ``save_eval_results`` inserts
  the summary header (``accuracy``/``correct_count``/``total_count``) at line 0
  and names the file ``BFCL_v4_<category>_score.json`` under
  ``<score_dir>/<model_name>/<directory-structure>/``.
- ``eval_checker/eval_runner.py`` (single-turn AST) records ONLY failed cases
  after the header, so a perfect run is a header-only one-line file; model
  directories use ``model_name.replace("/", "_")`` and the official evaluate
  path raises ``ValueError`` for models outside ``MODEL_CONFIG_MAPPING``.

SUBSTITUTE_JUSTIFICATION
- substitute: ``_RecordingRunner`` process-runner callables, the synthetic
  official-format score artifacts written by the parse/run-level tests, and
  the copied config bundle used for manifest-drift assertions; the default-runner
  pin-bypass regression replaces BFCL version capture and clears ``PATH``
- replaces: the external ``bfcl`` CLI process, its charged provider calls, the
  score artifacts the real evaluate phase would author, and the operator's
  installed config bundle; the pin-bypass regression replaces installed
  distribution metadata and external-command discovery
- necessity: the assertions require deterministic score-artifact states
  (header-only perfect run, partial run with failure rows, unprefixed or
  duplicate artifacts, unsupported-model rejection, and pin drift before
  launch) that a real bfcl install cannot safely and deterministically
  manufacture on demand; installing a deliberately stale BFCL distribution
  into the operator environment is not isolated or safe for this assertion
- real-option: an official bfcl-eval install at the pinned commit plus a
  supported registered model and provider credentials; those prerequisites are
  not available in the local Tier-0 environment
- proof-limit: proves BenchEval-side parsing, artifact location, and
  supported-model gating only — not BFCL execution, scorer correctness, model
  quality, or live readiness
- real-proof: BLOCKED until the BFCL dev-box lifecycle is provisioned and its
  native score artifact qualifies through BenchEval live proof
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
import yaml

from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import (
    BfclCliResult,
    parse_bfcl_instance_outcome,
    run_bfcl_instance,
)
from bencheval.exceptions import BenchEvalError

# The only model registered in config/models.yaml that the pinned upstream
# MODEL_CONFIG_MAPPING supports (constants/model_config.py:180).
_SUPPORTED_MODEL = "gpt-5.2-2025-12-11"
# Registered in config/models.yaml but absent from the pinned upstream
# MODEL_CONFIG_MAPPING — the official evaluate path refuses it.
_UNSUPPORTED_MODEL = "kimi-k2.7-code"
_PINNED_HARNESS_VERSION = "bfcl-eval@2026.3.23"


def _write_score_jsonl(
    score_dir: Path,
    model_dir: str,
    filename: str,
    rows: list[dict[str, object]],
    *,
    group: str = "non_live",
) -> Path:
    score_file = score_dir / model_dir / group / filename
    score_file.parent.mkdir(parents=True, exist_ok=True)
    score_file.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return score_file


def _parse(
    tmp_path: Path,
    score_dir: Path,
    *,
    model_id: str = _SUPPORTED_MODEL,
    instance_id: str = "simple_python",
):
    cli = BfclCliResult(0, "", "", 0.1, ("bfcl", "evaluate"))
    return parse_bfcl_instance_outcome(
        instance_id=instance_id,
        cli=cli,
        artifacts_dir=tmp_path / "inst",
        repo_root=tmp_path,
        harness_version="bfcl@test",
        score_dir=score_dir,
        model_id=model_id,
    )


def test_header_only_score_file_is_a_perfect_pass(tmp_path: Path) -> None:
    # A perfect upstream run records zero failed cases, so the official
    # artifact is exactly one JSONL line: the summary header.
    score_dir = tmp_path / "scores"
    _write_score_jsonl(
        score_dir,
        _SUPPORTED_MODEL,
        "BFCL_v4_simple_python_score.json",
        [{"accuracy": 1.0, "correct_count": 1, "total_count": 1}],
    )
    out = _parse(tmp_path, score_dir)
    assert out.primary_pass is True
    assert out.partial_score == 1.0
    assert out.failure_class is None
    assert out.verifier_log_path is not None
    assert out.verifier_log_path.endswith("BFCL_v4_simple_python_score.json")


def test_partial_score_with_failure_rows_is_model_wrong_solution(tmp_path: Path) -> None:
    # Upstream records one row per FAILED case after the header.
    score_dir = tmp_path / "scores"
    _write_score_jsonl(
        score_dir,
        _SUPPORTED_MODEL,
        "BFCL_v4_simple_python_score.json",
        [
            {"accuracy": 0.5, "correct_count": 1, "total_count": 2},
            {
                "id": "simple_python_1",
                "model_name": _SUPPORTED_MODEL,
                "test_category": "simple_python",
                "valid": False,
                "error": ["decoded output does not match"],
                "error_type": "ast:exec_output_mismatch",
                "prompt": {"id": "simple_python_1", "question": "..."},
                "model_result_raw": "def f(): ...",
                "possible_answer": [{"f": {"x": [1]}}],
            },
        ],
    )
    out = _parse(tmp_path, score_dir)
    assert out.primary_pass is False
    assert out.partial_score == pytest.approx(0.5)
    assert out.failure_class == "model_wrong_solution"


_FAILURE_ROW = {
    "id": "simple_python_1",
    "valid": False,
    "error": ["decoded output does not match"],
    "error_type": "ast:exec_output_mismatch",
}


@pytest.mark.parametrize(
    "rows",
    [
        pytest.param(
            [{"accuracy": 1.0, "correct_count": 0, "total_count": 1}, _FAILURE_ROW],
            id="accuracy-incoherent-with-counts",
        ),
        pytest.param(
            [{"accuracy": True, "correct_count": 1, "total_count": 1}],
            id="accuracy-bool",
        ),
        pytest.param(
            [{"accuracy": 1.0, "correct_count": True, "total_count": 1}],
            id="correct-count-bool",
        ),
        pytest.param(
            [{"accuracy": float("nan"), "correct_count": 1, "total_count": 1}],
            id="accuracy-nan",
        ),
        pytest.param(
            [{"accuracy": float("inf"), "correct_count": 1, "total_count": 1}],
            id="accuracy-infinity",
        ),
        pytest.param(
            [
                {"accuracy": 0.0, "correct_count": 0, "total_count": 2},
                _FAILURE_ROW,
                {**_FAILURE_ROW, "error": ["other mismatch"]},
            ],
            id="duplicate-failure-ids",
        ),
        pytest.param(
            [
                {"accuracy": 0.5, "correct_count": 1, "total_count": 2},
                {**_FAILURE_ROW, "valid": True},
            ],
            id="failure-row-valid-true",
        ),
        pytest.param(
            [{"accuracy": 0.0, "correct_count": 0, "total_count": 2}, _FAILURE_ROW],
            id="failure-row-count-mismatch",
        ),
    ],
)
def test_incoherent_score_artifacts_fail_closed(
    tmp_path: Path,
    rows: list[dict[str, object]],
) -> None:
    """One negative case per parser coherence arm: a well-located artifact whose
    header counts, accuracy, or failure rows violate the pinned upstream
    contract is unparseable and can never grant a pass."""
    score_dir = tmp_path / "scores"
    _write_score_jsonl(
        score_dir,
        _SUPPORTED_MODEL,
        "BFCL_v4_simple_python_score.json",
        rows,
    )
    out = _parse(tmp_path, score_dir)
    assert out.primary_pass is False
    assert out.partial_score == 0.0
    assert out.failure_class == "runtime_output_unparseable"


def test_score_file_without_version_prefix_is_not_located(tmp_path: Path) -> None:
    # The historical bare ``<category>.json`` name is not the official
    # ``BFCL_v4_<category>_score.json`` artifact and must not be scored.
    score_dir = tmp_path / "scores"
    _write_score_jsonl(
        score_dir,
        _SUPPORTED_MODEL,
        "simple_python.json",
        [{"accuracy": 1.0, "correct_count": 1, "total_count": 1}],
    )
    out = _parse(tmp_path, score_dir)
    assert out.primary_pass is False
    assert out.failure_class == "harness_failure"
    assert out.verifier_log_path is None


def test_score_file_with_wrong_version_prefix_is_not_located(tmp_path: Path) -> None:
    score_dir = tmp_path / "scores"
    _write_score_jsonl(
        score_dir,
        _SUPPORTED_MODEL,
        "BFCL_v3_simple_python_score.json",
        [{"accuracy": 1.0, "correct_count": 1, "total_count": 1}],
    )
    out = _parse(tmp_path, score_dir)
    assert out.primary_pass is False
    assert out.failure_class == "harness_failure"
    assert out.verifier_log_path is None


def test_model_directory_uses_upstream_slash_normalization(tmp_path: Path) -> None:
    # eval_runner.py: model directories are ``model_name.replace("/", "_")``.
    score_dir = tmp_path / "scores"
    _write_score_jsonl(
        score_dir,
        "org_model-x",
        "BFCL_v4_simple_python_score.json",
        [{"accuracy": 1.0, "correct_count": 1, "total_count": 1}],
    )
    out = _parse(tmp_path, score_dir, model_id="org/model-x")
    assert out.primary_pass is True
    assert out.verifier_log_path is not None
    assert "org_model-x" in out.verifier_log_path


def test_ambiguous_duplicate_score_artifacts_fail_closed(tmp_path: Path) -> None:
    # Two exact-name candidates under the normalized model directory cannot be
    # disambiguated; scoring either one would be an invented verdict.
    score_dir = tmp_path / "scores"
    rows = [{"accuracy": 1.0, "correct_count": 1, "total_count": 1}]
    _write_score_jsonl(
        score_dir, _SUPPORTED_MODEL, "BFCL_v4_simple_python_score.json", rows, group="non_live"
    )
    _write_score_jsonl(
        score_dir, _SUPPORTED_MODEL, "BFCL_v4_simple_python_score.json", rows, group="live"
    )
    out = _parse(tmp_path, score_dir)
    assert out.primary_pass is False
    assert out.partial_score == 0.0
    assert out.failure_class == "runtime_output_unparseable"


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(
        self,
        command: Sequence[str],
        *,
        cwd: Path | None,
        timeout_sec: int,
        env: Mapping[str, str],
    ) -> BfclCliResult:
        del cwd, timeout_sec, env
        self.calls.append(tuple(command))
        return BfclCliResult(0, "", "", 0.1, tuple(command))


def _copied_config_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = Path(__file__).resolve().parents[2]
    bundle = tmp_path / "bundle"
    shutil.copytree(repo / "config", bundle / "config")
    monkeypatch.setenv("BENCHEVAL_HOME", str(bundle))
    return bundle


def test_manifest_upstream_commit_drift_is_rejected_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _copied_config_bundle(tmp_path, monkeypatch)
    manifest = bundle / "config" / "bfcl-v4-supported-models.yaml"
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    raw["upstream_commit"] = "0" * 40
    manifest.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_SUPPORTED_MODEL,
    )
    runner = _RecordingRunner()
    with pytest.raises(BenchEvalError, match="upstream_commit"):
        run_bfcl_instance(
            plan=plan,
            instance_id="simple_python",
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=runner,
            harness_version=_PINNED_HARNESS_VERSION,
        )
    assert runner.calls == []


def test_harness_package_version_drift_is_rejected_before_launch(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_SUPPORTED_MODEL,
    )
    runner = _RecordingRunner()
    with pytest.raises(BenchEvalError, match="bfcl_eval_version"):
        run_bfcl_instance(
            plan=plan,
            instance_id="simple_python",
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=runner,
            harness_version="bfcl-eval@0.0.0",
        )
    assert runner.calls == []


def test_default_runner_recaptures_installed_version_before_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_SUPPORTED_MODEL,
    )
    monkeypatch.setattr(
        "bencheval.bfcl_native_adapter.bfcl_harness_version",
        lambda: "bfcl-eval@0.0.0",
    )
    # Make the pre-fix bypass safe to reproduce: even if it skips the pin gate,
    # no external ``bfcl`` command can launch from this test process.
    monkeypatch.setenv("PATH", "")
    # The real/default runner resolves the provider credential before the
    # harness pin gate; satisfy that precondition so the recapture assertion
    # below still discriminates the harness-version path.
    monkeypatch.setenv("BYTELLM_API_KEY", "test-credential-placeholder")

    with pytest.raises(BenchEvalError, match="bfcl_eval_version"):
        run_bfcl_instance(
            plan=plan,
            instance_id="simple_python",
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            harness_version=_PINNED_HARNESS_VERSION,
        )


def test_unsupported_model_is_rejected_before_any_harness_launch(tmp_path: Path) -> None:
    # The pinned upstream evaluate path raises ValueError for models outside
    # MODEL_CONFIG_MAPPING; BenchEval must fail before spending a charged
    # generate phase on a model the official scorer will refuse.
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_UNSUPPORTED_MODEL,
    )
    runner = _RecordingRunner()
    with pytest.raises(BenchEvalError, match="not supported"):
        run_bfcl_instance(
            plan=plan,
            instance_id="simple_python",
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=runner,
        )
    assert runner.calls == []


def test_runtime_default_model_is_rejected_before_any_harness_launch(tmp_path: Path) -> None:
    # "runtime-default" cannot be checked against the upstream model map, so it
    # can never be scored by the official evaluate path.
    base_plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_SUPPORTED_MODEL,
    )
    plan = base_plan.model_copy(update={"model_id": "runtime-default"})
    runner = _RecordingRunner()
    with pytest.raises(BenchEvalError, match="not supported"):
        run_bfcl_instance(
            plan=plan,
            instance_id="simple_python",
            artifacts_dir=tmp_path / "artifacts",
            repo_root=tmp_path,
            process_runner=runner,
        )
    assert runner.calls == []
