#!/usr/bin/env python3
"""Build one SummaryRow from manifest + stamp + header JSON and append it as JSONL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from bencheval import JsonlSummarySink, StrictSummaryBuilder
from bencheval.exceptions import BenchEvalError
from bencheval.manifest import load_manifest
from bencheval.models import RunStamp


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    desc = "Emit a strict SummaryRow into JSONL from offline inputs."
    p = argparse.ArgumentParser(description=desc)
    p.add_argument(
        "--eval-log",
        type=Path,
        required=True,
        help="Path for log_file derivation (file need not exist)",
    )
    p.add_argument("--manifest", type=Path, required=True, help="Task manifest .txt")
    p.add_argument(
        "--stamp-json",
        type=Path,
        required=True,
        dest="stamp_json",
        help="RunStamp fields as JSON",
    )
    p.add_argument(
        "--header-json",
        type=Path,
        required=True,
        dest="header_json",
        help="Eval header dict as JSON",
    )
    p.add_argument("--output", type=Path, required=True, help="Destination JSONL file")
    return p.parse_args(argv)


def _load_json(path: Path) -> dict[str, object]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise BenchEvalError(f"cannot read {path}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise BenchEvalError(f"invalid JSON in {path.name}: {e}") from e
    if not isinstance(data, dict):
        raise BenchEvalError(f"JSON in {path.name} must be a JSON object")
    return data


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parse_args(argv)
        stamp_raw = _load_json(args.stamp_json)
        try:
            stamp = RunStamp(**stamp_raw)
        except ValidationError as e:
            print(f"invalid RunStamp: {e}", file=sys.stderr)
            return 2
        manifest = load_manifest(args.manifest)
        header = _load_json(args.header_json)
        row = StrictSummaryBuilder().build(args.eval_log, stamp, manifest, header)
        JsonlSummarySink().append_jsonl(args.output, row)
        return 0
    except BenchEvalError as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
