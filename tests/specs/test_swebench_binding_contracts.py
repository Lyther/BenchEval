"""R5.1 contracts: the SWE-bench Verified diagnostic binds its exact API model and route.

Architecture §22.11 (engineering continuation) / §23.3 / roadmap R5.1. A
runtime-backed SWE plan snapshots the exact API model and the chosen
compatible route while keeping ``model_binding=runtime_configured`` and the
logical evidence identity; the Inspect selector is derived from the transport
protocol and the exact API name; the plan doctor, credential, endpoint, and
override checks run before any output is reserved; a generation log that names
another model or endpoint is refused before predictions are relabelled or the
official evaluator is invoked; retained snapshotless plans still load but need
replanning to launch.

Expected values come from the shipped registries through their real loaders
(``gpt-5.2-2025-12-11-FC`` -> API ``gpt-5.2-2025-12-11`` on ByteLLM,
``ollama-qwen3.5-397b-fc`` -> API ``qwen3.5:397b`` on direct Ollama Cloud), the
accepted binding design text, and the pinned Codex solver.

SUBSTITUTE_JUSTIFICATION
- substitute: injected ``SwebenchProcessRunner`` callables that write real
  Inspect ``.eval`` logs (through ``inspect_ai.log.write_eval_log``), planted
  official report/summary files, a temporary ``BENCHEVAL_HOME`` config bundle
  with an extra compatible provider profile, and explicit non-secret
  environments
- replaces: charged Codex/provider generation, Docker-backed official
  evaluation, and a real second compatible provider account
- necessity: a wrong-model generation log, endpoint drift after planning, a
  contradictory snapshot, and a missing credential must be forced
  deterministically before any charge or container effect
- real-option: the credential and endpoint refusals go through the real
  planner, doctor, and executor with no substitute; R5.2 supplies the real
  one-instance diagnostic on the selected ByteLLM route
- proof-limit: proves binding resolution, selector derivation, preflight
  ordering, and log-identity refusal; not that the Codex bridge serves the
  planned model on a real provider (R5.2 observes that)
- real-proof: pending R5.2 (roadmap R5)
- covered tests: every test in this module that injects a runner or a bundle
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from bencheval.application.dto import PlanRequestDTO
from bencheval.application.operations import OperatorOperations
from bencheval.benchmark_plan import plan_control_plane, run_plan_to_dry_run_dict
from bencheval.cli import main
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.doctor import run_plan_doctor
from bencheval.domain import RunPlan
from bencheval.evidence import INFRASTRUCTURE_FAILURE_CLASSES, read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.model_binding import resolve_model_binding
from bencheval.model_registry import load_model_registry
from bencheval.paths import repo_root, validate_config_bundle
from bencheval.swebench_adapter import (
    SwebenchCliResult,
    build_swebench_run_command,
    default_swebench_process_runner,
    preflight_swebench_launch,
    run_swebench_instance,
)
from tests.factories import write_swe_generation_log

_BENCHMARK = "swe-bench-verified"
_SLICE = "swe-bench-verified-diagnostic-1"
_TARGET = f"{_BENCHMARK}/{_SLICE}"
_INSTANCE_ID = "django__django-11099"
_FC_MODEL = "gpt-5.2-2025-12-11-FC"
_FC_API = "gpt-5.2-2025-12-11"
_QWEN = "ollama-qwen3.5-397b-fc"
_QWEN_API = "qwen3.5:397b"
_OTHER_MODEL = "kimi-k2.7-code"
_PLACEHOLDER_KEY = "placeholder-not-a-real-credential"
_BYTELLM_DEFAULT_ENDPOINT = "http://127.0.0.1:4000/v1"
_ACME_PROVIDER = "acme-compatible"
_ACME_MODEL = "acme-coder"
_ACME_API = "coder-1-2026-09"
_ACME_ENDPOINT = "https://llm.acme.example/v1"
_ACME_PROFILE = f"""schema_version: "0.1"
provider:
  id: {_ACME_PROVIDER}
  display_name: Acme compatible gateway
  kind: openai_compatible
  base_url_env: ACME_BASE_URL
  default_base_url: {_ACME_ENDPOINT}
  api_key_env: ACME_API_KEY
admission: admitted
"""
_LOG_NAME = "generation.eval"
_PATCH = "diff --git a/a b/a\n"


def _pin_route_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The public endpoint is part of the confirmed binding: fix it explicitly."""
    for name in ("BYTELLM_BASE_URL", "OLLAMA_CLOUD_BASE_URL", "BENCHEVAL_INSPECT_MODEL"):
        monkeypatch.delenv(name, raising=False)


def _plan(
    model_id: str = _FC_MODEL,
    provider_id: str | None = None,
    *,
    diagnostic: bool = True,
) -> RunPlan:
    return plan_control_plane(
        benchmark_id=_BENCHMARK,
        slice_id=_SLICE,
        runtime_id="codex-cli",
        model_id=model_id,
        provider_id=provider_id,
        diagnostic=diagnostic,
    )


def _cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def _bundle_with_acme_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A BENCHEVAL_HOME bundle whose only delta is one more compatible provider
    profile and one model row routed to it (configuration, no code)."""
    root = repo_root()
    bundle = tmp_path / "bundle"
    (bundle / "config").mkdir(parents=True)
    for name in ("benchmarks.yaml", "bfcl-v4-supported-models.yaml"):
        shutil.copy2(root / "config" / name, bundle / "config" / name)
    for sub in ("runtimes", "providers", "slices", "agents"):
        shutil.copytree(root / "config" / sub, bundle / "config" / sub)
    (bundle / "config" / "providers" / f"{_ACME_PROVIDER}.yaml").write_text(
        _ACME_PROFILE, encoding="utf-8"
    )
    registry = load_model_registry(root / "config" / "models.yaml").model_dump(
        mode="json", exclude_none=True
    )
    registry["models"].append(
        {
            "id": _ACME_MODEL,
            "family": "local",
            "display_name": "Acme Coder (compatible route)",
            "provider_route": _ACME_PROVIDER,
            "api_model": _ACME_API,
        }
    )
    (bundle / "config" / "models.yaml").write_text(json.dumps(registry), encoding="utf-8")
    validate_config_bundle(bundle)
    monkeypatch.setenv("BENCHEVAL_HOME", str(bundle))
    return bundle


def _plant_official_inputs(instance_dir: Path) -> None:
    official = instance_dir / "official-dataset"
    official.mkdir(parents=True, exist_ok=True)
    (official / "test.jsonl").write_text("{}\n", encoding="utf-8")


def _plant_resolved_report(instance_dir: Path, *, model_name: str, run_id: str) -> None:
    (instance_dir / "report.json").write_text(
        json.dumps({_INSTANCE_ID: {"resolved": True}}), encoding="utf-8"
    )
    (instance_dir / f"{model_name}.{run_id}.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "resolved_ids": [_INSTANCE_ID],
                "unresolved_ids": [],
                "empty_patch_ids": [],
                "error_ids": [],
                "infra_failure_ids": [],
                "ambiguous_failure_ids": [],
            }
        ),
        encoding="utf-8",
    )


class _RecordingRunner:
    """An injected runner that writes what the generation phase would retain."""

    def __init__(self, artifacts: Path, *, on_generate, on_evaluate=None) -> None:
        self.artifacts = artifacts
        self.commands: list[tuple[str, ...]] = []
        self._on_generate = on_generate
        self._on_evaluate = on_evaluate

    def __call__(
        self, command: Sequence[str], *, cwd: Path | None, timeout_sec: int
    ) -> SwebenchCliResult:
        argv = tuple(str(part) for part in command)
        self.commands.append(argv)
        instance_dir = self.artifacts / _INSTANCE_ID
        if len(self.commands) == 1:
            self._on_generate(instance_dir)
        elif self._on_evaluate is not None:
            self._on_evaluate(instance_dir)
        return SwebenchCliResult(0, "", "", 0.1, argv)


# --- plan snapshot and selector -------------------------------------------------------


def test_runtime_backed_swe_plan_snapshots_the_exact_api_model_and_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_route_environment(monkeypatch)
    plan = _plan()

    snapshot = plan.model_binding_snapshot
    assert snapshot is not None
    # The runtime still owns its model configuration; the snapshot fixes what
    # the bridge must serve, and evidence identity stays logical.
    assert plan.model_binding == "runtime_configured"
    assert plan.model_id == _FC_MODEL
    assert snapshot.model_id == _FC_MODEL
    assert snapshot.api_model == _FC_API
    assert snapshot.provider_id == "bytellm" == plan.provider_id
    assert snapshot.provider_kind == "openai_compatible"
    assert snapshot.base_url == _BYTELLM_DEFAULT_ENDPOINT
    assert snapshot == resolve_model_binding(_FC_MODEL, "bytellm")
    shown = run_plan_to_dry_run_dict(plan)
    assert shown["model_binding_snapshot"]["api_model"] == _FC_API
    assert shown["model_binding_snapshot"]["sha256"] == snapshot.sha256


@pytest.mark.parametrize(
    ("model_id", "api_model", "provider_id"),
    [(_FC_MODEL, _FC_API, "bytellm"), (_QWEN, _QWEN_API, "ollama-cloud")],
)
def test_generation_selector_derives_from_protocol_and_exact_api_name(
    model_id: str, api_model: str, provider_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_route_environment(monkeypatch)
    plan = _plan(model_id)
    assert plan.model_binding_snapshot is not None

    command = build_swebench_run_command(
        plan=plan, instance_id=_INSTANCE_ID, artifacts_dir=Path("run-owned").resolve()
    )

    # OpenAI-compatible transport -> Inspect's openai/ namespace with the exact
    # API name; neither the route id nor the logical id is a selector.
    assert command[command.index("--model") + 1] == f"openai/{api_model}"
    assert f"{provider_id}/" not in " ".join(command)
    assert f"openai/{model_id}" not in command
    # The confirmed public endpoint travels with the generation so the retained
    # log records the endpoint the bridge was configured with.
    assert command[command.index("--model-base-url") + 1] == plan.model_binding_snapshot.base_url
    assert command[command.index("--solver") + 1] == "inspect_swe/codex_cli"
    assert "version=0.148.0" in command


def test_arbitrary_compatible_provider_route_is_configuration_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_route_environment(monkeypatch)
    monkeypatch.delenv("ACME_API_KEY", raising=False)
    monkeypatch.delenv("ACME_BASE_URL", raising=False)
    _bundle_with_acme_route(tmp_path, monkeypatch)

    plan = _plan(_ACME_MODEL)
    snapshot = plan.model_binding_snapshot
    assert snapshot is not None
    assert snapshot.provider_id == _ACME_PROVIDER == plan.provider_id
    assert snapshot.api_model == _ACME_API
    assert snapshot.base_url == _ACME_ENDPOINT
    command = build_swebench_run_command(
        plan=plan, instance_id=_INSTANCE_ID, artifacts_dir=tmp_path / "run-owned"
    )
    assert command[command.index("--model") + 1] == f"openai/{_ACME_API}"

    with pytest.raises(BenchEvalError, match="ACME_API_KEY"):
        preflight_swebench_launch(plan, real_runner=True)
    report = run_plan_doctor(plan)
    by_name = {check.name: check for check in report.checks}
    assert by_name["provider_credentials"].status == "fail"
    assert by_name["swe_launch_identity"].status == "fail"

    monkeypatch.setenv("ACME_API_KEY", _PLACEHOLDER_KEY)
    identity = preflight_swebench_launch(plan, real_runner=True)
    assert identity["inspect_model"] == f"openai/{_ACME_API}"
    assert identity["base_url"] == _ACME_ENDPOINT
    assert identity["provider_id"] == _ACME_PROVIDER
    by_name = {check.name: check for check in run_plan_doctor(plan).checks}
    assert by_name["provider_credentials"].status == "pass"
    assert by_name["swe_launch_identity"].status == "pass"


# --- plan / CLI / console parity --------------------------------------------------------


def test_cli_dry_run_doctor_and_console_expose_one_swe_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_route_environment(monkeypatch)
    monkeypatch.setenv("BYTELLM_API_KEY", _PLACEHOLDER_KEY)
    expected = _plan(provider_id="bytellm").model_binding_snapshot
    assert expected is not None
    argv = ["--runtime", "codex-cli", "--model", _FC_MODEL, "--provider", "bytellm", "--diagnostic"]

    code, out, err = _cli(["run", _TARGET, *argv, "--dry-run"])
    assert code == 0, err
    shown = json.loads(out)
    assert shown["model_binding"] == "runtime_configured"
    assert shown["model_binding_snapshot"]["api_model"] == _FC_API
    assert shown["model_binding_snapshot"]["sha256"] == expected.sha256

    _, doctor_out, _ = _cli(["doctor", _TARGET, *argv])
    doctor = json.loads(doctor_out)
    assert doctor["selection"]["model_binding_sha256"] == expected.sha256
    assert "swe_launch_identity" in {check["name"] for check in doctor["checks"]}

    view = OperatorOperations().preflight(
        PlanRequestDTO(
            benchmark_id=_BENCHMARK,
            slice_id=_SLICE,
            model_id=_FC_MODEL,
            runtime_id="codex-cli",
            provider_id="bytellm",
            diagnostic=True,
        )
    )
    assert view.selection is not None
    assert view.selection["model_binding_sha256"] == expected.sha256
    assert "swe_launch_identity" in {check.name for check in view.checks}


def test_plan_doctor_confirms_the_swe_launch_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    _pin_route_environment(monkeypatch)
    monkeypatch.setenv("BYTELLM_API_KEY", _PLACEHOLDER_KEY)
    plan = _plan()

    report = run_plan_doctor(plan)

    by_name = {check.name: check for check in report.checks}
    identity = by_name["swe_launch_identity"]
    assert identity.status == "pass"
    assert f"openai/{_FC_API}" in identity.message
    assert _BYTELLM_DEFAULT_ENDPOINT in identity.message
    assert by_name["provider_credentials"].status == "pass"
    assert report.selection is not None
    assert report.selection["model_binding_sha256"] == plan.model_binding_snapshot.sha256


# --- preflight before any output -------------------------------------------------------


def test_real_runner_refuses_before_any_output_without_the_route_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_route_environment(monkeypatch)
    monkeypatch.delenv("BYTELLM_API_KEY", raising=False)
    plan = _plan()
    failing = [check for check in run_plan_doctor(plan).checks if check.status == "fail"]
    assert {check.name for check in failing} >= {"provider_credentials", "swe_launch_identity"}
    evidence = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"

    with pytest.raises(BenchEvalError, match="backend preflight failed") as excinfo:
        execute_control_plane_run(
            plan=plan,
            output_path=evidence,
            artifacts_dir=artifacts,
            run_id="r51-no-credential",
            swebench_process_runner=default_swebench_process_runner,
        )

    for check in failing:
        assert check.message in str(excinfo.value), check.name
    assert not evidence.exists()
    assert not artifacts.exists()


def test_endpoint_drift_after_planning_is_refused_before_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_route_environment(monkeypatch)
    monkeypatch.setenv("BYTELLM_BASE_URL", "http://127.0.0.1:4000")
    plan = _plan()
    assert plan.model_binding_snapshot is not None
    assert plan.model_binding_snapshot.base_url == _BYTELLM_DEFAULT_ENDPOINT
    monkeypatch.setenv("BYTELLM_BASE_URL", "http://127.0.0.1:4999")
    runner = _RecordingRunner(tmp_path / "artifacts", on_generate=lambda d: None)
    evidence = tmp_path / "evidence.jsonl"

    with pytest.raises(BenchEvalError, match="confirmed binding endpoint"):
        execute_control_plane_run(
            plan=plan,
            output_path=evidence,
            artifacts_dir=tmp_path / "artifacts",
            run_id="r51-endpoint-drift",
            swebench_process_runner=runner,
        )

    assert runner.commands == []
    assert not evidence.exists()
    assert not (tmp_path / "artifacts").exists()


# --- conflicting overrides -------------------------------------------------------------


def test_provider_override_contradicting_the_declared_route_is_refused_at_planning() -> None:
    with pytest.raises(BenchEvalError, match="routed to provider 'bytellm'"):
        _plan(_FC_MODEL, provider_id="ollama-cloud")


def test_inspect_model_override_contradicting_the_planned_model_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_route_environment(monkeypatch)
    plan = _plan()
    monkeypatch.setenv("BENCHEVAL_INSPECT_MODEL", "openai/unrelated-model")

    with pytest.raises(BenchEvalError, match="planned model"):
        build_swebench_run_command(
            plan=plan, instance_id=_INSTANCE_ID, artifacts_dir=Path("run-owned")
        )


def test_snapshot_naming_another_model_is_refused_before_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_route_environment(monkeypatch)
    plan = _plan()
    other = resolve_model_binding(_OTHER_MODEL, "bytellm")
    # A retained plan edited after confirmation: the snapshot no longer names
    # the plan's model. Frozen models are copied, never mutated.
    conflicting = plan.model_copy(update={"model_binding_snapshot": other})
    runner = _RecordingRunner(tmp_path / "artifacts", on_generate=lambda d: None)
    evidence = tmp_path / "evidence.jsonl"

    with pytest.raises(BenchEvalError, match="conflicts with its binding snapshot"):
        preflight_swebench_launch(conflicting, real_runner=False)
    with pytest.raises(BenchEvalError, match="conflicts with its binding snapshot"):
        execute_control_plane_run(
            plan=conflicting,
            output_path=evidence,
            artifacts_dir=tmp_path / "artifacts",
            run_id="r51-snapshot-conflict",
            swebench_process_runner=runner,
        )

    assert runner.commands == []
    assert not evidence.exists()
    assert not (tmp_path / "artifacts").exists()


# --- generation log identity ----------------------------------------------------------


def test_wrong_model_generation_log_is_refused_before_relabelling_or_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_route_environment(monkeypatch)
    plan = _plan()
    artifacts = tmp_path / "artifacts"
    runner = _RecordingRunner(
        artifacts,
        on_generate=lambda d: write_swe_generation_log(
            d, model=f"openai/{_OTHER_MODEL}", base_url=_BYTELLM_DEFAULT_ENDPOINT
        ),
    )

    outcome = run_swebench_instance(
        plan=plan,
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=runner,
        timeout_sec=30,
        run_id="r51-wrong-model",
    )

    assert len(runner.commands) == 1
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_config_drift"
    assert outcome.failure_class in INFRASTRUCTURE_FAILURE_CLASSES
    assert not (artifacts / _INSTANCE_ID / "predictions.jsonl").exists()
    assert outcome.predictions_path is None
    assert outcome.adapter_metadata["generation_model_expected"] == f"openai/{_FC_API}"
    assert outcome.adapter_metadata["generation_model_observed"] == f"openai/{_OTHER_MODEL}"
    assert any(path.endswith(f".bound-{_LOG_NAME}") for path in outcome.identity_artifact_paths)


@pytest.mark.parametrize(
    ("event_model", "base_url"),
    [
        (f"openai/{_OTHER_MODEL}", _BYTELLM_DEFAULT_ENDPOINT),
        (None, "http://127.0.0.1:4999/v1"),
    ],
    ids=["model-event-names-another-model", "log-records-another-endpoint"],
)
def test_generation_log_event_or_endpoint_mismatch_is_refused(
    event_model: str | None,
    base_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_route_environment(monkeypatch)
    plan = _plan()
    artifacts = tmp_path / "artifacts"
    runner = _RecordingRunner(
        artifacts,
        on_generate=lambda d: write_swe_generation_log(
            d, model=f"openai/{_FC_API}", base_url=base_url, event_model=event_model
        ),
    )

    outcome = run_swebench_instance(
        plan=plan,
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=runner,
        timeout_sec=30,
        run_id="r51-log-mismatch",
    )

    assert len(runner.commands) == 1
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_config_drift"
    assert not (artifacts / _INSTANCE_ID / "predictions.jsonl").exists()


def test_matching_generation_log_relabels_predictions_logically_and_reaches_the_evaluator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_route_environment(monkeypatch)
    plan = _plan()
    assert plan.model_binding_snapshot is not None
    artifacts = tmp_path / "artifacts"
    run_id = "r51-matching-model"

    def generate(instance_dir: Path) -> None:
        write_swe_generation_log(
            instance_dir, model=f"openai/{_FC_API}", base_url=_BYTELLM_DEFAULT_ENDPOINT
        )
        _plant_official_inputs(instance_dir)

    runner = _RecordingRunner(
        artifacts,
        on_generate=generate,
        on_evaluate=lambda d: _plant_resolved_report(d, model_name=_FC_MODEL, run_id=run_id),
    )

    execute_control_plane_run(
        plan=plan,
        output_path=tmp_path / "evidence.jsonl",
        artifacts_dir=artifacts,
        run_id=run_id,
        swebench_process_runner=runner,
    )

    assert len(runner.commands) == 2
    assert runner.commands[0][:3] == ("inspect", "eval", "inspect_evals/swe_bench")
    assert runner.commands[1][:2] == ("swebench", "eval")
    rows = [
        json.loads(line)
        for line in (artifacts / _INSTANCE_ID / "predictions.jsonl").read_text().splitlines()
    ]
    # The official row keeps the logical evidence identity; the API name lives
    # in the binding, never in a relabelled prediction.
    assert rows == [
        {"instance_id": _INSTANCE_ID, "model_name_or_path": _FC_MODEL, "model_patch": _PATCH}
    ]
    record = read_evidence_jsonl(tmp_path / "evidence.jsonl")[0]
    assert record.primary_pass is True
    assert record.model_id == _FC_MODEL
    assert record.adapter_metadata["model_binding_sha256"] == plan.model_binding_snapshot.sha256
    assert record.adapter_metadata["api_model"] == _FC_API
    assert record.adapter_metadata["inspect_model"] == f"openai/{_FC_API}"
    assert record.adapter_metadata["generation_model_observed"] == f"openai/{_FC_API}"
    assert any(path.endswith(f".bound-{_LOG_NAME}") for path in record.artifact_paths)


# --- historical reads ----------------------------------------------------------------


def test_historical_snapshotless_swe_plan_loads_but_needs_replanning_to_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_route_environment(monkeypatch)
    monkeypatch.setenv("BYTELLM_API_KEY", _PLACEHOLDER_KEY)
    retained = _plan().model_dump(mode="json")
    # Plans retained before R5.1 carry no snapshot for runtime-backed SWE runs.
    retained["model_binding_snapshot"] = None

    historical = RunPlan.model_validate(retained)

    assert historical.model_binding_snapshot is None
    assert historical.model_binding == "runtime_configured"
    with pytest.raises(BenchEvalError, match="re-plan"):
        build_swebench_run_command(
            plan=historical, instance_id=_INSTANCE_ID, artifacts_dir=Path("run-owned")
        )
    with pytest.raises(BenchEvalError, match="re-plan"):
        preflight_swebench_launch(historical, real_runner=False)
    by_name = {check.name: check for check in run_plan_doctor(historical).checks}
    assert by_name["swe_launch_identity"].status == "fail"
    assert "re-plan" in by_name["swe_launch_identity"].message
    runner = _RecordingRunner(tmp_path / "artifacts", on_generate=lambda d: None)
    evidence = tmp_path / "evidence.jsonl"
    with pytest.raises(BenchEvalError, match="re-plan"):
        execute_control_plane_run(
            plan=historical,
            output_path=evidence,
            artifacts_dir=tmp_path / "artifacts",
            run_id="r51-historical",
            swebench_process_runner=runner,
        )
    assert runner.commands == []
    assert not evidence.exists()
    assert not (tmp_path / "artifacts").exists()


def test_stale_bound_generation_log_cannot_stand_in_for_the_current_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_route_environment(monkeypatch)
    plan = _plan()
    artifacts = tmp_path / "artifacts"
    instance_dir = artifacts / _INSTANCE_ID
    # A twin left behind by another run names the planned model; the fresh
    # generation log does not. The stale twin is cleared before generation like
    # every other stale authoritative artifact, so only the current log counts.
    stale = write_swe_generation_log(
        instance_dir, model=f"openai/{_FC_API}", base_url=_BYTELLM_DEFAULT_ENDPOINT
    )
    stale.rename(instance_dir / f".bound-{_LOG_NAME}")
    runner = _RecordingRunner(
        artifacts,
        on_generate=lambda d: write_swe_generation_log(
            d, model=f"openai/{_OTHER_MODEL}", base_url=_BYTELLM_DEFAULT_ENDPOINT
        ),
    )

    outcome = run_swebench_instance(
        plan=plan,
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=runner,
        timeout_sec=30,
        run_id="r51-stale-twin",
    )

    assert len(runner.commands) == 1
    assert outcome.failure_class == "runtime_config_drift"
    assert outcome.adapter_metadata["generation_model_observed"] == f"openai/{_OTHER_MODEL}"
    assert not (instance_dir / "predictions.jsonl").exists()


# --- positive attribution is required (review F001) ---------------------------------------


def _plant_prediction(instance_dir: Path) -> None:
    instance_dir.mkdir(parents=True, exist_ok=True)
    (instance_dir / "predictions.jsonl").write_text(
        json.dumps(
            {"instance_id": _INSTANCE_ID, "model_name_or_path": _FC_MODEL, "model_patch": _PATCH}
        )
        + "\n",
        encoding="utf-8",
    )


def _unreadable_log(instance_dir: Path) -> None:
    instance_dir.mkdir(parents=True, exist_ok=True)
    (instance_dir / _LOG_NAME).write_bytes(b"not an inspect log")


def _eventless_log(instance_dir: Path) -> None:
    from inspect_ai.log import read_eval_log, write_eval_log

    path = write_swe_generation_log(
        instance_dir, model=f"openai/{_FC_API}", base_url=_BYTELLM_DEFAULT_ENDPOINT
    )
    log = read_eval_log(str(path))
    log.samples[0].events = []
    write_eval_log(log, str(path))


@pytest.mark.parametrize(
    "generation",
    [
        lambda d: None,
        _unreadable_log,
        _eventless_log,
    ],
    ids=["no-log", "unreadable-log", "log-without-model-events"],
)
def test_existing_prediction_without_positive_generation_identity_never_reaches_the_evaluator(
    generation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin_route_environment(monkeypatch)
    plan = _plan()
    artifacts = tmp_path / "artifacts"

    def generate(instance_dir: Path) -> None:
        _plant_prediction(instance_dir)
        _plant_official_inputs(instance_dir)
        generation(instance_dir)

    runner = _RecordingRunner(artifacts, on_generate=generate)

    outcome = run_swebench_instance(
        plan=plan,
        instance_id=_INSTANCE_ID,
        artifacts_dir=artifacts,
        repo_root=tmp_path,
        process_runner=runner,
        timeout_sec=30,
        run_id="r51-unattributed-prediction",
    )

    # One command: the evaluator is never invoked on an unattributed prediction.
    assert len(runner.commands) == 1
    assert outcome.primary_pass is False
    assert outcome.failure_class == "runtime_output_unparseable"
    assert outcome.failure_class in INFRASTRUCTURE_FAILURE_CLASSES
    assert outcome.adapter_metadata["missing_artifact"] == "generation log (.eval)"
    assert _INSTANCE_ID in outcome.adapter_metadata["generation_identity_mismatch"]
    assert outcome.adapter_metadata["generation_model_expected"] == f"openai/{_FC_API}"
    assert outcome.predictions_path is None
