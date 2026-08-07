"""Run id helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def new_run_id() -> str:
    stamp = datetime.now(tz=UTC).strftime("run-%Y%m%d-%H%M%S-%f")
    return f"{stamp}-{uuid4().hex[:8]}"


__all__ = ["new_run_id"]
