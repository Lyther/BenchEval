"""Strict JSONL summary reader; the reciprocal of JsonlSummarySink."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from bencheval.exceptions import BenchEvalError, SummaryValidationError
from bencheval.models import SummaryRow


def _parse_line(line: str, source: str, line_no: int) -> SummaryRow:
    try:
        return SummaryRow.model_validate_json(line)
    except json.JSONDecodeError as e:
        raise SummaryValidationError(
            f"{source}:line {line_no}: invalid JSON: {e}",
        ) from e
    except ValidationError as e:
        errs = e.errors()
        if len(errs) == 1 and errs[0].get("type") == "json_invalid":
            raise SummaryValidationError(
                f"{source}:line {line_no}: invalid JSON: {e}",
            ) from e
        raise SummaryValidationError(f"{source}:line {line_no}: {e}") from e


def read_summary_jsonl(path: Path | str) -> list[SummaryRow]:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise BenchEvalError(f"cannot read summary jsonl {p}: {e}") from e

    rows: list[SummaryRow] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        rows.append(_parse_line(line, p.name, line_no))
    return rows
