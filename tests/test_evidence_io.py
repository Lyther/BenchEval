"""Evidence JSONL read path error handling."""

from __future__ import annotations

import pytest

from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError


def test_read_evidence_jsonl_invalid_utf8_raises_bencheval_error(tmp_path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_bytes(b"\xff\xfe\n")
    with pytest.raises(BenchEvalError, match="decode"):
        read_evidence_jsonl(path)
