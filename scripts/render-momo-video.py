#!/usr/bin/env python3
"""Render a MOMO event stream to a terminal-style MP4 video."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ANSI_PATTERN = re.compile(r"\033\[[0-9;]*m")

KIND_RGB: dict[str, tuple[int, int, int]] = {
    "system": (88, 195, 223),
    "target": (214, 119, 252),
    "model": (125, 173, 255),
    "queue": (88, 195, 223),
    "start": (125, 173, 255),
    "llm": (230, 237, 243),
    "tool": (125, 173, 255),
    "debug": (139, 148, 158),
    "break": (255, 210, 77),
    "pass": (86, 211, 100),
    "fail": (255, 123, 114),
    "invalid": (255, 210, 77),
    "artifact": (88, 195, 223),
    "summary": (88, 224, 255),
}


@dataclass(frozen=True, slots=True)
class EventLine:
    elapsed_sec: float
    kind: str
    display: str


@dataclass(frozen=True, slots=True)
class RenderOptions:
    width: int
    height: int
    fps: int
    speed: float
    font: str
    font_size: int
    max_lines: int
    line_width: int
    title: str
    hold_sec: float


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render MOMO events.jsonl to MP4")
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--font", default="Menlo")
    parser.add_argument("--font-size", type=int, default=26)
    parser.add_argument("--max-lines", type=int, default=29)
    parser.add_argument("--line-width", type=int, default=112)
    parser.add_argument("--hold-sec", type=float, default=4.0)
    parser.add_argument(
        "--title",
        default="MOMO | GLM 5.2 / Kilo / CyBench | Production Run",
    )
    parser.add_argument(
        "--ass-only",
        action="store_true",
        help="write the ASS sidecar only; useful for renderer tests",
    )
    args = parser.parse_args(argv)

    if args.speed <= 0:
        print("error: --speed must be > 0", file=sys.stderr)
        return 2
    if args.fps <= 0:
        print("error: --fps must be > 0", file=sys.stderr)
        return 2

    output = args.output or default_output_path(args.events)
    output.parent.mkdir(parents=True, exist_ok=True)
    ass_path = output.with_suffix(".ass")
    options = RenderOptions(
        width=args.width,
        height=args.height,
        fps=args.fps,
        speed=args.speed,
        font=args.font,
        font_size=args.font_size,
        max_lines=args.max_lines,
        line_width=args.line_width,
        title=args.title,
        hold_sec=args.hold_sec,
    )
    events = load_events(args.events)
    ass_text, duration_sec = build_ass(events, options)
    ass_path.write_text(ass_text, encoding="utf-8")
    if args.ass_only:
        print(ass_path)
        return 0
    render_mp4(events, output, options, duration_sec)
    print(output)
    return 0


def default_output_path(events_path: Path) -> Path:
    run_id = events_path.parent.name
    return Path("results") / "videos" / f"{run_id}.mp4"


def load_events(path: Path) -> list[EventLine]:
    rows: list[EventLine] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        elapsed = float(payload.get("elapsed_sec", 0.0))
        kind = str(payload.get("kind", "system"))
        display = str(payload.get("display", payload.get("message", "")))
        rows.append(
            EventLine(
                elapsed_sec=max(0.0, elapsed),
                kind=kind,
                display=strip_ansi(display),
            ),
        )
    if not rows:
        raise ValueError(f"{path} has no events")
    return rows


def build_ass(events: list[EventLine], options: RenderOptions) -> tuple[str, float]:
    timeline = normalize_timeline(events, options.speed)
    duration = timeline[-1][0] + options.hold_sec
    terminal_lines: list[tuple[str, str]] = []
    dialogues: list[str] = []

    title = ass_escape(options.title)
    subtitle = "Live terminal evidence | redacted public playback"
    title_text = (
        r"{\an7\pos(64,42)\b1\fs54\c&HFFEC8B&}MOMO"
        rf"\N{{\fs25\b0\c&HFFFFFF&}}{title}"
        rf"\N{{\fs20\c&H9EA7B3&}}{subtitle}"
    )
    dialogues.append(dialogue(0.0, duration, "Title", title_text))

    for index, (event_time, event) in enumerate(timeline):
        terminal_lines.extend(wrap_event(event, options.line_width))
        terminal_lines = terminal_lines[-options.max_lines :]
        end_time = timeline[index + 1][0] if index + 1 < len(timeline) else duration
        if end_time <= event_time:
            end_time = event_time + 0.05
        text = build_terminal_text(terminal_lines)
        dialogues.append(dialogue(event_time, end_time, "Terminal", text))

    header = ass_header(options)
    return header + "\n".join(dialogues) + "\n", duration


def normalize_timeline(events: list[EventLine], speed: float) -> list[tuple[float, EventLine]]:
    normalized: list[tuple[float, EventLine]] = []
    previous = 0.0
    min_spacing = 0.045
    for event in events:
        desired = event.elapsed_sec / speed
        current = max(desired, previous + min_spacing if normalized else 0.0)
        normalized.append((current, event))
        previous = current
    return normalized


def wrap_event(event: EventLine, width: int) -> list[tuple[str, str]]:
    display = collapse_whitespace(event.display)
    wrapped = textwrap.wrap(
        display,
        width=max(40, width),
        break_long_words=True,
        break_on_hyphens=False,
    )
    if not wrapped:
        return [(event.kind, "")]
    lines = [(event.kind, wrapped[0])]
    for continuation in wrapped[1:]:
        lines.append((event.kind, " " * 14 + continuation))
    return lines


def build_terminal_text(lines: list[tuple[str, str]]) -> str:
    rendered = []
    for kind, line in lines:
        color = ass_color(KIND_RGB.get(kind, (230, 237, 243)))
        rendered.append(rf"{{\c{color}}}{ass_escape(line)}")
    return r"{\an7\pos(64,166)}" + r"\N".join(rendered)


def ass_header(options: RenderOptions) -> str:
    style_format = ",".join(
        [
            "Format: Name",
            "Fontname",
            "Fontsize",
            "PrimaryColour",
            "SecondaryColour",
            "OutlineColour",
            "BackColour",
            "Bold",
            "Italic",
            "Underline",
            "StrikeOut",
            "ScaleX",
            "ScaleY",
            "Spacing",
            "Angle",
            "BorderStyle",
            "Outline",
            "Shadow",
            "Alignment",
            "MarginL",
            "MarginR",
            "MarginV",
            "Encoding",
        ],
    )
    title_style = ",".join(
        [
            "Style: Title",
            options.font,
            "34",
            "&H00FFFFFF",
            "&H00FFFFFF",
            "&H00000000",
            "&H00000000",
            "0",
            "0",
            "0",
            "0",
            "100",
            "100",
            "0",
            "0",
            "1",
            "0",
            "0",
            "7",
            "0",
            "0",
            "0",
            "1",
        ],
    )
    terminal_style = ",".join(
        [
            "Style: Terminal",
            options.font,
            str(options.font_size),
            "&H00E6EDF3",
            "&H00FFFFFF",
            "&H00000000",
            "&H00000000",
            "0",
            "0",
            "0",
            "0",
            "100",
            "100",
            "0",
            "0",
            "1",
            "0",
            "0",
            "7",
            "0",
            "0",
            "0",
            "1",
        ],
    )
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {options.width}",
            f"PlayResY: {options.height}",
            "WrapStyle: 2",
            "ScaledBorderAndShadow: yes",
            "",
            "[V4+ Styles]",
            style_format,
            title_style,
            terminal_style,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
            "",
        ],
    )


def dialogue(start: float, end: float, style: str, text: str) -> str:
    return f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}"


def render_mp4(
    events: list[EventLine],
    output: Path,
    options: RenderOptions,
    duration_sec: float,
) -> None:
    try:
        import cv2
        import numpy as np
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "rendering MP4 requires OpenCV in the invoking Python environment",
        ) from exc

    timeline = normalize_timeline(events, options.speed)
    states = build_terminal_states(timeline, options)
    frame_count = max(1, int(duration_sec * options.fps))
    raw_output = output.with_suffix(".raw.mp4")
    writer = open_video_writer(raw_output, options, cv2)
    for frame_index in range(frame_count):
        elapsed = frame_index / options.fps
        state_index = state_index_for_time(states, elapsed)
        terminal_lines = states[state_index][1]
        frame = draw_frame(
            terminal_lines,
            elapsed_sec=elapsed,
            duration_sec=duration_sec,
            options=options,
            cv2=cv2,
            np=np,
        )
        writer.write(frame)
    writer.release()
    transcode_h264(raw_output, output)


def build_terminal_states(
    timeline: list[tuple[float, EventLine]],
    options: RenderOptions,
) -> list[tuple[float, list[tuple[str, str]]]]:
    terminal_lines: list[tuple[str, str]] = []
    states: list[tuple[float, list[tuple[str, str]]]] = []
    for event_time, event in timeline:
        terminal_lines.extend(wrap_event(event, options.line_width))
        terminal_lines = terminal_lines[-options.max_lines :]
        states.append((event_time, list(terminal_lines)))
    return states or [(0.0, [])]


def state_index_for_time(
    states: list[tuple[float, list[tuple[str, str]]]],
    elapsed: float,
) -> int:
    index = 0
    for candidate, (start, _) in enumerate(states):
        if start > elapsed:
            break
        index = candidate
    return index


def open_video_writer(output: Path, options: RenderOptions, cv2: Any) -> Any:
    writer = cv2.VideoWriter(
        str(output),
        cv2.VideoWriter_fourcc(*"mp4v"),
        options.fps,
        (options.width, options.height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"cannot open video writer for {output}")
    return writer


def transcode_h264(raw_output: Path, output: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raw_output.replace(output)
        return
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(raw_output),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(output),
    ]
    subprocess.run(cmd, check=True)
    raw_output.unlink(missing_ok=True)


def draw_frame(
    terminal_lines: list[tuple[str, str]],
    *,
    elapsed_sec: float,
    duration_sec: float,
    options: RenderOptions,
    cv2: Any,
    np: Any,
) -> Any:
    frame = np.zeros((options.height, options.width, 3), dtype=np.uint8)
    frame[:, :] = (18, 11, 7)
    cv2.rectangle(frame, (34, 34), (options.width - 34, 116), (32, 22, 14), -1)
    cv2.rectangle(frame, (42, 130), (options.width - 42, options.height - 58), (24, 17, 10), -1)
    cv2.rectangle(frame, (42, 130), (options.width - 42, options.height - 58), (64, 49, 32), 1)
    cv2.putText(
        frame,
        "MOMO",
        (64, 78),
        cv2.FONT_HERSHEY_DUPLEX,
        1.35,
        (139, 236, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        options.title,
        (220, 73),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (245, 245, 245),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        f"{ass_time(elapsed_sec)} / {ass_time(duration_sec)}",
        (options.width - 360, 74),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.62,
        (180, 175, 165),
        1,
        cv2.LINE_AA,
    )
    y = 174
    line_height = max(24, int(options.font_size * 1.18))
    font_scale = max(0.45, options.font_size / 43.0)
    for kind, line in terminal_lines:
        bgr = rgb_to_bgr(KIND_RGB.get(kind, (230, 237, 243)))
        cv2.putText(
            frame,
            line,
            (64, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (0, 0, 0),
            3,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            line,
            (64, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            bgr,
            1,
            cv2.LINE_AA,
        )
        y += line_height
    bar_left = 64
    bar_right = options.width - 64
    bar_y = options.height - 34
    cv2.rectangle(frame, (bar_left, bar_y), (bar_right, bar_y + 5), (55, 45, 38), -1)
    progress = 0.0 if duration_sec <= 0 else min(1.0, elapsed_sec / duration_sec)
    cv2.rectangle(
        frame,
        (bar_left, bar_y),
        (bar_left + int((bar_right - bar_left) * progress), bar_y + 5),
        (100, 205, 255),
        -1,
    )
    return frame


def ass_time(seconds: float) -> str:
    hundredths = round(max(0.0, seconds) * 100)
    centiseconds = hundredths % 100
    total_seconds = hundredths // 100
    secs = total_seconds % 60
    total_minutes = total_seconds // 60
    mins = total_minutes % 60
    hours = total_minutes // 60
    return f"{hours}:{mins:02d}:{secs:02d}.{centiseconds:02d}"


def ass_color(rgb: tuple[int, int, int]) -> str:
    red, green, blue = rgb
    return f"&H00{blue:02X}{green:02X}{red:02X}&"


def rgb_to_bgr(rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    red, green, blue = rgb
    return (blue, green, red)


def ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", "(").replace("}", ")").replace("\n", r"\N")


def ffmpeg_filter_path(path: Path) -> str:
    text = path.as_posix()
    for char in ("\\", ":", ",", "[", "]", "'"):
        text = text.replace(char, "\\" + char)
    return text


def collapse_whitespace(text: str) -> str:
    return " ".join(text.strip().split())


def strip_ansi(text: str) -> str:
    return ANSI_PATTERN.sub("", text)


if __name__ == "__main__":
    raise SystemExit(main())
