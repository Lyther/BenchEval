"""CF2.2 contracts: a ``kind: harbor`` native agent profile is dispatched through
the Terminal-Bench adapter and Harbor's official verifier, with honest actor
identity and no score inferred from the agent process.

Architecture §23.6 / roadmap CF2.2. Expected values come from the accepted
design text, the shipped profile ``config/agents/terminus-2.yaml`` (admitted
2026-09-09 for exactly the CF2.3 combination; its pre-admission ``draft`` state
is rebuilt through the real loader where the draft gates are the subject), the
CF1 model binding (``qwen3.5:397b`` on the direct Ollama Cloud endpoint), and
the read-only probe of Harbor 0.17.1 on dev-box-cpu (2026-09-08): ``--agent``
takes an upstream name, ``--agent-kwarg`` values are ``json.loads``-typed with a
plain-string fallback, Terminus-2 runs host-side through LiteLLM with
``model_name``/``api_base`` kwargs and accepts ``temperature`` /
``max_thinking_tokens``, credentials come from the ``harbor`` process
environment (``--env-file`` is ``load_dotenv(override=True)``), and its trial
result reports ``agent_info`` name ``terminus-2`` version ``2.0.0``.

SUBSTITUTE_JUSTIFICATION
- substitute: a recording Harbor runner that writes an official-shaped trial
  result, temporary agent catalogs through the real loader, hand-built frozen
  ``RunPlan`` payloads, and a placeholder provider key in the process env
- replaces: Harbor/Docker launches, the Ollama Cloud call, and editing
  config/agents/ for every negative case
- necessity: forged/missing/zero results, a profile edited after planning, and
  secret placement must be forced deterministically without a container or a
  charged model call
- real-option: none for the negative cases; the shipped profile and the
  shipped model registry are used directly for the positive planning cases
- proof-limit: proves dispatch, argv/env shape, identity checks, evidence axes,
  and retention; the real official reward is CF2.3's proof
- real-proof: CF2.3 ``run-20260908-150221-437459-86b913ba`` (official reward
  1.0, diagnostic row, retained ``execution/actor-binding.json`` digest
  ``_CF23_ACTOR_SHA``); the admitted profile's first ordinary run is CF3.1's
- covered tests: every test in this module
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from bencheval.actor_binding import (
    ActorBinding,
    actor_binding_for_agent,
    actor_binding_sha256,
    build_actor_binding,
)
from bencheval.agent_registry import (
    AgentCatalog,
    default_agents_dir,
    load_agent_catalog,
    load_agent_profile,
)
from bencheval.application.dto import PlanRequestDTO
from bencheval.application.operations import OperatorOperations
from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import execute_control_plane_run
from bencheval.domain import RunPlan
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.live_proof import qualify_lane
from bencheval.model_binding import resolve_model_binding
from bencheval.paths import repo_root
from bencheval.terminal_bench_harbor import HarborCliResult

_AGENT = "terminus-2"
_QWEN_ID = "ollama-qwen3.5-397b-fc"
_QWEN_API = "qwen3.5:397b"
_ENDPOINT = "https://ollama.com/v1"
_PLACEHOLDER_KEY = "placeholder-not-a-real-credential"
_ACTOR_MANIFEST = "execution/actor-binding.json"
# Digest of the actor binding retained by the CF2.3 run (dev-box
# results/.../run-20260908-150221-437459-86b913ba/.../execution/actor-binding.json).
_CF23_ACTOR_SHA = "sha256:ff5c68e8c01ed6d5eea3e8449a5769ff28331714674dfc43c7a448859958ef5d"
_BUNDLE_FILES = ("benchmarks.yaml", "models.yaml", "bfcl-v4-supported-models.yaml")
_BUNDLE_DIRS = ("runtimes", "providers", "slices", "agents")
_PATH_FLAGS = frozenset({"--jobs-dir", "--env-file"})
# Ordinary supported Terminus-2 settings (installed constructor signature).
_TUNED_KWARGS: dict[str, object] = {
    "parser_name": "json",
    "temperature": 0.7,
    "max_thinking_tokens": 1024,
    "record_terminal_session": False,
}


def _catalog_with_kwargs(tmp_path: Path, kwargs: dict[str, object]) -> AgentCatalog:
    d = tmp_path / "agents"
    d.mkdir(parents=True)
    (d / "momo.yaml").write_bytes((default_agents_dir() / "momo.yaml").read_bytes())
    raw = load_agent_catalog().by_id(_AGENT).model_dump(mode="json")
    raw["agent"]["kwargs"] = kwargs
    (d / "terminus-2.yaml").write_text(json.dumps(raw), encoding="utf-8")
    return load_agent_catalog(d)


def _draft_catalog(tmp_path: Path) -> AgentCatalog:
    """The shipped profile with its admission reverted to ``draft`` (pre-admission state)."""
    d = tmp_path / "draft-agents"
    d.mkdir(parents=True)
    (d / "momo.yaml").write_bytes((default_agents_dir() / "momo.yaml").read_bytes())
    raw = load_agent_catalog().by_id(_AGENT).model_dump(mode="json")
    raw["admission"] = "draft"
    (d / "terminus-2.yaml").write_text(json.dumps(raw), encoding="utf-8")
    return load_agent_catalog(d)


def _bundle_with_draft_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A BENCHEVAL_HOME config bundle whose only delta is ``terminus-2`` back in draft."""
    root = repo_root()
    bundle = tmp_path / "bundle"
    (bundle / "config").mkdir(parents=True)
    for name in _BUNDLE_FILES:
        (bundle / "config" / name).write_bytes((root / "config" / name).read_bytes())
    for sub in _BUNDLE_DIRS:
        shutil.copytree(root / "config" / sub, bundle / "config" / sub)
    raw = load_agent_catalog().by_id(_AGENT).model_dump(mode="json")
    raw["admission"] = "draft"
    (bundle / "config" / "agents" / "terminus-2.yaml").write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setenv("BENCHEVAL_HOME", str(bundle))
    return bundle


def _stable_argv(cmd: tuple[str, ...]) -> tuple[str, ...]:
    """argv without the per-run jobs dir and env-file paths."""
    out: list[str] = []
    skip = False
    for tok in cmd:
        if skip:
            skip = False
            continue
        out.append(tok)
        skip = tok in _PATH_FLAGS
    return tuple(out)


def _trial_result(reward: float, *, name: str = _AGENT, version: str = "2.0.0") -> str:
    return json.dumps(
        {
            "agent_info": {"name": name, "version": version, "model_info": None},
            "verifier_result": {"rewards": {"reward": reward}},
            "stats": {"n_errors": 0},
        }
    )


class _Recorder:
    """Records argv and the env-file bytes visible at launch; writes one trial result."""

    def __init__(self, result_text: str | None) -> None:
        self.result_text = result_text
        self.calls: list[tuple[str, ...]] = []
        self.env_files: list[str] = []

    def __call__(self, command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        cmd = tuple(command)
        self.calls.append(cmd)
        if "--env-file" in cmd:
            self.env_files.append(Path(cmd[cmd.index("--env-file") + 1]).read_text("utf-8"))
        if self.result_text is not None:
            out = Path(cmd[cmd.index("--jobs-dir") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "result.json").write_text(self.result_text, encoding="utf-8")
        return HarborCliResult(returncode=0, stdout="", stderr="", latency_sec=0.1, command=cmd)


def _launch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OLLAMA_CLOUD_BASE_URL",
        "BENCHEVAL_HARBOR_FORWARD_PROXY",
        "OPENAI_BASE_URL",
        "ANTHROPIC_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", _PLACEHOLDER_KEY)


def _expected_actor_binding(kwargs: dict[str, object] | None = None) -> ActorBinding:
    return build_actor_binding(
        actor_kind="agent",
        actor_id=_AGENT,
        harbor_agent=_AGENT,
        agent_version_pin="2.0.0",
        kwargs=dict(kwargs if kwargs is not None else {"parser_name": "json"}),
        source="harbor==0.17.1 built-in",
    )


def _agent_plan(*, diagnostic: bool = False, kwargs: dict[str, object] | None = None) -> RunPlan:
    """Frozen plan for the native agent, built by hand so executor gates are hit directly."""
    base = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id=_QWEN_ID,
    )
    payload = base.model_dump(mode="json")
    payload.update(
        runtime_id=None,
        runtime_kind=None,
        agent_id=_AGENT,
        model_binding="bencheval_injected",
        model_binding_snapshot=resolve_model_binding(_QWEN_ID).model_dump(mode="json"),
        actor_binding_snapshot=_expected_actor_binding(kwargs).model_dump(mode="json"),
        comparison_validity="diagnostic_only" if diagnostic else "adapter_smoke",
        diagnostic=diagnostic,
    )
    return RunPlan.model_validate(payload)


def _kwarg_tokens(cmd: tuple[str, ...]) -> set[str]:
    return {cmd[i + 1] for i, tok in enumerate(cmd[:-1]) if tok == "--agent-kwarg"}


# --- binding shape -------------------------------------------------------------------


def test_harbor_agent_profile_is_a_discriminated_native_binding(tmp_path: Path) -> None:
    shipped = load_agent_catalog().by_id(_AGENT)
    assert shipped.admission == "admitted"
    assert shipped.agent.kind == "harbor"
    assert shipped.agent.harbor_agent == _AGENT
    assert shipped.agent.version_pin == "2.0.0"
    assert shipped.agent.supported_harnesses == ("harbor",)
    assert load_agent_catalog().by_id("momo").agent.kind == "external_cli"
    assert actor_binding_for_agent(shipped) == _expected_actor_binding()
    assert actor_binding_for_agent(shipped).sha256 == _CF23_ACTOR_SHA

    base = shipped.model_dump(mode="json")

    def variant(**agent_fields: object) -> str:
        raw = json.loads(json.dumps(base))
        raw["agent"].update(agent_fields)
        return json.dumps(raw)

    for text, reason in (
        (variant(harbor_import_path="my_pkg.agents:Custom"), "exactly one"),
        (variant(harbor_agent=None), "exactly one"),
        (variant(kind="external_cli"), "command"),
        (variant(harbor_agent="bad name"), "pattern"),
        (variant(version_pin=None), "version_pin"),
    ):
        path = tmp_path / "bad.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(BenchEvalError, match=reason):
            load_agent_profile(path)


def test_native_kwargs_accept_supported_settings_and_refuse_routing_or_credentials(
    tmp_path: Path,
) -> None:
    tuned = _catalog_with_kwargs(tmp_path, _TUNED_KWARGS).by_id(_AGENT)
    assert tuned.agent.kwargs == _TUNED_KWARGS
    binding = actor_binding_for_agent(tuned)
    assert binding.kwargs == _TUNED_KWARGS
    assert binding.sha256 == actor_binding_sha256(binding)
    assert binding.sha256 != _expected_actor_binding().sha256

    base = load_agent_catalog().by_id(_AGENT).model_dump(mode="json")
    for kwargs, reason in (
        ({"api_key": "x"}, "credential"),
        ({"api_token": "x"}, "credential"),
        ({"openai_api_key": "x"}, "credential"),
        ({"model_name": "other"}, "reserved"),
        ({"api_base": "https://elsewhere.example/v1"}, "reserved"),
        ({"version": "9.9.9"}, "reserved"),
        ({"temperature": float("nan")}, "finite"),
        ({"Bad-Name": 1}, "identifier"),
    ):
        raw = json.loads(json.dumps(base))
        raw["agent"]["kwargs"] = kwargs
        path = tmp_path / "bad.yaml"
        path.write_text(json.dumps(raw).replace("NaN", ".nan"), encoding="utf-8")
        with pytest.raises(BenchEvalError, match=reason):
            load_agent_profile(path)
        with pytest.raises(ValueError, match=reason):
            build_actor_binding(
                actor_kind="agent", actor_id=_AGENT, harbor_agent=_AGENT, kwargs=kwargs
            )


# --- planner gates -------------------------------------------------------------------


def test_admission_preserves_the_cf23_binding_and_permits_an_ordinary_plan(
    tmp_path: Path,
) -> None:
    """Admitted for exactly the demonstrated combination; the binding did not move."""
    ordinary = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id=None,
        agent_id=_AGENT,
        model_id=_QWEN_ID,
    )
    assert ordinary.diagnostic is False
    assert ordinary.comparison_validity == "adapter_smoke"
    assert ordinary.agent_id == _AGENT and ordinary.runtime_id is None
    assert ordinary.actor_binding_snapshot is not None
    assert ordinary.actor_binding_snapshot.sha256 == _CF23_ACTOR_SHA
    assert ordinary.model_binding_snapshot is not None
    assert ordinary.model_binding_snapshot.api_model == _QWEN_API
    assert ordinary.model_binding_snapshot.base_url == _ENDPOINT
    assert ordinary.provider_id == "ollama-cloud"
    # The same profile in its pre-admission state plans only as diagnostic
    # evidence, on the identical actor binding.
    draft = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id=None,
        agent_id=_AGENT,
        model_id=_QWEN_ID,
        diagnostic=True,
        agent_catalog=_draft_catalog(tmp_path),
    )
    assert draft.comparison_validity == "diagnostic_only"
    assert draft.actor_binding_snapshot == ordinary.actor_binding_snapshot


def test_draft_native_agent_plans_only_with_explicit_diagnostic(tmp_path: Path) -> None:
    draft = _draft_catalog(tmp_path)
    with pytest.raises(BenchEvalError, match="draft"):
        plan_control_plane(
            benchmark_id="terminal-bench",
            slice_id="tier1-one",
            runtime_id=None,
            agent_id=_AGENT,
            model_id=_QWEN_ID,
            agent_catalog=draft,
        )
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id=None,
        agent_id=_AGENT,
        model_id=_QWEN_ID,
        diagnostic=True,
        agent_catalog=draft,
    )
    assert plan.agent_id == _AGENT and plan.runtime_id is None and plan.runtime_kind is None
    assert plan.diagnostic is True
    assert plan.comparison_validity == "diagnostic_only"
    assert plan.network_policy == "benchmark_required"
    assert plan.provider_id == "ollama-cloud"


def test_scaffold_agent_rejects_even_with_diagnostic() -> None:
    with pytest.raises(BenchEvalError, match="scaffold"):
        plan_control_plane(
            benchmark_id="terminal-bench",
            slice_id="tier1-one",
            runtime_id=None,
            agent_id="momo",
            model_id=_QWEN_ID,
            diagnostic=True,
        )


def test_model_only_benchmark_rejects_native_agent(tmp_path: Path) -> None:
    with pytest.raises(BenchEvalError, match="does not support harness"):
        plan_control_plane(
            benchmark_id="bfcl-v4",
            slice_id="tool-order-canonical-plumbing-2",
            runtime_id=None,
            agent_id=_AGENT,
            model_id=_QWEN_ID,
            diagnostic=True,
        )
    # A profile may claim any harness; the planner and the executor still
    # refuse to dispatch an agent through a model-only adapter.
    d = tmp_path / "agents"
    d.mkdir()
    raw = load_agent_catalog().by_id(_AGENT).model_dump(mode="json")
    raw["agent"]["supported_harnesses"] = ["harbor", "bfcl-native"]
    (d / "terminus-2.yaml").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(BenchEvalError, match="model-only"):
        plan_control_plane(
            benchmark_id="bfcl-v4",
            slice_id="tool-order-canonical-plumbing-2",
            runtime_id=None,
            agent_id=_AGENT,
            model_id=_QWEN_ID,
            diagnostic=True,
            agent_catalog=load_agent_catalog(d),
        )
    bfcl = plan_control_plane(
        benchmark_id="bfcl-v4",
        slice_id="tool-order-canonical-plumbing-2",
        runtime_id=None,
        model_id=_QWEN_ID,
        diagnostic=True,
    )
    forged = RunPlan.model_validate(
        {
            **bfcl.model_dump(mode="json"),
            "agent_id": _AGENT,
            "actor_binding_snapshot": _expected_actor_binding().model_dump(mode="json"),
        }
    )
    with pytest.raises(BenchEvalError, match="model-only"):
        execute_control_plane_run(
            plan=forged, output_path=tmp_path / "e.jsonl", artifacts_dir=tmp_path / "art"
        )
    assert not (tmp_path / "e.jsonl").exists()


def test_agent_plan_snapshots_actor_and_model_bindings(tmp_path: Path) -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id=None,
        agent_id=_AGENT,
        model_id=_QWEN_ID,
        diagnostic=True,
    )
    assert plan.actor_binding_snapshot == _expected_actor_binding()
    assert plan.model_binding_snapshot is not None
    assert plan.model_binding_snapshot.api_model == _QWEN_API
    assert plan.model_binding_snapshot.base_url == _ENDPOINT
    # A changed native kwarg is a different actor binding and therefore a new plan.
    replanned = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id=None,
        agent_id=_AGENT,
        model_id=_QWEN_ID,
        diagnostic=True,
        agent_catalog=_catalog_with_kwargs(tmp_path, {"parser_name": "xml"}),
    )
    assert replanned.actor_binding_snapshot is not None
    assert replanned.actor_binding_snapshot.sha256 != plan.actor_binding_snapshot.sha256


def test_console_shares_the_admission_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops = OperatorOperations()
    preview = ops.plan(
        PlanRequestDTO(
            benchmark_id="terminal-bench",
            slice_id="tier1-one",
            agent_id=_AGENT,
            model_id=_QWEN_ID,
        )
    )
    assert preview.agent_id == _AGENT and preview.runtime_id is None
    assert preview.diagnostic is False and preview.executable is True
    # An admitted agent on an executable row has no diagnostic opt-in (same
    # rule as bfcl-v4 after its admission).
    with pytest.raises(BenchEvalError, match="diagnostic mode is only valid"):
        ops.plan(
            PlanRequestDTO(
                benchmark_id="terminal-bench",
                slice_id="tier1-one",
                agent_id=_AGENT,
                model_id=_QWEN_ID,
                diagnostic=True,
            )
        )
    # The console reads the catalog planning reads: with the profile reverted
    # to draft in a config bundle, the draft gate applies unchanged.
    _bundle_with_draft_profile(tmp_path, monkeypatch)
    with pytest.raises(BenchEvalError, match="draft"):
        ops.plan(
            PlanRequestDTO(
                benchmark_id="terminal-bench",
                slice_id="tier1-one",
                agent_id=_AGENT,
                model_id=_QWEN_ID,
            )
        )
    preview = ops.plan(
        PlanRequestDTO(
            benchmark_id="terminal-bench",
            slice_id="tier1-one",
            agent_id=_AGENT,
            model_id=_QWEN_ID,
            diagnostic=True,
        )
    )
    assert preview.agent_id == _AGENT and preview.runtime_id is None and preview.diagnostic is True
    with pytest.raises(BenchEvalError, match="scaffold"):
        ops.plan(
            PlanRequestDTO(
                benchmark_id="terminal-bench",
                slice_id="tier1-one",
                agent_id="momo",
                model_id=_QWEN_ID,
                diagnostic=True,
            )
        )


# --- dispatch through the official verifier -------------------------------------------


def test_native_agent_dispatches_through_harbor_and_official_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _launch_env(monkeypatch)
    catalog = _catalog_with_kwargs(tmp_path, _TUNED_KWARGS)
    plan = _agent_plan(kwargs=_TUNED_KWARGS)
    runner = _Recorder(_trial_result(1.0))
    evidence = tmp_path / "evidence.jsonl"
    artifacts = tmp_path / "artifacts"

    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=artifacts,
        harbor_process_runner=runner,
        run_id="cf2-agent",
        agent_catalog=catalog,
    )

    assert summary.instance_count == 1
    (cmd,) = runner.calls
    assert cmd[:2] == ("harbor", "run")
    assert cmd[cmd.index("--agent") + 1] == _AGENT
    assert cmd[cmd.index("--model") + 1] == f"openai/{_QWEN_API}"
    # Harbor json-decodes kwarg values: numbers and booleans travel typed, plain
    # strings stay strings; the endpoint comes from the confirmed model binding.
    assert _kwarg_tokens(cmd) == {
        f"api_base={_ENDPOINT}",
        "parser_name=json",
        "temperature=0.7",
        "max_thinking_tokens=1024",
        "record_terminal_session=false",
    }
    assert "--agent-env" not in cmd
    assert not any(_PLACEHOLDER_KEY in token for token in cmd)
    # The provider key reaches the host-side harbor process only through the
    # mode-0600 env file, which is gone after launch.
    (env_text,) = runner.env_files
    assert f"OPENAI_API_KEY={_PLACEHOLDER_KEY}" in env_text.splitlines()
    assert not Path(cmd[cmd.index("--env-file") + 1]).exists()

    (row,) = read_evidence_jsonl(evidence)
    assert row.agent_id == _AGENT and row.runtime_id is None and row.runtime_kind is None
    assert row.adapter_id == "terminal-bench-harbor" and row.harness_kind == "harbor"
    assert row.runtime_version == "2.0.0"
    assert row.primary_pass is True and row.partial_score == 1.0
    assert row.native_score is not None
    assert row.native_score["verdict_provenance"] == "harbor_verifier_result"
    assert row.native_score["verifier_result"] == {"rewards": {"reward": 1.0}}
    assert row.verifier_integrity_label == "native"
    assert row.interpretation_label == "adapter_smoke"
    assert row.adapter_metadata["actor_binding_sha256"] == plan.actor_binding_snapshot.sha256
    assert row.adapter_metadata["model_binding_sha256"] == plan.model_binding_snapshot.sha256
    retained = ActorBinding.model_validate_json((artifacts / _ACTOR_MANIFEST).read_text("utf-8"))
    assert retained == plan.actor_binding_snapshot
    assert any(path.endswith(_ACTOR_MANIFEST) for path in row.artifact_paths)


def test_official_zero_reward_is_a_wrong_solution_not_an_infrastructure_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CF2.3 must not need Terminus-2 to solve the task to prove the lifecycle."""
    _launch_env(monkeypatch)
    runner = _Recorder(_trial_result(0.0))
    evidence = tmp_path / "evidence.jsonl"
    execute_control_plane_run(
        plan=_agent_plan(),
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        harbor_process_runner=runner,
        run_id="cf2-zero",
    )
    (row,) = read_evidence_jsonl(evidence)
    assert row.agent_id == _AGENT and row.runtime_id is None
    assert row.primary_pass is False and row.partial_score == 0.0
    assert row.failure_class == "model_wrong_solution"
    assert row.verifier_integrity_label == "native"
    assert row.runtime_version == "2.0.0"
    assert row.native_score is not None
    assert row.native_score["verdict_provenance"] == "harbor_verifier_result"
    assert row.native_score["verifier_result"] == {"rewards": {"reward": 0.0}}


def test_forged_or_missing_agent_result_cannot_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _launch_env(monkeypatch)
    cases = {
        "wrong-version": _trial_result(1.0, version="9.9.9"),
        "wrong-agent": _trial_result(1.0, name="oracle"),
        "no-result": None,
    }
    for label, text in cases.items():
        runner = _Recorder(text)
        evidence = tmp_path / label / "evidence.jsonl"
        execute_control_plane_run(
            plan=_agent_plan(),
            output_path=evidence,
            artifacts_dir=tmp_path / label / "art",
            harbor_process_runner=runner,
            run_id=f"cf2-{label}",
        )
        (row,) = read_evidence_jsonl(evidence)
        assert row.agent_id == _AGENT and row.runtime_id is None
        assert row.primary_pass is False, label
        assert row.partial_score == 0.0, label
        assert row.failure_class is not None, label


def test_profile_changed_after_planning_is_refused_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execution launches the confirmed binding or stops; it never rereads a
    changed profile silently."""
    _launch_env(monkeypatch)
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id=None,
        agent_id=_AGENT,
        model_id=_QWEN_ID,
    )
    runner = _Recorder(_trial_result(1.0))
    evidence = tmp_path / "evidence.jsonl"
    with pytest.raises(BenchEvalError, match="changed since planning"):
        execute_control_plane_run(
            plan=plan,
            output_path=evidence,
            artifacts_dir=tmp_path / "art",
            harbor_process_runner=runner,
            run_id="cf2-drift",
            agent_catalog=_catalog_with_kwargs(tmp_path, {"parser_name": "xml"}),
        )
    assert runner.calls == []
    assert not evidence.exists()


def test_non_diagnostic_draft_agent_plan_is_refused_at_execution(tmp_path: Path) -> None:
    runner = _Recorder(_trial_result(1.0))
    with pytest.raises(BenchEvalError, match="draft"):
        execute_control_plane_run(
            plan=_agent_plan(diagnostic=False),
            output_path=tmp_path / "e.jsonl",
            artifacts_dir=tmp_path / "art",
            harbor_process_runner=runner,
            run_id="cf2-refused",
            agent_catalog=_draft_catalog(tmp_path),
        )
    assert runner.calls == []
    assert not (tmp_path / "e.jsonl").exists()


def test_admitted_agent_run_is_ordinary_evidence_and_draft_stays_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Admission changes the row's standing, never the launch or the binding."""
    _launch_env(monkeypatch)
    runner = _Recorder(_trial_result(1.0))
    evidence = tmp_path / "ordinary.jsonl"
    execute_control_plane_run(
        plan=_agent_plan(),
        output_path=evidence,
        artifacts_dir=tmp_path / "ordinary",
        harbor_process_runner=runner,
        run_id="cf2-admitted",
    )
    (row,) = read_evidence_jsonl(evidence)
    assert row.interpretation_label == "adapter_smoke" and row.primary_pass is True
    assert row.adapter_metadata["actor_binding_sha256"] == _CF23_ACTOR_SHA
    lane = qualify_lane(
        evidence,
        expected_instances=1,
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        require_runtime=False,
        repo_root=tmp_path,
    )
    assert "diagnostic-interpretation" not in " ".join(lane.reasons)

    # The pre-admission state runs only as diagnostic evidence that can never
    # qualify for live proof, through the identical launch.
    draft_runner = _Recorder(_trial_result(1.0))
    draft_evidence = tmp_path / "draft.jsonl"
    execute_control_plane_run(
        plan=_agent_plan(diagnostic=True),
        output_path=draft_evidence,
        artifacts_dir=tmp_path / "draft",
        harbor_process_runner=draft_runner,
        run_id="cf2-draft",
        agent_catalog=_draft_catalog(tmp_path),
    )
    (draft_row,) = read_evidence_jsonl(draft_evidence)
    assert draft_row.interpretation_label == "diagnostic"
    assert draft_row.adapter_metadata["actor_binding_sha256"] == _CF23_ACTOR_SHA
    draft_lane = qualify_lane(
        draft_evidence,
        expected_instances=1,
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        require_runtime=False,
        repo_root=tmp_path,
    )
    assert draft_lane.ok is False
    assert "diagnostic-interpretation" in " ".join(draft_lane.reasons)
    assert _stable_argv(runner.calls[0]) == _stable_argv(draft_runner.calls[0])


def test_string_kwargs_that_harbor_would_retype_arrive_as_strings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Harbor json-decodes kwarg values and also maps True/False/None literals."""
    _launch_env(monkeypatch)
    kwargs: dict[str, object] = {
        "parser_name": "json",
        "session_id": "None",
        "tmux_pane_width": "160",
    }
    catalog = _catalog_with_kwargs(tmp_path, kwargs)
    runner = _Recorder(_trial_result(1.0))
    execute_control_plane_run(
        plan=_agent_plan(kwargs=kwargs),
        output_path=tmp_path / "e.jsonl",
        artifacts_dir=tmp_path / "art",
        harbor_process_runner=runner,
        run_id="cf2-literals",
        agent_catalog=catalog,
    )
    (cmd,) = runner.calls
    tokens = _kwarg_tokens(cmd)
    assert 'session_id="None"' in tokens
    assert 'tmux_pane_width="160"' in tokens
    assert json.loads('"None"') == "None" and json.loads('"160"') == "160"
    with pytest.raises(BenchEvalError, match="whitespace"):
        _catalog_with_kwargs(tmp_path / "ws", {"parser_name": " json"})


def test_failed_agent_attempt_still_carries_the_confirmed_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _launch_env(monkeypatch)
    plan = _agent_plan()

    def timing_out(command, *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        from bencheval.exceptions import AdapterFailureError

        raise AdapterFailureError(
            "harbor CLI timed out", failure_label="runtime_budget_exceeded", latency_sec=1.0
        )

    evidence = tmp_path / "evidence.jsonl"
    execute_control_plane_run(
        plan=plan,
        output_path=evidence,
        artifacts_dir=tmp_path / "art",
        harbor_process_runner=timing_out,
        run_id="cf2-timeout",
    )
    (row,) = read_evidence_jsonl(evidence)
    assert row.primary_pass is False and row.failure_class == "runtime_budget_exceeded"
    assert row.agent_id == _AGENT and row.runtime_id is None
    assert row.adapter_metadata["actor_binding_sha256"] == plan.actor_binding_snapshot.sha256
    assert row.adapter_metadata["model_binding_sha256"] == plan.model_binding_snapshot.sha256
    assert any(path.endswith(_ACTOR_MANIFEST) for path in row.artifact_paths)
    assert row.runtime_config_hash is not None
