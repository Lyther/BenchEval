"""F003: Harbor must not put proxy secret values on argv."""

from __future__ import annotations

from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.terminal_bench_harbor import (
    build_harbor_run_command,
    write_harbor_proxy_env_file,
)

# SUBSTITUTE_JUSTIFICATION
# - substitute: monkeypatched proxy env with a literal test credential in
#   test_harbor_command_omits_proxy_secret_argv_tokens
# - replaces: operator proxy configuration/secret
# - necessity: argv non-disclosure needs a known canary and cannot use a real secret
# - real-option: real proxy credentials cannot safely appear in process metadata
# - proof-limit: proves command construction only, not live proxy/Harbor behavior
# - real-proof: live Harbor pilot plus local process inspection remains required

_SECRET_PROXY = "http://user:s3cr3t-proxy-token@proxy.example:8118"


def test_harbor_command_omits_proxy_secret_argv_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BENCHEVAL_HARBOR_FORWARD_PROXY", "1")
    monkeypatch.setenv("HTTPS_PROXY", _SECRET_PROXY)
    monkeypatch.setenv("https_proxy", _SECRET_PROXY)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    proxy_env = write_harbor_proxy_env_file(network_policy=plan.network_policy)
    assert proxy_env is not None
    try:
        cmd = build_harbor_run_command(
            plan=plan,
            instance_id="fix-git",
            artifacts_dir=tmp_path,
            proxy_env_file=proxy_env,
        )
        assert "--env-file" in cmd
        env_file = Path(cmd[cmd.index("--env-file") + 1])
        assert env_file.is_file()
        assert _SECRET_PROXY in env_file.read_text(encoding="utf-8")
        env_tokens = [cmd[i + 1] for i, tok in enumerate(cmd[:-1]) if tok == "--agent-env"]
        assert env_tokens == ["ANTHROPIC_CUSTOM_MODEL_OPTION=kimi-k2.7-code"]
        for token in cmd:
            assert _SECRET_PROXY not in token
            assert "s3cr3t-proxy-token" not in token
    finally:
        proxy_env.unlink(missing_ok=True)
