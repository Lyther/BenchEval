"""CF3.1 contracts: supported-host preparation and plan-aware preflight.

Architecture §23.7 / roadmap CF3.1 / AR-36. A clean supported host follows one
pinned per-benchmark preparation recipe, and preflight consumes the same
resolved benchmark/slice/model/actor selection as planning. Undeclared
dependencies, missing credentials, and unsupported bindings fail before any
charge, from the installed package/config-bundle surface and not only from a
source checkout.

Expected values come from the accepted design text, the shipped catalog and
registries through their real loaders, the CF2.3 retained actor-binding
digest, the existing doctor check names, and the dependency groups declared in
``pyproject.toml`` (``eval`` extra, ``bfcl`` group).

SUBSTITUTE_JUSTIFICATION
- substitute: pytest monkeypatch of Docker availability in the executor
  ordering case, and scrubbed subprocess environments
- replaces: a host whose Docker daemon is down, and a host without provider
  credentials or harness dependencies
- necessity: the ordering contract needs a doctor-only failure that the
  launch-identity check does not already catch, which no single developer host
  exposes deterministically; the wheel cases need deterministic absence
- real-option: the wheel-surface cases run the real installed package in a
  fresh ``uv run --no-project`` environment where every harness dependency is
  genuinely absent; no substitute is used there
- proof-limit: proves selection identity, dispatch, messages, ordering, and
  the installed surface; not that a prepared host launches
- real-proof: CF3.1 clean-host rehearsal on the dev-box (fresh checkout, venv
  and results root, all four families' doctor green, one minimal registered
  run per family) — executed 2026-09-09 (roadmap CF3.1)
- covered tests: test_executor_preflight_precedes_output_reservation,
  test_executor_refuses_unrouted_model_without_the_selected_credential,
  test_cli_refuses_unrouted_model_run_before_reservation,
  test_installed_wheel_preflights_all_four_families_with_exact_misses,
  test_bencheval_home_bundle_preflights_the_same_selection
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest

from bencheval.application.dto import PlanRequestDTO
from bencheval.application.operations import OperatorOperations
from bencheval.benchmark_plan import plan_control_plane, run_plan_to_dry_run_dict
from bencheval.cli import main
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.doctor import PREPARATION_RECIPES, run_plan_doctor
from bencheval.domain import RunPlan
from bencheval.exceptions import BenchEvalError
from bencheval.model_registry import load_model_registry
from bencheval.paths import repo_root, validate_config_bundle
from bencheval.provider_registry import DEFAULT_PROVIDER_ID

_QWEN = "ollama-qwen3.5-397b-fc"
_CF23_ACTOR_SHA = "sha256:ff5c68e8c01ed6d5eea3e8449a5769ff28331714674dfc43c7a448859958ef5d"
_PLACEHOLDER_KEY = "placeholder-not-a-real-credential"
_EVAL_EXTRA = "uv sync --extra eval"
_BFCL_GROUP = "uv sync --group bfcl"
_HLE_JUDGE = "gpt-5.3-chat-2026-03-03"
_SELECTION_KEYS = (
    "benchmark_id",
    "slice_id",
    "harness_kind",
    "adapter_id",
    "runtime_id",
    "agent_id",
    "provider_id",
    "model_id",
    "judge_model_id",
    "diagnostic",
)
# One executable family per official harness: the cheapest shipped selection.
_FAMILIES: dict[str, dict[str, str | None]] = {
    "harbor": {"target": "terminal-bench/tier1-one", "agent": "terminus-2", "model": _QWEN},
    "inspect-evals": {"target": "gpqa-diamond/smoke", "agent": None, "model": "kimi-k2.7-code"},
    "hle-native": {"target": "hle/smoke", "agent": None, "model": "kimi-k2.7-code"},
    "bfcl-native": {
        "target": "bfcl-v4/tool-order-canonical-plumbing-2",
        "agent": None,
        "model": "gpt-5.2-2025-12-11-FC",
    },
}
_REQUIRED_CHECKS: dict[str, set[str]] = {
    "harbor": {
        "harbor_cli",
        "docker",
        "harbor_actor_binding",
        "harbor_launch_identity",
        "provider_credentials",
    },
    "inspect-evals": {
        "inspect_ai_import",
        "inspect_openai_client",
        "inspect_evals_import",
        "docker",
        "provider_credentials",
    },
    "hle-native": {
        "hle_harness",
        "hle_dependencies",
        "hle_dataset_token",
        "provider_credentials",
        "judge_provider_credentials",
    },
    "bfcl-native": {
        "bfcl_model_support",
        "bfcl_harness",
        "bfcl_package_data",
        "provider_credentials",
    },
}
_BACKEND_BY_HARNESS = {
    "harbor": "harbor",
    "inspect-evals": "inspect",
    "hle-native": "hle-native",
    "bfcl-native": "bfcl-native",
}
_SCRUBBED_ENV_PREFIXES = (
    "BENCHEVAL_",
    "OLLAMA_",
    "BYTELLM_",
    "OPENAI_",
    "ANTHROPIC_",
    "HF_",
    "HUGGING",
)
_KEEP_ENV = (
    "PATH",
    "HOME",
    "TMPDIR",
    "LANG",
    "LC_ALL",
    "UV_CACHE_DIR",
    "UV_PYTHON",
    "SSL_CERT_FILE",
)


def _family_plan(harness: str) -> RunPlan:
    spec = _FAMILIES[harness]
    benchmark_id, slice_id = str(spec["target"]).split("/", 1)
    return plan_control_plane(
        benchmark_id=benchmark_id,
        slice_id=slice_id,
        runtime_id=None,
        agent_id=spec["agent"],
        model_id=str(spec["model"]),
    )


def _placeholder_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OLLAMA_CLOUD_BASE_URL",
        "BENCHEVAL_HARBOR_FORWARD_PROXY",
        "BENCHEVAL_HLE_HOME",
        "BENCHEVAL_HOME",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", _PLACEHOLDER_KEY)
    monkeypatch.setenv("BYTELLM_API_KEY", _PLACEHOLDER_KEY)


def _expected_selection(plan: RunPlan) -> dict[str, object]:
    data = run_plan_to_dry_run_dict(plan)
    expected: dict[str, object] = {key: data[key] for key in _SELECTION_KEYS}
    expected["instance_count"] = len(plan.instances)
    expected["model_binding_sha256"] = (
        plan.model_binding_snapshot.sha256 if plan.model_binding_snapshot else None
    )
    expected["actor_binding_sha256"] = (
        plan.actor_binding_snapshot.sha256 if plan.actor_binding_snapshot else None
    )
    return expected


def _cli(argv: list[str]) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


def _scrubbed_env() -> dict[str, str]:
    """A clean-host process environment: no credentials, no checkout venv on PATH."""
    env = {k: v for k, v in os.environ.items() if k in _KEEP_ENV}
    checkout = str(repo_root())
    env["PATH"] = os.pathsep.join(
        entry
        for entry in env.get("PATH", "").split(os.pathsep)
        if entry and not entry.startswith(checkout) and "/.venv/" not in entry
    )
    for key, value in os.environ.items():
        if key.startswith("UV_") and key not in env:
            env[key] = value
    for key in list(env):
        if key.startswith(_SCRUBBED_ENV_PREFIXES):
            del env[key]
    return env


# --- selection identity ---------------------------------------------------------------


def test_plan_doctor_reports_the_planned_selection_for_every_executable_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor consumes the resolved plan: same benchmark/slice/model/actor identity."""
    _placeholder_credentials(monkeypatch)
    for harness, required in _REQUIRED_CHECKS.items():
        plan = _family_plan(harness)
        assert plan.harness_kind == harness
        report = run_plan_doctor(plan)
        assert report.backend == _BACKEND_BY_HARNESS[harness], harness
        assert report.selection == _expected_selection(plan), harness
        names = {check.name for check in report.checks}
        assert required <= names, (harness, names)
        assert report.ok is all(check.status != "fail" for check in report.checks), harness
        assert report.recipe == PREPARATION_RECIPES[harness]
        assert report.host is not None
        assert report.host["config_root"] == str(repo_root())
        assert report.host["config_source"] == "checkout"
        assert report.host["results_root"] == str(Path.cwd() / "results")
        # The recipe is actionable here: this config root is a checkout with its lockfile.
        preparation = report.host["preparation"]
        assert preparation["context"] == "checkout"
        assert preparation["checkout"] == str(repo_root())
        assert (Path(preparation["checkout"]) / "uv.lock").is_file()
        assert PREPARATION_RECIPES[harness].install in preparation["hint"]
        payload = report.to_dict()
        assert payload["selection"] == report.selection
        assert payload["recipe"]["install"] == PREPARATION_RECIPES[harness].install
        assert payload["host"]["preparation"] == preparation
    # The agent selection carries the confirmed CF2.3 binding, not a re-read profile.
    harbor = run_plan_doctor(_family_plan("harbor"))
    assert harbor.selection is not None
    assert harbor.selection["actor_binding_sha256"] == _CF23_ACTOR_SHA
    assert harbor.selection["agent_id"] == "terminus-2"
    assert harbor.selection["runtime_id"] is None


def test_hle_preflight_requires_the_pinned_judge_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The slice pins a judge on its own route; its credential is a preflight condition."""
    _placeholder_credentials(monkeypatch)
    monkeypatch.delenv("BYTELLM_API_KEY", raising=False)
    plan = plan_control_plane(
        benchmark_id="hle", slice_id="smoke", runtime_id=None, agent_id=None, model_id=_QWEN
    )
    assert plan.judge_model_id == _HLE_JUDGE
    report = run_plan_doctor(plan)
    by_name = {check.name: check for check in report.checks}
    assert by_name["provider_credentials"].status == "pass"
    judge = by_name["judge_provider_credentials"]
    assert judge.status == "fail"
    assert "BYTELLM_API_KEY" in judge.message and _HLE_JUDGE in judge.message
    assert _PLACEHOLDER_KEY not in judge.message
    assert report.ok is False
    monkeypatch.setenv("BYTELLM_API_KEY", _PLACEHOLDER_KEY)
    again = {check.name: check for check in run_plan_doctor(plan).checks}
    assert again["judge_provider_credentials"].status == "pass"


def test_inspect_openai_client_floor_is_a_preflight_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inspect refuses an openai client below its floor at launch; doctor says it first."""
    inspect_ai = pytest.importorskip("inspect_ai")
    from inspect_ai.model._providers.providers import validate_openai_client

    _placeholder_credentials(monkeypatch)
    try:
        validate_openai_client("OpenAI API")
        expected = "pass"
    except Exception:  # Inspect's own dependency error type
        expected = "fail"
    report = run_plan_doctor(_family_plan("inspect-evals"))
    check = next(check for check in report.checks if check.name == "inspect_openai_client")
    assert check.status == expected, (inspect_ai.__version__, check.message)
    if expected == "fail":
        assert "openai" in check.message and "prepare:" in check.message
        assert report.ok is False


def test_model_only_gpqa_preflight_does_not_require_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _placeholder_credentials(monkeypatch)
    monkeypatch.setattr("bencheval.doctor.docker_available", lambda: False)
    report = run_plan_doctor(_family_plan("inspect-evals"))
    docker = next(check for check in report.checks if check.name == "docker")
    assert docker.status == "skip"


def test_configured_bfcl_diagnostic_plan_stays_preflightable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _placeholder_credentials(monkeypatch)
    plan = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="tool-order-canonical-plumbing-2",
        runtime_id=None,
        agent_id=None,
        model_id=_QWEN,
        diagnostic=True,
    )
    assert plan.comparison_validity == "diagnostic_only"
    report = run_plan_doctor(plan)
    assert report.selection is not None and report.selection["diagnostic"] is True
    support = next(check for check in report.checks if check.name == "bfcl_model_support")
    assert support.status == "pass" and "configured" in support.message


# --- preparation recipes -----------------------------------------------------------------


def test_preparation_recipes_cover_every_executable_family_with_exact_commands() -> None:
    families = {_family_plan(harness).harness_kind for harness in _FAMILIES}
    assert families <= set(PREPARATION_RECIPES)
    for harness, recipe in PREPARATION_RECIPES.items():
        assert recipe.harness_kind == harness
        assert recipe.install.startswith("uv sync"), harness
        # No installed-environment preparation path is claimed: every recipe
        # runs in a BenchEval checkout at its lockfile.
        assert recipe.context == "checkout", harness
        assert recipe.external, harness
    assert PREPARATION_RECIPES["harbor"].install == _EVAL_EXTRA
    assert PREPARATION_RECIPES["inspect-evals"].install == _EVAL_EXTRA
    assert PREPARATION_RECIPES["hle-native"].install == _EVAL_EXTRA
    assert PREPARATION_RECIPES["bfcl-native"].install == _BFCL_GROUP
    assert any("docker" in item.lower() for item in PREPARATION_RECIPES["harbor"].external)
    assert any("BENCHEVAL_HLE_HOME" in item for item in PREPARATION_RECIPES["hle-native"].external)
    assert any("HF_TOKEN" in item for item in PREPARATION_RECIPES["hle-native"].external)


# --- CLI and console share the run selection ---------------------------------------------


def test_cli_doctor_accepts_the_run_selection_and_shares_planner_refusals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _placeholder_credentials(monkeypatch)
    code, out, err = _cli(
        ["doctor", "terminal-bench/tier1-one", "--agent", "terminus-2", "--model", _QWEN]
    )
    assert code in (0, 1), err
    payload = json.loads(out)
    assert payload["backend"] == "harbor"
    assert payload["selection"]["agent_id"] == "terminus-2"
    assert payload["selection"]["actor_binding_sha256"] == _CF23_ACTOR_SHA
    assert payload["recipe"]["install"] == _EVAL_EXTRA
    assert {"harbor_cli", "harbor_actor_binding", "provider_credentials"} <= {
        check["name"] for check in payload["checks"]
    }
    assert _PLACEHOLDER_KEY not in out

    # Planner refusals are the doctor's refusals, word for word what `run`
    # says: nothing is probed for a plan that could never launch.
    refusals = (
        ["bfcl-v4/tool-order-canonical-plumbing-2", "--agent", "terminus-2", "--model", _QWEN],
        ["terminal-bench/tier1-one", "--agent", "momo", "--model", _QWEN],
        ["terminal-bench/no-such-slice", "--runtime", "claude-code", "--model", _QWEN],
        ["terminal-bench/tier1-one", "--agent", "terminus-2", "--model", _QWEN, "--diagnostic"],
    )
    for argv in refusals:
        code, out, err = _cli(["doctor", *argv])
        run_code, run_out, run_err = _cli(["run", *argv, "--dry-run"])
        assert code == run_code == 1, argv
        assert out == "" and run_out == "", argv
        assert err == run_err and err.startswith("error:"), argv
    assert "scaffold" in _cli(["doctor", *refusals[1]])[2]
    code, out, err = _cli(["doctor", "terminal-bench/tier1-one", "--runtime", "claude-code"])
    assert code == 2 and "--model" in err
    code, out, err = _cli(
        ["doctor", "terminal-bench/tier1-one", "--model", _QWEN, "--backend", "harbor"]
    )
    assert code == 2 and "--backend" in err

    # The legacy backend form is unchanged and carries no selection.
    code, out, err = _cli(["doctor", "--backend", "inspect", "--model", "kimi-k2.7-code"])
    assert code in (0, 1), err
    legacy = json.loads(out)
    assert legacy["backend"] == "inspect" and legacy["selection"] is None
    assert "inspect_ai_import" in {check["name"] for check in legacy["checks"]}


def test_console_preflight_uses_the_plan_request(monkeypatch: pytest.MonkeyPatch) -> None:
    _placeholder_credentials(monkeypatch)
    ops = OperatorOperations()
    view = ops.preflight(
        PlanRequestDTO(
            benchmark_id="terminal-bench",
            slice_id="tier1-one",
            agent_id="terminus-2",
            model_id=_QWEN,
        )
    )
    assert view.backend == "harbor"
    assert view.selection is not None
    assert view.selection["actor_binding_sha256"] == _CF23_ACTOR_SHA
    assert view.selection["slice_id"] == "tier1-one"
    assert {"harbor_actor_binding", "provider_credentials"} <= {row.name for row in view.checks}
    with pytest.raises(BenchEvalError, match="scaffold"):
        ops.preflight(
            PlanRequestDTO(
                benchmark_id="terminal-bench",
                slice_id="tier1-one",
                agent_id="momo",
                model_id=_QWEN,
            )
        )


# --- executor: preflight precedes reservation ---------------------------------------------


def _remove_one_prerequisite(harness: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> str:
    """Remove one relevant prerequisite; return the doctor check that must fail."""
    if harness == "harbor":
        # Not covered by the launch-identity check: only the doctor sees it.
        monkeypatch.setattr("bencheval.doctor.docker_available", lambda: False)
        return "docker"
    # Model-only families: the candidate's route credential (for HLE also the
    # judge's). Point HLE at an empty checkout so no dataset work can start.
    monkeypatch.delenv("BYTELLM_API_KEY", raising=False)
    if harness == "hle-native":
        monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(tmp_path / "no-hle-checkout"))
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    return "provider_credentials"


@pytest.mark.parametrize("harness", sorted(_FAMILIES))
def test_executor_preflight_precedes_output_reservation(
    harness: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every real execution path stops on a missing prerequisite before any
    evidence file or artifacts tree exists and before any launch, with the
    plan doctor's own failing checks as the reason."""
    _placeholder_credentials(monkeypatch)
    failing = _remove_one_prerequisite(harness, monkeypatch, tmp_path)
    plan = _family_plan(harness)
    report = run_plan_doctor(plan)
    by_name = {check.name: check for check in report.checks}
    assert by_name[failing].status == "fail", harness
    failed = [check for check in report.checks if check.status == "fail"]
    evidence = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    with pytest.raises(BenchEvalError, match="backend preflight failed") as excinfo:
        execute_control_plane_run(
            plan=plan,
            output_path=evidence,
            artifacts_dir=artifacts,
            run_id=f"cf3-order-{harness}",
        )
    for check in failed:
        assert check.message in str(excinfo.value), (harness, check.name)
    assert not evidence.exists()
    assert not artifacts.exists()


# --- unrouted models follow the selected provider (CF3.2 F001) ---------------------------

# The four selections above with their optional ``provider_route`` removed
# (candidates and the HLE judge): the plan then selects ``--provider`` or the
# shipped default, and launch resolves that route's credential.
_UNROUTED_MODELS = frozenset({_QWEN, "gpt-5.2-2025-12-11", "gpt-5.2-2025-12-11-FC", _HLE_JUDGE})
_UNROUTED_CASES: dict[str, dict[str, str | None]] = {
    "harbor": {
        "target": "terminal-bench/tier1-one",
        "agent": "terminus-2",
        "model": _QWEN,
        "provider": "ollama-cloud",
        "env": "OLLAMA_API_KEY",
        "other": "BYTELLM_API_KEY",
    },
    "inspect-evals": {
        "target": "gpqa-diamond/smoke",
        "agent": None,
        "model": "gpt-5.2-2025-12-11",
        "provider": None,  # the shipped default provider
        "env": "BYTELLM_API_KEY",
        "other": "OLLAMA_API_KEY",
    },
    "hle-native": {
        "target": "hle/smoke",
        "agent": None,
        "model": "gpt-5.2-2025-12-11",
        "provider": "ollama-cloud",  # the unrouted judge follows the candidate's route
        "env": "OLLAMA_API_KEY",
        "other": "BYTELLM_API_KEY",
    },
    "bfcl-native": {
        "target": "bfcl-v4/tool-order-canonical-plumbing-2",
        "agent": None,
        "model": "gpt-5.2-2025-12-11-FC",
        "provider": "bytellm",
        "env": "BYTELLM_API_KEY",
        "other": "OLLAMA_API_KEY",
    },
}


def _bundle_with_unrouted_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A BENCHEVAL_HOME bundle whose only delta drops ``provider_route`` from
    the selected candidates and the HLE judge (a valid registry shape)."""
    root = repo_root()
    bundle = tmp_path / "bundle"
    (bundle / "config").mkdir(parents=True)
    for name in ("benchmarks.yaml", "bfcl-v4-supported-models.yaml"):
        shutil.copy2(root / "config" / name, bundle / "config" / name)
    for sub in ("runtimes", "providers", "slices", "agents"):
        shutil.copytree(root / "config" / sub, bundle / "config" / sub)
    registry = load_model_registry(root / "config" / "models.yaml").model_dump(
        mode="json", exclude_none=True
    )
    unrouted = 0
    for row in registry["models"]:
        if row["id"] in _UNROUTED_MODELS:
            assert row.pop("provider_route") is not None
            unrouted += 1
    assert unrouted == len(_UNROUTED_MODELS)
    (bundle / "config" / "models.yaml").write_text(json.dumps(registry), encoding="utf-8")
    validate_config_bundle(bundle)
    monkeypatch.setenv("BENCHEVAL_HOME", str(bundle))
    return bundle


def _unrouted_plan(harness: str) -> RunPlan:
    case = _UNROUTED_CASES[harness]
    benchmark_id, slice_id = str(case["target"]).split("/", 1)
    plan = plan_control_plane(
        benchmark_id=benchmark_id,
        slice_id=slice_id,
        runtime_id=None,
        agent_id=case["agent"],
        model_id=str(case["model"]),
        provider_id=case["provider"],
    )
    assert plan.provider_id == (case["provider"] or DEFAULT_PROVIDER_ID)
    return plan


def test_unrouted_model_preflight_follows_the_selected_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registered model may omit ``provider_route``; the plan then selects
    ``--provider`` or the default. Doctor checks that selected route's credential
    (and the judge's resolved route), exactly what launch resolves, not the
    model's absent route."""
    _placeholder_credentials(monkeypatch)
    _bundle_with_unrouted_models(tmp_path, monkeypatch)
    for harness, case in _UNROUTED_CASES.items():
        env, other = str(case["env"]), str(case["other"])
        plan = _unrouted_plan(harness)
        assert plan.model_binding_snapshot is not None
        assert plan.model_binding_snapshot.provider_id == plan.provider_id
        monkeypatch.setenv(env, _PLACEHOLDER_KEY)
        monkeypatch.setenv(other, _PLACEHOLDER_KEY)
        with_key = {check.name: check for check in run_plan_doctor(plan).checks}
        assert with_key["provider_credentials"].status == "pass", harness
        # Only the selected route's credential is missing: the other provider's
        # key must not stand in for it.
        monkeypatch.delenv(env)
        report = run_plan_doctor(plan)
        by_name = {check.name: check for check in report.checks}
        cred = by_name["provider_credentials"]
        assert cred.status == "fail", (harness, cred.message)
        assert env in cred.message and plan.provider_id in cred.message, cred.message
        assert _PLACEHOLDER_KEY not in cred.message
        if harness == "hle-native":
            assert plan.judge_binding_snapshot is not None
            assert plan.judge_binding_snapshot.provider_id == plan.provider_id
            assert with_key["judge_provider_credentials"].status == "pass"
            judge = by_name["judge_provider_credentials"]
            assert judge.status == "fail", judge.message
            assert env in judge.message and _HLE_JUDGE in judge.message, judge.message
        assert report.ok is False, harness


def test_cli_refuses_unrouted_model_run_before_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reviewed probe: an unrouted model on ``--provider bytellm`` with no
    credentials. Doctor fails on the selected route, and ``run`` stops with the
    doctor's reason before any evidence file, artifacts tree, or run plan exists."""
    _placeholder_credentials(monkeypatch)
    _bundle_with_unrouted_models(tmp_path, monkeypatch)
    monkeypatch.delenv("BYTELLM_API_KEY")
    monkeypatch.delenv("OLLAMA_API_KEY")
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    argv = ["gpqa-diamond/smoke", "--model", "gpt-5.2-2025-12-11", "--provider", "bytellm"]
    code, out, err = _cli(["doctor", *argv])
    assert code == 1, err
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["selection"]["provider_id"] == "bytellm"
    cred = _checks(payload)["provider_credentials"]
    assert cred["status"] == "fail" and "BYTELLM_API_KEY" in cred["message"], cred
    code, out, err = _cli(["run", *argv, "-y"])
    assert code == 1, err
    assert "backend preflight failed" in err and "BYTELLM_API_KEY" in err, err
    assert not (workdir / "results").exists()
    assert not any(workdir.rglob("run-plan.json"))


@pytest.mark.parametrize("harness", sorted(_UNROUTED_CASES))
def test_executor_refuses_unrouted_model_without_the_selected_credential(
    harness: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every real execution path: the selected route's credential is the
    doctor's failing check, and nothing is reserved."""
    _placeholder_credentials(monkeypatch)
    _bundle_with_unrouted_models(tmp_path, monkeypatch)
    case = _UNROUTED_CASES[harness]
    monkeypatch.delenv(str(case["env"]))
    if harness == "hle-native":
        monkeypatch.setenv("BENCHEVAL_HLE_HOME", str(tmp_path / "no-hle-checkout"))
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    plan = _unrouted_plan(harness)
    evidence = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"
    with pytest.raises(BenchEvalError, match="backend preflight failed") as excinfo:
        execute_control_plane_run(
            plan=plan,
            output_path=evidence,
            artifacts_dir=artifacts,
            run_id=f"cf32-f001-{harness}",
        )
    reason = str(excinfo.value)
    assert "provider_credentials:" in reason and str(case["env"]) in reason, reason
    if harness == "hle-native":
        assert "judge_provider_credentials:" in reason, reason
    assert not evidence.exists()
    assert not artifacts.exists()


# --- the installed surface -------------------------------------------------------------------


def test_config_bundle_requires_agent_profiles(tmp_path: Path) -> None:
    root = repo_root()
    bundle = tmp_path / "bundle"
    (bundle / "config").mkdir(parents=True)
    for name in ("benchmarks.yaml", "models.yaml", "bfcl-v4-supported-models.yaml"):
        shutil.copy2(root / "config" / name, bundle / "config" / name)
    for sub in ("runtimes", "providers", "slices"):
        shutil.copytree(root / "config" / sub, bundle / "config" / sub)
    with pytest.raises(BenchEvalError, match="config/agents"):
        validate_config_bundle(bundle)
    (bundle / "config" / "agents").mkdir()
    with pytest.raises(BenchEvalError, match="config/agents"):
        validate_config_bundle(bundle)
    shutil.copy2(
        root / "config" / "agents" / "terminus-2.yaml",
        bundle / "config" / "agents" / "terminus-2.yaml",
    )
    validate_config_bundle(bundle)


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if shutil.which("uv") is None:
        pytest.skip("uv required to build/install the wheel")
    wheel_dir = tmp_path_factory.mktemp("wheels")
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheel_dir)],
        cwd=str(repo_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr
    (wheel,) = wheel_dir.glob("*.whl")
    return wheel


def _wheel_doctor(
    wheel: Path, workdir: Path, argv: list[str], *, env: dict[str, str]
) -> tuple[int, dict[str, object], str]:
    proc = subprocess.run(
        ["uv", "run", "--no-project", "--with", str(wheel), "bencheval", "doctor", *argv],
        cwd=str(workdir),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "Traceback" not in proc.stderr, proc.stderr
    payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, payload, proc.stderr


def _checks(payload: dict[str, object]) -> dict[str, dict[str, str]]:
    return {row["name"]: row for row in payload["checks"]}  # type: ignore[index,misc]


def test_installed_wheel_preflights_all_four_families_with_exact_misses(
    built_wheel: Path, tmp_path: Path
) -> None:
    """Installed wheel, empty cwd, no credentials, no harness dependency: every
    family names its exact misses and the recipe; nothing crashes or passes."""
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    env = _scrubbed_env()

    code, payload, _ = _wheel_doctor(
        built_wheel,
        workdir,
        ["terminal-bench/tier1-one", "--agent", "terminus-2", "--model", _QWEN],
        env=env,
    )
    assert code == 1 and payload["ok"] is False
    checks = _checks(payload)
    assert checks["harbor_cli"]["status"] == "fail"
    assert _EVAL_EXTRA in checks["harbor_cli"]["message"]
    # The bare command cannot run here (no pyproject/lockfile): the guidance
    # says so instead of repeating it.
    assert "uv.lock" in checks["harbor_cli"]["message"]
    assert payload["host"]["preparation"]["context"] == "installed_wheel"
    assert payload["host"]["preparation"]["checkout"] is None
    assert _EVAL_EXTRA in payload["host"]["preparation"]["hint"]
    assert "uv.lock" in payload["host"]["preparation"]["hint"]
    assert checks["provider_credentials"]["status"] == "fail"
    assert "OLLAMA_API_KEY" in checks["provider_credentials"]["message"]
    selection = payload["selection"]
    assert selection["actor_binding_sha256"] == _CF23_ACTOR_SHA  # agents ship in the wheel
    assert selection["model_id"] == _QWEN and selection["provider_id"] == "ollama-cloud"
    assert payload["recipe"]["install"] == _EVAL_EXTRA
    host = payload["host"]
    assert host["config_source"] == "wheel"
    assert "site-packages" in host["config_root"] and host["config_root"].endswith("_bundled")
    assert host["results_root"] == str(workdir / "results")

    code, payload, _ = _wheel_doctor(
        built_wheel, workdir, ["gpqa-diamond/smoke", "--model", "kimi-k2.7-code"], env=env
    )
    assert code == 1 and payload["ok"] is False
    checks = _checks(payload)
    assert checks["inspect_ai_import"]["status"] == "fail"
    assert _EVAL_EXTRA in checks["inspect_ai_import"]["message"]
    assert checks["inspect_evals_import"]["status"] == "fail"
    assert "BYTELLM_API_KEY" in checks["provider_credentials"]["message"]

    code, payload, _ = _wheel_doctor(
        built_wheel, workdir, ["hle/smoke", "--model", "kimi-k2.7-code"], env=env
    )
    assert code == 1 and payload["ok"] is False
    checks = _checks(payload)
    assert checks["hle_harness"]["status"] == "fail"
    assert checks["hle_dependencies"]["status"] == "fail"
    assert _EVAL_EXTRA in checks["hle_dependencies"]["message"]
    assert checks["judge_provider_credentials"]["status"] == "fail"
    assert "BYTELLM_API_KEY" in checks["judge_provider_credentials"]["message"]
    assert any("BENCHEVAL_HLE_HOME" in item for item in payload["recipe"]["external"])

    code, payload, _ = _wheel_doctor(
        built_wheel,
        workdir,
        ["bfcl-v4/tool-order-canonical-plumbing-2", "--model", "gpt-5.2-2025-12-11-FC"],
        env=env,
    )
    assert code == 1 and payload["ok"] is False
    checks = _checks(payload)
    assert checks["bfcl_harness"]["status"] == "fail"
    assert _BFCL_GROUP in checks["bfcl_harness"]["message"]
    assert "uv.lock" in checks["bfcl_harness"]["message"]
    assert payload["recipe"]["install"] == _BFCL_GROUP
    assert payload["recipe"]["context"] == "checkout"
    assert not (workdir / "results").exists()


def test_bencheval_home_bundle_preflights_the_same_selection(
    built_wheel: Path, tmp_path: Path
) -> None:
    if shutil.which("rsync") is None:
        pytest.skip("rsync required by bundle exporter")
    bundle = tmp_path / "bundle"
    export = subprocess.run(
        [str(repo_root() / "scripts" / "export-config-bundle.sh"), str(bundle)],
        cwd=str(repo_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    assert export.returncode == 0, export.stderr
    validate_config_bundle(bundle)
    workdir = tmp_path / "elsewhere"
    workdir.mkdir()
    env = {**_scrubbed_env(), "BENCHEVAL_HOME": str(bundle)}
    code, payload, _ = _wheel_doctor(
        built_wheel,
        workdir,
        ["terminal-bench/tier1-one", "--agent", "terminus-2", "--model", _QWEN],
        env=env,
    )
    assert code == 1 and payload["ok"] is False
    assert payload["selection"]["actor_binding_sha256"] == _CF23_ACTOR_SHA
    assert payload["host"]["config_source"] == "bencheval_home"
    assert Path(payload["host"]["config_root"]) == bundle.resolve()
    # An exported bundle is configuration, not a project: no lockfile, no bare command.
    assert payload["host"]["preparation"]["context"] == "config_bundle"
    assert payload["host"]["preparation"]["checkout"] is None
    assert payload["host"]["results_root"] == str(workdir / "results")
