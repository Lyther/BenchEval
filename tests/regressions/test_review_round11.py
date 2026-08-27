"""Round-11 review findings: Harbor real-schema verdicts (F002) + agent version pins (F003).

SUBSTITUTE_JUSTIFICATION
- substitute: (a) the recorded artifact
  ``tests/regressions/data/tb_harbor_trial_result_pass.json`` (a verbatim copy of
  ``results/raw/tb-claude-code-haiku-one-20260618T150500Z/fix-git/2026-06-18__23-05-50/fix-git__WK9ABoL/result.json``
  with only the two operator-home path fields ``trial_uri`` and
  ``config.trials_dir`` sanitized, plus the proxy-env values
  ``config.agent.env.NO_PROXY``/``no_proxy`` trimmed to ``127.0.0.1,localhost``
  to drop internal proxy hosts); (b) synthetic ``result.json`` payloads
  constructed by the stub ``HarborProcessRunner`` callables and parse-level
  tests below; (c) ``_RecordingInstallAgent`` overriding the container
  command-execution boundary; (d) a monkeypatched ``_run_version_command`` spy
- replaces: (a)(b) the external Harbor CLI process, its Docker environment, and
  the trial result files a real run would author; (c) the container-side
  npm/Node install commands; (d) the host runtime CLI version probe
- necessity: the assertions require deterministic verdict and agent-identity
  states (partial rewards, malformed verifier payloads, absent/mismatched
  agent_info, install-command content) that a live Harbor run cannot safely and
  deterministically manufacture on demand; (d) observing whether the host probe
  is invoked requires intercepting that seam without executing host CLIs
- real-option: the dev-box Harbor live lane with Docker and provider
  credentials; not available in the local Tier-0 environment
- proof-limit: proves BenchEval-side parsing, command construction, provenance
  stamping, and fail-closed mappings only — not Harbor execution, verifier
  correctness, agent behavior, or live readiness
- real-proof: BLOCKED until the dev-box live lane re-qualifies with pinned
  agent versions (docs/ops/dev-box-pilot.md)
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest

from bencheval import terminal_bench_harbor
from bencheval.benchmark_plan import plan_control_plane
from bencheval.control_plane_executor import (
    _capture_runtime_provenance,
    execute_control_plane_run,
)
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.harbor_claude_code_npm import ClaudeCodeNpmInstall
from bencheval.runtime_registry import load_runtime_catalog
from bencheval.terminal_bench_harbor import (
    HarborCliResult,
    build_harbor_run_command,
    parse_harbor_instance_outcome,
)

_RECORDED_PASS_ARTIFACT = Path(__file__).parent / "data" / "tb_harbor_trial_result_pass.json"

# Reviewer-measured registry versions pinned in config/runtimes/*.yaml.
_EXPECTED_PINS = {"claude-code": "2.1.235", "codex-cli": "0.148.0"}


def _tb_plan(runtime_id: str = "claude-code"):
    return plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id=runtime_id,
        model_id="kimi-k2.7-code",
    )


def _real_schema_result(
    *,
    reward: object = 1.0,
    agent_name: object = "claude-code",
    agent_version: object = "2.1.235",
    omit_agent_info: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "verifier_result": {"rewards": {"reward": reward}},
        "exception_info": None,
    }
    if not omit_agent_info:
        payload["agent_info"] = {
            "name": agent_name,
            "version": agent_version,
            "model_info": None,
        }
    return payload


def _parse(tmp_path: Path, payload: dict[str, object], **kwargs):
    art = tmp_path / "inst"
    art.mkdir()
    (art / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    return parse_harbor_instance_outcome(
        instance_id="tb-1",
        cli=HarborCliResult(0, "", "", 0.1, ("harbor", "run")),
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="harbor@test",
        **kwargs,
    )


# ---------------------------------------------------------------- F002 -----


def test_f002_recorded_real_trial_result_scores_as_pass(tmp_path: Path) -> None:
    """The retained real dev-box artifact (reward 1.0, exception_info null) passes."""
    art = tmp_path / "inst"
    art.mkdir()
    shutil.copyfile(_RECORDED_PASS_ARTIFACT, art / "result.json")
    out = parse_harbor_instance_outcome(
        instance_id="fix-git",
        cli=HarborCliResult(0, "", "", 0.1, ("harbor", "run")),
        artifacts_dir=art,
        repo_root=tmp_path,
        harness_version="harbor@test",
    )
    assert out.primary_pass is True
    assert out.partial_score == 1.0
    assert out.failure_class is None
    assert out.native_score["verdict_provenance"] == "harbor_verifier_result"
    # agent_info is extracted unconditionally (F003 stamp source).
    assert out.agent_name == "claude-code"
    assert out.agent_version == "2.1.181"


@pytest.mark.parametrize(
    ("reward", "expected_pass", "expected_partial"),
    [
        pytest.param(1.0, True, 1.0, id="reward-1.0-passes"),
        pytest.param(1, True, 1.0, id="reward-int-1-passes"),
        pytest.param(0.0, False, 0.0, id="reward-0.0-is-model-failure"),
        pytest.param(0.5, False, 0.5, id="reward-0.5-partial-credit"),
    ],
)
def test_f002_official_reward_rule(
    tmp_path: Path,
    reward: object,
    expected_pass: bool,
    expected_partial: float,
) -> None:
    """Official passing rule: reward == 1.0; sub-1.0 rewards are partial credit."""
    out = _parse(tmp_path, _real_schema_result(reward=reward))
    assert out.primary_pass is expected_pass
    assert out.partial_score == expected_partial
    if expected_pass:
        assert out.failure_class is None
    else:
        assert out.failure_class == "model_wrong_solution"
    assert out.native_score["verdict_provenance"] == "harbor_verifier_result"


@pytest.mark.parametrize(
    "verifier_result",
    [
        pytest.param({"rewards": {"reward": True}}, id="reward-bool"),
        pytest.param({"rewards": {"reward": "1.0"}}, id="reward-str"),
        pytest.param({"rewards": {"reward": None}}, id="reward-null"),
        pytest.param({"rewards": {}}, id="reward-missing"),
        pytest.param({"rewards": {"reward": 1.5}}, id="reward-out-of-range"),
        pytest.param({"rewards": {"reward": float("nan")}}, id="reward-nan"),
        pytest.param({"rewards": {"reward": float("inf")}}, id="reward-infinity"),
        pytest.param({"rewards": [1.0]}, id="rewards-not-a-dict"),
        pytest.param(None, id="verifier-result-null"),
        pytest.param("1.0", id="verifier-result-not-a-dict"),
    ],
)
def test_f002_malformed_verifier_result_fails_closed(
    tmp_path: Path,
    verifier_result: object,
) -> None:
    payload = _real_schema_result()
    payload["verifier_result"] = verifier_result
    out = _parse(tmp_path, payload)
    assert out.primary_pass is False
    assert out.partial_score == 0.0
    assert out.failure_class == "runtime_output_unparseable"


def test_f002_malformed_verifier_result_cannot_fall_back_to_legacy_keys(
    tmp_path: Path,
) -> None:
    """A present-but-malformed verifier_result must not fall back to the legacy
    top-level booleans — the official schema is authoritative once present."""
    payload = _real_schema_result()
    payload["verifier_result"] = {"rewards": {"reward": "1.0"}}
    payload["resolved"] = True
    out = _parse(tmp_path, payload)
    assert out.primary_pass is False
    assert out.failure_class == "runtime_output_unparseable"


def test_f002_verifier_result_dominates_legacy_keys(tmp_path: Path) -> None:
    payload = _real_schema_result(reward=1.0)
    payload["resolved"] = False
    out = _parse(tmp_path, payload)
    assert out.primary_pass is True
    assert out.native_score["verdict_provenance"] == "harbor_verifier_result"


def test_f002_legacy_boolean_path_kept_and_provenance_stamped(tmp_path: Path) -> None:
    out = _parse(tmp_path, {"resolved": True})
    assert out.primary_pass is True
    assert out.partial_score == 1.0
    assert out.failure_class is None
    assert out.native_score["verdict_provenance"] == "legacy_top_level_boolean"


def test_f002_exception_info_still_dominates_verifier_result(tmp_path: Path) -> None:
    payload = _real_schema_result(reward=1.0)
    payload["exception_info"] = {"exception_type": "AgentTimeoutError"}
    out = _parse(tmp_path, payload)
    assert out.primary_pass is False
    assert out.failure_class == "runtime_launch_failure"


@pytest.mark.parametrize(
    "exception_info",
    [
        pytest.param("AgentTimeoutError", id="exception-info-str"),
        pytest.param(["AgentTimeoutError"], id="exception-info-list"),
        pytest.param(True, id="exception-info-bool"),
    ],
)
def test_f002a_non_object_exception_info_is_a_schema_violation(
    tmp_path: Path,
    exception_info: object,
) -> None:
    """``exception_info`` must be absent, null, or an object (Harbor
    ``ExceptionInfo``). A present-but-non-object value is not the official
    schema; even a pass-bearing reward cannot rescue the artifact."""
    payload = _real_schema_result(reward=1.0)
    payload["exception_info"] = exception_info
    out = _parse(tmp_path, payload)
    assert out.primary_pass is False
    assert out.partial_score == 0.0
    assert out.failure_class == "runtime_output_unparseable"


def test_f002_stats_errors_still_dominate_verifier_result(tmp_path: Path) -> None:
    payload = _real_schema_result(reward=1.0)
    payload["stats"] = {"n_errors": 1}
    out = _parse(tmp_path, payload)
    assert out.primary_pass is False
    assert out.failure_class == "harness_failure"


# ---------------------------------------------------------------- F003 -----


def test_f003_runtime_catalog_pins_agent_versions() -> None:
    catalog = load_runtime_catalog()
    for runtime_id, pin in _EXPECTED_PINS.items():
        profile = catalog.by_id(runtime_id)
        assert profile.versioning.agent_version_pin == pin


@pytest.mark.parametrize("runtime_id", sorted(_EXPECTED_PINS))
def test_f003_build_command_pins_agent_version(runtime_id: str, tmp_path: Path) -> None:
    plan = _tb_plan(runtime_id)
    cmd = build_harbor_run_command(
        plan=plan,
        instance_id="tb-smoke-001",
        artifacts_dir=tmp_path / "art",
    )
    pin_tokens = [
        cmd[i + 1]
        for i, tok in enumerate(cmd[:-1])
        if tok == "--agent-kwarg" and cmd[i + 1].startswith("version=")
    ]
    assert pin_tokens == [f"version={_EXPECTED_PINS[runtime_id]}"]


def test_f003_missing_agent_version_pin_cannot_launch(tmp_path: Path) -> None:
    catalog = load_runtime_catalog()
    profile = catalog.by_id("claude-code")
    unpinned = profile.model_copy(
        update={"versioning": profile.versioning.model_copy(update={"agent_version_pin": None})},
    )
    modified = catalog.model_copy(update={"runtimes": (unpinned,)})
    with pytest.raises(BenchEvalError, match="agent_version_pin"):
        terminal_bench_harbor._harbor_agent_version_pin("claude-code", catalog=modified)


def test_f003_installer_requires_explicit_version(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="version"):
        ClaudeCodeNpmInstall(logs_dir=tmp_path)
    agent = ClaudeCodeNpmInstall(logs_dir=tmp_path, version="2.1.235")
    assert agent._version == "2.1.235"


def test_f003_install_command_pins_npm_version_and_verifies_node_checksum(
    tmp_path: Path,
) -> None:
    recorded: list[str] = []

    class _RecordingInstallAgent(ClaudeCodeNpmInstall):
        async def exec_as_root(self, environment, command, env=None):
            recorded.append(command)

        async def exec_as_agent(self, environment, command, env=None):
            recorded.append(command)

    agent = _RecordingInstallAgent(logs_dir=tmp_path, version="2.1.235")
    asyncio.run(agent.install(environment=object()))
    assert len(recorded) == 2
    install_command = recorded[-1]
    assert "npm install -g --no-audit --no-fund" in install_command
    assert "@anthropic-ai/claude-code@2.1.235" in install_command
    assert "sha256sum -c" in install_command
    from bencheval.harbor_claude_code_npm import _NODE_TARBALL_SHA256

    assert _NODE_TARBALL_SHA256 in install_command


@pytest.mark.parametrize(
    ("agent_info", "case_id"),
    [
        pytest.param(None, "agent-info-absent"),
        pytest.param({"name": "claude-code", "version": "0.0.0"}, "version-mismatch"),
        pytest.param({"name": "codex", "version": "2.1.235"}, "name-mismatch"),
        pytest.param({"name": "claude-code", "version": None}, "version-null"),
        pytest.param({"name": "claude-code"}, "version-key-missing"),
        pytest.param("claude-code", "agent-info-not-a-dict"),
    ],
)
def test_f003_uncaptured_agent_identity_fails_closed_as_config_drift(
    tmp_path: Path,
    agent_info: object,
    case_id: str,
) -> None:
    payload = _real_schema_result(reward=1.0, omit_agent_info=True)
    if agent_info is not None or case_id != "agent-info-absent":
        payload["agent_info"] = agent_info
    out = _parse(
        tmp_path,
        payload,
        expected_agent_name="claude-code",
        expected_agent_version="2.1.235",
    )
    assert out.primary_pass is False, case_id
    assert out.partial_score == 0.0, case_id
    assert out.failure_class == "runtime_config_drift", case_id


def test_f003_matching_agent_identity_preserves_pass_and_stamps_version(
    tmp_path: Path,
) -> None:
    out = _parse(
        tmp_path,
        _real_schema_result(reward=1.0),
        expected_agent_name="claude-code",
        expected_agent_version="2.1.235",
    )
    assert out.primary_pass is True
    assert out.failure_class is None
    assert out.agent_name == "claude-code"
    assert out.agent_version == "2.1.235"


def _stub_harbor_runner(payload: dict[str, object]):
    def _runner(command, *, cwd, timeout_sec: int) -> HarborCliResult:
        out_dir = Path(command[command.index("--jobs-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
        return HarborCliResult(0, "", "", 0.0, tuple(command))

    return _runner


def test_f003_evidence_row_runtime_version_is_container_agent_version(
    tmp_path: Path,
) -> None:
    plan = _tb_plan().model_copy(update={"instances": _tb_plan().instances[:1]})
    evidence_path = tmp_path / "evidence.jsonl"
    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        harbor_process_runner=_stub_harbor_runner(_real_schema_result(reward=1.0)),
        run_id="r11-agent-version",
    )
    assert summary.passed_count == 1
    rows = read_evidence_jsonl(evidence_path)
    assert len(rows) == 1
    # The agent ran inside the Harbor container; the host `claude --version`
    # probe is meaningless for this row and must not stamp it.
    assert rows[0].runtime_version == "2.1.235"


def test_f003_evidence_row_with_agent_version_mismatch_is_config_drift(
    tmp_path: Path,
) -> None:
    plan = _tb_plan().model_copy(update={"instances": _tb_plan().instances[:1]})
    evidence_path = tmp_path / "evidence.jsonl"
    payload = _real_schema_result(reward=1.0, agent_version="0.0.0")
    summary = execute_control_plane_run(
        plan=plan,
        output_path=evidence_path,
        artifacts_dir=tmp_path / "artifacts",
        harbor_process_runner=_stub_harbor_runner(payload),
        run_id="r11-agent-drift",
    )
    assert summary.passed_count == 0
    rows = read_evidence_jsonl(evidence_path)
    assert rows[0].failure_class == "runtime_config_drift"
    assert "runtime_config_drift" in rows[0].failure_labels
    assert rows[0].primary_pass is False


def test_f003_harbor_plans_skip_the_host_version_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        "bencheval.control_plane_executor._run_version_command",
        lambda command: calls.append(tuple(command)) or "host-x.y.z",
    )
    harbor = _capture_runtime_provenance(_tb_plan())
    assert calls == []
    assert harbor is not None
    assert harbor.runtime_version is None
    assert harbor.runtime_config_hash is not None

    swe_plan = plan_control_plane(
        benchmark_id="swe-bench-verified",
        slice_id="swe-bench-verified-smoke-10",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )
    swe = _capture_runtime_provenance(swe_plan)
    assert calls == []
    assert swe is not None
    assert swe.runtime_version is None
    assert swe.runtime_config_hash is not None


def test_f003_agent_version_pin_changes_runtime_config_hash() -> None:
    catalog = load_runtime_catalog()
    profile = catalog.by_id("claude-code")
    plan = _tb_plan()
    pinned = _capture_runtime_provenance(plan, profile=profile)
    other = _capture_runtime_provenance(
        plan,
        profile=profile.model_copy(
            update={
                "versioning": profile.versioning.model_copy(
                    update={"agent_version_pin": "9.9.9"},
                ),
            },
        ),
    )
    assert pinned is not None and other is not None
    assert pinned.runtime_config_hash != other.runtime_config_hash
    # Determinism: identical inputs hash identically.
    again = _capture_runtime_provenance(plan, profile=profile)
    assert again is not None
    assert again.runtime_config_hash == pinned.runtime_config_hash
