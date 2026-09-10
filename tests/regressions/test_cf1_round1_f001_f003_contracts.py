"""CF1 review round 1 (F001–F003): retained-snapshot compatibility, upstream API-name binding,
and BFCL-only diagnostic policy.

SUBSTITUTE_JUSTIFICATION
- substitute: the retained CF1.3 proofs, lock, and report copied verbatim into
  ``tests/fixtures/exposure/cf13`` (real dev-box artifacts, unchanged bytes);
  a pinned-shaped substitute registry text and package for the mismatch cases
  (`_REGISTRY_TEXT`, `_package` from the registration contracts); in-memory
  registries and temporary provider catalogs through the real loaders
- replaces: the live Ollama Cloud runs and the installed bfcl-eval distribution
- necessity: the compatibility regression must load the exact retained bytes
  without regenerating them; a mismatched upstream key must be forced without a
  charged call or a mutated site-packages
- real-option: the fixture is the real proof; the upstream-registry check also
  runs against the installed package where bfcl-eval is present (dev-box)
- proof-limit: proves loader/report compatibility, the shared binding check,
  and planner classification only
- real-proof: CF1.3 runs ccfbce2e / 84ea6c6f / 21f44c90 (2026-09-08)
- covered tests: every test in this module
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.bfcl_native_adapter import bfcl_pinned_harness_version, run_bfcl_instance
from bencheval.bfcl_package import upstream_registration, verify_upstream_binding
from bencheval.doctor import bfcl_model_support_check
from bencheval.domain import RunPlan
from bencheval.exceptions import BenchEvalError
from bencheval.exposure_report import verify_exposure_study_lock
from bencheval.model_binding import (
    ModelBinding,
    canonical_sha256,
    model_binding_sha256,
    resolve_model_binding,
)
from tests.specs.test_bfcl_config_registration_contracts import (
    _REGISTRY_TEXT,
    _package,
    _runner,
)
from tests.specs.test_config_model_binding_contracts import (
    _CANDIDATE,
    _QWEN_ENTRY,
    _QWEN_ID,
    _providers,
    _registry,
)

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "exposure" / "cf13"
_UPSTREAM_FC: dict[str, object] = {
    "id": "gpt-5.2-2025-12-11-FC",
    "family": "openai",
    "display_name": "GPT 5.2 FC (upstream key)",
    "provider_route": "bytellm",
    "api_model": "gpt-5.2-2025-12-11",
    "backend_bindings": {"bfcl": {"mode": "upstream"}},
}


# --- F001 --------------------------------------------------------------------------


def test_retained_cf1_snapshots_keep_their_digests_after_schema_extension() -> None:
    for name in ("canonical/run-plan.json", "candidate/run-plan.json", "gpt-oss-run-plan.json"):
        payload = json.loads((_FIXTURE / name).read_text(encoding="utf-8"))
        snapshot = payload["model_binding_snapshot"]
        assert "display_name" not in snapshot["bfcl"]  # retained before provenance fields existed
        binding = ModelBinding.model_validate(snapshot)
        assert binding.sha256 == snapshot["sha256"] == model_binding_sha256(binding)
        assert RunPlan.model_validate(payload).model_binding_snapshot == binding
    # A freshly resolved binding carries provenance and therefore a new digest;
    # the retained one is not silently re-labelled.
    fresh = resolve_model_binding(_QWEN_ID)
    retained = json.loads((_FIXTURE / "canonical/run-plan.json").read_text())[
        "model_binding_snapshot"
    ]["sha256"]
    assert fresh.bfcl is not None and fresh.bfcl.display_name is not None
    assert fresh.sha256 != retained


def test_retained_cf1_lock_reproduces_the_report_bytes_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied = tmp_path / "copied"
    shutil.copytree(_FIXTURE / "canonical", copied / "canonical")
    shutil.copytree(_FIXTURE / "candidate", copied / "candidate")
    shutil.copy2(_FIXTURE / "lock.json", copied / "lock.json")
    monkeypatch.chdir(copied)
    verified = verify_exposure_study_lock(
        None,
        lock_path=copied / "lock.json",
        canonical_proof=copied / "canonical",
        candidate_proof=copied / "candidate",
        output=copied / "reproduced.json",
    )
    assert verified["ok"] is True
    assert (copied / "reproduced.json").read_bytes() == (_FIXTURE / "report.json").read_bytes()
    lock = json.loads((_FIXTURE / "lock.json").read_text(encoding="utf-8"))
    assert verified["report_sha256"] == lock["report_sha256"]
    assert lock["registration_sha256"].startswith("sha256:05b2da63")


# --- F002 --------------------------------------------------------------------------


def test_upstream_registration_is_read_from_the_pinned_registry() -> None:
    entry = upstream_registration(_REGISTRY_TEXT, "gpt-5.2-2025-12-11-FC")
    assert entry.model_name == "gpt-5.2-2025-12-11"
    assert entry.handler_class == "OpenAICompletionsHandler"
    assert entry.is_fc_model is True and entry.underscore_to_dot is False
    with pytest.raises(BenchEvalError, match="not a pinned registration"):
        upstream_registration(_REGISTRY_TEXT, "nope")


def test_upstream_binding_must_launch_the_confirmed_api_model(tmp_path: Path) -> None:
    catalog = _providers(tmp_path)
    good = resolve_model_binding(
        "gpt-5.2-2025-12-11-FC", models=_registry(_UPSTREAM_FC), providers=catalog
    )
    assert verify_upstream_binding(good, _REGISTRY_TEXT).model_name == "gpt-5.2-2025-12-11"
    mismatched = resolve_model_binding(
        "gpt-5.2-2025-12-11-FC",
        models=_registry({**_UPSTREAM_FC, "api_model": "qwen3.5:397b"}),
        providers=catalog,
    )
    with pytest.raises(BenchEvalError, match="not the confirmed api_model"):
        verify_upstream_binding(mismatched, _REGISTRY_TEXT)
    # A legacy FC row without api_model would confirm the logical id; the pinned
    # key launches a different vendor name, so it is refused too.
    legacy = resolve_model_binding(
        "gpt-5.2-2025-12-11-FC",
        models=_registry({k: v for k, v in _UPSTREAM_FC.items() if k != "api_model"}),
        providers=catalog,
    )
    with pytest.raises(BenchEvalError, match="not the confirmed api_model"):
        verify_upstream_binding(legacy, _REGISTRY_TEXT)


def test_doctor_and_launch_share_the_upstream_api_name_check(tmp_path: Path) -> None:
    catalog = _providers(tmp_path)
    ok = bfcl_model_support_check(
        "gpt-5.2-2025-12-11-FC", models=_registry(_UPSTREAM_FC), registry_text=_REGISTRY_TEXT
    )
    assert ok.status == "pass" and "gpt-5.2-2025-12-11" in ok.message
    bad = bfcl_model_support_check(
        "gpt-5.2-2025-12-11-FC",
        models=_registry({**_UPSTREAM_FC, "api_model": "qwen3.5:397b"}),
        registry_text=_REGISTRY_TEXT,
    )
    assert bad.status == "fail" and "not the confirmed api_model" in bad.message

    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="tool-order-canonical-plumbing-2",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11-FC",
        model_registry=_registry({**_UPSTREAM_FC, "api_model": "qwen3.5:397b"}),
        provider_catalog=catalog,
    )
    assert plan.model_binding_snapshot is not None
    assert plan.model_binding_snapshot.api_model == "qwen3.5:397b"
    envs: list[dict[str, str]] = []
    with pytest.raises(BenchEvalError, match="not the confirmed api_model"):
        run_bfcl_instance(
            plan=plan,
            instance_id="multiple_19",
            artifacts_dir=tmp_path / "art",
            repo_root=tmp_path,
            process_runner=_runner(envs),
            harness_version=bfcl_pinned_harness_version(),
            package_source=_package(tmp_path / "site"),
        )
    assert envs == []


# --- F003 --------------------------------------------------------------------------


def test_bfcl_configuration_does_not_change_other_adapters_classification(
    tmp_path: Path,
) -> None:
    from bencheval.application.dto import PlanRequestDTO
    from bencheval.application.operations import OperatorOperations

    catalog = _providers(tmp_path)
    with_bfcl = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id=_QWEN_ID,
        model_registry=_registry(_QWEN_ENTRY, _CANDIDATE),
        provider_catalog=catalog,
    )
    stripped = {k: v for k, v in _QWEN_ENTRY.items() if k != "backend_bindings"}
    without_bfcl = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id=_QWEN_ID,
        model_registry=_registry(stripped, _CANDIDATE),
        provider_catalog=catalog,
    )
    assert with_bfcl.comparison_validity == without_bfcl.comparison_validity == "adapter_smoke"
    assert with_bfcl.diagnostic is False
    # The configured-registration diagnostic exception is BFCL-only: the
    # executable GPQA row still refuses diagnostic mode for this model.
    with pytest.raises(BenchEvalError, match="demoted"):
        OperatorOperations().plan(
            PlanRequestDTO(
                benchmark_id="gpqa-diamond", slice_id="smoke", model_id=_QWEN_ID, diagnostic=True
            )
        )


# --- N001 (non-blocking): the canonical digest contract is frozen ------------------


def test_binding_digest_canonical_form_is_frozen() -> None:
    """Independent oracle: the contract text (compact, key-sorted JSON, nulls omitted)
    hashed here by hand must equal the implementation's digest, now and later."""
    snapshot = json.loads((_FIXTURE / "canonical/run-plan.json").read_text(encoding="utf-8"))[
        "model_binding_snapshot"
    ]
    body = {k: v for k, v in snapshot.items() if k != "sha256"}
    body["bfcl"] = {k: v for k, v in body["bfcl"].items() if v is not None}
    hand_text = json.dumps(body, sort_keys=True, separators=(",", ":"))
    hand_digest = "sha256:" + hashlib.sha256(hand_text.encode("utf-8")).hexdigest()
    assert hand_digest == snapshot["sha256"]
    assert canonical_sha256(snapshot) == hand_digest
    # Nulls are dropped at every depth, and ``sha256`` never hashes itself.
    assert canonical_sha256({**snapshot, "bfcl": {**snapshot["bfcl"], "handler": None}}) == (
        canonical_sha256(
            {k: v for k, v in snapshot.items() if k != "bfcl"}
            | {"bfcl": {k: v for k, v in snapshot["bfcl"].items() if k != "handler"}}
        )
    )
    # Scoped compatibility claim: a draft hashed with explicit nulls is a
    # different, unsupported format and is refused rather than re-labelled.
    with_null_form = json.dumps(
        {**body, "bfcl": {**body["bfcl"], "handler": None}}, sort_keys=True, separators=(",", ":")
    )
    null_digest = "sha256:" + hashlib.sha256(with_null_form.encode("utf-8")).hexdigest()
    assert null_digest != hand_digest
    with pytest.raises(ValueError, match="sha256"):
        ModelBinding.model_validate({**snapshot, "sha256": null_digest})


def test_only_the_top_level_self_digest_is_excluded_from_the_canonical_form() -> None:
    """A nested member that happens to be named ``sha256`` is ordinary data."""
    from bencheval.actor_binding import build_actor_binding

    assert canonical_sha256({"a": {"sha256": "first"}}) != canonical_sha256(
        {"a": {"sha256": "second"}}
    )
    assert canonical_sha256({"a": 1, "sha256": "ignored"}) == canonical_sha256({"a": 1})
    first = build_actor_binding(
        actor_kind="agent", actor_id="x", harbor_agent="x", kwargs={"sha256": "first"}
    )
    second = build_actor_binding(
        actor_kind="agent", actor_id="x", harbor_agent="x", kwargs={"sha256": "second"}
    )
    assert first.sha256 != second.sha256
