"""F014/F007: RunPlan.network_policy must gate Harbor launch network claims."""

from __future__ import annotations

from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import BenchEvalError
from bencheval.terminal_bench_harbor import (
    build_harbor_run_command,
    write_harbor_proxy_env_file,
)

# SUBSTITUTE_JUSTIFICATION
# - substitute: monkeypatched proxy env in
#   test_network_policy_deny_is_rejected_as_unenforceable and
#   test_network_policy_benchmark_required_allows_opt_in_proxy_forward
# - replaces: operator proxy state while retaining real command-policy logic
# - necessity: mutually exclusive network-policy states require controlled env
# - real-option: changing the host proxy between tests is unsafe/nondeterministic
# - proof-limit: proves launch-policy decisions, not container network enforcement
# - real-proof: BLOCKED until the live Harbor pilot observes the actual network path


def test_network_policy_deny_is_rejected_as_unenforceable(
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
    monkeypatch.setenv("https_proxy", "http://user:s3cr3t@proxy.example:8118")

    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    ).model_copy(update={"network_policy": "deny"})

    with pytest.raises(BenchEvalError, match="cannot enforce network_policy=deny"):
        build_harbor_run_command(
            plan=plan,
            instance_id="fix-git",
            artifacts_dir=tmp_path,
        )
    assert not (tmp_path / ".bencheval-harbor-proxy.env").exists()


def test_network_policy_benchmark_required_allows_opt_in_proxy_forward(
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
    monkeypatch.setenv("https_proxy", "http://proxy.example:8118")

    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    assert plan.network_policy == "benchmark_required"

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
        assert env_file.resolve() == proxy_env.resolve()
        assert env_file.parent != tmp_path
        assert "https_proxy=http://proxy.example:8118" in env_file.read_text(encoding="utf-8")
    finally:
        proxy_env.unlink(missing_ok=True)
