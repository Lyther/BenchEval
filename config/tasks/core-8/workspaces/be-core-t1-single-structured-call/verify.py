#!/usr/bin/env python3
"""Deterministic verifier for be-core-t1-single-structured-call."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _score(candidate: dict[str, object], reference: dict[str, object]) -> dict[str, object]:
    tool_ok = candidate.get("tool") == reference.get("tool")
    args_ok = candidate.get("arguments") == reference.get("arguments")
    partial_metrics = {
        "tool_selection": 1.0 if tool_ok else 0.0,
        "argument_match": 1.0 if args_ok else 0.0,
    }
    partial_score = sum(partial_metrics.values()) / len(partial_metrics)
    primary_pass = tool_ok and args_ok
    return {
        "primary_pass": primary_pass,
        "partial_score": partial_score,
        "partial_metrics": partial_metrics,
    }


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: verify.py <candidate.json>\n")
        raise SystemExit(2)
    workspace = Path(__file__).resolve().parent
    candidate = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    reference = json.loads((workspace / "reference.json").read_text(encoding="utf-8"))
    result = _score(candidate, reference)
    sys.stdout.write(json.dumps(result) + "\n")
    return 0 if result["primary_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
