"""Structured preflight / doctor artifacts for live pilot (negative evidence)."""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from bencheval.exceptions import BenchEvalError


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
) -> Path:
    """Write JSON preflight artifact (pass or blocked)."""
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "preflight_v1",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "host": socket.gethostname(),
        "benchmark_id": benchmark_id,
        "slice_id": slice_id,
        "runtime_id": runtime_id,
        "model_id": model_id,
        "ok": ok,
        "doctor_backend": doctor_backend,
        "reasons": list(reasons or []),
        "extra": extra or {},
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
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
