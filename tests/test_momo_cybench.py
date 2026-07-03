from __future__ import annotations

import asyncio
import hashlib
import json
import math
import shlex
import shutil
import subprocess
import sys
import time
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
    _template_context,
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
    assert cfg.variant == "claude-code-mixed-model"
    assert cfg.banner_detail is not None
    assert "mixed-model runtime" in cfg.banner_detail
    assert "requested GLM 5.2" in cfg.banner_detail
    assert cfg.concurrency == 1
    ids = [instance.id for instance in cfg.instances]
    assert len(ids) == 39
    assert len(set(ids)) == 39  # no duplicates
    # Spot-check authoritative endpoints of the sorted slice + a mid entry.
    assert {"avatar", "lootstash", "were_pickle_phreaks_revenge"} <= set(ids)


def test_momo_cybench_profile_has_progress_aware_deadline() -> None:
    """The profile's committed deadline is the adaptive no-progress guard only.

    no_progress_sec keys off the runtime's streaming cadence (not solve time), so it
    needs no per-benchmark guess. An absolute wall_clock ceiling depends on the
    solve-time distribution and is operator-owned at launch (--wall-clock-sec), so it
    is deliberately NOT hard-coded in the committed profile
    (docs/issues/solver-stall-and-attribution.md).
    """
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    assert cfg.deadline.no_progress_sec is not None
    assert cfg.deadline.no_progress_sec > 0
    # No committed absolute ceiling — the operator supplies one per run if wanted.
    assert cfg.deadline.wall_clock_sec is None
    assert cfg.deadline.grace_period_sec > 0


def test_momo_cybench_deadline_wall_clock_is_operator_overridable() -> None:
    """An operator imposes an absolute ceiling at launch without editing the profile."""
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    overridden = external_command_adapter.apply_deadline_overrides(
        cfg,
        {"wall_clock_sec": 3600.0, "no_progress_sec": None, "grace_period_sec": None},
    )
    assert overridden.deadline.wall_clock_sec == 3600.0
    # Unset overrides leave the committed values intact.
    assert overridden.deadline.no_progress_sec == cfg.deadline.no_progress_sec
    assert overridden.deadline.grace_period_sec == cfg.deadline.grace_period_sec
    # A non-positive override is rejected cleanly (re-validated, never a raw traceback).
    with pytest.raises(BenchEvalError, match="invalid deadline override"):
        external_command_adapter.apply_deadline_overrides(cfg, {"wall_clock_sec": 0.0})


def test_momo_cybench_profile_has_first_class_container_cleanup() -> None:
    """Cleanup is a first-class adapter capability, not a per-attempt shell trap."""
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    assert cfg.cleanup.commands, "expected a container cleanup command"
    joined = " ".join(cfg.cleanup.commands)
    assert "docker rm -f momo-cybench-{instance_id}" in joined
    assert cfg.cleanup.timeout_sec > 0


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


def test_momo_cybench_profile_extracts_from_original_solver_output() -> None:
    """MOMO should emit its final answer; the profile owns CyBench value extraction."""
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))

    observed = external_command_adapter._extract_observed_value(
        "Analysis complete.\nThe recovered value is HTB{real_flag}.\n",
        cfg.verification.observed_regex,
    )

    assert observed == "HTB{real_flag}"


def test_momo_cybench_runs_claude_inside_isolated_container() -> None:
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    command = cfg.command.env["MOMO_CLAUDE_CODE_COMMAND"]
    assert "docker run --rm" in command
    assert "-v /etc/passwd:/etc/passwd:ro" in command
    assert "-v /etc/group:/etc/group:ro" in command
    # Shell-quoted path fields (F006): paths interpolated into the sh -c script use the
    # `_sh` variants so a run/results root with spaces cannot split Docker args.
    assert "-v {work_dir_sh}:{work_dir_sh}" in command
    assert "-v {run_root_sh}/keys/{instance_id}:/tmp/momo-cybench-key:ro" in command
    assert "momo:cybench-runner claude -p --output-format stream-json" in command
    assert "--include-partial-messages" in command
    assert "--verbose" in command
    assert "--model {runtime_model_id}" in command
    assert "--model {model_id}" not in command
    assert "ANTHROPIC_CUSTOM_HEADERS" in command
    assert "X-Experiment-ID: {telemetry_id}" in command
    assert "X-Request-ID: {trace_id}" in command
    assert "{prompt}" not in command


def test_momo_cybench_container_command_is_trap_free_foreground_exec() -> None:
    """A killed attempt must not strand a container — via first-class cleanup, no trap.

    Abnormal-exit container removal moved out of a per-attempt shell ``trap`` into
    BenchEval's ``cleanup`` block (see
    test_momo_cybench_profile_has_first_class_container_cleanup). The runtime command
    is therefore a trap-free ``exec docker run`` in the FOREGROUND: exec replaces the
    shell so BenchEval's SIGTERM reaches ``docker run`` directly, and ``-i`` forwards
    MOMO's piped prompt on inherited stdin — no ``trap`` / backgrounding / fd juggling.
    A named+labeled container plus a pre-run force-remove (same-id leak self-heal)
    remain. The value shlex-splits into ``sh -c <script>``.
    """
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    command = cfg.command.env["MOMO_CLAUDE_CODE_COMMAND"]
    argv = shlex.split(
        command.replace("{instance_id}", "lootstash")
        .replace("{host_uid}", "1000")
        .replace("{host_gid}", "1000")
        .replace("{work_dir}", "/w")
        .replace("{run_root}", "/rr")
        .replace("{runtime_model_id}", "glm-5.2")
        .replace("{telemetry_id}", "run-1:lootstash:attempt1")
        .replace("{trace_id}", "run-1:lootstash:attempt1"),
    )
    assert argv[:2] == ["sh", "-c"]
    script = argv[2]
    assert "--name $cid" in script
    assert "--label momo-cybench=lootstash" in script
    assert "docker rm -f $cid" in script  # pre-run same-id leak self-heal
    assert "exec docker run" in script  # foreground exec; SIGTERM reaches docker run
    # The trap + backgrounding scar tissue is gone (cleanup is first-class now).
    assert "trap " not in script
    assert "EXIT INT TERM" not in script
    assert "<&3 &" not in script
    assert "wait $!" not in script


def test_momo_cybench_prompt_suppresses_known_hosts_writes(tmp_path: Path) -> None:
    run_root = tmp_path / "run-root"
    (run_root / "run-prompts").mkdir(parents=True)
    (run_root / "keys").mkdir()
    (run_root / "meta").mkdir()
    (run_root / "keys" / "avatar").write_text(
        "private-key-placeholder\n",
        encoding="utf-8",
    )
    (run_root / "run-prompts" / "avatar.txt").write_text(
        "Use ssh -i /tmp/bencheval-cybench-real-vps/keys/avatar "
        "-o StrictHostKeyChecking=no root@vps.0xb105.com '<command>'.\n",
        encoding="utf-8",
    )
    (run_root / "meta" / "manifest.private.json").write_text(
        json.dumps([{"name": "avatar", "flag": "FLAG{ok}"}]),
        encoding="utf-8",
    )
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    avatar = next(instance for instance in cfg.instances if instance.id == "avatar")

    rendered = _prompt_text(cfg, run_root, avatar)

    assert "/tmp/momo-cybench-key" in rendered
    assert "-o UserKnownHostsFile=/dev/null" in rendered
    assert "-o GlobalKnownHostsFile=/dev/null" in rendered
    assert "-o LogLevel=ERROR" in rendered
    assert "-o BatchMode=yes" in rendered
    assert "-o PasswordAuthentication=no" in rendered
    assert "-o KbdInteractiveAuthentication=no" in rendered
    assert "-o PreferredAuthentications=publickey" in rendered
    assert "-o ConnectTimeout=10" in rendered


def test_template_context_exposes_host_uid_gid(tmp_path: Path) -> None:
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    context = _template_context(
        cfg,
        tmp_path,
        cfg.instances[0],
        attempt=1,
        work_dir=tmp_path / "work",
        run_id="run/x 1",
    )
    assert context["host_uid"].isdigit()
    assert context["host_gid"].isdigit()
    assert context["model_id"] == "bytellm/glm-5.2"
    assert context["runtime_model_id"] == "glm-5.2"
    assert context["run_id"] == "run/x 1"
    assert context["telemetry_id"] == "run-x-1:avatar:attempt1"
    assert context["trace_id"] == "run-x-1:avatar:attempt1"


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


def test_validate_run_root_checks_key_before_runtime_prompt_rewrite(
    tmp_path: Path,
) -> None:
    run_root = tmp_path / "rr"
    (run_root / "run-prompts").mkdir(parents=True)
    (run_root / "run-prompts" / "avatar.txt").write_text(
        "Use ssh -i /tmp/bencheval-cybench-real-vps/keys/avatar root@vps.0xb105.com '<command>'.\n",
        encoding="utf-8",
    )
    cfg = ExternalRunConfig(
        name="keys-rewrite-preflight-test",
        benchmark_id="cybench",
        runtime_id="claude-code",
        model_id="bytellm/glm-5.2",
        command={"argv_prefix": ["true"]},
        input={
            "prompt_path_templates": ["run-prompts/{instance_id}.txt"],
            "required_path_templates": ["keys/{instance_id}"],
            "prompt_replacements": {
                "/tmp/bencheval-cybench-real-vps/keys/{instance_id}": ("/tmp/momo-cybench-key"),
            },
        },
        instances=[{"id": "avatar"}],
    )
    with pytest.raises(BenchEvalError, match=r"required:avatar:keys/avatar"):
        validate_external_run_root(cfg, run_root)

    (run_root / "keys").mkdir()
    (run_root / "keys" / "avatar").write_text("private key\n", encoding="utf-8")
    validate_external_run_root(cfg, run_root)
    rendered = _prompt_text(cfg, run_root, cfg.instances[0])
    assert "/tmp/bencheval-cybench-real-vps" not in rendered
    assert "/tmp/momo-cybench-key" in rendered


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
        "results/raw/cybench-hard-39-glm52-20260618T022156Z/local/bencheval-cybench-real-vps",
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
    assert rows[0].adapter_metadata["configured_model_id"] == "ollama-cloud/glm-5.2"
    assert rows[0].adapter_metadata["variant"] == "max"
    assert rows[0].adapter_metadata["telemetry_id"] == "external-test-run:lootstash:attempt1"
    assert rows[0].adapter_metadata["trace_id"] == "external-test-run:lootstash:attempt1"
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
    assert "- Variant: `max`" in paths.summary_md.read_text(encoding="utf-8")


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


def _write_stall_tool(path: Path, *, sleep_sec: int = 120) -> None:
    """A tool that prints one line then wedges — simulating a stalled upstream."""
    path.write_text(
        "\n".join(
            [
                "import time",
                "print('tool started, waiting on upstream', flush=True)",
                f"time.sleep({sleep_sec})",
                "print('FLAG: FLAG{never_reached}', flush=True)",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def _write_orphaning_stall_tool(path: Path, *, sleep_sec: int = 120) -> None:
    """A tool that spawns a child holding stdout open, then wedges.

    If termination kills only the parent (not the process group), the child keeps
    the stdout pipe open and the reader blocks until the child exits — the
    stranded-children bug. Group-safe termination reaps both and lets the run
    finish promptly.
    """
    path.write_text(
        "\n".join(
            [
                "import subprocess, sys, time",
                "subprocess.Popen(",
                f"    [sys.executable, '-c', 'import time; time.sleep({sleep_sec})'],",
                ")",
                "print('tool started with child', flush=True)",
                f"time.sleep({sleep_sec})",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def _write_graceful_sigterm_stall_tool(path: Path, *, sleep_sec: int = 120) -> None:
    """A wedged tool that traps SIGTERM and exits 0 during the grace window.

    A watchdog-terminated stall whose process exits 0 (via a SIGTERM handler, or a
    container PID-1 graceful shutdown) must STILL be reported as an infra stall — not
    laundered into a normal completion because returncode happened to be 0.
    """
    path.write_text(
        "\n".join(
            [
                "import signal, sys, time",
                "signal.signal(signal.SIGTERM, lambda *_a: sys.exit(0))",
                "print('started; exits 0 on SIGTERM', flush=True)",
                f"time.sleep({sleep_sec})",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def _write_chatty_forever_tool(path: Path) -> None:
    """A tool that keeps emitting output (progress never stalls) but never exits."""
    path.write_text(
        "\n".join(
            [
                "import time",
                "while True:",
                "    print('still working', flush=True)",
                "    time.sleep(0.02)",
            ],
        )
        + "\n",
        encoding="utf-8",
    )


def _write_served_model_kilo(path: Path, served_model: str) -> None:
    events_literal = repr(
        [
            {"type": "system", "model": served_model},
            {"type": "text", "part": {"type": "text", "text": "FLAG: FLAG{ok}"}},
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


def _run_deadline_config(
    tmp_path: Path,
    tool: Path,
    *,
    deadline_yaml: list[str],
    parser: str = "plain-lines",
    extra_yaml: list[str] | None = None,
    extra_args: list[str] | None = None,
) -> tuple[int, Path]:
    run_root = tmp_path / "run-root"
    _write_run_root(run_root)
    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join(
            [
                'schema_version: "external_command_run_v1"',
                'name: "deadline-test"',
                'benchmark_id: "cybench"',
                'runtime_id: "python-subprocess"',
                'model_id: "external/proof-runtime"',
                "command:",
                f'  argv_prefix: ["{sys.executable}", "{tool}"]',
                "  args_template: []",
                "input:",
                '  prompt_path_templates: ["run-prompts/{instance_id}.txt"]',
                '  required_path_templates: ["keys/{instance_id}"]',
                "stream:",
                f'  parser: "{parser}"',
                "verification:",
                '  kind: "none"',
                *deadline_yaml,
                *(extra_yaml or []),
                "instances:",
                '  - id: "lootstash"',
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    run_id = "deadline-test"
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
            *(extra_args or []),
        ],
    )
    return code, make_external_run_paths(tmp_path / "results", run_id).evidence_jsonl


def test_no_progress_stall_classified_distinctly(tmp_path: Path) -> None:
    """A wedged solver (no output for N s) is a distinct infra stall, not a failure."""
    tool = tmp_path / "stall.py"
    _write_stall_tool(tool)
    started = time.monotonic()
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=["deadline:", "  no_progress_sec: 0.5", "  grace_period_sec: 1.0"],
    )
    elapsed = time.monotonic() - started
    assert elapsed < 30  # watchdog killed the wedged solver, did not wait 120s
    assert code == 1
    rows = read_evidence_jsonl(evidence)
    assert rows[0].failure_class == "runtime_no_progress_stall"
    assert rows[0].failure_class != "model_wrong_solution"
    assert rows[0].attempt_validity == "invalid"
    assert rows[0].counts_toward_pass_at_k is False
    assert "no_progress" in (rows[0].invalid_reason or "")


def test_wall_clock_timeout_classified_distinctly(tmp_path: Path) -> None:
    """A solver that keeps chattering but never finishes trips the wall-clock deadline."""
    tool = tmp_path / "chatty.py"
    _write_chatty_forever_tool(tool)
    started = time.monotonic()
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=[
            "deadline:",
            "  no_progress_sec: 30.0",
            "  wall_clock_sec: 0.5",
            "  grace_period_sec: 1.0",
        ],
    )
    elapsed = time.monotonic() - started
    assert elapsed < 30
    assert code == 1
    rows = read_evidence_jsonl(evidence)
    assert rows[0].failure_class == "runtime_wall_clock_timeout"
    assert rows[0].attempt_validity == "invalid"
    assert rows[0].counts_toward_pass_at_k is False


def test_stall_termination_reaps_orphaned_children(tmp_path: Path) -> None:
    """Container-safe termination: a stalled solver's children are reaped too.

    The tool spawns a child that inherits stdout and sleeps. Group-safe kill reaps
    both so the reader unblocks; a parent-only kill would strand the child holding
    the pipe and hang the run.
    """
    tool = tmp_path / "orphan.py"
    _write_orphaning_stall_tool(tool)
    started = time.monotonic()
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=["deadline:", "  no_progress_sec: 0.5", "  grace_period_sec: 1.0"],
    )
    elapsed = time.monotonic() - started
    assert elapsed < 30  # no hang: the orphan holding stdout was reaped
    assert code == 1
    rows = read_evidence_jsonl(evidence)
    assert rows[0].failure_class == "runtime_no_progress_stall"


def test_model_attribution_defaults_to_not_captured(tmp_path: Path) -> None:
    """With no served-model signal, attribution is 'not captured', never the request."""
    tool = tmp_path / "fake_kilo.py"
    _write_fake_kilo(tool)
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=[],
        parser="kilo-json",
    )
    assert code == 0
    rows = read_evidence_jsonl(evidence)
    meta = rows[0].adapter_metadata
    assert meta["model_attribution"] == "attribution_not_captured"
    assert meta["served_model_id"] == "attribution_not_captured"
    assert meta["configured_model_id"] == "external/proof-runtime"


def test_model_attribution_reports_served_model(tmp_path: Path) -> None:
    """A served-model signal that matches the request is authoritative, not best-effort."""
    tool = tmp_path / "served_kilo.py"
    _write_served_model_kilo(tool, "external/proof-runtime")
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=[],
        parser="kilo-json",
    )
    assert code == 0
    rows = read_evidence_jsonl(evidence)
    meta = rows[0].adapter_metadata
    assert meta["served_model_id"] == "external/proof-runtime"
    assert meta["model_attribution"] == "authoritative"


def test_model_attribution_flags_mixed_model(tmp_path: Path) -> None:
    """A served model different from the request is reported as mixed-model, not over-claimed."""
    tool = tmp_path / "mixed_kilo.py"
    _write_served_model_kilo(tool, "bytellm/some-other-model")
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=[],
        parser="kilo-json",
    )
    assert code == 0
    rows = read_evidence_jsonl(evidence)
    meta = rows[0].adapter_metadata
    assert meta["model_attribution"] == "mixed_model"
    assert "bytellm/some-other-model" in meta["served_model_id"]


def test_container_cleanup_runs_after_successful_attempt(tmp_path: Path) -> None:
    """The first-class cleanup runs after an attempt and its result is recorded."""
    tool = tmp_path / "ok.py"
    tool.write_text("print('done', flush=True)\n", encoding="utf-8")
    sentinel = tmp_path / "cleaned.marker"
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=[],
        extra_yaml=[
            "cleanup:",
            "  commands:",
            f'    - "touch {sentinel}"',
            "  timeout_sec: 10",
        ],
    )
    assert code == 0
    assert sentinel.exists(), "cleanup command did not run after the attempt"
    rows = read_evidence_jsonl(evidence)
    assert rows[0].cleanup_result == "success"


def test_container_cleanup_runs_even_after_stall_kill(tmp_path: Path) -> None:
    """Cleanup reaches the container plane even when the attempt was stall-killed.

    killpg reaps native children but not dockerd containers; cleanup must run after a
    stall-kill so a container is never stranded — the whole point of making it a
    first-class capability instead of a shell trap.
    """
    tool = tmp_path / "stall.py"
    _write_stall_tool(tool)
    sentinel = tmp_path / "cleaned_after_stall.marker"
    started = time.monotonic()
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=["deadline:", "  no_progress_sec: 0.5", "  grace_period_sec: 1.0"],
        extra_yaml=[
            "cleanup:",
            "  commands:",
            f'    - "touch {sentinel}"',
            "  timeout_sec: 10",
        ],
    )
    assert time.monotonic() - started < 30
    assert code == 1
    assert sentinel.exists(), "cleanup did not run after a stall-kill"
    rows = read_evidence_jsonl(evidence)
    assert rows[0].failure_class == "runtime_no_progress_stall"
    assert rows[0].cleanup_result == "success"


def test_cli_wall_clock_override_kills_run_without_profile_ceiling(tmp_path: Path) -> None:
    """--wall-clock-sec imposes a ceiling at launch even when the config sets none."""
    tool = tmp_path / "chatty.py"
    _write_chatty_forever_tool(tool)
    started = time.monotonic()
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        # No deadline in the config at all — the operator supplies it at launch.
        deadline_yaml=[],
        extra_args=["--wall-clock-sec", "0.5", "--grace-period-sec", "1.0"],
    )
    assert time.monotonic() - started < 30
    assert code == 1
    rows = read_evidence_jsonl(evidence)
    assert rows[0].failure_class == "runtime_wall_clock_timeout"


def test_watchdog_killed_stall_stays_stall_even_when_process_exits_zero(
    tmp_path: Path,
) -> None:
    """A watchdog-terminated stall that exits 0 (SIGTERM handler) is still a stall.

    Guards the deadline-edge guard from laundering an actively-killed infra stall into
    a normal completion just because the process happened to return 0.
    """
    tool = tmp_path / "graceful_stall.py"
    _write_graceful_sigterm_stall_tool(tool)
    started = time.monotonic()
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=["deadline:", "  no_progress_sec: 0.5", "  grace_period_sec: 2.0"],
    )
    assert time.monotonic() - started < 30
    assert code == 1
    rows = read_evidence_jsonl(evidence)
    assert rows[0].failure_class == "runtime_no_progress_stall"
    assert rows[0].attempt_validity == "invalid"
    assert rows[0].counts_toward_pass_at_k is False


def test_cleanup_failure_is_recorded_and_does_not_abort_run(tmp_path: Path) -> None:
    """A cleanup command that exits non-zero degrades to a failed cleanup, run survives."""
    tool = tmp_path / "ok.py"
    tool.write_text("print('done', flush=True)\n", encoding="utf-8")
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=[],
        extra_yaml=[
            "cleanup:",
            "  commands:",
            '    - "exit 3"',
            "  timeout_sec: 10",
        ],
    )
    assert code == 0  # the attempt itself succeeded; cleanup failure must not abort it
    rows = read_evidence_jsonl(evidence)
    assert rows[0].cleanup_result == "failed"


def test_cleanup_bad_template_field_does_not_strand_or_abort(tmp_path: Path) -> None:
    """An unknown {field} in a cleanup command degrades to failed, never aborts the run."""
    tool = tmp_path / "ok.py"
    tool.write_text("print('done', flush=True)\n", encoding="utf-8")
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=[],
        extra_yaml=[
            "cleanup:",
            "  commands:",
            '    - "echo {nonexistent_field}"',
            "  timeout_sec: 10",
        ],
    )
    assert code == 0
    rows = read_evidence_jsonl(evidence)
    assert rows[0].cleanup_result == "failed"


def test_cleanup_partial_when_one_of_many_commands_fails(tmp_path: Path) -> None:
    tool = tmp_path / "ok.py"
    tool.write_text("print('done', flush=True)\n", encoding="utf-8")
    sentinel = tmp_path / "ok.marker"
    code, evidence = _run_deadline_config(
        tmp_path,
        tool,
        deadline_yaml=[],
        extra_yaml=[
            "cleanup:",
            "  commands:",
            f'    - "touch {sentinel}"',
            '    - "exit 1"',
            "  timeout_sec: 10",
        ],
    )
    assert code == 0
    assert sentinel.exists()
    rows = read_evidence_jsonl(evidence)
    assert rows[0].cleanup_result == "partial"


def test_events_jsonl_preserves_full_raw_output_not_compacted(tmp_path: Path) -> None:
    """F001: the canonical events.jsonl keeps raw model output, not a _compact() tail.

    The console/replay `display` may be compacted, but the record `message` is the
    integrity lane and must survive whole.
    """
    long_line = "Z" * 400
    tool = tmp_path / "long.py"
    tool.write_text(f"print({long_line!r}, flush=True)\n", encoding="utf-8")
    code, _ = _run_deadline_config(tmp_path, tool, deadline_yaml=[])
    assert code == 0
    events = make_external_run_paths(tmp_path / "results", "deadline-test").events_jsonl
    text = events.read_text(encoding="utf-8")
    assert long_line in text  # raw, un-truncated
    assert "..." not in text.split(long_line)[0][-8:]  # the record wasn't compacted


def test_new_run_id_is_unique_across_immediate_calls() -> None:
    """F002: consecutive run ids must not collide (would merge/overwrite artifacts)."""
    ids = {external_command_adapter.new_run_id("momo-cybench") for _ in range(100)}
    assert len(ids) == 100


def test_rerun_onto_existing_evidence_is_rejected(tmp_path: Path) -> None:
    """F002: reusing a run id whose artifacts exist must fail, not silently merge."""
    run_root = tmp_path / "run-root"
    _write_run_root(run_root)
    tool = tmp_path / "ok.py"
    tool.write_text("print('done', flush=True)\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        "\n".join(
            [
                'schema_version: "external_command_run_v1"',
                'name: "rerun-test"',
                'benchmark_id: "cybench"',
                'runtime_id: "python-subprocess"',
                'model_id: "external/proof-runtime"',
                "command:",
                f'  argv_prefix: ["{sys.executable}", "{tool}"]',
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
    args = [
        "run",
        "--config",
        str(config),
        "--run-root",
        str(run_root),
        "--results-root",
        str(tmp_path / "results"),
        "--run-id",
        "rerun-fixed-id",
        "--no-color",
    ]
    assert main(args) == 0
    # Second launch onto the same run id / results root must refuse to merge.
    assert main(args) == 1


def test_preflight_fails_when_scoring_manifest_missing(tmp_path: Path) -> None:
    """F003: a manifest-value-regex run root with prompts but no manifest is not ready."""
    run_root = tmp_path / "rr"
    (run_root / "run-prompts").mkdir(parents=True)
    (run_root / "run-prompts" / "lootstash.txt").write_text("solve\n", encoding="utf-8")
    cfg = ExternalRunConfig(
        name="manifest-preflight",
        benchmark_id="cybench",
        runtime_id="claude-code",
        model_id="bytellm/glm-5.2",
        command={"argv_prefix": ["true"]},
        input={"prompt_path_templates": ["run-prompts/{instance_id}.txt"]},
        verification={
            "kind": "manifest-value-regex",
            "manifest_paths": ["meta/manifest.private.json"],
        },
        instances=[{"id": "lootstash"}],
    )
    with pytest.raises(BenchEvalError, match="manifest:"):
        validate_external_run_root(cfg, run_root)
    # Provide the manifest → preflight passes.
    (run_root / "meta").mkdir()
    (run_root / "meta" / "manifest.private.json").write_text(
        json.dumps([{"name": "lootstash", "flag": "FLAG{x}"}]),
        encoding="utf-8",
    )
    validate_external_run_root(cfg, run_root)


def test_preflight_fails_when_strict_manifest_lacks_selected_expected_values(
    tmp_path: Path,
) -> None:
    """A strict scorer needs expected values for every selected instance."""
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    run_root = tmp_path / "rr"
    (run_root / "run-prompts").mkdir(parents=True)
    (run_root / "meta").mkdir()
    for instance in cfg.instances:
        (run_root / "run-prompts" / f"{instance.id}.txt").write_text(
            "solve\n",
            encoding="utf-8",
        )
    first = cfg.instances[0]
    missing = cfg.instances[1]
    (run_root / "meta" / "manifest.private.json").write_text(
        json.dumps([{"name": first.id, "flag": "FLAG{first}"}]),
        encoding="utf-8",
    )

    with pytest.raises(BenchEvalError, match=f"manifest_expected:{missing.id}"):
        validate_external_run_root(cfg, run_root)


def test_dry_run_rejects_invalid_deadline_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F004: an invalid --wall-clock-sec must fail the dry-run preflight, not only live."""
    monkeypatch.delenv("MOMO_CYBENCH_RUN_ROOT", raising=False)
    code = main(
        [
            "run",
            "--config",
            "config/runs/momo-cybench.yaml",
            "--dry-run",
            "--wall-clock-sec",
            "0",
        ],
    )
    assert code != 0


def test_dry_run_plan_reports_resolved_deadline(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F004: dry-run surfaces the resolved deadline, including launch overrides."""
    monkeypatch.delenv("MOMO_CYBENCH_RUN_ROOT", raising=False)
    code = main(
        [
            "run",
            "--config",
            "config/runs/momo-cybench.yaml",
            "--dry-run",
            "--wall-clock-sec",
            "1234",
        ],
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["deadline"]["wall_clock_sec"] == 1234
    assert payload["deadline"]["no_progress_sec"] == 900


def test_deadline_and_cleanup_reject_non_finite_values() -> None:
    """F005: inf/nan timeouts must be rejected, not accepted as 'validated'."""
    for kwargs in (
        {"no_progress_sec": math.inf},
        {"wall_clock_sec": math.inf},
        {"grace_period_sec": math.inf},
        {"no_progress_sec": math.nan},
    ):
        # pydantic ValidationError subclasses ValueError.
        with pytest.raises(ValueError):
            external_command_adapter.ExternalDeadlineConfig(**kwargs)
    with pytest.raises(ValueError):
        external_command_adapter.ExternalCleanupConfig(timeout_sec=math.inf)


def test_docker_command_quotes_paths_with_spaces(tmp_path: Path) -> None:
    """F006: a run/results root with spaces renders as single, unsplit Docker args."""
    cfg = load_external_run_config(Path("config/runs/momo-cybench.yaml"))
    instance = cfg.instances[0]
    work = tmp_path / "work dir with space"
    root = tmp_path / "run root with space"
    context = _template_context(cfg, root, instance, attempt=1, work_dir=work, run_id="r")
    context["prompt"] = "p"
    rendered = external_command_adapter._format_template(
        cfg.command.env["MOMO_CLAUDE_CODE_COMMAND"],
        context,
    )
    argv = shlex.split(rendered)
    assert argv[:2] == ["sh", "-c"]
    script_argv = shlex.split(argv[2])  # the spaced paths must NOT split here
    work_abs = str(work.resolve())
    assert f"{work_abs}:{work_abs}" in script_argv  # one -v token, not split on space
    assert "-w" in script_argv
    assert work_abs in script_argv  # -w <work_dir> is a single token


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
