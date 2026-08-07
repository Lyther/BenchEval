"""RED contracts for the remaining security-sensitive development work.

These tests exercise real loopback HTTP servers and the real public evidence
serializer. They intentionally do not replace an upstream provider or the
redaction implementation with a test double.
"""

from __future__ import annotations

import http.client
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bencheval.anthropic_role_shim import _AnthropicRoleShimHandler, _ShimServer
from bencheval.evidence import EvidenceRecord
from bencheval.run_bundle import _redact_record

_AUTH_ENV = "BENCHEVAL_SPEC_ANTHROPIC_TOKEN"
_INBOUND_ENV = "BENCHEVAL_SPEC_ANTHROPIC_INBOUND_TOKEN"
_UPSTREAM_TOKEN = "development-token-value"
_INBOUND_TOKEN = "development-inbound-capability"


class _RecordingServer(ThreadingHTTPServer):
    requests: list[tuple[str, dict[str, str], bytes]]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _RecordingHandler)
        self.requests = []


class _RecordingHandler(BaseHTTPRequestHandler):
    server: _RecordingServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        size = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(size)
        headers = {key.lower(): value for key, value in self.headers.items()}
        self.server.requests.append((self.path, headers, body))
        response = b'{"ok":true}'
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


@contextmanager
def _serving(server: ThreadingHTTPServer) -> Iterator[ThreadingHTTPServer]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post(port: int, target: str, *, inbound: str | None = _INBOUND_TOKEN) -> tuple[int, bytes]:
    headers = {"content-type": "application/json"}
    if inbound is not None:
        headers["authorization"] = f"Bearer {inbound}"
        headers["x-api-key"] = inbound
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        connection.request(
            "POST",
            target,
            body=json.dumps({"messages": [{"role": "user", "content": "hello"}]}),
            headers=headers,
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_anthropic_shim_confines_forwarding_to_configured_origin() -> None:
    """Relative targets work; absolute-form targets cannot redirect injected auth."""
    upstream = _RecordingServer()
    alternate = _RecordingServer()
    previous_token = os.environ.get(_AUTH_ENV)
    previous_inbound = os.environ.get(_INBOUND_ENV)
    os.environ[_AUTH_ENV] = _UPSTREAM_TOKEN
    os.environ[_INBOUND_ENV] = _INBOUND_TOKEN
    try:
        with _serving(upstream), _serving(alternate):
            upstream_port = upstream.server_address[1]
            shim = _ShimServer(
                ("127.0.0.1", 0),
                _AnthropicRoleShimHandler,
                upstream=f"http://127.0.0.1:{upstream_port}",
                timeout_sec=2,
                auth_token_env=_AUTH_ENV,
                inbound_token_env=_INBOUND_ENV,
            )
            with _serving(shim):
                shim_port = shim.server_address[1]
                legitimate_status, _ = _post(shim_port, "/v1/messages")
                alternate_port = alternate.server_address[1]
                rejected_status, _ = _post(
                    shim_port,
                    f"http://127.0.0.1:{alternate_port}/credential-capture",
                )
    finally:
        if previous_token is None:
            os.environ.pop(_AUTH_ENV, None)
        else:
            os.environ[_AUTH_ENV] = previous_token
        if previous_inbound is None:
            os.environ.pop(_INBOUND_ENV, None)
        else:
            os.environ[_INBOUND_ENV] = previous_inbound

    assert legitimate_status == HTTPStatus.OK
    assert len(upstream.requests) == 1
    forwarded_path, forwarded_headers, _ = upstream.requests[0]
    assert forwarded_path == "/v1/messages"
    assert forwarded_headers["authorization"] == f"Bearer {_UPSTREAM_TOKEN}"
    assert forwarded_headers["x-api-key"] == _UPSTREAM_TOKEN

    assert rejected_status == HTTPStatus.BAD_REQUEST
    assert alternate.requests == []


def test_public_evidence_redacts_uri_userinfo_but_preserves_public_endpoint() -> None:
    record = EvidenceRecord(
        run_id="redaction-contract",
        task_id="redaction-contract-task",
        model_id="provider/model",
        execution_profile="E0",
        primary_pass=True,
        partial_score=1.0,
        cost_usd=0.0,
        latency_sec=0.1,
        adapter_metadata={
            "proxy_command": ("runner --proxy http://alice:s3ns1t1v3@proxy.example:8080/v1"),
            "public_endpoint": "https://api.example.test/v1/messages",
        },
        created_at=datetime(2026, 8, 6, tzinfo=UTC),
    )

    redacted = _redact_record(record)
    serialized = redacted.model_dump_json()

    assert "s3ns1t1v3" not in serialized
    assert "alice:" not in serialized
    assert redacted.adapter_metadata["public_endpoint"] == ("https://api.example.test/v1/messages")
