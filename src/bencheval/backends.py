"""Execution backend identifiers for BenchEval runs."""

from __future__ import annotations

from typing import Literal

ExecutionBackend = Literal["local", "inspect", "harbor"]

LOCAL_BACKEND: ExecutionBackend = "local"
INSPECT_BACKEND: ExecutionBackend = "inspect"
HARBOR_BACKEND: ExecutionBackend = "harbor"
