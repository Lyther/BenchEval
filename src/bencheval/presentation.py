"""Public presentation helpers for derived artifacts.

This module owns redaction and ANSI stripping for **derived public artifacts**
(public reports, demo videos, shareable transcripts). It is deliberately
separate from :mod:`bencheval.replay` so the raw canonical record loader/replayer
never imports presentation/redaction policy.

Canonical run records are raw. Redaction belongs here, in the presentation layer,
and derived artifacts must carry provenance (source path/hash, redaction mode,
generated time).
"""

from __future__ import annotations

import re

_FLAG_RE = re.compile(r"(?im)^FLAG:\s*(?P<flag>\S[^\r\n]*)")
_EMBEDDED_FLAG_RE = re.compile(r"\b[A-Z0-9_]+\{[^}\r\n]{1,240}\}")
_SECRET_RE = re.compile(
    r"(?i)(sk-[a-z0-9_\-]{8,}|api[_-]?key\s*[=:]\s*[^\s]+|authorization:\s*[^\s]+)",
)

_ANSI_STRIP_RE = re.compile(r"\033\[[0-9;]*m")


def redact_for_public_presentation(text: str, *, redact: bool = True) -> str:
    """Redact flags and secrets from text for **derived public artifacts** only.

    This is NOT called by ``replay()`` or ``load_run_record()``. Canonical run
    records are raw. Use this helper when generating a public report, demo video,
    or shareable transcript that must not expose flags/secrets.

    Provenance: callers should record the source path/hash, redaction mode, and
    generation time alongside the derived artifact.
    """
    sanitized = text
    if redact:
        sanitized = _FLAG_RE.sub("FLAG: [redacted]", sanitized)
        sanitized = _EMBEDDED_FLAG_RE.sub("[redacted-flag]", sanitized)
    sanitized = _SECRET_RE.sub("[redacted-secret]", sanitized)
    return sanitized


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences (for plain-text derived logs)."""
    return _ANSI_STRIP_RE.sub("", text)


__all__ = [
    "redact_for_public_presentation",
    "strip_ansi",
]
