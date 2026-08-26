"""HTTP shim for Anthropic-compatible providers that reject system-role messages."""

from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import os
import threading
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bencheval.exceptions import BenchEvalError

JsonObject = dict[str, Any]

_DEFAULT_ALLOWED_PATHS: frozenset[str] = frozenset(
    {
        "/v1/messages",
        "/v1/chat/completions",
        "/v1/responses",
        "/v1/completions",
    },
)
_ALLOWED_QUERIES: frozenset[str] = frozenset({"beta=true"})
_DEFAULT_MAX_BODY_BYTES = 16 * 1024 * 1024
_DEFAULT_MAX_INFLIGHT = 32
_INBOUND_HEADER = "x-bencheval-shim-token"
_ALLOWED_UPSTREAM_SCHEMES = frozenset({"http", "https"})


class _NoRedirect(HTTPRedirectHandler):
    """Never follow redirects: credentialed hops must stay on the configured origin."""

    def redirect_request(
        self,
        req: Request,
        fp: object,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> Request | None:
        return None


_UPSTREAM_OPENER = build_opener(_NoRedirect)

_HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
_REQUEST_DROP_HEADERS = _HOP_BY_HOP_HEADERS | {
    "accept-encoding",
    "host",
    _INBOUND_HEADER,
    "authorization",
    "x-api-key",
}


def _content_to_system_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str):
                    texts.append(text)
        return "\n".join(texts)
    return json.dumps(content, ensure_ascii=False, sort_keys=True)


def _rewrite_developer_roles(items: list[object]) -> list[object]:
    rewritten: list[object] = []
    for item in items:
        if isinstance(item, Mapping) and item.get("role") == "developer":
            rewritten.append({**dict(item), "role": "system"})
        else:
            rewritten.append(item)
    return rewritten


def normalize_anthropic_payload(payload: JsonObject) -> JsonObject:
    """Rewrite gateway-incompatible roles, then lift system messages for Anthropic."""
    normalized = dict(payload)
    for key in ("messages", "input"):
        raw_items = normalized.get(key)
        if isinstance(raw_items, list):
            rewritten = _rewrite_developer_roles(raw_items)
            if rewritten != raw_items:
                normalized[key] = rewritten
    raw_messages = normalized.get("messages")
    if not isinstance(raw_messages, list):
        return normalized

    system_parts: list[str] = []
    messages: list[object] = []
    for raw_message in raw_messages:
        if isinstance(raw_message, Mapping) and raw_message.get("role") == "system":
            system_text = _content_to_system_text(raw_message.get("content", ""))
            if system_text:
                system_parts.append(system_text)
            continue
        messages.append(raw_message)

    if not system_parts:
        return normalized

    lifted = dict(normalized)
    lifted["messages"] = messages
    existing_system = lifted.get("system")
    if existing_system is not None:
        system_parts.insert(0, _content_to_system_text(existing_system))
    lifted["system"] = "\n\n".join(part for part in system_parts if part)
    return lifted


def _validated_request_path(raw_target: str, allowed_paths: frozenset[str]) -> str | None:
    """Return an allowlisted path, or None if the request target is unsafe / unknown."""
    if not raw_target:
        return None
    # Reject encoding tricks and Windows-style separators before any parsing.
    if "%" in raw_target or "\\" in raw_target:
        return None
    if raw_target.startswith("//") or "://" in raw_target:
        return None
    parts = urlsplit(raw_target)
    if parts.scheme or parts.netloc or parts.fragment:
        return None
    if parts.query and parts.query not in _ALLOWED_QUERIES:
        return None
    path = parts.path
    if not path.startswith("/") or "@" in path:
        return None
    segments = path.split("/")
    if any(segment in (".", "..") for segment in segments):
        return None
    if path not in allowed_paths:
        return None
    return path


def _normalize_upstream(upstream: str) -> str:
    parts = urlsplit(upstream.strip())
    if parts.scheme not in _ALLOWED_UPSTREAM_SCHEMES or not parts.netloc:
        raise ValueError(
            f"upstream must be an absolute http(s) URL with a host (got {upstream!r})",
        )
    if parts.username or parts.password:
        raise ValueError("upstream URL must not embed userinfo credentials")
    return upstream.rstrip("/") + "/"


class _ShimServer(ThreadingHTTPServer):
    upstream: str
    timeout_sec: float
    auth_token_env: str | None
    inbound_token_env: str | None
    allowed_paths: frozenset[str]
    max_body_bytes: int
    inflight: threading.Semaphore

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        upstream: str,
        timeout_sec: float,
        auth_token_env: str | None,
        inbound_token_env: str | None = None,
        allowed_paths: set[str] | frozenset[str] | None = None,
        max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES,
        max_inflight: int = _DEFAULT_MAX_INFLIGHT,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.upstream = _normalize_upstream(upstream)
        self.timeout_sec = timeout_sec
        self.auth_token_env = auth_token_env
        self.inbound_token_env = inbound_token_env
        if allowed_paths is None:
            self.allowed_paths = _DEFAULT_ALLOWED_PATHS
        else:
            self.allowed_paths = frozenset(allowed_paths)
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be >= 1")
        self.max_body_bytes = max_body_bytes
        self.inflight = threading.Semaphore(max_inflight)


def _forward_headers(
    source_headers: Mapping[str, str],
    *,
    auth_token: str | None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in source_headers.items():
        lowered = key.lower()
        if lowered in _REQUEST_DROP_HEADERS or lowered.startswith("x-bencheval-"):
            continue
        headers[key] = value
    headers["content-type"] = "application/json"
    headers["accept-encoding"] = "identity"
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"
        headers["x-api-key"] = auth_token
    return headers


class _AnthropicRoleShimHandler(BaseHTTPRequestHandler):
    server: _ShimServer

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(HTTPStatus.OK, {"ok": True})
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        if not self.server.inflight.acquire(blocking=False):
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"type": "busy_error", "message": "too many in-flight requests"},
            )
            return
        try:
            self._handle_post()
        finally:
            self.server.inflight.release()

    def _handle_post(self) -> None:
        if not self._inbound_authorized():
            self._send_json(
                HTTPStatus.UNAUTHORIZED,
                {
                    "type": "authentication_error",
                    "message": "missing or invalid inbound shim capability token",
                },
            )
            return
        validated_path = _validated_request_path(self.path, self.server.allowed_paths)
        if validated_path is None:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {
                    "type": "invalid_request_error",
                    "message": "request target is not an allowlisted relative path",
                },
            )
            return
        try:
            content_length = self._declared_content_length()
            if content_length > self.server.max_body_bytes:
                self._send_json(
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    {
                        "type": "invalid_request_error",
                        "message": "request body exceeds max-body-bytes",
                    },
                )
                return
            body = self.rfile.read(content_length) if content_length else b""
            payload = json.loads(body.decode("utf-8")) if body else {}
            if not isinstance(payload, dict):
                raise ValueError("expected JSON object")
            normalized = normalize_anthropic_payload(payload)
            upstream_body = json.dumps(normalized).encode("utf-8")
            self._forward(validated_path, upstream_body)
        except (ValueError, UnicodeDecodeError) as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"type": "invalid_request_error", "message": str(exc)},
            )
        except BenchEvalError as exc:
            self._send_json(
                HTTPStatus.BAD_GATEWAY,
                {"type": "upstream_error", "message": str(exc)},
            )

    def _inbound_authorized(self) -> bool:
        """Require per-run capability before attaching upstream provider credentials."""
        if self.server.inbound_token_env is None:
            # Fail closed when upstream credential injection is configured.
            return self.server.auth_token_env is None
        expected = os.environ.get(self.server.inbound_token_env)
        if not expected:
            return False
        expected_bytes = expected.encode()
        presented = self.headers.get(_INBOUND_HEADER)
        if presented is not None and hmac.compare_digest(
            presented.encode(),
            expected_bytes,
        ):
            return True
        auth = self.headers.get("Authorization", "")
        if hmac.compare_digest(auth.encode(), f"Bearer {expected}".encode()):
            return True
        api_key = self.headers.get("x-api-key", "")
        return hmac.compare_digest(api_key.encode(), expected_bytes)

    def _declared_content_length(self) -> int:
        content_length = self.headers.get("content-length")
        if content_length is None:
            return 0
        try:
            length = int(content_length)
        except ValueError as exc:
            raise ValueError("invalid content-length") from exc
        if length < 0:
            raise ValueError("invalid content-length")
        return length

    def _forward(self, path: str, body: bytes) -> None:
        # Retain the configured upstream origin unconditionally: never let any
        # residue of the client-supplied request target redirect credentials.
        origin = self.server.upstream.rstrip("/")
        target = origin + path
        configured = urlsplit(origin)
        final = urlsplit(target)
        if (final.scheme, final.netloc) != (configured.scheme, configured.netloc):
            raise BenchEvalError("refusing to forward off the configured upstream origin")
        auth_token = None
        if self.server.auth_token_env is not None:
            auth_token = os.environ.get(self.server.auth_token_env)
        # Never forward the caller's inbound capability/auth headers upstream.
        headers = _forward_headers(self.headers, auth_token=None)
        for key in list(headers):
            lowered = key.lower()
            if lowered in {"authorization", "x-api-key", _INBOUND_HEADER} or lowered.startswith(
                "x-bencheval-"
            ):
                headers.pop(key, None)
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
            headers["x-api-key"] = auth_token
        request = Request(target, data=body, headers=headers, method="POST")
        try:
            # Redirects are disabled: a cross-origin 302 must not receive credentials.
            with _UPSTREAM_OPENER.open(request, timeout=self.server.timeout_sec) as response:
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in _HOP_BY_HOP_HEADERS:
                        self.send_header(key, value)
                self.end_headers()
                self._stream_response(response)
        except HTTPError as exc:
            # Never reflect redirects. API callers commonly preserve custom auth
            # headers (including x-api-key) across cross-origin redirects; exposing
            # Location would disclose the per-run shim capability and let its holder
            # invoke provider-credentialed forwarding.
            if 300 <= exc.code < 400:
                self._send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {
                        "type": "upstream_error",
                        "message": "upstream redirects are not permitted",
                    },
                )
                return
            self.send_response(exc.code)
            for key, value in exc.headers.items():
                if key.lower() not in _HOP_BY_HOP_HEADERS:
                    self.send_header(key, value)
            self.end_headers()
            self._stream_response(exc)
        except URLError as exc:
            raise BenchEvalError(f"failed to reach Anthropic upstream: {exc}") from exc

    def _stream_response(self, response: object) -> None:
        read = getattr(response, "read", None)
        if not callable(read):
            raise BenchEvalError("upstream response is not readable")
        while True:
            chunk = read(65536)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()

    def _send_json(self, status: HTTPStatus, payload: JsonObject) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_LOOPBACK_HOSTNAMES = frozenset({"localhost", "localhost.localdomain"})


def _validate_bind_host(host: str, *, allow_remote_bind: bool) -> None:
    """Refuse non-loopback binds unless the operator explicitly opts in.

    The shim injects upstream provider credentials, so binding it beyond
    loopback must be a deliberate, visible choice (the live pilot binds the
    Docker host gateway for benchmark containers and passes the flag).
    """
    if allow_remote_bind:
        return
    normalized = host.strip().lower().strip("[]").rstrip(".")
    if normalized in _LOOPBACK_HOSTNAMES:
        return
    try:
        addr = ipaddress.ip_address(normalized)
    except ValueError:
        addr = None
    if addr is not None:
        mapped = addr.ipv4_mapped if isinstance(addr, ipaddress.IPv6Address) else None
        if addr.is_loopback or (mapped is not None and mapped.is_loopback):
            return
    raise BenchEvalError(
        f"refusing to bind the credential-injecting shim to remote host {host!r} "
        "without --allow-remote-bind",
    )


def run_server(
    *,
    host: str,
    port: int,
    upstream: str,
    timeout_sec: float,
    auth_token_env: str | None = None,
    inbound_token_env: str | None = None,
    allowed_paths: Sequence[str] | None = None,
    max_body_bytes: int = _DEFAULT_MAX_BODY_BYTES,
    allow_remote_bind: bool = False,
) -> None:
    _validate_bind_host(host, allow_remote_bind=allow_remote_bind)
    paths: set[str] | None = None
    if allowed_paths is not None:
        paths = set(_DEFAULT_ALLOWED_PATHS)
        paths.update(allowed_paths)
    if auth_token_env and not inbound_token_env:
        raise BenchEvalError(
            "inbound-token-env is required when auth-token-env injects upstream credentials",
        )
    server = _ShimServer(
        (host, port),
        _AnthropicRoleShimHandler,
        upstream=upstream,
        timeout_sec=timeout_sec,
        auth_token_env=auth_token_env,
        inbound_token_env=inbound_token_env,
        allowed_paths=paths,
        max_body_bytes=max_body_bytes,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite Anthropic system-role messages and Codex developer-role "
            "items, then lift system text to the top-level system field."
        ),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument(
        "--auth-token-env",
        default=None,
        help="Environment variable whose value is injected as bearer and x-api-key auth upstream",
    )
    parser.add_argument(
        "--inbound-token-env",
        default=None,
        help=(
            "Env var holding the per-run inbound capability token. Callers must present it "
            f"via Authorization Bearer, x-api-key, or {_INBOUND_HEADER}. Required with "
            "--auth-token-env."
        ),
    )
    parser.add_argument(
        "--allow-path",
        action="append",
        default=[],
        help="Additional allowlisted POST path (repeatable; defaults always included)",
    )
    parser.add_argument(
        "--max-body-bytes",
        type=int,
        default=_DEFAULT_MAX_BODY_BYTES,
        help="Reject Content-Length above this size with 413 before reading the body",
    )
    parser.add_argument(
        "--allow-remote-bind",
        action="store_true",
        help=(
            "Permit binding beyond loopback (e.g. the Docker host gateway for benchmark "
            "containers). Off by default: the shim injects upstream credentials."
        ),
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    run_server(
        host=args.host,
        port=args.port,
        upstream=args.upstream,
        timeout_sec=args.timeout_sec,
        auth_token_env=args.auth_token_env,
        inbound_token_env=args.inbound_token_env,
        allowed_paths=args.allow_path or None,
        max_body_bytes=args.max_body_bytes,
        allow_remote_bind=args.allow_remote_bind,
    )


if __name__ == "__main__":
    main()


__all__ = ["normalize_anthropic_payload", "run_server"]
