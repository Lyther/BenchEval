"""H1: public run bundles must not disclose proxy/provider credentials.

Covers both source defects: run_bundle public redaction misses credentialed
URIs / signed URLs / token formats / env assignments, and the Harbor adapter
stored the full secret-bearing command line in evidence ``adapter_metadata``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.evidence import JsonlEvidenceSink
from bencheval.exceptions import AdapterFailureError
from bencheval.run_bundle import _redact_string, export_run_bundle
from bencheval.terminal_bench_harbor import (
    HarborCliResult,
    build_harbor_run_command,
    parse_harbor_instance_outcome,
    run_terminal_bench_instance,
)

# SUBSTITUTE_JUSTIFICATION
# - substitute: monkeypatched credential/proxy env and injected timeout runner in
#   test_public_export_scrubs_process_env_secret_values,
#   test_harbor_command_metadata_omits_proxy_credentials, and
#   test_harbor_timeout_metadata_omits_proxy_credentials
# - replaces: operator secrets and a real Harbor timeout
# - necessity: literal secret canaries and deterministic timeout metadata are required
#   without exposing real credentials or disrupting Harbor
# - real-option: real secrets are unsafe; a live timeout is nondeterministic
# - proof-limit: proves local redaction/metadata behavior, not live Harbor security
# - real-proof: BLOCKED until a credentialed dev-box pilot inspects the public bundle
from tests.factories import make_control_plane_evidence_record as _cp_record


def test_redact_credentialed_proxy_urls() -> None:
    cases = [
        "http://alice:s3ns1t1v3@proxy.example:8118",
        "https://bob:hun_ter2w0rds@proxy.example:8443/v1",
        "socks5://carol:p%40ssw0rd@proxy.example:1080",
        "runner --proxy http://alice:s3ns1t1v3@proxy.example:8080/v1",
    ]
    for raw in cases:
        redacted = _redact_string(raw)
        assert "s3ns1t1v3" not in redacted
        assert "hun_ter2w0rds" not in redacted
        assert "p%40ssw0rd" not in redacted
        assert "alice:" not in redacted
        assert "bob:" not in redacted
        assert "carol:" not in redacted
    assert _redact_string(cases[0]) == "http://proxy.example:8118"
    embedded = _redact_string(cases[3])
    assert embedded == "runner --proxy http://proxy.example:8080/v1"


def test_redact_common_token_formats() -> None:
    secrets = [
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh",
        "github_pat_11ABCDEFGH0aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "AKIAIOSFODNN7EXAMPLE",
        "xoxb-" + ("1" * 12) + "-" + ("a" * 14),
        (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c"
        ),
    ]
    for secret in secrets:
        redacted = _redact_string(f"prefix {secret} suffix")
        assert secret not in redacted

    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIBogIBAAJBAK7plusmaterial\n"
        "-----END RSA PRIVATE KEY-----"
    )
    redacted_pem = _redact_string(pem)
    assert "MIIBogIBAAJBAK" not in redacted_pem
    assert "PRIVATE KEY" not in redacted_pem

    unterminated = "-----BEGIN OPENSSH PRIVATE KEY-----\nabc123keymaterial"
    assert _redact_string(unterminated) == "[redacted]"

    bearer = _redact_string("Authorization: Bearer tokbearer1234567890")
    assert "tokbearer1234567890" not in bearer


def test_redact_signed_urls_and_query_secrets() -> None:
    amz = (
        "https://bucket.s3.example/obj"
        "?X-Amz-Signature=deadbeefcafe123&X-Amz-Credential=AKIAEXAMPLE%2F20260806"
    )
    redacted_amz = _redact_string(amz)
    assert "deadbeefcafe123" not in redacted_amz
    assert "AKIAEXAMPLE" not in redacted_amz
    assert "bucket.s3.example" in redacted_amz

    sig = _redact_string("https://cdn.example/file?sig=abc123signature456&ok=1")
    assert "abc123signature456" not in sig
    assert "ok=1" in sig

    query = _redact_string("https://api.example/call?token=toksecretvalue&api_key=keysecretvalue")
    assert "toksecretvalue" not in query
    assert "keysecretvalue" not in query

    plain = _redact_string("sig=plainsecretsig another=1")
    assert "plainsecretsig" not in plain
    assert "another=1" in plain


def test_redact_env_assignment_forms() -> None:
    proxy = _redact_string("HTTPS_PROXY=http://user:p4ssw0rd@proxy.internal:8118")
    assert "p4ssw0rd" not in proxy
    assert "user:" not in proxy
    assert "HTTPS_PROXY=" in proxy

    key = _redact_string("OPENAI_API_KEY=sk-livekeyvalue12345")
    assert "sk-livekeyvalue12345" not in key

    mixed = _redact_string("flags HTTPS_PROXY=http://user:p4ssw0rd@proxy.internal:8118 end")
    assert "p4ssw0rd" not in mixed
    assert "end" in mixed


def test_extra_secrets_are_scrubbed_literally() -> None:
    secret = "h0rs3-batt3ry-stapl3"
    redacted = _redact_string(f"auth {secret} used", extra_secrets=(secret,))
    assert secret not in redacted
    assert redacted == "auth [redacted] used"

    short_value = "a mini story"
    assert _redact_string(short_value, extra_secrets=("mini",)) == short_value


def test_public_export_scrubs_process_env_secret_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "h0rs3-batt3ry-stapl3"
    monkeypatch.setenv("BENCHEVAL_H1_TEST_CREDENTIAL", secret)
    record = _cp_record(instance_id="tb-001").model_copy(
        update={"adapter_metadata": {"note": f"auth {secret} used"}},
    )
    evidence = tmp_path / "ev.jsonl"
    JsonlEvidenceSink().append_jsonl(evidence, record)

    bundle_dir = tmp_path / "pub"
    export_run_bundle(evidence_path=evidence, output_dir=bundle_dir, redaction="public")

    blob = (bundle_dir / "evidence.jsonl").read_text(encoding="utf-8")
    assert secret not in blob
    assert "auth [redacted] used" in blob


def test_clean_urls_and_benign_words_survive() -> None:
    endpoint = "https://api.example.test/v1/messages"
    assert _redact_string(endpoint) == endpoint
    download = "https://downloads.example/releases/tool.tar.gz"
    assert _redact_string(download) == download
    words = "tokenizer monkey bandwidth"
    assert _redact_string(words) == words


def _credentialed_proxy_env(monkeypatch: pytest.MonkeyPatch) -> str:
    proxy_url = "http://alice:s3ns1t1v3@proxy.example:8118"
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "no_proxy",
        "BENCHEVAL_CLAUDE_CODE_ALLOWED_TOOLS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BENCHEVAL_HARBOR_FORWARD_PROXY", "1")
    monkeypatch.setenv("https_proxy", proxy_url)
    return proxy_url


def test_harbor_command_metadata_omits_proxy_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proxy_url = _credentialed_proxy_env(monkeypatch)
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )
    instance_dir = tmp_path / "inst"
    instance_dir.mkdir()
    from bencheval.terminal_bench_harbor import write_harbor_proxy_env_file

    proxy_env = write_harbor_proxy_env_file(network_policy=plan.network_policy)
    assert proxy_env is not None
    cmd = build_harbor_run_command(
        plan=plan,
        instance_id="fix-git",
        artifacts_dir=instance_dir,
        proxy_env_file=proxy_env,
    )
    try:
        # Proxy secrets must live in the env file only — never as argv tokens.
        assert "--env-file" in cmd
        assert proxy_url not in cmd
        assert f"https_proxy={proxy_url}" not in cmd
        env_tokens = [cmd[i + 1] for i, tok in enumerate(cmd[:-1]) if tok == "--agent-env"]
        assert "ANTHROPIC_CUSTOM_MODEL_OPTION=kimi-k2.7-code" in env_tokens
        assert all(proxy_url not in token for token in env_tokens)
        assert all("proxy" not in token.lower() for token in env_tokens)
        env_file = Path(cmd[cmd.index("--env-file") + 1])
        assert proxy_url in env_file.read_text(encoding="utf-8")
    finally:
        proxy_env.unlink(missing_ok=True)

    cli = HarborCliResult(
        returncode=1,
        stdout="",
        stderr="boom",
        latency_sec=0.2,
        command=cmd,
    )
    outcome = parse_harbor_instance_outcome(
        instance_id="fix-git",
        cli=cli,
        artifacts_dir=instance_dir,
        repo_root=tmp_path,
        harness_version=None,
    )
    stored = outcome.adapter_metadata["harbor_command"]
    assert "s3ns1t1v3" not in stored
    assert "alice:" not in stored
    assert proxy_url not in stored


def test_harbor_timeout_metadata_omits_proxy_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _credentialed_proxy_env(monkeypatch)
    plan = plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="claude-code",
        model_id="kimi-k2.7-code",
    )

    def timeout_runner(command, *, cwd, timeout_sec: int):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout_sec)

    with pytest.raises(AdapterFailureError) as exc_info:
        run_terminal_bench_instance(
            plan=plan,
            instance_id="fix-git",
            artifacts_dir=tmp_path / "a",
            repo_root=tmp_path,
            process_runner=timeout_runner,
            timeout_sec=1,
        )
    stored = exc_info.value.adapter_metadata["harbor_command"]
    assert "s3ns1t1v3" not in stored
    assert "alice:" not in stored
