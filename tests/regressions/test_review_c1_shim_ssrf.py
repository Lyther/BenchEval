"""C1: the Anthropic role shim must never forward injected credentials to attacker-chosen origins.

SUBSTITUTE_JUSTIFICATION
- substitute: local loopback HTTP servers that record/capture requests
- replaces: a real provider origin and an attacker-controlled redirect/host
- necessity: deterministic credential-leak assertions without live provider traffic
- real-option: live Anthropic-compatible provider + hostile redirect host on a provisioned network
- proof-limit: proves shim request filtering/origin pinning only; not live provider auth or Harbor
- real-proof: BLOCKED until a provisioned dev-box run exercises the real provider path
"""

from __future__ import annotations

import http.client
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NamedTuple

import pytest

from bencheval.anthropic_role_shim import _AnthropicRoleShimHandler, _parser, _ShimServer

_AUTH_ENV = "BENCHEVAL_C1_REGRESSION_TOKEN"
_INBOUND_ENV = "BENCHEVAL_C1_INBOUND_TOKEN"
_TOKEN = "c1-regression-token-value"
_INBOUND_TOKEN = "c1-inbound-capability-token"
_DEFAULT_MAX_BODY_BYTES = 16 * 1024 * 1024
_ALLOWLISTED_PATHS = (
    "/v1/messages",
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/completions",
)


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
        payload = b'{"ok":true}'
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


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


class _ShimStack(NamedTuple):
    shim_port: int
    upstream: _RecordingServer
    capture: _RecordingServer


@pytest.fixture
def shim_stack() -> Iterator[_ShimStack]:
    upstream = _RecordingServer()
    capture = _RecordingServer()
    previous_token = os.environ.get(_AUTH_ENV)
    previous_inbound = os.environ.get(_INBOUND_ENV)
    os.environ[_AUTH_ENV] = _TOKEN
    os.environ[_INBOUND_ENV] = _INBOUND_TOKEN
    try:
        with _serving(upstream), _serving(capture):
            shim = _ShimServer(
                ("127.0.0.1", 0),
                _AnthropicRoleShimHandler,
                upstream=f"http://127.0.0.1:{upstream.server_address[1]}",
                timeout_sec=2,
                auth_token_env=_AUTH_ENV,
                inbound_token_env=_INBOUND_ENV,
            )
            with _serving(shim):
                yield _ShimStack(shim.server_address[1], upstream, capture)
    finally:
        if previous_token is None:
            os.environ.pop(_AUTH_ENV, None)
        else:
            os.environ[_AUTH_ENV] = previous_token
        if previous_inbound is None:
            os.environ.pop(_INBOUND_ENV, None)
        else:
            os.environ[_INBOUND_ENV] = previous_inbound


def _post(
    port: int,
    target: str,
    payload: dict[str, object] | None = None,
    *,
    inbound: str | None = _INBOUND_TOKEN,
) -> tuple[int, bytes]:
    headers = {"content-type": "application/json"}
    if inbound is not None:
        headers["authorization"] = f"Bearer {inbound}"
        headers["x-api-key"] = inbound
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(
            "POST",
            target,
            body=json.dumps(
                payload
                if payload is not None
                else {"messages": [{"role": "user", "content": "hello"}]}
            ),
            headers=headers,
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _assert_rejected(stack: _ShimStack, target: str) -> None:
    status, _ = _post(stack.shim_port, target)
    assert status == HTTPStatus.BAD_REQUEST
    assert stack.upstream.requests == []
    assert stack.capture.requests == []


def test_absolute_form_target_cannot_redirect_injected_credentials(
    shim_stack: _ShimStack,
) -> None:
    capture_port = shim_stack.capture.server_address[1]
    status, _ = _post(
        shim_stack.shim_port,
        f"http://127.0.0.1:{capture_port}/credential-capture",
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert shim_stack.capture.requests == []
    assert shim_stack.upstream.requests == []


def test_protocol_relative_target_is_rejected(shim_stack: _ShimStack) -> None:
    capture_port = shim_stack.capture.server_address[1]
    _assert_rejected(shim_stack, f"//127.0.0.1:{capture_port}/credential-capture")


def test_userinfo_target_is_rejected(shim_stack: _ShimStack) -> None:
    capture_port = shim_stack.capture.server_address[1]
    status, _ = _post(
        shim_stack.shim_port,
        f"http://attacker@127.0.0.1:{capture_port}/credential-capture",
    )

    assert status == HTTPStatus.BAD_REQUEST
    assert shim_stack.capture.requests == []
    assert shim_stack.upstream.requests == []


@pytest.mark.parametrize("target", ["/\\evil", "http:\\evil-host.example"])
def test_backslash_targets_are_rejected(shim_stack: _ShimStack, target: str) -> None:
    _assert_rejected(shim_stack, target)


@pytest.mark.parametrize(
    "target",
    [
        "/v1%2f..%2fadmin",  # encoded slashes
        "/v1/%2e%2e/admin",  # encoded dot-segment traversal
        "/v1/messages%3a@127.0.0.1/x",  # encoded colon plus userinfo marker
        "/v1/messages%3fdebug=1",  # encoded query introducer
    ],
)
def test_percent_encoded_targets_are_rejected(shim_stack: _ShimStack, target: str) -> None:
    _assert_rejected(shim_stack, target)


def test_percent_encoded_protocol_relative_target_reaches_no_server(
    shim_stack: _ShimStack,
) -> None:
    capture_port = shim_stack.capture.server_address[1]
    _assert_rejected(shim_stack, f"/%2f/127.0.0.1:{capture_port}/credential-capture")


@pytest.mark.parametrize("target", ["/v1/../messages", "/v1/./admin", "/v1/messages/../admin"])
def test_path_traversal_is_rejected(shim_stack: _ShimStack, target: str) -> None:
    _assert_rejected(shim_stack, target)


@pytest.mark.parametrize(
    "target",
    ["/v1/admin", "/v1/messages/extra", "/v1", "/messages", "/v1/messagesx"],
)
def test_non_allowlisted_paths_are_rejected(shim_stack: _ShimStack, target: str) -> None:
    _assert_rejected(shim_stack, target)


def test_query_string_target_is_rejected(shim_stack: _ShimStack) -> None:
    _assert_rejected(shim_stack, "/v1/messages?x=1")


def test_oversized_content_length_is_rejected_before_body_is_read(
    shim_stack: _ShimStack,
) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", shim_stack.shim_port, timeout=5)
    try:
        connection.putrequest("POST", "/v1/messages")
        connection.putheader("content-type", "application/json")
        connection.putheader("authorization", f"Bearer {_INBOUND_TOKEN}")
        connection.putheader("x-api-key", _INBOUND_TOKEN)
        connection.putheader("content-length", str(_DEFAULT_MAX_BODY_BYTES + 1))
        connection.endheaders()
        connection.send(b'{"messages": []')  # far short of the declared length
        # If the shim tried to read the full declared body first, getresponse
        # would block until the client timeout instead of answering 413.
        response = connection.getresponse()
        status = response.status
        response.read()
    finally:
        connection.close()

    assert status == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
    assert shim_stack.upstream.requests == []


@pytest.mark.parametrize("path", _ALLOWLISTED_PATHS)
def test_allowlisted_paths_forward_with_auth_and_normalized_payload(
    shim_stack: _ShimStack,
    path: str,
) -> None:
    payload = {
        "model": "glm-5.1",
        "messages": [
            {"role": "system", "content": "be concise"},
            {"role": "user", "content": "hello"},
        ],
    }

    status, body = _post(shim_stack.shim_port, path, payload)

    assert status == HTTPStatus.OK
    assert json.loads(body) == {"ok": True}
    assert len(shim_stack.upstream.requests) == 1
    forwarded_path, headers, forwarded_body = shim_stack.upstream.requests[0]
    assert forwarded_path == path
    assert headers["authorization"] == f"Bearer {_TOKEN}"
    assert headers["x-api-key"] == _TOKEN
    normalized = json.loads(forwarded_body)
    assert normalized["system"] == "be concise"
    assert [message["role"] for message in normalized["messages"]] == ["user"]
    assert shim_stack.capture.requests == []


def test_healthz_still_works(shim_stack: _ShimStack) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", shim_stack.shim_port, timeout=5)
    try:
        connection.request("GET", "/healthz")
        response = connection.getresponse()
        status = response.status
        body = response.read()
    finally:
        connection.close()

    assert status == HTTPStatus.OK
    assert json.loads(body) == {"ok": True}


def test_custom_allowed_paths_extend_the_default_set() -> None:
    upstream = _RecordingServer()
    previous_token = os.environ.get(_AUTH_ENV)
    previous_inbound = os.environ.get(_INBOUND_ENV)
    os.environ[_AUTH_ENV] = _TOKEN
    os.environ[_INBOUND_ENV] = _INBOUND_TOKEN
    try:
        with _serving(upstream):
            shim = _ShimServer(
                ("127.0.0.1", 0),
                _AnthropicRoleShimHandler,
                upstream=f"http://127.0.0.1:{upstream.server_address[1]}",
                timeout_sec=2,
                auth_token_env=_AUTH_ENV,
                inbound_token_env=_INBOUND_ENV,
                allowed_paths=set(_ALLOWLISTED_PATHS) | {"/v1/models"},
            )
            with _serving(shim):
                port = shim.server_address[1]
                custom_status, _ = _post(port, "/v1/models")
                default_status, _ = _post(port, "/v1/messages")
                rejected_status, _ = _post(port, "/v1/admin")
    finally:
        if previous_token is None:
            os.environ.pop(_AUTH_ENV, None)
        else:
            os.environ[_AUTH_ENV] = previous_token
        if previous_inbound is None:
            os.environ.pop(_INBOUND_ENV, None)
        else:
            os.environ[_INBOUND_ENV] = previous_inbound

    assert custom_status == HTTPStatus.OK
    assert default_status == HTTPStatus.OK
    assert rejected_status == HTTPStatus.BAD_REQUEST
    assert [path for path, _, _ in upstream.requests] == ["/v1/models", "/v1/messages"]


def test_cli_accepts_repeatable_allow_path_and_max_body_bytes() -> None:
    args = _parser().parse_args(
        [
            "--port",
            "4011",
            "--upstream",
            "http://127.0.0.1:4000",
            "--allow-path",
            "/v1/models",
            "--allow-path",
            "/v1/embeddings",
            "--max-body-bytes",
            "1024",
        ]
    )

    assert args.allow_path == ["/v1/models", "/v1/embeddings"]
    assert args.max_body_bytes == 1024
