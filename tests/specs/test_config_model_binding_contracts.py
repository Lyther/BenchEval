"""CF1.1 contracts: typed model/provider bindings resolved from configuration only.

Architecture §23.3 / roadmap CF1.1. Expected values come from the accepted
design text (the §23.3 example entry, the direct Ollama Cloud endpoint, the
pinned BFCL registry key/API-name split), not from implementation output.

SUBSTITUTE_JUSTIFICATION
- substitute: in-memory model registries and temporary provider-profile
  directories loaded through the real loaders, carrying the §23.3 example
  entries, plus explicit non-secret environments
- replaces: editing the shipped config/models.yaml and config/providers/ for
  every negative case, and the operator's real .env
- necessity: mismatched protocol, missing API name, tampered digests, and
  secret leakage must be forced deterministically without a provider call
- real-option: the shipped registries are used directly wherever the case is
  about shipped rows (gpt-5.2 FC, ollama-cloud)
- proof-limit: proves configuration resolution and plan snapshotting only; no
  launch or official score is proven here
- real-proof: CF1.3 dev-box plumbing pair through the official CLI
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError

from bencheval.benchmark_plan import plan_control_plane, run_plan_to_dry_run_dict
from bencheval.domain import RunPlan
from bencheval.exceptions import BenchEvalError
from bencheval.model_binding import ModelBinding, model_binding_sha256, resolve_model_binding
from bencheval.model_registry import ModelRegistry, load_model_registry
from bencheval.provider_registry import (
    default_providers_dir,
    load_provider_catalog,
    resolve_openai_compatible_launch,
)

_OLLAMA_ENDPOINT = "https://ollama.com/v1"
_QWEN_ID = "ollama-qwen3.5-397b-fc"
_QWEN_API = "qwen3.5:397b"
_SECRET = "not-a-real-key-7f3a"

# The §23.3 example entry, verbatim.
_QWEN_ENTRY: dict[str, object] = {
    "id": _QWEN_ID,
    "family": "qwen",
    "display_name": "Qwen3.5 397B via Ollama Cloud (FC)",
    "provider_route": "ollama-cloud",
    "api_model": _QWEN_API,
    "backend_bindings": {
        "bfcl": {
            "mode": "configured",
            "handler": "openai_completions_fc",
            "underscore_to_dot": True,
        }
    },
}
_LEGACY_ENTRY: dict[str, object] = {
    "id": "legacy-row",
    "family": "openai",
    "display_name": "Legacy row without binding fields",
    "provider_route": "bytellm",
}
_JUDGE_ELSEWHERE: dict[str, object] = {
    "id": "gpt-5.3-chat-2026-03-03",
    "family": "openai",
    "display_name": "Judge routed to another provider",
    "provider_route": "ollama-cloud",
    "api_model": "gpt-5.3-chat-2026-03-03",
}
_CANDIDATE: dict[str, object] = {
    "id": "gpt-5.2-2025-12-11",
    "family": "openai",
    "display_name": "Candidate on ByteLLM",
    "provider_route": "bytellm",
}
_PINNED_SHAPE = """from bfcl_eval.model_handler.api_inference.openai_completion import (
    OpenAICompletionsHandler,
)
api_inference_model_map = {
    "gpt-5.2-2025-12-11-FC": ModelConfig(
        model_name="gpt-5.2-2025-12-11",
        model_handler=OpenAICompletionsHandler,
        is_fc_model=True,
        underscore_to_dot=False,
    ),
}
MODEL_CONFIG_MAPPING = {**api_inference_model_map}
"""
_OLLAMA_PROFILE = """schema_version: "0.1"
provider:
  id: ollama-cloud
  display_name: Ollama Cloud
  kind: openai_compatible
  base_url_env: OLLAMA_CLOUD_BASE_URL
  default_base_url: https://ollama.com/v1
  api_key_env: OLLAMA_API_KEY
admission: admitted
"""
_NATIVE_PROFILE = """schema_version: "0.1"
provider:
  id: anthropic-direct
  display_name: Anthropic native
  kind: anthropic_native
  base_url_env: ANTHROPIC_BASE_URL
  default_base_url: https://api.anthropic.com
  api_key_env: ANTHROPIC_API_KEY
admission: draft
"""


def _registry(*entries: dict[str, object]) -> ModelRegistry:
    return ModelRegistry.model_validate({"schema_version": 1, "models": list(entries)})


def _providers(tmp_path: Path, *extra: tuple[str, str]):
    d = tmp_path / "providers"
    d.mkdir(parents=True)
    shutil.copy2(default_providers_dir() / "bytellm.yaml", d / "bytellm.yaml")
    (d / "ollama-cloud.yaml").write_text(_OLLAMA_PROFILE, encoding="utf-8")
    for name, text in extra:
        (d / name).write_text(text, encoding="utf-8")
    return load_provider_catalog(d)


# --- provider protocol -----------------------------------------------------------


def test_shipped_ollama_cloud_is_a_direct_openai_compatible_route() -> None:
    # Direct Cloud access: https://ollama.com/v1 with OLLAMA_API_KEY; the local
    # daemon's OLLAMA_HOST must not steer it.
    launch = resolve_openai_compatible_launch(
        "ollama-cloud",
        environ={"OLLAMA_API_KEY": _SECRET, "OLLAMA_HOST": "http://127.0.0.1:11434"},
    )
    assert launch.base_url == _OLLAMA_ENDPOINT
    assert launch.environment["OPENAI_BASE_URL"] == _OLLAMA_ENDPOINT
    assert launch.environment["OPENAI_API_KEY"] == _SECRET
    override = resolve_openai_compatible_launch(
        "ollama-cloud",
        environ={"OLLAMA_API_KEY": _SECRET, "OLLAMA_CLOUD_BASE_URL": "https://mirror.test/v1"},
    )
    assert override.base_url == "https://mirror.test/v1"
    with pytest.raises(BenchEvalError, match="OLLAMA_API_KEY"):
        resolve_openai_compatible_launch("ollama-cloud", environ={})


def test_unsupported_provider_protocol_fails_as_a_typed_compatibility_error(
    tmp_path: Path,
) -> None:
    catalog = _providers(tmp_path, ("anthropic-direct.yaml", _NATIVE_PROFILE))
    registry = _registry(
        {
            "id": "claude-direct",
            "family": "anthropic",
            "display_name": "Claude on a native protocol",
            "provider_route": "anthropic-direct",
            "api_model": "claude-opus-5",
        }
    )
    with pytest.raises(BenchEvalError, match="anthropic_native"):
        resolve_model_binding("claude-direct", models=registry, providers=catalog)


# --- model registry schema -------------------------------------------------------


def test_configured_bfcl_binding_requires_explicit_api_name_and_known_handler() -> None:
    registry = _registry(_QWEN_ENTRY)
    entry = registry.by_id(_QWEN_ID)
    assert entry.api_model == _QWEN_API
    assert entry.backend_bindings is not None and entry.backend_bindings.bfcl is not None
    assert entry.backend_bindings.bfcl.mode == "configured"
    assert entry.backend_bindings.bfcl.underscore_to_dot is True

    without_api = {k: v for k, v in _QWEN_ENTRY.items() if k != "api_model"}
    with pytest.raises((ValidationError, BenchEvalError), match="api_model"):
        _registry(without_api)

    unknown_handler = json.loads(json.dumps(_QWEN_ENTRY))
    unknown_handler["backend_bindings"]["bfcl"]["handler"] = "my_custom_handler"
    with pytest.raises((ValidationError, BenchEvalError)):
        _registry(unknown_handler)

    # Configured mode must state the normalization flag; it is never guessed.
    no_flag = json.loads(json.dumps(_QWEN_ENTRY))
    del no_flag["backend_bindings"]["bfcl"]["underscore_to_dot"]
    with pytest.raises((ValidationError, BenchEvalError), match="underscore_to_dot"):
        _registry(no_flag)

    # Upstream mode reuses the pinned registration; a handler key is not its call.
    upstream_with_handler = json.loads(json.dumps(_QWEN_ENTRY))
    upstream_with_handler["backend_bindings"]["bfcl"]["mode"] = "upstream"
    with pytest.raises((ValidationError, BenchEvalError), match="upstream"):
        _registry(upstream_with_handler)


# --- pure resolver ---------------------------------------------------------------


def test_resolver_binds_logical_id_api_name_protocol_endpoint_and_bfcl_registry(
    tmp_path: Path,
) -> None:
    catalog = _providers(tmp_path)
    binding = resolve_model_binding(
        _QWEN_ID,
        models=_registry(_QWEN_ENTRY),
        providers=catalog,
        environ={"OLLAMA_API_KEY": _SECRET},
    )
    assert binding.model_id == _QWEN_ID
    assert binding.api_model == _QWEN_API
    assert binding.provider_id == "ollama-cloud"
    assert binding.provider_kind == "openai_compatible"
    assert binding.base_url == _OLLAMA_ENDPOINT
    assert binding.bfcl is not None
    assert binding.bfcl.mode == "configured"
    assert binding.bfcl.registry_id == _QWEN_ID  # defaults to the logical id
    assert binding.bfcl.handler == "openai_completions_fc"
    assert binding.bfcl.underscore_to_dot is True
    assert binding.sha256 == model_binding_sha256(binding)
    # Non-secret by construction: the credential never reaches the binding.
    assert _SECRET not in binding.model_dump_json()
    # A declared endpoint override is part of the binding identity; a secret is not.
    moved = resolve_model_binding(
        _QWEN_ID,
        models=_registry(_QWEN_ENTRY),
        providers=catalog,
        environ={"OLLAMA_CLOUD_BASE_URL": "https://mirror.test/v1", "OLLAMA_API_KEY": "other"},
    )
    assert moved.base_url == "https://mirror.test/v1"
    assert moved.sha256 != binding.sha256


def test_legacy_row_keeps_its_verbatim_api_name_and_declares_no_bfcl_binding(
    tmp_path: Path,
) -> None:
    binding = resolve_model_binding(
        "legacy-row", models=_registry(_LEGACY_ENTRY), providers=_providers(tmp_path)
    )
    assert binding.api_model == "legacy-row"
    assert binding.provider_id == "bytellm"
    assert binding.bfcl is None


def test_shipped_bfcl_fc_row_declares_upstream_binding_with_its_true_api_name() -> None:
    # gpt-5.2-2025-12-11-FC is a pinned upstream MODEL_CONFIG_MAPPING key whose
    # ModelConfig.model_name (the vendor API name) is gpt-5.2-2025-12-11.
    binding = resolve_model_binding("gpt-5.2-2025-12-11-FC")
    assert binding.provider_id == "bytellm"
    assert binding.api_model == "gpt-5.2-2025-12-11"
    assert binding.bfcl is not None
    assert binding.bfcl.mode == "upstream"
    assert binding.bfcl.registry_id == "gpt-5.2-2025-12-11-FC"


def test_route_mismatch_and_unknown_ids_fail_before_any_launch(tmp_path: Path) -> None:
    catalog = _providers(tmp_path)
    with pytest.raises(BenchEvalError, match="routed"):
        resolve_model_binding(_QWEN_ID, "bytellm", models=_registry(_QWEN_ENTRY), providers=catalog)
    with pytest.raises(BenchEvalError, match="unknown model"):
        resolve_model_binding("nope", models=_registry(_QWEN_ENTRY), providers=catalog)


def test_binding_digest_tracks_the_api_name_and_rejects_tampering(tmp_path: Path) -> None:
    catalog = _providers(tmp_path)
    a = resolve_model_binding(_QWEN_ID, models=_registry(_QWEN_ENTRY), providers=catalog)
    renamed = {**_QWEN_ENTRY, "api_model": "qwen3.5:397b-cloud"}
    b = resolve_model_binding(_QWEN_ID, models=_registry(renamed), providers=catalog)
    assert a.sha256 != b.sha256
    payload = a.model_dump(mode="json")
    payload["api_model"] = "something-else"
    with pytest.raises(ValidationError, match="sha256"):
        ModelBinding.model_validate(payload)


# --- planner snapshots -----------------------------------------------------------


def test_plan_snapshots_the_resolved_binding_and_legacy_plans_still_load() -> None:
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="smoke-5",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11-FC",
    )
    snapshot = plan.model_binding_snapshot
    assert snapshot is not None
    assert snapshot.sha256 == resolve_model_binding("gpt-5.2-2025-12-11-FC").sha256
    assert plan.judge_binding_snapshot is None
    shown = run_plan_to_dry_run_dict(plan)
    assert shown["model_binding_snapshot"]["sha256"] == snapshot.sha256
    assert _SECRET not in json.dumps(shown)
    # Plans written before CF1 carry no snapshot and must still validate.
    legacy = plan.model_dump(mode="json")
    del legacy["model_binding_snapshot"]
    del legacy["judge_binding_snapshot"]
    assert RunPlan.model_validate(legacy).model_binding_snapshot is None


def test_hle_judge_resolves_its_own_provider_route(tmp_path: Path) -> None:
    from bencheval.hle_adapter import resolve_hle_phase_launches

    catalog = _providers(tmp_path)
    registry = _registry(_CANDIDATE, _JUDGE_ELSEWHERE)
    plan = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
        model_registry=registry,
        provider_catalog=catalog,
    )
    assert plan.provider_id == "bytellm"
    assert plan.judge_model_id == "gpt-5.3-chat-2026-03-03"
    assert plan.judge_binding_snapshot is not None
    assert plan.judge_binding_snapshot.provider_id == "ollama-cloud"
    environ = {"BYTELLM_API_KEY": "b", "OLLAMA_API_KEY": _SECRET}
    prediction, judge = resolve_hle_phase_launches(
        plan, environ=environ, require_api_key=True, providers=catalog
    )
    assert prediction.base_url == "http://127.0.0.1:4000/v1"
    assert judge.base_url == _OLLAMA_ENDPOINT
    assert judge.environment["OPENAI_API_KEY"] == _SECRET
    # The official scripts receive the exact API names, not the logical ids.
    from bencheval.hle_adapter import hle_effective_model_ids

    assert hle_effective_model_ids(plan) == ("gpt-5.2-2025-12-11", "gpt-5.3-chat-2026-03-03")
    renamed = _registry(
        {**_CANDIDATE, "api_model": "gpt-5.2-2025-12-11-vendor"},
        {**_JUDGE_ELSEWHERE, "api_model": "judge-vendor-name"},
    )
    plan2 = plan_control_plane(
        benchmark_id="hle",
        slice_id="smoke",
        runtime_id=None,
        model_id="gpt-5.2-2025-12-11",
        model_registry=renamed,
        provider_catalog=catalog,
    )
    assert hle_effective_model_ids(plan2) == ("gpt-5.2-2025-12-11-vendor", "judge-vendor-name")
    # An endpoint override that changed after confirmation is refused, not followed.
    with pytest.raises(BenchEvalError, match="confirmed binding endpoint"):
        resolve_hle_phase_launches(
            plan,
            environ={**environ, "OLLAMA_CLOUD_BASE_URL": "https://elsewhere.test/v1"},
            require_api_key=True,
            providers=catalog,
        )


# --- adapters derive native namespaces from the binding ----------------------------


def test_gpqa_inspect_namespace_comes_from_protocol_and_api_name(tmp_path: Path) -> None:
    from bencheval.gpqa_adapter import build_gpqa_run_command

    catalog = _providers(tmp_path)
    plan = plan_control_plane(
        benchmark_id="gpqa-diamond",
        slice_id="smoke",
        runtime_id=None,
        model_id=_QWEN_ID,
        model_registry=_registry(_QWEN_ENTRY, _CANDIDATE),
        provider_catalog=catalog,
    )
    command = build_gpqa_run_command(plan=plan, sample_limit=1, log_dir=tmp_path / "logs")
    # OpenAI-compatible transport -> Inspect's openai/ namespace with the exact API name;
    # the route id never becomes a namespace.
    assert command[command.index("--model") + 1] == f"openai/{_QWEN_API}"


def test_cli_and_application_accept_diagnostic_for_a_configured_registration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from bencheval.application.dto import PlanRequestDTO
    from bencheval.application.operations import OperatorOperations
    from bencheval.cli import main

    assert (
        main(
            [
                "run",
                "bfcl-v4/tool-order-canonical-plumbing-2",
                "--model",
                _QWEN_ID,
                "--diagnostic",
                "--dry-run",
            ]
        )
        == 0
    )
    shown = json.loads(capsys.readouterr().out)
    assert shown["provider_id"] == "ollama-cloud"
    assert shown["comparison_validity"] == "diagnostic_only"
    assert shown["model_binding_snapshot"]["bfcl"]["mode"] == "configured"
    # Without --diagnostic the same plan is refused on the executable row.
    assert (
        main(["run", "bfcl-v4/tool-order-canonical-plumbing-2", "--model", _QWEN_ID, "--dry-run"])
        != 0
    )
    capsys.readouterr()
    preview = OperatorOperations().plan(
        PlanRequestDTO(
            benchmark_id="bfcl-v4",
            slice_id="tool-order-canonical-plumbing-2",
            model_id=_QWEN_ID,
            diagnostic=True,
        )
    )
    assert preview.diagnostic is True and preview.provider_id == "ollama-cloud"


def test_doctor_reports_configured_bfcl_registration_as_supported() -> None:
    from bencheval.doctor import bfcl_model_support_check

    registry = _registry(_QWEN_ENTRY, _LEGACY_ENTRY)
    configured = bfcl_model_support_check(_QWEN_ID, models=registry)
    assert configured.status == "pass"
    assert "configured" in configured.message
    # Upstream keys are checked against the pinned registry's real API name;
    # the pinned-shaped text stands in for the installed file on hosts without
    # bfcl-eval (the dev-box doctor reads the installed, pin-verified file).
    upstream = bfcl_model_support_check(
        "gpt-5.2-2025-12-11-FC", models=load_model_registry(), registry_text=_PINNED_SHAPE
    )
    assert upstream.status == "pass" and "gpt-5.2-2025-12-11" in upstream.message
    unbound = bfcl_model_support_check("legacy-row", models=registry)
    assert unbound.status == "fail"
