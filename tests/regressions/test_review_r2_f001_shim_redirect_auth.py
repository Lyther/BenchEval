"""F001: shim must not follow cross-origin redirects with injected credentials.

Also requires an inbound capability token so unauthenticated callers cannot
use the shim as a provider-credential oracle.
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

import httpx
import pytest

from bencheval.anthropic_role_shim import _AnthropicRoleShimHandler, _ShimServer

# SUBSTITUTE_JUSTIFICATION
# - substitute: env_tokens fixture with test-only inbound/upstream capabilities
# - replaces: real operator credentials while using real local HTTP servers/sockets
# - necessity: auth/redirect assertions require known distinct canary tokens
# - real-option: real credentials are unsafe and unnecessary for the local boundary
# - proof-limit: proves local token/redirect handling, not remote provider behavior
# - real-proof: real upstream reachability remains part of the dev-box pilot
# - covered tests: test_cross_origin_redirect_does_not_forward_injected_credentials,
#   test_redirect_following_client_cannot_disclose_inbound_capability, and
#   test_unauthenticated_caller_cannot_reach_upstream

_AUTH_ENV = "BENCHEVAL_R2_F001_UPSTREAM_TOKEN"
_INBOUND_ENV = "BENCHEVAL_R2_F001_INBOUND_TOKEN"
_UPSTREAM_TOKEN = "upstream-provider-secret-token"
_INBOUND_TOKEN = "inbound-capability-token-value"


class _RedirectUpstream(ThreadingHTTPServer):
    redirect_to: str
    redirect_status: HTTPStatus

    def __init__(
        self,
        redirect_to: str,
        redirect_status: HTTPStatus = HTTPStatus.FOUND,
    ) -> None:
        super().__init__(("127.0.0.1", 0), _RedirectHandler)
        self.redirect_to = redirect_to
        self.redirect_status = redirect_status


class _RedirectHandler(BaseHTTPRequestHandler):
    server: _RedirectUpstream

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_POST(self) -> None:
        self.send_response(self.server.redirect_status)
        self.send_header("Location", self.server.redirect_to)
        self.end_headers()


class _CaptureServer(ThreadingHTTPServer):
    requests: list[dict[str, str]]

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _CaptureHandler)
        self.requests = []


class _CaptureHandler(BaseHTTPRequestHandler):
    server: _CaptureServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def _capture(self) -> None:
        self.server.requests.append({key.lower(): value for key, value in self.headers.items()})
        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self) -> None:
        self._capture()

    def do_POST(self) -> None:
        size = int(self.headers.get("content-length", "0"))
        self.rfile.read(size)
        self._capture()


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


def _post(
    port: int,
    *,
    inbound: str | None,
    path: str = "/v1/messages",
) -> tuple[int, bytes]:
    headers = {"content-type": "application/json"}
    if inbound is not None:
        headers["authorization"] = f"Bearer {inbound}"
        headers["x-api-key"] = inbound
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(
            "POST",
            path,
            body=json.dumps({"messages": [{"role": "user", "content": "hi"}]}),
            headers=headers,
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


@pytest.fixture
def env_tokens() -> Iterator[None]:
    previous_up = os.environ.get(_AUTH_ENV)
    previous_in = os.environ.get(_INBOUND_ENV)
    os.environ[_AUTH_ENV] = _UPSTREAM_TOKEN
    os.environ[_INBOUND_ENV] = _INBOUND_TOKEN
    try:
        yield
    finally:
        if previous_up is None:
            os.environ.pop(_AUTH_ENV, None)
        else:
            os.environ[_AUTH_ENV] = previous_up
        if previous_in is None:
            os.environ.pop(_INBOUND_ENV, None)
        else:
            os.environ[_INBOUND_ENV] = previous_in


def test_cross_origin_redirect_does_not_forward_injected_credentials(env_tokens: None) -> None:
    capture = _CaptureServer()
    with _serving(capture):
        capture_url = f"http://127.0.0.1:{capture.server_address[1]}/stolen"
        upstream = _RedirectUpstream(capture_url)
        with _serving(upstream):
            shim = _ShimServer(
                ("127.0.0.1", 0),
                _AnthropicRoleShimHandler,
                upstream=f"http://127.0.0.1:{upstream.server_address[1]}",
                timeout_sec=2,
                auth_token_env=_AUTH_ENV,
                inbound_token_env=_INBOUND_ENV,
            )
            with _serving(shim):
                status, _ = _post(shim.server_address[1], inbound=_INBOUND_TOKEN)

    assert status == HTTPStatus.BAD_GATEWAY
    assert capture.requests == []


@pytest.mark.parametrize("redirect_status", [HTTPStatus.FOUND, HTTPStatus.TEMPORARY_REDIRECT])
@pytest.mark.parametrize(
    ("header_name", "header_value"),
    [
        ("authorization", f"Bearer {_INBOUND_TOKEN}"),
        ("x-api-key", _INBOUND_TOKEN),
        ("x-bencheval-shim-token", _INBOUND_TOKEN),
    ],
)
def test_redirect_following_client_cannot_disclose_inbound_capability(
    env_tokens: None,
    redirect_status: HTTPStatus,
    header_name: str,
    header_value: str,
) -> None:
    capture = _CaptureServer()
    with _serving(capture):
        capture_url = f"http://127.0.0.1:{capture.server_address[1]}/stolen"
        upstream = _RedirectUpstream(capture_url, redirect_status)
        with _serving(upstream):
            shim = _ShimServer(
                ("127.0.0.1", 0),
                _AnthropicRoleShimHandler,
                upstream=f"http://127.0.0.1:{upstream.server_address[1]}",
                timeout_sec=2,
                auth_token_env=_AUTH_ENV,
                inbound_token_env=_INBOUND_ENV,
            )
            with (
                _serving(shim),
                httpx.Client(
                    follow_redirects=True,
                    timeout=5,
                    trust_env=False,
                ) as client,
            ):
                response = client.post(
                    f"http://127.0.0.1:{shim.server_address[1]}/v1/messages",
                    headers={header_name: header_value},
                    json={"messages": [{"role": "user", "content": "hi"}]},
                )

    assert response.status_code == HTTPStatus.BAD_GATEWAY
    assert capture.requests == []


def test_unauthenticated_caller_cannot_reach_upstream(env_tokens: None) -> None:
    class _OkUpstream(ThreadingHTTPServer):
        hits: int

        def __init__(self) -> None:
            super().__init__(("127.0.0.1", 0), _OkHandler)
            self.hits = 0

    class _OkHandler(BaseHTTPRequestHandler):
        server: _OkUpstream

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:
            self.server.hits += 1
            payload = b'{"ok":true}'
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    upstream = _OkUpstream()
    with _serving(upstream):
        shim = _ShimServer(
            ("127.0.0.1", 0),
            _AnthropicRoleShimHandler,
            upstream=f"http://127.0.0.1:{upstream.server_address[1]}",
            timeout_sec=2,
            auth_token_env=_AUTH_ENV,
            inbound_token_env=_INBOUND_ENV,
        )
        with _serving(shim):
            denied_status, _ = _post(shim.server_address[1], inbound=None)
            assert denied_status == HTTPStatus.UNAUTHORIZED
            assert upstream.hits == 0
            ok_status, _ = _post(shim.server_address[1], inbound=_INBOUND_TOKEN)
            assert ok_status == HTTPStatus.OK
            assert upstream.hits == 1
