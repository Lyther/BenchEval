"""CF2.1 contracts: runtime profiles select Harbor behavior through a closed
``launch.harbor`` binding, never through the public runtime id.

Architecture §23.6 / roadmap CF2.1. Expected values come from the accepted
design text, the shipped profiles' current effective launch (a human-locked
example that must be preserved), and the read-only probe of the installed
Harbor 0.17.1 agent registry on dev-box-cpu (2026-09-08), not from the
implementation under test.

SUBSTITUTE_JUSTIFICATION
- substitute: temporary runtime-profile directories derived from the shipped
  YAML through the real loader, an argv-recording Harbor runner, and the
  locked list of installed Harbor 0.17.1 agent names
- replaces: editing config/runtimes/ for every renamed/invalid profile and a
  Harbor/Docker launch for the fail-before-launch cases
- necessity: a renamed profile, an unknown selector, and a forbidden recipe
  must be forced deterministically without a container or provider charge
- real-option: the installed-registry case runs against the real Harbor
  distribution where it is installed (dev-box) and skips elsewhere
- proof-limit: proves binding resolution and argv/identity construction; the
  Claude/Codex live re-proof and the Terminus-2 attempt belong to CF2.3
- real-proof: CF2.3 dev-box attempts (pending)
- covered tests: every test in this module
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml

from bencheval.benchmark_plan import plan_control_plane
from bencheval.domain import HarborRuntimeBinding, RuntimeCatalog
from bencheval.exceptions import BenchEvalError
from bencheval.runtime_registry import (
    default_runtimes_dir,
    load_runtime_catalog,
    load_runtime_profile,
)
from bencheval.terminal_bench_harbor import (
    CLAUDE_CODE_NPM_IMPORT_PATH,
    CODEX_NPM_IMPORT_PATH,
    HarborCliResult,
    build_harbor_run_command,
    installed_harbor_agent_names,
    run_terminal_bench_instance,
    verify_harbor_runtime_binding,
)

# Selectors this spec relies on, each confirmed present in the read-only probe
# of ``harbor.models.agent.name.AgentName`` (pinned Harbor 0.17.1, dev-box-cpu,
# 2026-09-08). The full upstream enum is a dependency detail, not a BenchEval
# support promise, so only this subset is locked.
_INSTALLED_SELECTORS: tuple[str, ...] = ("claude-code", "codex", "gemini-cli", "terminus-2")
# §23.6: the two shipped CLI integrations keep their code-owned install recipes.
_CLAUDE_BINDING = {
    "agent": "claude-code",
    "install_recipe": "claude_code_npm",
    "setup_timeout_multiplier": 8,
}
_CODEX_BINDING = {"agent": "codex", "install_recipe": "codex_npm", "setup_timeout_multiplier": 8}
_LAUNCH_ENV = (
    "ANTHROPIC_BASE_URL",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "BENCHEVAL_CLAUDE_CODE_ALLOWED_TOOLS",
    "NO_PROXY",
    "no_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "http_proxy",
    "https_proxy",
    "BENCHEVAL_HARBOR_FORWARD_PROXY",
)


def _profile(
    base_id: str, *, runtime_id: str, harbor: dict[str, object] | None, pin: str | None = None
) -> dict[str, object]:
    raw = load_runtime_profile(default_runtimes_dir() / f"{base_id}.yaml").model_dump(mode="json")
    raw["runtime"]["id"] = runtime_id
    raw["launch"]["harbor"] = harbor
    if pin is not None:
        raw["versioning"]["agent_version_pin"] = pin
    return raw


def _catalog(tmp_path: Path, *profiles: dict[str, object]) -> RuntimeCatalog:
    d = tmp_path / "runtimes"
    d.mkdir(parents=True)
    for raw in profiles:
        (d / f"{raw['runtime']['id']}.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_runtime_catalog(d)


def _clear_launch_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _LAUNCH_ENV:
        monkeypatch.delenv(name, raising=False)


def _recorder(calls: list[tuple[str, ...]]):
    def run(command: Sequence[str], *, cwd: Path | None, timeout_sec: int) -> HarborCliResult:
        calls.append(tuple(command))
        return HarborCliResult(
            returncode=0, stdout="", stderr="", latency_sec=0.0, command=tuple(command)
        )

    return run


def _expected_shipped_argv(
    *, agent_import_path: str, pin: str, extra: tuple[str, ...], artifacts_dir: Path, model: str
) -> tuple[str, ...]:
    return (
        "harbor",
        "run",
        "--yes",
        "--agent",
        agent_import_path,
        "--agent-setup-timeout-multiplier",
        "8",
        "--agent-kwarg",
        f"version={pin}",
        *extra,
        "--dataset",
        "terminal-bench/terminal-bench-2-1",
        "--include-task-name",
        "terminal-bench/fix-git",
        "--jobs-dir",
        str((artifacts_dir / "harbor-package").resolve()),
        "--n-concurrent",
        "1",
        "--model",
        model,
    )


# --- preserved behavior (human-locked example) --------------------------------------


def test_shipped_profiles_preserve_their_effective_launch_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact argv the shipped profiles launch today is the migration contract."""
    _clear_launch_env(monkeypatch)
    claude = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    codex = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="codex-cli",
        model_id="glm-5.2",
    )
    assert build_harbor_run_command(
        plan=claude, instance_id="fix-git", artifacts_dir=tmp_path
    ) == _expected_shipped_argv(
        agent_import_path=CLAUDE_CODE_NPM_IMPORT_PATH,
        pin="2.1.235",
        extra=("--agent-env", "ANTHROPIC_CUSTOM_MODEL_OPTION=kimi-k2.7-code"),
        artifacts_dir=tmp_path,
        model="kimi-k2.7-code",
    )
    assert build_harbor_run_command(
        plan=codex, instance_id="fix-git", artifacts_dir=tmp_path
    ) == _expected_shipped_argv(
        agent_import_path=CODEX_NPM_IMPORT_PATH,
        pin="0.148.0",
        extra=(),
        artifacts_dir=tmp_path,
        model="glm-5.2",
    )


# --- CF2.1 ---------------------------------------------------------------------------


def test_shipped_runtime_profiles_declare_their_harbor_driver_binding() -> None:
    catalog = load_runtime_catalog()
    assert catalog.by_id("claude-code").launch.harbor == HarborRuntimeBinding(**_CLAUDE_BINDING)
    assert catalog.by_id("codex-cli").launch.harbor == HarborRuntimeBinding(**_CODEX_BINDING)


def test_public_profile_id_does_not_select_harbor_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A renamed copy of the Claude profile with the same binding launches identically."""
    _clear_launch_env(monkeypatch)
    catalog = _catalog(
        tmp_path,
        _profile("claude-code", runtime_id="claude-code", harbor=_CLAUDE_BINDING),
        _profile("claude-code", runtime_id="claude-code-alt", harbor=_CLAUDE_BINDING),
    )
    commands = []
    for runtime_id in ("claude-code", "claude-code-alt"):
        plan = plan_control_plane(
            benchmark_id="terminal-bench",
            slice_id="tier1-one",
            runtime_id=runtime_id,
            model_id="kimi-k2.7-code",
            runtime_catalog=catalog,
        )
        commands.append(
            build_harbor_run_command(
                plan=plan, instance_id="fix-git", artifacts_dir=tmp_path, runtime_catalog=catalog
            )
        )
    assert commands[0] == commands[1]
    assert commands[1][commands[1].index("--agent") + 1] == CLAUDE_CODE_NPM_IMPORT_PATH
    assert "ANTHROPIC_CUSTOM_MODEL_OPTION=kimi-k2.7-code" in commands[1]


def test_new_selector_on_the_installed_driver_needs_no_python_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A YAML-only profile naming a built-in Harbor agent launches by name: no
    install recipe, no BenchEval import path, no launch-time version kwarg (the
    built-in identity is compared against the catalog pin after the run)."""
    _clear_launch_env(monkeypatch)
    catalog = _catalog(
        tmp_path,
        _profile(
            "codex-cli", runtime_id="gemini-cli-native", harbor={"agent": "gemini-cli"}, pin="1.0.0"
        ),
    )
    binding = catalog.by_id("gemini-cli-native").launch.harbor
    assert binding is not None
    verify_harbor_runtime_binding(binding, installed_agents=_INSTALLED_SELECTORS)
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="gemini-cli-native",
        model_id="glm-5.2",
        runtime_catalog=catalog,
    )
    cmd = build_harbor_run_command(
        plan=plan, instance_id="fix-git", artifacts_dir=tmp_path, runtime_catalog=catalog
    )
    assert cmd[cmd.index("--agent") + 1] == "gemini-cli"
    assert not any(token.startswith("bencheval.") for token in cmd)
    assert not any(token.startswith("version=") for token in cmd)
    assert "--agent-setup-timeout-multiplier" not in cmd


def test_unsupported_selector_or_recipe_fails_before_any_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_launch_env(monkeypatch)
    # Closed recipe vocabulary: YAML cannot name arbitrary installation code.
    with pytest.raises(BenchEvalError, match="install_recipe"):
        _catalog(
            tmp_path / "recipe",
            _profile(
                "codex-cli",
                runtime_id="curl-pipe",
                harbor={"agent": "codex", "install_recipe": "curl_pipe_sh"},
            ),
        )
    catalog = _catalog(
        tmp_path / "selector",
        _profile("codex-cli", runtime_id="ghost-agent", harbor={"agent": "not-an-agent"}, pin="1"),
    )
    binding = catalog.by_id("ghost-agent").launch.harbor
    assert binding is not None
    with pytest.raises(BenchEvalError, match="not an installed Harbor agent"):
        verify_harbor_runtime_binding(binding, installed_agents=_INSTALLED_SELECTORS)
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="ghost-agent",
        model_id="glm-5.2",
        runtime_catalog=catalog,
    )
    calls: list[tuple[str, ...]] = []
    with pytest.raises(BenchEvalError, match="not an installed Harbor agent"):
        run_terminal_bench_instance(
            plan=plan,
            instance_id="fix-git",
            artifacts_dir=tmp_path / "art",
            repo_root=tmp_path,
            process_runner=_recorder(calls),
            runtime_catalog=catalog,
            installed_agents=_INSTALLED_SELECTORS,
        )
    assert calls == []


def test_conflicting_install_recipe_is_rejected_at_the_schema_boundary(tmp_path: Path) -> None:
    """A recipe installs exactly one upstream agent; naming another cannot launch."""
    for index, (agent, recipe) in enumerate(
        (("codex", "claude_code_npm"), ("claude-code", "codex_npm"))
    ):
        with pytest.raises(BenchEvalError, match="install_recipe"):
            _catalog(
                tmp_path / f"conflict-{index}",
                _profile(
                    "codex-cli",
                    runtime_id="conflicting",
                    harbor={"agent": agent, "install_recipe": recipe},
                ),
            )


def test_installed_harbor_registers_the_selectors_this_spec_relies_on() -> None:
    """Uncharged native-interface evidence against the real pinned distribution."""
    pytest.importorskip("harbor")
    assert set(_INSTALLED_SELECTORS) <= set(installed_harbor_agent_names())


def test_runtime_profile_changed_after_planning_is_refused_before_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The confirmed runtime binding must still be the profile's binding at launch."""
    _clear_launch_env(monkeypatch)
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    assert plan.actor_binding_snapshot is not None
    assert plan.actor_binding_snapshot.actor_kind == "runtime"
    assert plan.actor_binding_snapshot.agent_version_pin == "2.1.235"
    drifted = _catalog(
        tmp_path,
        _profile("claude-code", runtime_id="claude-code", harbor=_CLAUDE_BINDING, pin="2.1.236"),
    )
    calls: list[tuple[str, ...]] = []
    with pytest.raises(BenchEvalError, match="changed since planning"):
        run_terminal_bench_instance(
            plan=plan,
            instance_id="fix-git",
            artifacts_dir=tmp_path / "art",
            repo_root=tmp_path,
            process_runner=_recorder(calls),
            runtime_catalog=drifted,
        )
    assert calls == []


def test_doctor_verifies_runtime_and_agent_bindings_against_installed_harbor() -> None:
    pytest.importorskip("harbor")
    from bencheval.doctor import run_doctor

    def check(**selection: str):
        report = run_doctor("harbor", **selection)
        return next(c for c in report.checks if c.name == "harbor_actor_binding")

    assert check(runtime_id="claude-code").status == "pass"
    assert check(runtime_id="codex-cli").status == "pass"
    terminus = check(agent_id="terminus-2")
    assert terminus.status == "pass" and "2.0.0" in terminus.message
    assert check(agent_id="momo").status == "fail"
    assert check(runtime_id="no-such-runtime").status == "fail"
