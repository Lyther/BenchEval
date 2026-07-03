from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_renderer() -> object:
    script = Path("scripts/render-run-video.py")
    spec = importlib.util.spec_from_file_location("render_run_video", script)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_render_run_video_ass_only_builds_timeline(tmp_path: Path) -> None:
    renderer = _load_renderer()
    events = tmp_path / "events.jsonl"
    events.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "elapsed_sec": 0.0,
                        "kind": "system",
                        "display": "[00:00:00] SYSTEM    run_id=momo-test",
                    },
                ),
                json.dumps(
                    {
                        "elapsed_sec": 1.0,
                        "kind": "pass",
                        "display": "[00:00:01] PASS      urgent#1  FLAG: [redacted-flag]",
                    },
                ),
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "video.mp4"

    code = renderer.main(
        [
            "--events",
            str(events),
            "--output",
            str(output),
            "--ass-only",
            "--speed",
            "2",
            "--title",
            "BenchEval Test",
        ],
    )

    assert code == 0
    ass = output.with_suffix(".ass").read_text(encoding="utf-8")
    assert "BenchEval Test" in ass
    assert "run_id=momo-test" in ass
    assert "[redacted-flag]" in ass
    assert "Style: Terminal" in ass


def test_render_run_video_default_output_path() -> None:
    renderer = _load_renderer()
    events = Path("results/raw/external-run-20260625T092928Z/events.jsonl")
    assert renderer.default_output_path(events) == Path(
        "results/videos/external-run-20260625T092928Z.mp4",
    )
