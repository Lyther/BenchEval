"""Append-only JSONL summary sink; not thread-safe."""

from __future__ import annotations

from pathlib import Path

from bencheval.exceptions import BenchEvalError
from bencheval.models import SummaryRow


class JsonlSummarySink:
    """Append ``SummaryRow`` as JSON lines via ``model_dump_json``; single-threaded only."""

    def append_jsonl(self, path: Path, row: SummaryRow) -> None:
        target = path.resolve()
        if target.exists() and not target.is_file():
            raise BenchEvalError(f"path exists but is not a regular file: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        line = row.model_dump_json() + "\n"
        with target.open("a", encoding="utf-8") as f:
            f.write(line)
