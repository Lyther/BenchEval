"""Backward-compatible entrypoint for older MOMO CyBench invocations.

The implementation now lives in :mod:`bencheval.external_command_adapter`.
This module intentionally contains no benchmark runner logic; it exists only so
older scripts that call ``python -m bencheval.momo_cybench`` keep delegating to
the generic external-command adapter.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from bencheval.exceptions import BenchEvalError
from bencheval.external_command_adapter import (
    ExternalAttemptResult,
    ExternalInstance,
    ExternalInstanceResult,
    ExternalRunConfig,
    ExternalRunPaths,
    load_external_run_config,
    make_external_run_paths,
    plan_external_run,
    replay,
    run_external_command,
    validate_external_run_root,
)
from bencheval.paths import repo_root

MomoChallenge = ExternalInstance
MomoCybenchConfig = ExternalRunConfig
RunPaths = ExternalRunPaths
AttemptResult = ExternalAttemptResult
ChallengeResult = ExternalInstanceResult


def load_config(path: Path) -> ExternalRunConfig:
    """Load a generic external-command config."""
    return load_external_run_config(path)


def make_run_paths(results_root: Path, run_id: str) -> ExternalRunPaths:
    """Compatibility alias for the generic external-command layout."""
    return make_external_run_paths(results_root, run_id)


def validate_run_root(config: ExternalRunConfig, run_root: Path) -> None:
    """Compatibility alias for generic run-root validation."""
    validate_external_run_root(config, run_root)


def _prepare_prompt_text(prompt: str, run_root: Path) -> str:
    """Compatibility helper for archived private prompt roots."""
    from bencheval.external_command_adapter import LEGACY_PRIVATE_ROOT_ALIAS

    return prompt.replace(LEGACY_PRIVATE_ROOT_ALIAS, str(run_root.resolve()))


def _sanitize_for_terminal(text: str, _flag_policy: object = None) -> str:
    """Compatibility helper: canonical and terminal output are raw."""
    return text


async def run_live(
    *,
    config: ExternalRunConfig,
    run_root: Path,
    results_root: Path,
    run_id: str | None = None,
    color: bool = True,
    remote_snapshot: bool | None = None,
) -> int:
    """Compatibility alias for generic external-command execution."""
    return await run_external_command(
        config=config,
        run_root=run_root,
        results_root=results_root,
        run_id=run_id,
        color=color,
        snapshot=remote_snapshot,
        producer_command="python -m bencheval.momo_cybench",
    )


def main(argv: list[str] | None = None) -> int:
    """Compatibility CLI for older ``python -m bencheval.momo_cybench`` calls."""
    parser = argparse.ArgumentParser(
        description="Compatibility wrapper for BenchEval external command runner",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=repo_root() / "config" / "runs" / "cybench-kilo-showcase.yaml",
    )
    parser.add_argument(
        "--run-root",
        type=Path,
        default=None,
        help="prepared benchmark root; defaults to config input.root_env",
    )
    parser.add_argument("--results-root", type=Path, default=repo_root() / "results")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    parser.add_argument(
        "--remote-snapshot",
        dest="snapshot",
        action="store_true",
        default=None,
        help="force configured host snapshot",
    )
    parser.add_argument(
        "--no-remote-snapshot",
        dest="snapshot",
        action="store_false",
        help="disable configured host snapshot",
    )
    parser.add_argument("--replay", type=Path, default=None, help="replay an events.jsonl file")
    parser.add_argument("--speed", type=float, default=1.0, help="replay speed multiplier")
    args = parser.parse_args(argv)

    try:
        if args.replay is not None:
            return replay(args.replay, color=not args.no_color, speed=args.speed)
        config = load_external_run_config(args.config)
        run_root = args.run_root
        if run_root is None and config.input.root_env:
            value = os.environ.get(config.input.root_env, "").strip()
            run_root = Path(value).expanduser() if value else None
        if args.dry_run:
            validate_external_run_root(config, run_root)
            payload = plan_external_run(
                config=config,
                run_root=run_root,
                results_root=args.results_root,
                run_id=args.run_id,
            )
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
            return 0
        return asyncio.run(
            run_external_command(
                config=config,
                run_root=run_root,
                results_root=args.results_root,
                run_id=args.run_id,
                color=not args.no_color,
                snapshot=args.snapshot,
                producer_command="python -m bencheval.momo_cybench",
            ),
        )
    except BenchEvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
