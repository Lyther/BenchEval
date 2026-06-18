"""HTTP shim for Anthropic-compatible providers that reject system-role messages."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bencheval.exceptions import BenchEvalError

JsonObject = dict[str, Any]

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
_REQUEST_DROP_HEADERS = _HOP_BY_HOP_HEADERS | {"accept-encoding", "host"}


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


def normalize_anthropic_payload(payload: JsonObject) -> JsonObject:
    """Move non-standard system-role messages into Anthropic's top-level system field."""
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        return dict(payload)

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
        return dict(payload)

    normalized = dict(payload)
    normalized["messages"] = messages
    existing_system = normalized.get("system")
    if existing_system is not None:
        system_parts.insert(0, _content_to_system_text(existing_system))
    normalized["system"] = "\n\n".join(part for part in system_parts if part)
    return normalized


class _ShimServer(ThreadingHTTPServer):
    upstream: str
    timeout_sec: float

    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        *,
        upstream: str,
        timeout_sec: float,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.upstream = upstream.rstrip("/") + "/"
        self.timeout_sec = timeout_sec


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
        try:
            body = self._read_body()
            payload = json.loads(body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("expected JSON object")
            normalized = normalize_anthropic_payload(payload)
            upstream_body = json.dumps(normalized).encode("utf-8")
            self._forward(upstream_body)
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

    def _read_body(self) -> bytes:
        content_length = self.headers.get("content-length")
        if content_length is None:
            return b""
        try:
            n = int(content_length)
        except ValueError as exc:
            raise ValueError("invalid content-length") from exc
        return self.rfile.read(n)

    def _forward(self, body: bytes) -> None:
        target = urljoin(self.server.upstream, self.path.lstrip("/"))
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in _REQUEST_DROP_HEADERS
        }
        headers["content-type"] = "application/json"
        headers["accept-encoding"] = "identity"
        request = Request(target, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.server.timeout_sec) as response:
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in _HOP_BY_HOP_HEADERS:
                        self.send_header(key, value)
                self.end_headers()
                self._stream_response(response)
        except HTTPError as exc:
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


def run_server(
    *,
    host: str,
    port: int,
    upstream: str,
    timeout_sec: float,
) -> None:
    server = _ShimServer(
        (host, port),
        _AnthropicRoleShimHandler,
        upstream=upstream,
        timeout_sec=timeout_sec,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rewrite Anthropic system-role messages to top-level system.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    return parser


def main() -> None:
    args = _parser().parse_args()
    run_server(
        host=args.host,
        port=args.port,
        upstream=args.upstream,
        timeout_sec=args.timeout_sec,
    )


if __name__ == "__main__":
    main()


__all__ = ["normalize_anthropic_payload", "run_server"]
