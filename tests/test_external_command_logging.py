from __future__ import annotations

import itertools
import json
import sqlite3
from pathlib import Path

from bencheval import external_command_adapter as adapter
from bencheval.external_command_adapter import (
    ExternalCommandConfig,
    ExternalEventSink,
    ExternalInstance,
    ExternalRunConfig,
    TeeConsole,
)


def _config() -> ExternalRunConfig:
    return ExternalRunConfig(
        name="logging-test",
        benchmark_id="unit",
        runtime_id="runtime",
        model_id="model",
        command=ExternalCommandConfig(argv_prefix=("echo",)),
        instances=[ExternalInstance(id="case")],
    )


def _event_messages(path: Path) -> list[str]:
    messages: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("record_type") == "event":
            messages.append(str(record["message"]))
    return messages


def _sink(tmp_path: Path) -> tuple[ExternalEventSink, TeeConsole, Path, Path]:
    console = TeeConsole(
        tmp_path / "console.ansi.log",
        tmp_path / "console.plain.log",
        color=False,
    )
    events = tmp_path / "events.jsonl"
    live_state = tmp_path / "live_state.sqlite"
    sink = ExternalEventSink(
        console,
        events,
        live_state,
        100.0,
        config=_config(),
        run_id="run",
    )
    return sink, console, events, live_state


def test_no_color_console_writes_only_plain_log(tmp_path: Path) -> None:
    ansi = tmp_path / "console.ansi.log"
    plain = tmp_path / "console.plain.log"

    console = TeeConsole(ansi, plain, color=False)
    console.line("hello", kind="llm")
    console.close()

    assert plain.read_text(encoding="utf-8") == "hello\n"
    assert not ansi.exists()


def test_high_volume_stream_goes_to_live_state_not_canonical(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # llm/tool/debug are the per-token mid-step stream: every event updates the
    # mutable live-state row (real-time stuck-detection) but NONE are appended to
    # the canonical events.jsonl.
    clock = itertools.count(1000)
    monkeypatch.setattr(adapter.time, "monotonic", lambda: float(next(clock)))
    sink, console, events, live_state = _sink(tmp_path)

    sink.emit("llm", "reason-1", instance_id="case", attempt=1)
    sink.emit("tool", "call-nmap", instance_id="case", attempt=1)
    sink.emit("llm", "reason-3-latest", instance_id="case", attempt=1)
    sink.close()
    console.close()

    # Canonical events.jsonl carries NO high-volume event records (routed, not dropped).
    assert _event_messages(events) == []
    body = events.read_text(encoding="utf-8")
    assert "reason-1" not in body
    assert "reason-3-latest" not in body

    # The live-state row exists and reflects the LATEST mid-step event -- every event
    # updated it (no rate-limit, no drop), so a monitor detects stuck steps by the
    # row's freshness.
    with sqlite3.connect(live_state) as conn:
        row = conn.execute(
            "SELECT instance_id, attempt, kind, message_preview, elapsed_sec "
            "FROM attempt_live_state",
        ).fetchone()
    assert row is not None
    assert (row[0], row[1], row[2]) == ("case", 1, "llm")
    assert "reason-3-latest" in row[3]
    assert row[4] > 0.0  # elapsed advanced with the stream


def test_benchmark_events_written_to_canonical_at_full_fidelity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    # Non-high-volume (benchmark / lifecycle) events are written to events.jsonl
    # complete and unredacted -- no compaction, no dropping. The canonical lane stays
    # the integrity-preserving scoring/audit record.
    clock = itertools.count(1000)
    monkeypatch.setattr(adapter.time, "monotonic", lambda: float(next(clock)))
    sink, console, events, _live_state = _sink(tmp_path)

    long_message = "solved flag{" + ("a" * 2000) + "}"
    sink.emit("pass", long_message, instance_id="case", attempt=1)
    sink.close()
    console.close()

    assert _event_messages(events) == [long_message]  # full, uncompacted, present
