"""Round-13 RED regression: BFCL cost_basis honesty stamp (review F005).

BFCL outcomes carry ``cost_usd=0.0`` because the ``bfcl`` CLI reports no cost;
without the ``cost_basis`` stamp a reader cannot distinguish "no metering" from
"zero spend". The stamp must survive into the EvidenceRecord and the PRIVATE
run-bundle export; the PUBLIC bundle redacts ``native_score`` wholesale by
design (pinned here so the retention claim stays precise).

SUBSTITUTE_JUSTIFICATION
- substitute: injected ``process_runner`` callable (subprocess boundary)
- replaces: the real ``bfcl`` CLI subprocess
- necessity: a real launch is a charged external effect, and the assertion is
  which metadata BenchEval stamps on the outcome, not bfcl behavior; the
  fabricated score artifact is real tmp_path content in the pinned layout
- real-option: live dev-box run of ``bfcl generate`` → ``bfcl evaluate``
- proof-limit: proves the stamp and its export retention only, not bfcl
  execution, scorer correctness, or live readiness
- real-proof: run-20260824-045622-854659-a46ae44d (registered `passed` real
  lifecycle; the diagnostic-labeled run-20260824-040631-228703-4756f857 ran the
  same lifecycle earlier)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import BfclCliResult
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.evidence import read_evidence_jsonl
from bencheval.run_bundle import export_run_bundle

_MODEL = "gpt-5.2-2025-12-11"
_BFCL_IDENTITY = "bfcl-v4@bfcl-eval-2026.3.23+data-79bb46df7e8c7d7b"


def _runner(
    command: Sequence[str],
    *,
    cwd: Path | None,
    timeout_sec: int,
    env: Mapping[str, str],
) -> BfclCliResult:
    del cwd, timeout_sec, env
    call = tuple(command)
    if call[1] == "evaluate":
        score_root = Path(call[list(call).index("--score-dir") + 1])
        score_file = score_root / _MODEL / "non_live" / "BFCL_v4_simple_python_score.json"
        score_file.parent.mkdir(parents=True, exist_ok=True)
        score_file.write_text(
            '{"accuracy": 1.0, "correct_count": 1, "total_count": 1}\n',
            encoding="utf-8",
        )
    return BfclCliResult(0, "", "", 0.1, call)


def _bfcl_evidence(tmp_path: Path) -> Path:
    base_plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id=_MODEL,
    )
    plan = base_plan.model_copy(update={"instances": base_plan.instances[:1]})
    evidence = tmp_path / "evidence.jsonl"
    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "artifacts",
        run_id="bfcl-cost-basis",
        bfcl_process_runner=_runner,
        bfcl_benchmark_identity=_BFCL_IDENTITY,
    )
    return evidence


def test_bfcl_evidence_stamps_unmeasured_cost_basis(tmp_path: Path) -> None:
    evidence = _bfcl_evidence(tmp_path)

    rows = read_evidence_jsonl(evidence)

    assert len(rows) == 1
    assert rows[0].cost_usd == 0.0
    assert rows[0].native_score is not None
    assert rows[0].native_score["cost_basis"] == "unmeasured_no_provider_metering"


def test_bfcl_cost_basis_survives_private_bundle_export(tmp_path: Path) -> None:
    evidence = _bfcl_evidence(tmp_path)

    export_run_bundle(
        evidence_path=evidence,
        output_dir=tmp_path / "bundle-private",
        redaction="private",
    )

    exported = read_evidence_jsonl(tmp_path / "bundle-private" / "evidence.jsonl")
    assert len(exported) == 1
    assert exported[0].native_score is not None
    assert exported[0].native_score["cost_basis"] == "unmeasured_no_provider_metering"


def test_public_bundle_redaction_still_strips_native_score(tmp_path: Path) -> None:
    """Public bundles zero ``native_score`` by design; the stamp must not leak."""
    evidence = _bfcl_evidence(tmp_path)

    export_run_bundle(
        evidence_path=evidence,
        output_dir=tmp_path / "bundle-public",
        redaction="public",
    )

    exported = read_evidence_jsonl(tmp_path / "bundle-public" / "evidence.jsonl")
    assert len(exported) == 1
    assert exported[0].native_score == {}
    assert "cost_basis" not in (tmp_path / "bundle-public" / "evidence.jsonl").read_text(
        encoding="utf-8",
    )
