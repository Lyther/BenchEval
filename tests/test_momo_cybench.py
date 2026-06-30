from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bencheval import external_command_adapter
from bencheval.cli import main
from bencheval.evidence import read_evidence_jsonl
from bencheval.exceptions import BenchEvalError
from bencheval.external_command_adapter import (
    ExternalRunConfig,
    _classify_result,
    _hit_output_cap,
    _prompt_text,
    load_external_run_config,
    make_external_run_paths,
    validate_external_run_root,
)
from bencheval.presentation import redact_for_public_presentation
from bencheval.replay import load_run_record


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


def _write_fake_exit(path: Path, exit_code: int) -> None:
    path.write_text(
        "\n".join(
            [
                "import sys",
                "print('tool started', flush=True)",
                f"raise SystemExit({exit_code})",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def test_load_external_command_config() -> None:
    cfg = load_external_run_config(Path("config/runs/cybench-kilo-showcase.yaml"))
    assert cfg.name == "cybench-kilo-showcase"
    assert cfg.model_id == "ollama-cloud/glm-5.2"
    assert [instance.id for instance in cfg.instances] == [
        "lootstash",
        "urgent",
        "packedaway",
    ]


def test_momo_cybench_profile_has_full_hard_39_slice() -> None:
    """The MOMO solver profile pins the real hard-39 instance list (not a skeleton).

    IDs are authoritative: each is a private-manifest `name` / `prompts/{id}.prompt.txt`
    stem from the hard-39 GLM-5.2 evidence export. Guards against silently regressing
    the committed profile back to the Phase 1b one-instance skeleton.
    """
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    assert cfg.name == "momo-cybench"
    assert cfg.benchmark_version == "hard-39-private"
    assert cfg.model_id == "bytellm/glm-5.2"
    ids = [instance.id for instance in cfg.instances]
    assert len(ids) == 39
    assert len(set(ids)) == 39  # no duplicates
    # Spot-check authoritative endpoints of the sorted slice + a mid entry.
    assert {"avatar", "lootstash", "were_pickle_phreaks_revenge"} <= set(ids)


def test_momo_cybench_scorer_is_strict_no_observed_without_expected() -> None:
    """The MOMO profile must score only against an official expected value.

    With ``allow_observed_without_expected=false``, a printed ``FLAG:`` whose
    instance has no expected value in the private manifest (``expected is None``)
    must be classified as NOT passed — never a self-asserted solve. A real
    expected value still scores by exact match. Guards the official-scorer-only
    requirement (peer review F001).
    """
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    assert cfg.verification.allow_observed_without_expected is False
    # Missing expected (e.g. manifest gap) + a printed flag must NOT pass.
    passed, value_match = _classify_result(
        config=cfg,
        returncode=0,
        observed="FLAG{anything_the_solver_printed}",
        expected=None,
    )
    assert passed is False
    assert value_match is None
    # A real expected value scores by exact match (positive control).
    ok_pass, ok_match = _classify_result(
        config=cfg,
        returncode=0,
        observed="HTB{real}",
        expected="HTB{real}",
    )
    assert ok_pass is True
    assert ok_match is True


def test_validate_run_root_reports_missing_private_material(tmp_path: Path) -> None:
    cfg = ExternalRunConfig(
        name="missing-root-test",
        benchmark_id="cybench",
        runtime_id="kilo",
        model_id="ollama-cloud/glm-5.2",
        command={"argv_prefix": ["true"]},
        input={"required_path_templates": ["keys/{instance_id}"]},
        instances=[{"id": "lootstash"}],
    )
    with pytest.raises(BenchEvalError, match="prompt:lootstash"):
        validate_external_run_root(cfg, tmp_path)


def test_validate_run_root_blocks_key_referenced_by_prompt(tmp_path: Path) -> None:
    """A key the SELECTED prompt references must exist, else preflight fails closed.

    Private material is required per-prompt: an SSH challenge whose prompt says
    `ssh -i .../keys/<id>` must have that key. The block is fail-fast (not a silent
    run with gaps). `bencheval run` calls this preflight before launch (peer review
    F003/F004).
    """
    run_root = tmp_path / "rr"
    (run_root / "run-prompts").mkdir(parents=True)
    (run_root / "run-prompts" / "skilift.txt").write_text(
        "Solve through ssh -i keys/skilift root@victim and print FLAG.\n",
        encoding="utf-8",
    )
    cfg = ExternalRunConfig(
        name="keys-preflight-test",
        benchmark_id="cybench",
        runtime_id="claude-code",
        model_id="bytellm/glm-5.2",
        command={"argv_prefix": ["true"]},
        input={
            "prompt_path_templates": ["run-prompts/{instance_id}.txt"],
            "required_path_templates": ["keys/{instance_id}"],
        },
        instances=[{"id": "skilift"}],
    )
    # Prompt references keys/skilift, so the missing key is a hard block.
    with pytest.raises(BenchEvalError, match=r"required:skilift:keys/skilift"):
        validate_external_run_root(cfg, run_root)


def test_validate_run_root_prompt_only_instance_needs_no_key(tmp_path: Path) -> None:
    """A prompt-only instance whose prompt references no key passes preflight even when
    `required_path_templates` lists `keys/{id}` — keys are required only when the
    selected prompt references them, so a non-SSH challenge is not falsely blocked
    (peer review F003)."""
    run_root = tmp_path / "rr"
    (run_root / "prompts").mkdir(parents=True)
    (run_root / "prompts" / "skilift.prompt.txt").write_text(
        "Reverse the binary and print the FLAG. No remote service.\n",
        encoding="utf-8",
    )
    cfg = ExternalRunConfig(
        name="prompt-only-test",
        benchmark_id="cybench",
        runtime_id="claude-code",
        model_id="bytellm/glm-5.2",
        command={"argv_prefix": ["true"]},
        input={
            "prompt_path_templates": [
                "run-prompts/{instance_id}.txt",
                "prompts/{instance_id}.prompt.txt",
            ],
            "required_path_templates": ["keys/{instance_id}"],
        },
        instances=[{"id": "skilift"}],
    )
    validate_external_run_root(cfg, run_root)  # must not raise — no key referenced


def test_full_hard39_profile_passes_preflight_against_historical_root() -> None:
    """The committed momo-cybench profile preflights cleanly against the historical
    hard-39 root: the four prompt-only instances (no key) pass because their prompts
    reference no key, and every key-using instance has its key (peer review F003)."""
    root = Path(
        "results/raw/cybench-hard-39-glm52-20260618T022156Z/local/bencheval-cybench-real-vps"
    )
    if not root.is_dir():
        pytest.skip("historical hard-39 run root not present")
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    validate_external_run_root(cfg, root)  # must not raise — false key blocker removed


def test_dry_run_without_run_root_is_labeled_shape_only(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dry-run of a `root_env` config with no `--run-root` (and the env var unset)
    must label itself shape-only — private material was NOT validated — so an omitted
    run root cannot read as a launch-ready plan (peer review F005)."""
    monkeypatch.delenv("MOMO_CYBENCH_RUN_ROOT", raising=False)
    code = main(["run", "--config", "config/runs/momo-cybench.yaml", "--dry-run"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_root"] is None
    assert payload["shape_only"] is True
    assert payload["private_material_validated"] is False
    assert "MOMO_CYBENCH_RUN_ROOT" in payload["note"]


def test_external_command_live_with_fake_kilo_writes_evidence(
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
                'schema_version: "external_command_run_v1"',
                'name: "external-test"',
                'benchmark_id: "cybench"',
                'benchmark_version: "hard-39-private"',
                'slice_id: "cybench-showcase"',
                'adapter_id: "external-command"',
                'runtime_id: "kilo"',
                'runtime_kind: "cli_agent"',
                'model_id: "ollama-cloud/glm-5.2"',
                'variant: "max"',
                'execution_profile: "E2"',
                'target_host: "vps.0xb105.com"',
                'banner_title: "BenchEval"',
                "command:",
                f'  argv_prefix: ["{sys.executable}", "{fake_kilo}"]',
                "  args_template: []",
                "input:",
                '  prompt_path_templates: ["run-prompts/{instance_id}.txt"]',
                '  required_path_templates: ["keys/{instance_id}"]',
                "stream:",
                '  parser: "kilo-json"',
                "  output_token_max: 131072",
                "verification:",
                '  kind: "manifest-value-regex"',
                r"  observed_regex: '(?im)^FLAG:\s*(?P<value>\S[^\r\n]*)'",
                '  manifest_paths: ["meta/manifest.private.json"]',
                "concurrency: 1",
                "max_attempts: 1",
                "instances:",
                '  - id: "lootstash"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    async def fail_snapshot(*args: object, **kwargs: object) -> None:
        raise AssertionError("config snapshot.enabled=false should be honored")

    monkeypatch.setattr(external_command_adapter, "_capture_snapshot", fail_snapshot)

    run_id = "external-test-run"
    code = main(
        [
            "run",
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
    assert "BenchEval" in out
    # Canonical records are raw: the flag appears unchanged in both stdout and
    # events.jsonl.
    assert "FLAG{ok}" in out
    paths = make_external_run_paths(tmp_path / "results", run_id)
    rows = read_evidence_jsonl(paths.evidence_jsonl)
    assert len(rows) == 1
    assert rows[0].primary_pass is True
    assert rows[0].adapter_metadata["result_check"] == "value_match"
    assert paths.events_jsonl.is_file()
    # The canonical events.jsonl must preserve the raw flag (no redaction).
    events_text = paths.events_jsonl.read_text(encoding="utf-8")
    assert "FLAG{ok}" in events_text
    assert "[redacted]" not in events_text
    record = load_run_record(paths.events_jsonl)
    assert record.schema_version == "bencheval_run_record_v1"
    assert record.header is not None
    assert record.header.run_id == run_id
    assert record.header.benchmark_id == "cybench"
    assert record.footer is not None
    expected_evidence_sha = hashlib.sha256(
        paths.evidence_jsonl.read_bytes(),
    ).hexdigest()
    assert record.footer.evidence_sha256 == expected_evidence_sha
    assert paths.summary_json.is_file()


def test_external_command_legacy_config_still_preserves_raw_canonical(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Legacy reference config shape is normalized into the generic adapter."""
    run_root = tmp_path / "run-root"
    _write_run_root(run_root)
    fake_kilo = tmp_path / "fake_kilo_legacy.py"
    _write_fake_kilo(fake_kilo)
    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join(
            [
                'name: "legacy-config-test"',
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

    run_id = "legacy-config-test"
    with pytest.warns(DeprecationWarning, match="legacy external command config"):
        code = main(
            [
                "run",
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
    capsys.readouterr()  # consume stdout (may contain redacted display)
    paths = make_external_run_paths(tmp_path / "results", run_id)
    # The canonical events.jsonl must preserve the raw flag.
    events_text = paths.events_jsonl.read_text(encoding="utf-8")
    assert "FLAG{ok}" in events_text
    assert "[redacted]" not in events_text


def test_external_command_nonzero_exit_is_runtime_tool_failure(tmp_path: Path) -> None:
    run_root = tmp_path / "run-root"
    _write_run_root(run_root)
    fake_tool = tmp_path / "fake_exit.py"
    _write_fake_exit(fake_tool, 7)
    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join(
            [
                'schema_version: "external_command_run_v1"',
                'name: "nonzero-test"',
                'benchmark_id: "external-proof"',
                'runtime_id: "python-subprocess"',
                'model_id: "external/proof-runtime"',
                "command:",
                f'  argv_prefix: ["{sys.executable}", "{fake_tool}"]',
                "  args_template: []",
                "input:",
                '  prompt_path_templates: ["run-prompts/{instance_id}.txt"]',
                "verification:",
                '  kind: "none"',
                "instances:",
                '  - id: "lootstash"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )

    run_id = "nonzero-test"
    code = main(
        [
            "run",
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

    assert code == 1
    rows = read_evidence_jsonl(
        make_external_run_paths(tmp_path / "results", run_id).evidence_jsonl,
    )
    assert rows[0].failure_class == "runtime_tool_failure"
    assert rows[0].invalid_reason == "process_exit=7"


def test_output_cap_uses_total_when_output_missing() -> None:
    assert _hit_output_cap({"total": 131072}, 131072) is True
    assert _hit_output_cap({"total": 131071}, 131072) is False
    assert _hit_output_cap({"output": 5, "total": 999}, 10) is False


def test_run_external_command_closes_console_when_sink_init_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = ExternalRunConfig(
        name="cleanup-test",
        benchmark_id="external-proof",
        runtime_id="python-subprocess",
        model_id="external/proof-runtime",
        command={"argv_prefix": ["true"]},
        instances=[{"id": "hello", "prompt_file": str(tmp_path / "prompt.txt")}],
    )
    (tmp_path / "prompt.txt").write_text("prompt\n", encoding="utf-8")
    closed: list[bool] = []
    original_close = external_command_adapter.TeeConsole.close

    def record_close(self: object) -> None:
        closed.append(True)
        original_close(self)

    class BrokenSink:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("sink init failed")

    monkeypatch.setattr(external_command_adapter.TeeConsole, "close", record_close)
    monkeypatch.setattr(external_command_adapter, "ExternalEventSink", BrokenSink)

    with pytest.raises(RuntimeError, match="sink init failed"):
        asyncio.run(
            external_command_adapter.run_external_command(
                config=cfg,
                run_root=None,
                results_root=tmp_path / "results",
                color=False,
            ),
        )

    assert closed == [True]


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

    async def fake_create_subprocess_exec(
        *_args: object,
        **_kwargs: object,
    ) -> SlowProcess:
        return SlowProcess()

    monkeypatch.setattr(
        external_command_adapter.shutil,
        "which",
        lambda _name: "/usr/bin/ssh",
    )
    monkeypatch.setattr(
        external_command_adapter.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    paths = make_external_run_paths(tmp_path / "results", "snapshot-timeout")
    cfg = ExternalRunConfig(
        name="snapshot-timeout",
        benchmark_id="cybench",
        runtime_id="kilo",
        model_id="ollama-cloud/glm-5.2",
        target_host="vps.0xb105.com",
        command={"argv_prefix": ["true"]},
        snapshot={
            "enabled": True,
            "timeout_sec": 0.001,
            "commands": {"host.txt": "hostname"},
        },
        instances=[{"id": "lootstash", "prompt_file": str(tmp_path / "prompt.txt")}],
    )
    (tmp_path / "prompt.txt").write_text("prompt\n", encoding="utf-8")
    sink = CapturingSink()

    asyncio.run(external_command_adapter._capture_snapshot(cfg, paths, sink))

    assert "timed out" in (paths.snapshot_dir / "host.txt").read_text(encoding="utf-8")
    assert any("timed out" in message for message in sink.messages)


def test_remote_snapshot_timeout_cleanup_error_still_writes_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CleanupErrorProcess:
        def __init__(self) -> None:
            self.killed = False
            self.waited = False

        async def communicate(self) -> tuple[bytes, None]:
            if not self.killed:
                await asyncio.sleep(60)
            raise ProcessLookupError("process already reaped")

        async def wait(self) -> int:
            self.waited = True
            return 0

        def kill(self) -> None:
            self.killed = True

    class CapturingSink:
        def __init__(self) -> None:
            self.messages: list[str] = []

        def emit(self, _kind: str, message: str, **_kwargs: object) -> None:
            self.messages.append(message)

    proc = CleanupErrorProcess()

    async def fake_create_subprocess_exec(
        *_args: object,
        **_kwargs: object,
    ) -> CleanupErrorProcess:
        return proc

    monkeypatch.setattr(
        external_command_adapter.shutil,
        "which",
        lambda _name: "/usr/bin/ssh",
    )
    monkeypatch.setattr(
        external_command_adapter.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    paths = make_external_run_paths(tmp_path / "results", "snapshot-timeout-cleanup")
    cfg = ExternalRunConfig(
        name="snapshot-timeout-cleanup",
        benchmark_id="cybench",
        runtime_id="kilo",
        model_id="ollama-cloud/glm-5.2",
        target_host="vps.0xb105.com",
        command={"argv_prefix": ["true"]},
        snapshot={
            "enabled": True,
            "timeout_sec": 0.001,
            "commands": {"host.txt": "hostname"},
        },
        instances=[{"id": "lootstash", "prompt_file": str(tmp_path / "prompt.txt")}],
    )
    (tmp_path / "prompt.txt").write_text("prompt\n", encoding="utf-8")
    sink = CapturingSink()

    asyncio.run(external_command_adapter._capture_snapshot(cfg, paths, sink))

    marker = (paths.snapshot_dir / "host.txt").read_text(encoding="utf-8")
    assert "timed out" in marker
    assert "cleanup after timeout failed" in marker
    assert proc.waited is True
    assert any("timed out" in message for message in sink.messages)


def test_prepare_prompt_text_rewrites_archived_private_root(tmp_path: Path) -> None:
    run_root = tmp_path / "private-root"
    prompt = (
        "Use ssh -i /tmp/bencheval-cybench-real-vps/keys/lootstash vps.0xb105.com '<command>'.\n"
    )
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text(prompt, encoding="utf-8")
    cfg = ExternalRunConfig(
        name="prompt-rewrite",
        benchmark_id="cybench",
        runtime_id="kilo",
        model_id="ollama-cloud/glm-5.2",
        command={"argv_prefix": ["true"]},
        instances=[{"id": "lootstash", "prompt_file": str(prompt_file)}],
    )
    prepared = _prompt_text(cfg, run_root, cfg.instances[0])
    assert "/tmp/bencheval-cybench-real-vps" not in prepared
    assert str(run_root.resolve() / "keys" / "lootstash") in prepared


def test_public_presentation_sanitizer_redacts_embedded_flag_tokens() -> None:
    """The sanitizer is for derived public artifacts only, not canonical records."""
    text = "Decoded candidate output. FLAG: HTB{example_secret} found in memory"
    assert redact_for_public_presentation(text, redact=True) == (
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
                "schema_version": "momo_event_v1",
                "elapsed_sec": 0.0,
                "kind": "pass",
                "display": "[00:00:00] PASS     lootstash  flag verified",
            },
        )
        + "\n",
        encoding="utf-8",
    )
    from bencheval.momo_cybench import main as compat_main

    assert compat_main(["--replay", str(events), "--no-color", "--speed", "100"]) == 0
    assert "flag verified" in capsys.readouterr().out


def test_shell_entrypoint_uses_generic_run_config() -> None:
    script = Path("scripts/external-command-run.sh")
    text = script.read_text(encoding="utf-8")
    assert "--config CONFIG" in text
    assert "bencheval run" in text


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="bash script",
)
def test_shell_entrypoint_help_executes() -> None:
    result = subprocess.run(
        ["bash", "scripts/external-command-run.sh", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Usage: scripts/external-command-run.sh --config CONFIG" in result.stderr
