"""Shared run execution result type."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bencheval.evidence import EvidenceRecord


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    evidence: EvidenceRecord
    verifier_log_path: Path
