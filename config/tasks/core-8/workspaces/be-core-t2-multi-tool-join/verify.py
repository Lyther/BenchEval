#!/usr/bin/env python3
"""Deterministic verifier for be-core-t2-multi-tool-join."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _score(candidate: dict[str, object], reference: dict[str, object]) -> dict[str, object]:
    ref_sequence = reference.get("tool_sequence")
    cand_sequence = candidate.get("tool_sequence")
    ref_result = reference.get("result")
    cand_result = candidate.get("result")

    order_ok = cand_sequence == ref_sequence
    result_ok = cand_result == ref_result
    partial_metrics = {
        "tool_order_correct": 1.0 if order_ok else 0.0,
        "final_object_match": 1.0 if result_ok else 0.0,
    }
    partial_score = sum(partial_metrics.values()) / len(partial_metrics)
    primary_pass = order_ok and result_ok
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
