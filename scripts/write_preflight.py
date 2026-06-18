#!/usr/bin/env python3
"""Write results/preflight/*.json for blocked live pilot steps."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bencheval.preflight_report import write_preflight_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write preflight_v1 JSON artifact")
    parser.add_argument("--output", type=str, required=True)
    parser.add_argument("--benchmark", required=True)
    parser.add_argument("--slice", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ok", choices=("true", "false"), required=True)
    parser.add_argument("--doctor-backend", default=None)
    parser.add_argument("--reason", action="append", default=[])
    args = parser.parse_args(argv)
    path = write_preflight_report(
        output_path=Path(args.output),
        benchmark_id=args.benchmark,
        slice_id=args.slice,
        runtime_id=args.runtime,
        model_id=args.model,
        ok=args.ok == "true",
        doctor_backend=args.doctor_backend,
        reasons=list(args.reason),
    )
    sys.stdout.write(f"{path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
