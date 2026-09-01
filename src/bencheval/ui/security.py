"""Loopback and per-process capability boundary for the private UI transport."""

from __future__ import annotations

import hmac
import ipaddress
from collections.abc import Awaitable, Callable, MutableMapping
from http.cookies import CookieError, SimpleCookie
from typing import cast
from urllib.parse import parse_qs, urlsplit

Scope = MutableMapping[str, object]
Message = MutableMapping[str, object]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
AsgiApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_COOKIE_NAME = "bencheval_ui"


def _headers(scope: Scope) -> dict[bytes, bytes]:
    raw = cast("list[tuple[bytes, bytes]]", scope.get("headers", []))
    return {bytes(key).lower(): bytes(value) for key, value in raw}


def _loopback_host(value: str, *, port: int) -> bool:
    try:
        parsed = urlsplit(f"//{value}")
        if parsed.hostname != "127.0.0.1":
            return False
        parsed_port = parsed.port
    except ValueError:
        return False
    return parsed_port in {None, port}


def _authorized_cookie(raw: str, capability: str) -> bool:
    cookie = SimpleCookie()
    try:
        cookie.load(raw)
    except CookieError:
        return False
    value = cookie.get(_COOKIE_NAME)
    return value is not None and hmac.compare_digest(value.value, capability)


class LoopbackCapabilityMiddleware:
    """Reject non-loopback/private-transport requests before NiceGUI handles them."""

    def __init__(self, app: AsgiApp, *, capability: str, port: int) -> None:
        self.app = app
        self.capability = capability
        self.port = port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope.get("type")
        if scope_type == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope_type not in {"http", "websocket"}:
            await self._deny(scope_type, send)
            return
        headers = _headers(scope)
        if any(
            name in headers
            for name in (
                b"forwarded",
                b"x-forwarded-for",
                b"x-forwarded-host",
                b"x-forwarded-proto",
            )
        ):
            await self._deny(scope_type, send)
            return
        host = headers.get(b"host", b"").decode("ascii", errors="ignore")
        client = scope.get("client")
        client_host = client[0] if isinstance(client, (list, tuple)) and client else ""
        try:
            client_is_loopback = ipaddress.ip_address(str(client_host)).is_loopback
        except ValueError:
            client_is_loopback = False
        if not client_is_loopback or not _loopback_host(host, port=self.port):
            await self._deny(scope_type, send)
            return
        origin = headers.get(b"origin")
        if origin is not None:
            try:
                parsed_origin = urlsplit(origin.decode("ascii", errors="ignore"))
                origin_scheme = parsed_origin.scheme
                origin_hostname = parsed_origin.hostname
                origin_port = parsed_origin.port
            except ValueError:
                await self._deny(scope_type, send)
                return
            if (
                origin_scheme != "http"
                or origin_hostname != "127.0.0.1"
                or origin_port != self.port
            ):
                await self._deny(scope_type, send)
                return
        cookie = headers.get(b"cookie", b"").decode("ascii", errors="ignore")
        if _authorized_cookie(cookie, self.capability):
            await self.app(scope, receive, self._security_headers(send))
            return
        if scope_type == "http" and scope.get("method") == "GET" and scope.get("path") == "/":
            query = parse_qs(bytes(scope.get("query_string", b"")).decode("ascii", errors="ignore"))
            supplied = query.get("cap", [""])[0]
            if hmac.compare_digest(supplied, self.capability):
                body = (
                    b"<!doctype html><meta charset=utf-8>"
                    b"<title>BenchEval</title>"
                    b"<script>history.replaceState(null,'','/');location.reload()</script>"
                )
                await send(
                    {
                        "type": "http.response.start",
                        "status": 200,
                        "headers": [
                            (
                                b"set-cookie",
                                (
                                    f"{_COOKIE_NAME}={self.capability}; Path=/; HttpOnly; "
                                    "SameSite=Strict"
                                ).encode("ascii"),
                            ),
                            (b"cache-control", b"no-store"),
                            (
                                b"content-security-policy",
                                b"default-src 'none'; script-src 'unsafe-inline'",
                            ),
                            (b"content-type", b"text/html; charset=utf-8"),
                            (b"referrer-policy", b"no-referrer"),
                        ],
                    },
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self._deny(scope_type, send)

    def _security_headers(self, send: Send) -> Send:
        async def secured(message: Message) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"content-security-policy", b"frame-ancestors 'none'; base-uri 'none'"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"x-frame-options", b"DENY"),
                    ],
                )
                message["headers"] = headers
            await send(message)

        return secured

    async def _deny(self, scope_type: object, send: Send) -> None:
        if scope_type == "websocket":
            await send({"type": "websocket.close", "code": 4403})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [(b"content-type", b"text/plain"), (b"cache-control", b"no-store")],
            },
        )
        await send({"type": "http.response.body", "body": b"Forbidden"})
