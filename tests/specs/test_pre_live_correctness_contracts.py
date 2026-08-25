"""RED contracts for the pre-live correctness patch (post-merge peer review).

One contract per accepted finding from the independent review of the merged
Tier-0 control plane:

1. Canonical pass@k eligibility: infrastructure failures are never eligible,
   even when explicit validity fields are absent or contradict the taxonomy.
2. Budget-class envelopes are hard caps: a stricter slice budget is preserved,
   never silently expanded to the class default; B0 is reachable; B3's zero
   defaults mean "no class envelope" and must not clamp the slice to zero.
3. ``rough_regression`` survives planning into the interpretation label.
4. HLE stamps a source-owned (git revision) harness version that satisfies the
   captured-provenance gate, or honestly reports none.
5. Structured preflight artifacts redact secret-shaped reasons/extra values.
6. External-agent instance directories reject symlinks before any write.
7. The credential shim refuses non-loopback binds without explicit opt-in, and
   the pilot passes that opt-in for its deliberate docker-gateway bind.

Positive controls are included so the patch cannot fail closed on honest input.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from bencheval.benchmark_plan import plan_control_plane
from bencheval.benchmark_registry import clear_benchmark_catalog_cache
from bencheval.control_plane_executor import control_plane_interpretation_label
from bencheval.evidence import EvidenceRecord, eligible_for_pass_at_k
from bencheval.exceptions import BenchEvalError
from bencheval.slice_manifest import clear_slice_manifest_cache

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TS = datetime(2026, 8, 6, tzinfo=UTC)
_GIT_REQUIRED = pytest.mark.skipif(shutil.which("git") is None, reason="git required")


def _record(**overrides: object) -> EvidenceRecord:
    base: dict[str, object] = {
        "run_id": "pre-live-contract",
        "task_id": "inst-1",
        "model_id": "provider/model",
        "execution_profile": "E0",
        "primary_pass": False,
        "partial_score": 0.0,
        "cost_usd": 0.0,
        "latency_sec": 1.0,
        "created_at": _TS,
    }
    return EvidenceRecord(**(base | overrides))


# --- 1. Canonical pass@k eligibility ---------------------------------------


def test_infrastructure_failure_rows_are_never_pass_at_k_eligible() -> None:
    infra = _record(failure_class="runtime_launch_failure")
    assert infra.counts_toward_pass_at_k is None
    assert infra.attempt_validity is None

    assert eligible_for_pass_at_k(infra) is False


def test_explicit_eligibility_stamp_cannot_override_infrastructure_failure() -> None:
    stamped = _record(failure_class="runtime_launch_failure", counts_toward_pass_at_k=True)

    assert eligible_for_pass_at_k(stamped) is False


def test_model_side_rows_and_validity_fields_keep_their_meaning() -> None:
    assert eligible_for_pass_at_k(_record(failure_class="model_wrong_solution")) is True
    assert eligible_for_pass_at_k(_record(attempt_validity="invalid")) is False
    assert eligible_for_pass_at_k(_record(attempt_validity="valid")) is True
    assert eligible_for_pass_at_k(_record(counts_toward_pass_at_k=False)) is False
    assert eligible_for_pass_at_k(_record(counts_toward_pass_at_k=True)) is True


def test_infrastructure_failure_taxonomy_has_a_canonical_home() -> None:
    from bencheval.evidence import INFRASTRUCTURE_FAILURE_CLASSES
    from bencheval.live_proof import INFRASTRUCTURE_FAILURE_CLASSES as live_classes

    assert "runtime_launch_failure" in INFRASTRUCTURE_FAILURE_CLASSES
    assert "runtime_output_cap_reached" in INFRASTRUCTURE_FAILURE_CLASSES
    assert "model_wrong_solution" not in INFRASTRUCTURE_FAILURE_CLASSES
    assert live_classes == INFRASTRUCTURE_FAILURE_CLASSES


# --- 2/3. Planning contracts via disposable real config bundles -------------


def _config_bundle(tmp_path: Path) -> Path:
    bundle = tmp_path / "bencheval-bundle"
    shutil.copytree(_REPO_ROOT / "config", bundle / "config")
    return bundle


def _edit_tb_slice(
    bundle: Path,
    *,
    cost: float,
    wall_per_instance: int,
    purpose: str | None = None,
) -> None:
    slice_path = bundle / "config" / "slices" / "terminal-bench-smoke-5.yaml"
    doc = yaml.safe_load(slice_path.read_text(encoding="utf-8"))
    doc["budget"]["max_total_cost_usd"] = cost
    doc["budget"]["max_wall_clock_sec_per_instance"] = wall_per_instance
    if purpose is not None:
        doc["slice"]["purpose"] = purpose
    slice_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def _plan_in_bundle(bundle: Path):
    previous_home = os.environ.get("BENCHEVAL_HOME")
    os.environ["BENCHEVAL_HOME"] = str(bundle)
    try:
        clear_benchmark_catalog_cache()
        clear_slice_manifest_cache()
        return plan_control_plane(
            benchmark_id="terminal-bench",
            slice_id="smoke-5",
            runtime_id="claude-code",
            model_id="kimi-k2.7-code",
        )
    finally:
        clear_benchmark_catalog_cache()
        clear_slice_manifest_cache()
        if previous_home is None:
            os.environ.pop("BENCHEVAL_HOME", None)
        else:
            os.environ["BENCHEVAL_HOME"] = previous_home


# Semantics under test (round-1 F005 contract): class values are per-instance
# wall / run-total cost classification ceilings; the slice's own envelope is
# always the effective cap. Per-instance and run-total wall are separate
# RunPlan fields; per-instance adapters consume the per-instance field directly
# — dividing the run total again is the defect this section locks out — while
# aggregate harnesses (GPQA/HLE) bound their single subprocess chain with the
# run total (round-3 F005).
def test_slice_budget_tighter_than_class_default_is_not_silently_expanded(
    tmp_path: Path,
) -> None:
    bundle = _config_bundle(tmp_path)
    _edit_tb_slice(bundle, cost=0.10, wall_per_instance=120)  # B1 ceilings: 0.25 / 180s

    plan = _plan_in_bundle(bundle)

    assert plan.budget_class == "B1"
    assert plan.max_cost_usd == pytest.approx(0.10)
    assert plan.max_wall_clock_sec_per_instance == 120
    assert plan.max_wall_clock_sec == 120 * len(plan.instances)


def test_budget_class_b0_is_reachable_and_caps_like_any_other_envelope(
    tmp_path: Path,
) -> None:
    bundle = _config_bundle(tmp_path)
    _edit_tb_slice(bundle, cost=0.04, wall_per_instance=50)  # B0 ceilings: 0.05 / 60s

    plan = _plan_in_bundle(bundle)

    assert plan.budget_class == "B0"
    assert plan.max_cost_usd == pytest.approx(0.04)
    assert plan.max_wall_clock_sec_per_instance == 50
    assert plan.max_wall_clock_sec == 50 * len(plan.instances)


def test_unbounded_budget_class_preserves_slice_values(tmp_path: Path) -> None:
    # Positive control: B3 declares no class envelope (zero defaults); the slice speaks.
    bundle = _config_bundle(tmp_path)
    _edit_tb_slice(bundle, cost=5.0, wall_per_instance=400)

    plan = _plan_in_bundle(bundle)

    assert plan.budget_class == "B3"
    assert plan.max_cost_usd == pytest.approx(5.0)
    assert plan.max_wall_clock_sec_per_instance == 400
    assert plan.max_wall_clock_sec == 400 * len(plan.instances)


def test_rough_regression_purpose_is_preserved_end_to_end(tmp_path: Path) -> None:
    bundle = _config_bundle(tmp_path)
    _edit_tb_slice(bundle, cost=1.0, wall_per_instance=240, purpose="rough_regression")

    plan = _plan_in_bundle(bundle)

    assert plan.comparison_validity == "rough_regression"
    assert control_plane_interpretation_label(plan) == "rough_regression"


# --- 4. HLE source-owned harness version ------------------------------------
#
# SUBSTITUTE_JUSTIFICATION (also covers the section-9 HLE provenance tests)
# - substitute: disposable git repository with two comment-only marker scripts
#   created by `_git_init_with_commit`, plus a test-authored HleHarnessPin
#   naming that repository's revision and content digests
# - replaces: the official CAIS HLE checkout (github.com/centerforaisafety/hle)
#   and the shipped upstream pin
# - necessity: the assertions target provenance-capture mechanics (pin
#   commit/content equality, toplevel identity, dirty state, symlink
#   rejection), which require controlled git states a network clone cannot
#   deterministically produce in a test run; injecting the pin exercises the
#   identical verification path the shipped constant takes
# - real-option: cloning the real HLE repo — network-dependent, single fixed
#   revision, and cannot produce the dirty/symlinked fault states on demand
# - proof-limit: proves provenance mechanics only; does not prove the real HLE
#   harness executes or scores, or that the shipped pin matches a live checkout
# - real-proof: BLOCKED — live HLE lane on dev-box with the official checkout
#   (operator provisioning required); all HLE results remain diagnostic only


def _git_init_with_commit(home: Path) -> str:
    subprocess.run(["git", "init"], cwd=home, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=home, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=spec@example.test", "-c", "user.name=spec", "commit", "-m", "i"],
        cwd=home,
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=home,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _synthetic_pin(home: Path, sha: str):
    import hashlib

    from bencheval.hle_adapter import HleHarnessPin

    digests = {}
    for name in ("run_model_predictions.py", "run_judge_results.py"):
        digests[name] = hashlib.sha256((home / "hle_eval" / name).read_bytes()).hexdigest()
    return HleHarnessPin(commit=sha, script_sha256=digests)


@_GIT_REQUIRED
def test_hle_captures_git_revision_as_harness_version(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _hle_harness_version
    from bencheval.provenance_gates import is_captured_harness_version

    home = tmp_path / "hle-checkout"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# official script\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# official script\n", encoding="utf-8")
    sha = _git_init_with_commit(home)
    pin = _synthetic_pin(home, sha)

    version = _hle_harness_version(home, pin=pin)

    assert version is not None
    assert sha in version
    assert is_captured_harness_version(version)


@_GIT_REQUIRED
def test_hle_does_not_borrow_a_foreign_repos_revision(tmp_path: Path) -> None:
    """A git root without the official HLE scripts is not an HLE checkout.

    With ``BENCHEVAL_HLE_HOME`` unset the adapter falls back to the cwd; if that
    cwd is an unrelated git root (e.g. the BenchEval repo itself), attributing
    its revision would fabricate provenance. Marker files must gate attribution.
    """
    from bencheval.hle_adapter import _hle_harness_version

    foreign = tmp_path / "foreign-repo"
    foreign.mkdir()
    (foreign / "README.md").write_text("not hle\n", encoding="utf-8")
    _git_init_with_commit(foreign)

    assert _hle_harness_version(foreign) is None


def test_hle_harness_version_is_honestly_absent_without_source_control(
    tmp_path: Path,
) -> None:
    from bencheval.hle_adapter import _hle_harness_version

    plain = tmp_path / "not-a-checkout"
    plain.mkdir()

    assert _hle_harness_version(plain) is None


# --- 5. Preflight redaction ---------------------------------------------------


def test_preflight_report_redacts_secret_shaped_reasons_and_extra(tmp_path: Path) -> None:
    from bencheval.preflight_report import write_preflight_report

    out = write_preflight_report(
        output_path=tmp_path / "preflight.json",
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="provider/model",
        ok=False,
        reasons=[
            "harbor doctor failed via http://alice:s3cr3t-pw@proxy.corp:8118",
            "OPENAI_API_KEY=sk-abcd1234efgh5678 present in environment",
        ],
        extra={
            "stderr": (
                "Authorization: Bearer "
                "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r"
            ),
            "note": "port 8080 closed",
        },
    )
    text = out.read_text(encoding="utf-8")

    assert "s3cr3t-pw" not in text
    assert "sk-abcd1234efgh5678" not in text
    assert "eyJhbGciOiJIUzI1NiJ9" not in text
    assert "port 8080 closed" in text


# --- 6. External-agent symlink guard ------------------------------------------
#
# SUBSTITUTE_JUSTIFICATION
# - substitute: tripwire `process_runner` that raises AssertionError when reached
# - replaces: the real external-agent CLI subprocess (momo)
# - necessity: the assertion targets the path-guard boundary only; the guard must
#   raise before any process is launched, and launching a real agent CLI is neither
#   safe nor deterministic in a test environment
# - real-option: executing the real momo CLI against a disposable instance dir —
#   cannot prove the guard ordering (runner is only reached when the guard is absent)
#   and would perform uncontrolled outward effects
# - proof-limit: proves only that symlinked instance dirs are rejected before writes
#   and process launch; it does not prove agent execution or scoring
# - real-proof: a live admitted external-agent lane (none admitted yet — BLOCKED on
#   provisioning) plus inspection of this guard in code review


def _agent_plan():
    return plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id=None,
        agent_id="momo",
        model_id="kimi-k2.7-code",
    )


def _tripwire(command: object, *, cwd: object, timeout_sec: object) -> object:
    raise AssertionError("process runner must not be reached")


def test_external_agent_rejects_symlinked_instance_directory(tmp_path: Path) -> None:
    from bencheval.external_agent_adapter import run_external_agent_instance

    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "inst-1").symlink_to(outside, target_is_directory=True)

    with pytest.raises(BenchEvalError, match="symlink"):
        run_external_agent_instance(
            plan=_agent_plan(),
            instance_id="inst-1",
            artifacts_dir=root,
            repo_root=tmp_path,
            process_runner=_tripwire,
        )
    assert list(outside.iterdir()) == []


def test_external_agent_rejects_a_preexisting_regular_file(tmp_path: Path) -> None:
    from bencheval.external_agent_adapter import run_external_agent_instance

    root = tmp_path / "artifacts"
    root.mkdir()
    (root / "inst-1").write_text("squatted\n", encoding="utf-8")

    with pytest.raises(BenchEvalError, match="not a directory"):
        run_external_agent_instance(
            plan=_agent_plan(),
            instance_id="inst-1",
            artifacts_dir=root,
            repo_root=tmp_path,
            process_runner=_tripwire,
        )


def test_external_agent_accepts_a_real_instance_directory(tmp_path: Path) -> None:
    from bencheval.external_agent_adapter import run_external_agent_instance

    root = tmp_path / "artifacts"

    with pytest.raises(AssertionError, match="must not be reached"):
        run_external_agent_instance(
            plan=_agent_plan(),
            instance_id="inst-1",
            artifacts_dir=root,
            repo_root=tmp_path,
            process_runner=_tripwire,
        )
    assert (root / "inst-1").is_dir()


# --- 7. Shim bind hygiene -------------------------------------------------------


def test_shim_remote_bind_requires_explicit_opt_in() -> None:
    from bencheval.anthropic_role_shim import _validate_bind_host

    with pytest.raises(BenchEvalError, match="remote"):
        _validate_bind_host("0.0.0.0", allow_remote_bind=False)
    with pytest.raises(BenchEvalError, match="remote"):
        _validate_bind_host("172.17.0.1", allow_remote_bind=False)
    _validate_bind_host("172.17.0.1", allow_remote_bind=True)


def test_shim_loopback_bind_needs_no_opt_in() -> None:
    from bencheval.anthropic_role_shim import _validate_bind_host

    _validate_bind_host("127.0.0.1", allow_remote_bind=False)
    _validate_bind_host("localhost", allow_remote_bind=False)
    _validate_bind_host("::1", allow_remote_bind=False)


def test_shim_loopback_aliases_are_not_misread_as_remote() -> None:
    from bencheval.anthropic_role_shim import _validate_bind_host

    _validate_bind_host("localhost.", allow_remote_bind=False)
    _validate_bind_host("::ffff:127.0.0.1", allow_remote_bind=False)


def test_pilot_opts_in_to_remote_shim_bind_explicitly() -> None:
    script = (_REPO_ROOT / "scripts" / "run-live-pilot-matrix.sh").read_text(encoding="utf-8")

    assert "--allow-remote-bind" in script


# ===========================================================================
# Round-1 review contracts (qa-review REJECTED findings F001–F009)
# ===========================================================================


# --- 8. F001: legacy v0.2 failure_labels veto pass@k eligibility ------------


def test_v02_legacy_infrastructure_label_is_never_eligible() -> None:
    row = _record(failure_labels=["runtime_launch_failure"])

    assert eligible_for_pass_at_k(row) is False


def test_explicit_stamp_cannot_override_a_legacy_infrastructure_label() -> None:
    row = _record(
        failure_labels=["runtime_launch_failure"],
        counts_toward_pass_at_k=True,
    )

    assert eligible_for_pass_at_k(row) is False


def _comparison_row(runtime_id: str, **overrides: object) -> EvidenceRecord:
    base: dict[str, object] = {
        "benchmark_id": "terminal-bench",
        "benchmark_version": "tb@2.1",
        "slice_id": "smoke-5",
        "adapter_id": "terminal-bench-harbor",
        "harness_kind": "harbor",
        "harness_version": "harbor@2.1.0",
        "runtime_id": runtime_id,
        "runtime_version": f"{runtime_id}@1.0.0",
        "runtime_config_hash": "sha256:" + "a" * 64,
        "provider_id": "bytellm",
        "provider_config_hash": "sha256:" + "b" * 64,
        "instance_id": "inst-1",
    }
    return _record(**(base | overrides))


def test_runtime_comparison_fails_closed_on_legacy_infrastructure_rows() -> None:
    from bencheval.runtime_compare import assess_runtime_comparison_validity

    baseline = [_comparison_row("claude-code", failure_labels=["runtime_launch_failure"])]
    current = [_comparison_row("codex-cli")]

    verdict = assess_runtime_comparison_validity(baseline, current)

    assert verdict.valid is False
    assert any("zero eligible attempts" in reason for reason in verdict.reasons)


def test_model_label_failure_labels_do_not_veto_eligibility() -> None:
    # Positive control: non-infrastructure legacy labels stay eligible.
    row = _record(failure_labels=["model_wrong_solution"])

    assert eligible_for_pass_at_k(row) is True


# --- 9. F002: HLE provenance binds the executed script content --------------
#
# The synthetic HLE repositories in this section are covered by the
# SUBSTITUTE_JUSTIFICATION at section 4 above (same substitute and boundary).


@_GIT_REQUIRED
def test_hle_dirty_worktree_changes_the_captured_identity(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _hle_harness_version
    from bencheval.provenance_gates import is_captured_harness_version

    home = tmp_path / "hle-checkout"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# official script\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# official script\n", encoding="utf-8")
    sha = _git_init_with_commit(home)
    pin = _synthetic_pin(home, sha)

    clean = _hle_harness_version(home, pin=pin)
    assert clean is not None and is_captured_harness_version(clean)
    assert "-dirty" not in clean

    # An untracked local file stamps the captured identity as mutable.
    (home / "notes.txt").write_text("local edits\n", encoding="utf-8")
    dirty = _hle_harness_version(home, pin=pin)
    assert dirty is not None
    assert dirty != clean
    assert "-dirty" in dirty

    # Drift in a pinned executed script breaks capture entirely.
    (eval_dir / "run_model_predictions.py").write_text("# tampered\n", encoding="utf-8")
    assert _hle_harness_version(home, pin=pin) is None


@_GIT_REQUIRED
def test_hle_rejects_scripts_symlinked_outside_the_checkout(tmp_path: Path) -> None:
    from bencheval.hle_adapter import _hle_harness_version

    home = tmp_path / "hle-checkout"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_judge_results.py").write_text("# official script\n", encoding="utf-8")
    outside = tmp_path / "outside" / "run_model_predictions.py"
    outside.parent.mkdir()
    outside.write_text("# foreign executable\n", encoding="utf-8")
    (eval_dir / "run_model_predictions.py").symlink_to(outside)
    _git_init_with_commit(home)

    assert _hle_harness_version(home) is None


@_GIT_REQUIRED
def test_hle_symlink_escape_is_rejected_even_after_content_changes(tmp_path: Path) -> None:
    # Reviewer probe: committed symlinks whose external targets later change
    # must never receive a captured harness identity.
    from bencheval.hle_adapter import _hle_harness_version

    home = tmp_path / "hle-checkout"
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    for name in ("run_model_predictions.py", "run_judge_results.py"):
        target = outside_dir / name
        target.write_text("# v1\n", encoding="utf-8")
        (eval_dir / name).symlink_to(target)
    _git_init_with_commit(home)

    assert _hle_harness_version(home) is None
    (outside_dir / "run_model_predictions.py").write_text("# v2 tampered\n", encoding="utf-8")
    assert _hle_harness_version(home) is None


def _plain_hle_home(home: Path) -> Path:
    eval_dir = home / "hle_eval"
    eval_dir.mkdir(parents=True)
    (eval_dir / "run_model_predictions.py").write_text("# official predict\n", encoding="utf-8")
    (eval_dir / "run_judge_results.py").write_text("# official judge\n", encoding="utf-8")
    return home


def test_hle_dataset_defaults_to_pinned_repo_and_refuses_mirror_divergence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Contract (pinned OFFICIAL dataset identity, product option (a) after the
    # review-F002 mirror revert): the catalog ``identity:`` block binds the
    # launched dataset to the official ``cais/hle`` repo at an immutable
    # revision. BENCHEVAL_HLE_DATASET may only restate it exactly; the reverted
    # third-party mirror (or any other value) is source drift and fails closed
    # before launch.
    from bencheval.hle_adapter import build_hle_run_commands

    home = _plain_hle_home(tmp_path / "hle-home")
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    monkeypatch.delenv("BENCHEVAL_HLE_DATASET", raising=False)
    default_cmds = build_hle_run_commands(
        plan=plan,
        max_samples=2,
        artifacts_dir=tmp_path / "artifacts",
        run_id="ds-default",
    )
    assert "cais/hle" in default_cmds[0]
    assert "cais/hle" in default_cmds[1]

    # Restating the pinned repo is accepted (identity unchanged).
    monkeypatch.setenv("BENCHEVAL_HLE_DATASET", "cais/hle")
    restated_cmds = build_hle_run_commands(
        plan=plan,
        max_samples=2,
        artifacts_dir=tmp_path / "artifacts",
        run_id="ds-restated",
    )
    assert "cais/hle" in restated_cmds[0]

    # The reverted mirror is drift and fails closed before any command build.
    from bencheval.exceptions import BenchEvalError

    monkeypatch.setenv("BENCHEVAL_HLE_DATASET", "macabdul9/hle_text_only")
    with pytest.raises(BenchEvalError, match="diverges"):
        build_hle_run_commands(
            plan=plan,
            max_samples=2,
            artifacts_dir=tmp_path / "artifacts",
            run_id="ds-mirror",
        )

    # A local parquet mirror is drift too.
    mirror = str(tmp_path / "hle-test.parquet")
    monkeypatch.setenv("BENCHEVAL_HLE_DATASET", mirror)
    with pytest.raises(BenchEvalError, match="diverges"):
        build_hle_run_commands(
            plan=plan,
            max_samples=2,
            artifacts_dir=tmp_path / "artifacts",
            run_id="ds-override",
        )


def test_hle_dataset_source_is_stamped_into_evidence_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The launched dataset source is never hidden from evidence. With the
    # official pin restored (product option (a) after the review-F002 mirror
    # revert), the stamped source is the pinned catalog repo ``cais/hle``.
    from bencheval.hle_adapter import HleCliResult, run_hle_slice

    home = _plain_hle_home(tmp_path / "hle-home")
    monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(home))
    monkeypatch.delenv("BENCHEVAL_HLE_DATASET", raising=False)
    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )

    def _observer(
        command: object,
        *,
        cwd: object,
        timeout_sec: object,
        env: object = None,
    ) -> object:
        return HleCliResult(1, "", "stop-after-observe", 0.1, tuple(command))

    outcomes = run_hle_slice(
        plan=plan,
        artifacts_dir=tmp_path / "artifacts",
        repo_root=tmp_path,
        process_runner=_observer,
        run_id="ds-metadata",
    )

    assert outcomes[0].adapter_metadata["hle_dataset"] == "cais/hle"


# --- 10. F003: post-launch path swap cannot redirect BenchEval log writes ----
#
# The `_swapper` runner below is covered by the section-6 SUBSTITUTE_JUSTIFICATION:
# it replaces the real agent CLI with a boundary tripwire that mutates the
# instance path instead of launching a process. proof-limit: proves only that
# BenchEval-owned log writes stay anchored to the approved directory inode and
# that the attempt fails closed; it does not prove agent execution or scoring.


def test_external_agent_cannot_redirect_post_launch_log_writes(tmp_path: Path) -> None:
    from bencheval.exceptions import AdapterFailureError
    from bencheval.external_agent_adapter import (
        ExternalAgentCliResult,
        run_external_agent_instance,
    )

    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "artifacts"
    root.mkdir()

    def _swapper(command: object, *, cwd: object, timeout_sec: object) -> object:
        target = root / "inst-1"
        shutil.rmtree(target)
        target.symlink_to(outside, target_is_directory=True)
        return ExternalAgentCliResult(
            returncode=0,
            stdout="agent stdout",
            stderr="agent stderr",
            latency_sec=0.1,
            command=tuple(command),
        )

    with pytest.raises(AdapterFailureError, match="replaced by symlink"):
        run_external_agent_instance(
            plan=_agent_plan(),
            instance_id="inst-1",
            artifacts_dir=root,
            repo_root=tmp_path,
            process_runner=_swapper,
        )

    # No BenchEval-owned log escaped through the swapped symlink.
    assert list(outside.iterdir()) == []


# --- 11. F004: preflight public mode is safe to share as a whole -------------


def test_preflight_public_mode_scrubs_the_entire_payload(tmp_path: Path) -> None:
    import socket

    from bencheval.preflight_report import write_preflight_report

    out = write_preflight_report(
        output_path=tmp_path / "preflight-public.json",
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="sk-abcd1234efgh5678/model",
        ok=False,
        doctor_backend="harbor via http://alice:s3cr3t-pw@proxy.corp:8118",
        reasons=["OPENAI_API_KEY=sk-abcd1234efgh5678 rejected"],
        extra={"api_key=sk-abcd1234efgh5678": "value", "note": "port 8080 closed"},
        visibility="public",
    )
    text = out.read_text(encoding="utf-8")

    assert socket.gethostname() not in text
    assert "sk-abcd1234efgh5678" not in text
    assert "s3cr3t-pw" not in text
    assert "port 8080 closed" in text
    assert '"visibility": "public"' in text
    # Public mode omits the hostname key entirely (not a null placeholder).
    assert '"host"' not in text


def test_preflight_private_mode_keeps_local_diagnostic_detail(tmp_path: Path) -> None:
    import socket

    from bencheval.preflight_report import write_preflight_report

    # Positive control: private artifacts keep operator-local detail (host), but
    # reasons/extra are still scrubbed — they carry subprocess/doctor output.
    out = write_preflight_report(
        output_path=tmp_path / "preflight-private.json",
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="provider/model",
        ok=True,
        visibility="private",
    )
    text = out.read_text(encoding="utf-8")

    assert socket.gethostname() in text
    assert '"visibility": "private"' in text


# --- 12. F007: aggregate model-only adapters label unmeasured cost honestly --
#
# SUBSTITUTE_JUSTIFICATION
# - substitute: synthetic Inspect eval log written by the injected runner below
# - replaces: live Inspect eval log on disk
# - necessity: exercise the control-plane GPQA wiring without live Inspect,
#   credentials, or the dataset download
# - real-option: live `inspect eval`; requires provider credentials + dataset
# - proof-limit: parser/label diagnostic only; does not prove live GPQA scoring
# - real-proof: BLOCKED until the live GPQA pilot (operator provisioning)


def test_gpqa_labels_cost_as_unmeasured_in_plan_and_evidence(tmp_path: Path) -> None:
    import json

    from bencheval.control_plane_executor import execute_control_plane_run
    from bencheval.evidence import read_evidence_jsonl
    from bencheval.gpqa_adapter import GpqaCliResult

    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id="kimi-k2.7-code",
    )
    assert "max_cost_usd_unenforced_estimate" in plan.caveats

    def fake(command: object, *, cwd: object, timeout_sec: object, env: object = None) -> object:
        log_dir = Path(command[command.index("--log-dir") + 1])
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "done.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "status": "success",
                    "eval": {
                        "created": "2024-01-01T00:00:00+00:00",
                        "task": "gpqa_diamond",
                        "task_id": "fixture",
                        "model": command[command.index("--model") + 1],
                    },
                    "results": {
                        "total_samples": 2,
                        "completed_samples": 2,
                        "scores": [
                            {
                                "name": "choice",
                                "scorer": "choice",
                                "metrics": {"accuracy": {"name": "accuracy", "value": 1.0}},
                            },
                        ],
                    },
                },
            ),
            encoding="utf-8",
        )
        return GpqaCliResult(0, f"Log: {log_dir / 'done.json'}\n", "", 0.05, tuple(command))

    evidence = tmp_path / "e.jsonl"
    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        gpqa_process_runner=fake,
        run_id="gpqa-cost-label",
    )
    rows = read_evidence_jsonl(evidence)

    assert len(rows) == 1
    assert rows[0].cost_usd == 0.0
    assert rows[0].native_score is not None
    assert rows[0].native_score["cost_basis"] == "unmeasured_no_provider_metering"


def test_external_agent_normal_path_writes_log_contents(tmp_path: Path) -> None:
    from bencheval.external_agent_adapter import (
        ExternalAgentCliResult,
        run_external_agent_instance,
    )

    root = tmp_path / "artifacts"

    def _ok(command: object, *, cwd: object, timeout_sec: object) -> object:
        return ExternalAgentCliResult(
            returncode=1,
            stdout="agent stdout body",
            stderr="agent stderr body",
            latency_sec=0.1,
            command=tuple(command),
        )

    run_external_agent_instance(
        plan=_agent_plan(),
        instance_id="inst-1",
        artifacts_dir=root,
        repo_root=tmp_path,
        process_runner=_ok,
    )

    capture = root.parent / f"{root.name}.capture" / "inst-1"
    assert (capture / "stdout.log").read_text(encoding="utf-8") == "agent stdout body"
    assert (capture / "stderr.log").read_text(encoding="utf-8") == "agent stderr body"
