from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from bencheval import momo_cybench
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.momo_cybench import (
    MomoCybenchConfig,
    _prepare_prompt_text,
    _sanitize_for_terminal,
    load_config,
    main,
    make_run_paths,
    validate_run_root,
)


def _write_run_root(root: Path, challenge_id: str = "lootstash") -> None:
    (root / "run-prompts").mkdir(parents=True)
    (root / "keys").mkdir()
    (root / "meta").mkdir()
    (root / "run-prompts" / f"{challenge_id}.txt").write_text(
        "Solve task through ssh and print FLAG.\n",
        encoding="utf-8",
    )
    key = root / "keys" / challenge_id
    key.write_text("private-key-placeholder\n", encoding="utf-8")
    key.chmod(0o600)
    (root / "meta" / "manifest.private.json").write_text(
        json.dumps([{"name": challenge_id, "flag": "FLAG{ok}"}]),
        encoding="utf-8",
    )


def _write_fake_kilo(path: Path) -> None:
    events_literal = repr(
        [
            {"type": "text", "part": {"type": "text", "text": "Starting analysis"}},
            {
                "type": "tool_use",
                "tokens": {"total": 10, "output": 3},
                "part": {
                    "type": "tool",
                    "tool": "bash",
                    "state": {
                        "status": "completed",
                        "input": {"description": "list files"},
                        "output": "artifact.bin",
                    },
                },
            },
            {
                "type": "text",
                "tokens": {"total": 20, "output": 8},
                "part": {"type": "text", "text": "FLAG: FLAG{ok}"},
            },
        ],
    )
    path.write_text(
        "\n".join(
            [
                "import json",
                f"events = {events_literal}",
                "for event in events:",
                "    print(json.dumps(event), flush=True)",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_momo_config() -> None:
    cfg = load_config(Path("config/momo/cybench-showcase.yaml"))
    assert cfg.name == "momo-cybench-glm52"
    assert cfg.model == "ollama-cloud/glm-5.2"
    assert [challenge.id for challenge in cfg.challenges] == [
        "lootstash",
        "urgent",
        "packedaway",
    ]


def test_validate_run_root_reports_missing_private_material(tmp_path: Path) -> None:
    cfg = MomoCybenchConfig(challenges=[{"id": "lootstash"}])
    with pytest.raises(BenchEvalError, match="prompt:lootstash"):
        validate_run_root(cfg, tmp_path)


def test_momo_live_with_fake_kilo_writes_evidence(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_root = tmp_path / "run-root"
    _write_run_root(run_root)
    fake_kilo = tmp_path / "fake_kilo.py"
    _write_fake_kilo(fake_kilo)
    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join(
            [
                'name: "momo-test"',
                'target_host: "vps.0xb105.com"',
                'model: "ollama-cloud/glm-5.2"',
                'variant: "max"',
                f'kilo_argv_prefix: ["{sys.executable}", "{fake_kilo}"]',
                "output_token_max: 131072",
                "concurrency: 1",
                "max_attempts: 1",
                "remote_snapshot: false",
                "challenges:",
                '  - id: "lootstash"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    async def fail_snapshot(*args: object, **kwargs: object) -> None:
        raise AssertionError("config remote_snapshot=false should be honored")

    monkeypatch.setattr(momo_cybench, "_capture_remote_snapshot", fail_snapshot)

    run_id = "momo-test-run"
    code = main(
        [
            "--config",
            str(config),
            "--run-root",
            str(run_root),
            "--results-root",
            str(tmp_path / "results"),
            "--run-id",
            run_id,
            "--no-color",
        ],
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "MOMO" in out
    assert "FLAG: [redacted]" in out
    paths = make_run_paths(tmp_path / "results", run_id)
    rows = read_evidence_jsonl(paths.evidence_jsonl)
    assert len(rows) == 1
    assert rows[0].primary_pass is True
    assert rows[0].adapter_metadata["flag_check"] == "flag_match"
    assert paths.events_jsonl.is_file()
    assert paths.summary_json.is_file()


def test_remote_snapshot_timeout_writes_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SlowProcess:
        def __init__(self) -> None:
            self.killed = False

        async def communicate(self) -> tuple[bytes, None]:
            if not self.killed:
                await asyncio.sleep(60)
            return b"", None

        def kill(self) -> None:
            self.killed = True

    class CapturingSink:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def emit(self, _kind: str, message: str, **_kwargs: object) -> None:
            self.messages.append(message)

    async def fake_create_subprocess_exec(*_args: object, **_kwargs: object) -> SlowProcess:
        return SlowProcess()

    monkeypatch.setattr(momo_cybench.shutil, "which", lambda _name: "/usr/bin/ssh")
    monkeypatch.setattr(
        momo_cybench.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    paths = make_run_paths(tmp_path / "results", "snapshot-timeout")
    cfg = MomoCybenchConfig(
        challenges=[{"id": "lootstash"}],
        remote_snapshot_timeout_sec=0.001,
    )
    sink = CapturingSink()

    asyncio.run(momo_cybench._capture_remote_snapshot(cfg, paths, sink))

    assert "timed out" in (paths.remote_dir / "host.txt").read_text(encoding="utf-8")
    assert any("timed out" in message for message in sink.messages)


def test_prepare_prompt_text_rewrites_archived_private_root(tmp_path: Path) -> None:
    run_root = tmp_path / "private-root"
    prompt = (
        "Use ssh -i /tmp/bencheval-cybench-real-vps/keys/lootstash vps.0xb105.com '<command>'.\n"
    )
    prepared = _prepare_prompt_text(prompt, run_root)
    assert "/tmp/bencheval-cybench-real-vps" not in prepared
    assert str(run_root.resolve() / "keys" / "lootstash") in prepared


def test_terminal_sanitizer_redacts_embedded_flag_tokens() -> None:
    text = "Decoded candidate output. FLAG: HTB{example_secret} found in memory"
    assert _sanitize_for_terminal(text, "redact") == (
        "Decoded candidate output. FLAG: [redacted-flag] found in memory"
    )


def test_momo_replay_prints_captured_display(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text(
        json.dumps(
            {
                "elapsed_sec": 0.0,
                "kind": "pass",
                "display": "[00:00:00] PASS     lootstash  flag verified",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    assert main(["--replay", str(events), "--no-color", "--speed", "100"]) == 0
    assert "flag verified" in capsys.readouterr().out


def test_shell_entrypoint_mentions_run_root() -> None:
    script = Path("scripts/momo-cybench-live.sh")
    text = script.read_text(encoding="utf-8")
    assert "MOMO_CYBENCH_RUN_ROOT" in text
    assert "bencheval.momo_cybench" in text
