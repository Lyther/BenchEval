"""Fail-closed redaction pipeline shared by public bundles and local artifacts.

Whole-string rules (sk-*, secret-indicator words, absolute paths) preserve the
historical public-export behavior; in-place rules strip URI userinfo,
signed/credential query params, common token formats, and secret-looking env
assignments while leaving the public remainder of a string intact. Anything the
pipeline cannot confidently classify fails closed to ``[redacted]``.
"""

from __future__ import annotations

import os
import re

from pydantic import JsonValue

_SECRET_SUBSTRINGS = (
    "api_key",
    "api-key",
    "secret",
    "token",
    "password",
    "authorization",
    "bearer",
)

_SK_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_ABS_PATH_PATTERN = re.compile(r"(?:^|[\s\"'=])(/[\w./-]+)")
# Strip URI userinfo (user:pass@host) without touching ordinary public endpoints.
# The character class admits raw "@" so a crafted authority with multiple
# delimiters redacts up to the LAST one — greedy matching must never leave a
# credential fragment behind (e.g. "alice@corp:pw@host" loses all userinfo).
# Query/fragment delimiters stop the match so a benign "@" there survives.
_URI_USERINFO_PATTERN = re.compile(
    r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<userinfo>[^/\s\"'?#]+@)",
)
# Secret-indicator words only count when not embedded in a larger alphanumeric
# word, so benign strings like "tokenizer" survive while "api_key" still trips.
_SECRET_SUBSTRING_PATTERN = re.compile(
    r"(?<![a-z0-9])(?:" + "|".join(_SECRET_SUBSTRINGS) + r")(?![a-z0-9])",
    re.IGNORECASE,
)
# Query parameters that carry signatures or credentials (URLs and plain k=v).
_SENSITIVE_QUERY_PATTERN = re.compile(
    r"\b(x-amz-signature|x-amz-credential|x-amz-security-token|access_token|api_key|apikey"
    r"|signature|password|secret|token|sig|key)=([^\s&\"']+)",
    re.IGNORECASE,
)
_GITHUB_TOKEN_PATTERN = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})\b",
)
_AWS_KEY_PATTERN = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_SLACK_TOKEN_PATTERN = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}\b")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?\b")
_PRIVATE_KEY_BLOCK_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_PRIVATE_KEY_MARKER_PATTERN = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")
_ENV_ASSIGNMENT_PATTERN = re.compile(r"(^|[\s\"'])([A-Za-z_][A-Za-z0-9_]*)=([^\s\"']+)")
_SECRET_NAME_PATTERN = re.compile(
    r"key|token|secret|password|passwd|credential|proxy",
    re.IGNORECASE,
)
_EXTRA_SECRET_MIN_LEN = 8


def _redact_env_assignments(value: str) -> str:
    """Redact ``NAME=value`` pairs whose NAME looks secret-bearing."""

    def repl(match: re.Match[str]) -> str:
        prefix, name = match.group(1), match.group(2)
        if _SECRET_NAME_PATTERN.search(name):
            return f"{prefix}{name}=[redacted]"
        return match.group(0)

    return _ENV_ASSIGNMENT_PATTERN.sub(repl, value)


def redact_string(value: str, *, extra_secrets: tuple[str, ...] = ()) -> str:
    """Fail-closed redaction for public export and shareable local artifacts.

    ``extra_secrets`` are caller-supplied literal values (e.g. process env
    secrets) scrubbed wherever they occur.
    """
    # Longest first: when one secret is a prefix of another, replacing the
    # short one first would disclose the longer secret's suffix.
    for secret in sorted(extra_secrets, key=len, reverse=True):
        if len(secret) >= _EXTRA_SECRET_MIN_LEN:
            value = value.replace(secret, "[redacted]")
    if _SK_PATTERN.search(value):
        return "[redacted]"
    if _URI_USERINFO_PATTERN.search(value):
        value = _URI_USERINFO_PATTERN.sub(r"\g<scheme>", value)
    if _SECRET_SUBSTRING_PATTERN.search(value):
        return "[redacted]"
    if value.startswith("/") or ":\\" in value:
        return "[redacted-path]"
    if _ABS_PATH_PATTERN.search(value):
        return "[redacted-path]"
    value = _SENSITIVE_QUERY_PATTERN.sub(r"\1=[redacted]", value)
    value = _GITHUB_TOKEN_PATTERN.sub("[redacted]", value)
    value = _AWS_KEY_PATTERN.sub("[redacted]", value)
    value = _SLACK_TOKEN_PATTERN.sub("[redacted]", value)
    value = _JWT_PATTERN.sub("[redacted]", value)
    value = _PRIVATE_KEY_BLOCK_PATTERN.sub("[redacted]", value)
    if _PRIVATE_KEY_MARKER_PATTERN.search(value):
        # Unterminated key block: ambiguous, fail closed.
        return "[redacted]"
    return _redact_env_assignments(value)


def env_secret_values() -> tuple[str, ...]:
    """Values of process env vars with secret-looking names.

    Deterministic (sorted) and never logged; used so public export scrubs live
    credential values even when their shape is not a known token format.
    """
    values = {
        value
        for name, value in os.environ.items()
        if len(value) >= _EXTRA_SECRET_MIN_LEN and _SECRET_NAME_PATTERN.search(name)
    }
    return tuple(sorted(values))


def sanitize_json_value(
    value: JsonValue,
    *,
    extra_secrets: tuple[str, ...] = (),
    sanitize_keys: bool = False,
) -> JsonValue:
    """Redact secret-shaped content in a JSON tree.

    ``sanitize_keys`` also redacts mapping keys; use it only for free-form
    payloads (e.g. preflight ``extra``). Typed record dumps have code-owned
    keys that must stay stable — and an env secret value can legitimately be a
    substring of a field name.
    """
    if isinstance(value, str):
        return redact_string(value, extra_secrets=extra_secrets)
    if isinstance(value, dict):
        return {
            (
                redact_string(str(k), extra_secrets=extra_secrets) if sanitize_keys else str(k)
            ): sanitize_json_value(
                v,
                extra_secrets=extra_secrets,
                sanitize_keys=sanitize_keys,
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            sanitize_json_value(v, extra_secrets=extra_secrets, sanitize_keys=sanitize_keys)
            for v in value
        ]
    return value


__all__ = ["env_secret_values", "redact_string", "sanitize_json_value"]
