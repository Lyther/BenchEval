"""Review round 1 regressions: F001–F004 (auth bases, passed status, preflight, artifacts)."""

# SUBSTITUTE_JUSTIFICATION
# - substitute: `_OkHandler` + local `HTTPServer` on 127.0.0.1 (three
#   `test_verify_auth_*` tests in this file)
# - replaces: the real provider/auth HTTP endpoints probed by
#   `scripts/verify_auth.sh`
# - necessity: the assertions target the script's routing, key-masking, and
#   base-URL selection behavior; probing the real provider endpoints is an
#   outward-facing, credentialed network call that cannot run deterministically
#   (or safely, with dummy keys) in a test environment
# - real-option: running verify_auth.sh against the real provider with live
#   credentials — operator-only, non-deterministic, and would consume quota
# - proof-limit: proves script routing/masking behavior only; it does not prove
#   real provider authentication, quota, or reachability
# - real-proof: BLOCKED — live provider verification on the dev-box pilot
#   (operator credential provisioning); these passes are diagnostic only

from __future__ import annotations

import os
import subprocess
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from bencheval.cli import main
from bencheval.evidence import EvidenceRecord
from bencheval.live_run_manifest import read_live_runs


class _OkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def do_POST(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"input_tokens":1}')

    def log_message(self, format: str, *args: object) -> None:
        return


def _run_verify_auth(
    repo_root: Path,
    *,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    script = repo_root / "scripts" / "verify_auth.sh"
    merged = {**os.environ, **env}
    for drop in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "MOONSHOT_API_KEY",
        "BYTELLM_API_KEY",
        "BYTELLM_PROXY_API_KEY",
    ):
        if drop not in env:
            merged.pop(drop, None)
    return subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env=merged,
    )


def _write_valid_evidence(path: Path, *, run_id: str = "run-passed") -> None:
    # Passed registration is proof-bearing: the positive row must qualify as a
    # real native-harness attempt (native verifier artifact on disk, full
    # provenance axes, pass@k-eligible) and match the CLI identity flags.
    verifier = path.parent / "native-verifier.json"
    verifier.write_text('{"resolved": true}\n', encoding="utf-8")
    record = EvidenceRecord(
        run_id=run_id,
        task_id="terminal-bench/fix-git",
        model_id="claude-haiku-4-5",
        execution_profile="E2",
        backend="harbor",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.01,
        latency_sec=10.0,
        artifact_paths=[str(verifier.resolve())],
        verifier_log_path=str(verifier.resolve()),
        created_at=datetime(2026, 6, 18, 15, 5, tzinfo=UTC),
        benchmark_id="terminal-bench",
        benchmark_version="terminal-bench@2.1",
        slice_id="smoke-5",
        adapter_id="terminal-bench-harbor",
        harness_kind="harbor",
        harness_version="harbor@0.1.0",
        runtime_id="claude-code",
        runtime_version="claude-code@1.0.0",
        runtime_config_hash="sha256:runtime-config",
        provider_id="bytellm",
        provider_config_hash="sha256:provider-config",
        instance_id="fix-git",
        interpretation_label="adapter_smoke",
        verifier_integrity_label="native",
        attempt_validity="valid",
        counts_toward_pass_at_k=True,
    )
    path.write_text(record.model_dump_json() + "\n", encoding="utf-8")


def test_verify_auth_routes_anthropic_base_url_without_logging_key_material() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server = HTTPServer(("127.0.0.1", 0), _OkHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        secret = "anthropic-secret-key-XYZZ"
        proc = _run_verify_auth(
            repo_root,
            env={
                "ANTHROPIC_API_KEY": secret,
                "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}/v1",
                "http_proxy": "http://127.0.0.1:9",
                "https_proxy": "http://127.0.0.1:9",
            },
        )
    finally:
        server.shutdown()

    assert proc.returncode == 0, proc.stderr
    assert secret not in proc.stderr + proc.stdout
    # F002: credential suffixes are never logged (endpoint identity suffices).
    assert "XYZZ" not in proc.stderr + proc.stdout


def test_verify_auth_routes_openai_base_url() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    server = HTTPServer(("127.0.0.1", 0), _OkHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        proc = _run_verify_auth(
            repo_root,
            env={
                "OPENAI_API_KEY": "openai-key-abcd",
                "OPENAI_BASE_URL": f"http://127.0.0.1:{port}/v1",
                "http_proxy": "http://127.0.0.1:9",
                "https_proxy": "http://127.0.0.1:9",
            },
        )
    finally:
        server.shutdown()

    assert proc.returncode == 0, proc.stderr


def test_verify_auth_prefers_bytellm_key_and_probes_protected_route() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    seen: dict[str, str] = {}

    class Handler(_OkHandler):
        def do_POST(self) -> None:
            seen["path"] = self.path
            seen["authorization"] = self.headers.get("Authorization", "")
            seen["x_api_key"] = self.headers.get("x-api-key", "")
            super().do_POST()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        secret = "bytellm-secret-key-ABCD"
        proc = _run_verify_auth(
            repo_root,
            env={
                "BYTELLM_API_KEY": secret,
                "OPENAI_API_KEY": "stale-openai-key",
                "OPENAI_BASE_URL": f"http://127.0.0.1:{port}/v1",
                "http_proxy": "http://127.0.0.1:9",
                "https_proxy": "http://127.0.0.1:9",
            },
        )
    finally:
        server.shutdown()

    assert proc.returncode == 0, proc.stderr
    assert seen["path"] == "/v1/messages/count_tokens"
    assert seen["authorization"] == f"Bearer {secret}"
    assert seen["x_api_key"] == secret
    assert secret not in proc.stderr + proc.stdout
    assert "stale-openai-key" not in proc.stderr + proc.stdout
    # F002: credential suffixes are never logged (endpoint identity suffices).
    assert "ABCD" not in proc.stderr + proc.stdout


def test_cli_register_accepts_status_passed(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    _write_valid_evidence(evidence)

    code = main(
        [
            "evidence",
            "register",
            "--run-id",
            "run-passed",
            "--model",
            "claude-haiku-4-5",
            "--benchmark",
            "terminal-bench",
            "--slice",
            "smoke-5",
            "--runtime",
            "claude-code",
            "--evidence",
            str(evidence),
            "--status",
            "passed",
            "--host",
            "dev-box",
            "--manifest-path",
            str(manifest),
        ],
    )
    assert code == 0
    assert read_live_runs(manifest)[0].status == "passed"


def test_cli_register_rejects_invalid_evidence_for_passed(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    evidence = tmp_path / "evidence.jsonl"
    evidence.write_text("{}\n", encoding="utf-8")

    code = main(
        [
            "evidence",
            "register",
            "--run-id",
            "run-passed",
            "--model",
            "claude-haiku-4-5",
            "--evidence",
            str(evidence),
            "--status",
            "passed",
            "--host",
            "dev-box",
            "--manifest-path",
            str(manifest),
        ],
    )
    assert code == 1
    assert not manifest.exists()


def test_cli_register_rejects_missing_evidence_for_completed(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    missing = tmp_path / "does-not-exist.jsonl"

    code = main(
        [
            "evidence",
            "register",
            "--run-id",
            "run-bad",
            "--model",
            "kimi-k2.7-code",
            "--evidence",
            str(missing),
            "--status",
            "completed",
            "--host",
            "h",
            "--manifest-path",
            str(manifest),
        ],
    )
    assert code == 1
    assert not manifest.exists()


def test_cli_register_allows_missing_with_dev_flag(tmp_path: Path) -> None:
    manifest = tmp_path / "runs.jsonl"
    missing = tmp_path / "nope.jsonl"

    code = main(
        [
            "evidence",
            "register",
            "--run-id",
            "run-dev",
            "--model",
            "kimi-k2.7-code",
            "--evidence",
            str(missing),
            "--status",
            "registered",
            "--host",
            "h",
            "--manifest-path",
            str(manifest),
            "--allow-missing-artifacts",
        ],
    )
    assert code == 0


def test_preflight_only_mode_exits_zero_without_incrementing_failed() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = repo_root / "scripts" / "run-live-pilot-matrix.sh"
    proc = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
        env={
            **os.environ,
            "BENCHEVAL_ALLOW_PREFLIGHT_ONLY": "1",
            "BENCHEVAL_PILOT_MODEL": "kimi-k2.7-code",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "preflight-only" in (proc.stdout + proc.stderr).lower()
