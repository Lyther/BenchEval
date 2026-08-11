"""Structured preflight / doctor artifacts for live pilot (negative evidence)."""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from bencheval.exceptions import BenchEvalError
from bencheval.redaction import env_secret_values, redact_string, sanitize_json_value


def write_preflight_report(
    *,
    output_path: Path,
    benchmark_id: str,
    slice_id: str,
    runtime_id: str,
    model_id: str,
    ok: bool,
    doctor_backend: str | None = None,
    reasons: list[str] | None = None,
    extra: dict[str, JsonValue] | None = None,
    visibility: Literal["private", "public"] = "private",
) -> Path:
    """Write JSON preflight artifact (pass or blocked).

    ``visibility="private"`` (default) keeps local diagnostic detail, including
    the hostname; treat the file as operator-local. ``visibility="public"``
    omits the hostname and scrubs every string-bearing field — top-level
    identifiers, ``reasons``, and ``extra`` values *and* mapping keys — with
    the same fail-closed pipeline as public run bundles, so the artifact is
    safe to share.
    """
    output_path = output_path.resolve()
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise BenchEvalError(
            f"cannot create preflight report parent {output_path.parent}: {e}",
        ) from e
    secrets = env_secret_values()
    public = visibility == "public"
    if visibility not in ("private", "public"):
        raise BenchEvalError(f"unknown preflight visibility: {visibility!r}")

    def scrub(text: str) -> str:
        return redact_string(text, extra_secrets=secrets) if public else text

    payload: dict[str, JsonValue] = {
        "schema_version": "preflight_v1",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "visibility": visibility,
        "benchmark_id": scrub(benchmark_id),
        "slice_id": scrub(slice_id),
        "runtime_id": scrub(runtime_id),
        "model_id": scrub(model_id),
        "ok": ok,
        "doctor_backend": scrub(doctor_backend) if doctor_backend is not None else None,
        "reasons": [redact_string(r, extra_secrets=secrets) for r in (reasons or [])],
        "extra": sanitize_json_value(extra or {}, extra_secrets=secrets, sanitize_keys=True),
    }
    if not public:
        # Operator-local diagnostics only; the key is absent in public mode.
        payload["host"] = socket.gethostname()
    try:
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        raise BenchEvalError(f"cannot write preflight report {output_path}: {e}") from e
    return output_path


def load_preflight_report(path: Path) -> dict[str, JsonValue]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise BenchEvalError(f"invalid preflight report {path}: {e}") from e
    if not isinstance(raw, dict):
        raise BenchEvalError(f"preflight report must be a JSON object: {path}")
    return raw


__all__ = ["load_preflight_report", "write_preflight_report"]
