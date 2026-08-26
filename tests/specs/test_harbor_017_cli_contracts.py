"""RED contracts for the locked Harbor 0.17.1 run CLI.

Live `harbor 0.17.1` rejected `--task-name`. The dataset instance selector is
`--include-task-name` with Harbor's namespaced id (`terminal-bench/fix-git`).
A custom Claude agent is `--agent module:Class`. `--agent-import-path` is
absent from `harbor run -h` (hidden deprecated alias).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import BenchEvalError
from bencheval.harbor_claude_code_npm import ClaudeCodeNpmInstall
from bencheval.harbor_codex_npm import _NODE_DIST, _NODE_TARBALL_SHA256, CodexNpmInstall
from bencheval.terminal_bench_harbor import (
    CLAUDE_CODE_NPM_IMPORT_PATH,
    CODEX_NPM_IMPORT_PATH,
    build_harbor_run_command,
)


def test_harbor_run_command_forwards_provider_base_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://172.17.0.1:4011")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://172.17.0.1:4011/v1")
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    cmd = build_harbor_run_command(
        plan=plan,
        instance_id="fix-git",
        artifacts_dir=Path("/tmp/harbor-017-cli"),
    )
    env_tokens = [cmd[i + 1] for i, tok in enumerate(cmd[:-1]) if tok == "--agent-env"]
    assert "ANTHROPIC_BASE_URL=http://172.17.0.1:4011" in env_tokens
    assert "OPENAI_BASE_URL=http://172.17.0.1:4011/v1" in env_tokens
    assert all("@" not in token for token in env_tokens)


@pytest.mark.parametrize(
    "url",
    [
        "http://172.17.0.1:4011?api_key=leak",
        "http://172.17.0.1:4011#frag",
    ],
)
def test_harbor_run_command_refuses_query_or_fragment_base_url(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url)
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    with pytest.raises(BenchEvalError, match="query or fragment"):
        build_harbor_run_command(
            plan=plan,
            instance_id="fix-git",
            artifacts_dir=Path("/tmp/harbor-017-cli"),
        )


def test_harbor_run_command_refuses_unsafe_custom_model_option() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    for model_id in ("kimi k2.7-code", "kimi=k2.7-code"):
        unsafe = plan.model_copy(update={"model_id": model_id})
        with pytest.raises(BenchEvalError, match="ANTHROPIC_CUSTOM_MODEL_OPTION"):
            build_harbor_run_command(
                plan=unsafe,
                instance_id="fix-git",
                artifacts_dir=Path("/tmp/harbor-017-cli"),
            )


def test_harbor_run_command_refuses_userinfo_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://user:secret@172.17.0.1:4011")
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    with pytest.raises(BenchEvalError, match="userinfo"):
        build_harbor_run_command(
            plan=plan,
            instance_id="fix-git",
            artifacts_dir=Path("/tmp/harbor-017-cli"),
        )


def test_harbor_run_command_forwards_claude_custom_model_option() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    cmd = build_harbor_run_command(
        plan=plan,
        instance_id="fix-git",
        artifacts_dir=Path("/tmp/harbor-017-cli"),
    )
    env_tokens = [cmd[i + 1] for i, tok in enumerate(cmd[:-1]) if tok == "--agent-env"]
    assert "ANTHROPIC_CUSTOM_MODEL_OPTION=kimi-k2.7-code" in env_tokens


def test_harbor_run_command_does_not_forward_custom_model_for_codex() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )
    cmd = build_harbor_run_command(
        plan=plan,
        instance_id="fix-git",
        artifacts_dir=Path("/tmp/harbor-017-codex"),
    )
    env_tokens = [cmd[i + 1] for i, tok in enumerate(cmd[:-1]) if tok == "--agent-env"]
    assert all("ANTHROPIC_CUSTOM_MODEL_OPTION=" not in token for token in env_tokens)


def test_harbor_run_command_uses_017_dataset_selector() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    cmd = build_harbor_run_command(
        plan=plan,
        instance_id="fix-git",
        artifacts_dir=Path("/tmp/harbor-017-cli"),
    )

    assert cmd[cmd.index("--include-task-name") + 1] == "terminal-bench/fix-git"
    assert "--task-name" not in cmd
    assert cmd[cmd.index("--agent") + 1] == CLAUDE_CODE_NPM_IMPORT_PATH
    assert "--agent-import-path" not in cmd


def test_harbor_run_command_uses_codex_npm_agent() -> None:
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="tier1-one",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )
    cmd = build_harbor_run_command(
        plan=plan,
        instance_id="fix-git",
        artifacts_dir=Path("/tmp/harbor-017-codex"),
    )
    assert cmd[cmd.index("--agent") + 1] == CODEX_NPM_IMPORT_PATH
    assert cmd[cmd.index("--include-task-name") + 1] == "terminal-bench/fix-git"


def test_codex_npm_install_pins_node_tarball_and_links_usr_local_bin(
    tmp_path: Path,
) -> None:
    # SUBSTITUTE_JUSTIFICATION
    # - substitute: recording exec_as_root/exec_as_agent on CodexNpmInstall
    # - replaces: a Harbor container install of Node + @openai/codex
    # - necessity: assert nvm is absent and /usr/local/bin links are emitted
    #   without launching Docker/npm
    # - real-option: live Harbor install; not deterministic in CI
    # - proof-limit: command-shape only; does not prove npm/Harbor succeed
    # - real-proof: live Terminal-Bench codex-cli install on the operator host
    import asyncio

    recorded: list[str] = []

    class _RecordingInstallAgent(CodexNpmInstall):
        async def exec_as_root(self, environment, command, env=None):
            recorded.append(command)

        async def exec_as_agent(self, environment, command, env=None):
            recorded.append(command)

    agent = _RecordingInstallAgent(logs_dir=tmp_path, version="0.148.0")
    asyncio.run(agent.install(environment=object()))
    assert len(recorded) == 3
    install_command = recorded[1]
    link_command = recorded[2]
    assert "nvm" not in install_command
    assert "@openai/codex@0.148.0" in install_command
    assert _NODE_TARBALL_SHA256 in install_command
    assert "sha256sum -c" in install_command
    assert "/tmp/bencheval-codex-bins" in install_command
    assert "mkdir -p /usr/local/bin" in link_command
    assert "/usr/local/bin/node" in link_command
    assert "/usr/local/bin/codex" in link_command
    assert "/tmp/bencheval-codex-bins" in link_command
    assert f".local/{_NODE_DIST}/bin/codex" in link_command


def test_codex_npm_writes_http_provider_into_codex_home_config(tmp_path: Path) -> None:
    # Harbor Codex.run() reads $CODEX_HOME/config.toml (/tmp/codex-home), not
    # the evidence mount at /logs/agent/config.toml. Live 20260825T163552Z
    # used websocket via the host proxy because only openai_base_url was set.
    agent = CodexNpmInstall(logs_dir=tmp_path, version="0.148.0")
    command = agent._build_register_mcp_servers_command()
    assert command is not None
    assert 'cat >"$CODEX_HOME/config.toml"' in command
    assert 'model_provider = "bytellm"' in command
    assert 'base_url = "${OPENAI_BASE_URL}"' in command
    assert 'wire_api = "responses"' in command
    assert "supports_websockets = false" in command
    assert "[model_providers.bytellm]" in command
    assert "/logs/agent/config.toml" not in command


def test_codex_exec_clears_forwarded_proxy(tmp_path: Path) -> None:
    # SUBSTITUTE_JUSTIFICATION
    # - substitute: recording _exec on CodexNpmInstall
    # - replaces: Harbor docker exec of `codex exec` with a forwarded host proxy
    # - necessity: assert proxy vars are cleared without launching Docker/Codex
    # - real-option: live Harbor exec; not deterministic in CI
    # - proof-limit: env-shape only; does not prove Codex honors empty proxy
    # - real-proof: live Terminal-Bench codex-cli on the operator host
    # Live 20260825T165018Z reached HTTP /v1/responses but received the
    # corporate-proxy HTML 403. Codex exec must not inherit forwarded http_proxy
    # for 172.17.0.1.
    import asyncio

    recorded: list[dict[str, object]] = []

    class _Probe(CodexNpmInstall):
        async def _exec(
            self, environment, command, user=None, env=None, cwd=None, timeout_sec=None
        ):
            recorded.append({"command": command, "env": env})

            class _Result:
                return_code = 0
                stdout = ""
                stderr = ""

            return _Result()

    agent = _Probe(logs_dir=tmp_path, version="0.148.0")
    forwarded = {
        "http_proxy": "http://sys-proxy-rd-relay.byted.org:8118",
        "https_proxy": "http://sys-proxy-rd-relay.byted.org:8118",
        "HTTP_PROXY": "http://sys-proxy-rd-relay.byted.org:8118",
        "HTTPS_PROXY": "http://sys-proxy-rd-relay.byted.org:8118",
        "OPENAI_BASE_URL": "http://172.17.0.1:4011/v1",
    }
    asyncio.run(
        agent.exec_as_agent(
            object(),
            "npm install -g --no-audit --no-fund @openai/codex@0.148.0",
            env=dict(forwarded),
        )
    )
    asyncio.run(
        agent.exec_as_agent(
            object(),
            "codex exec --model kimi-k2.7-code",
            env=dict(forwarded),
        )
    )
    assert len(recorded) == 2
    install_env = recorded[0]["env"]
    exec_env = recorded[1]["env"]
    assert isinstance(install_env, dict)
    assert isinstance(exec_env, dict)
    assert install_env["http_proxy"] == forwarded["http_proxy"]
    assert install_env["https_proxy"] == forwarded["https_proxy"]
    assert install_env["HTTP_PROXY"] == forwarded["HTTP_PROXY"]
    assert install_env["HTTPS_PROXY"] == forwarded["HTTPS_PROXY"]
    assert exec_env["http_proxy"] == ""
    assert exec_env["https_proxy"] == ""
    assert exec_env["HTTP_PROXY"] == ""
    assert exec_env["HTTPS_PROXY"] == ""
    assert exec_env["OPENAI_BASE_URL"] == "http://172.17.0.1:4011/v1"


def test_claude_print_clears_forwarded_proxy(tmp_path: Path) -> None:
    # SUBSTITUTE_JUSTIFICATION
    # - substitute: recording _exec on ClaudeCodeNpmInstall
    # - replaces: Harbor docker exec of `claude --verbose` with a forwarded host proxy
    # - necessity: assert proxy vars are cleared without launching Docker/Claude
    # - real-option: live Harbor exec; not deterministic in CI
    # - proof-limit: env-shape only; does not prove Claude honors empty proxy
    # - real-proof: live Terminal-Bench claude-code on the operator host
    # Live 20260825T161739Z never reached the shim (duration_api_ms=0). After
    # CUSTOM_MODEL_OPTION, Claude must not inherit forwarded http_proxy for
    # 172.17.0.1:4011 (same CONNECT 403 as Codex).
    import asyncio

    recorded: list[dict[str, object]] = []

    class _Probe(ClaudeCodeNpmInstall):
        async def _exec(
            self, environment, command, user=None, env=None, cwd=None, timeout_sec=None
        ):
            recorded.append({"command": command, "env": env})

            class _Result:
                return_code = 0
                stdout = ""
                stderr = ""

            return _Result()

    agent = _Probe(logs_dir=tmp_path, version="2.1.235")
    forwarded = {
        "http_proxy": "http://sys-proxy-rd-relay.byted.org:8118",
        "https_proxy": "http://sys-proxy-rd-relay.byted.org:8118",
        "HTTP_PROXY": "http://sys-proxy-rd-relay.byted.org:8118",
        "HTTPS_PROXY": "http://sys-proxy-rd-relay.byted.org:8118",
        "ANTHROPIC_BASE_URL": "http://172.17.0.1:4011",
    }
    asyncio.run(
        agent.exec_as_agent(
            object(),
            "npm install -g --no-audit --no-fund @anthropic-ai/claude-code@2.1.235",
            env=dict(forwarded),
        )
    )
    asyncio.run(
        agent.exec_as_agent(
            object(),
            'export PATH="$HOME/.local/bin:$PATH"; claude --verbose --print -- hi',
            env=dict(forwarded),
        )
    )
    assert len(recorded) == 2
    install_env = recorded[0]["env"]
    exec_env = recorded[1]["env"]
    assert isinstance(install_env, dict)
    assert isinstance(exec_env, dict)
    assert install_env["http_proxy"] == forwarded["http_proxy"]
    assert exec_env["http_proxy"] == ""
    assert exec_env["https_proxy"] == ""
    assert exec_env["HTTP_PROXY"] == ""
    assert exec_env["HTTPS_PROXY"] == ""
    assert exec_env["ANTHROPIC_BASE_URL"] == "http://172.17.0.1:4011"


def test_locked_harbor_help_matches_emitted_flags() -> None:
    try:
        import click
        from harbor.cli.main import app as harbor_app
        from typer.main import get_command
    except ImportError:
        pytest.skip("harbor CLI not installed")

    root = get_command(harbor_app)
    run = root.get_command(click.Context(root), "run")
    assert run is not None
    options = {
        option: parameter
        for parameter in run.params
        for option in (
            tuple(getattr(parameter, "opts", ())) + tuple(getattr(parameter, "secondary_opts", ()))
        )
    }

    assert "--include-task-name" in options
    assert "--task-name" not in options
    assert "module.path:ClassName" in (options["--agent"].help or "")
    assert options["--agent-import-path"].hidden is True
