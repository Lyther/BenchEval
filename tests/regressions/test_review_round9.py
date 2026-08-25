"""Round-9 qa-review regressions (external reviewer REJECTED: F001-F004).

Root contract under repair: nested Harbor ``result.json`` candidates escape
the pinned tree (F001 — the real Harbor layout nests the job result one level
below ``--jobs-dir``, per results/raw/tb-claude-code-haiku-one-20260618T150500Z
/fix-git/2026-06-18__23-05-50/result.json, so option (a) direct-children-only
would break real scoring; the fix pins the located chain at the post-run
check); verify_auth.sh expands credentials into curl argv and logs credential
suffixes (F002); ``bencheval report`` leaks a traceback on output-path errors
(F003); and round 8's fd-leak test lacked a SUBSTITUTE_JUSTIFICATION (F004,
record added in test_review_round8.py).

SUBSTITUTE_JUSTIFICATION (F001 stub Harbor runner + white-box swap hook)
- substitute: a boundary ``process_runner`` callable authoring a synthetic
  nested Harbor job layout, with rename-and-recreate / symlink swaps hooked to
  the ``write_text_at_exclusive`` instant that follows the post-run identity
  check
- replaces: the real Harbor CLI subprocess and a surviving same-uid mutator
  swapping the nested job directory between the post-run check and the scored
  read
- necessity: the swap must occur at the exact post-check instant, which a real
  Harbor subprocess cannot produce deterministically
- real-option: executing the real ``harbor run`` against a disposable jobs dir
  - Docker/Harbor dependent and cannot schedule the swap on demand
- proof-limit: proves chain-pinning and fail-closed behavior only; does not
  prove Harbor executes or scores
- real-proof: BLOCKED - live terminal-bench lane on dev-box (operator
  provisioning required); all Harbor results remain diagnostic only

SUBSTITUTE_JUSTIFICATION (F002 PATH-prepended curl wrapper)
- substitute: a fake ``curl`` on PATH that logs its argv to a file and sleeps
  (simulating a slow in-flight request) instead of performing HTTPS I/O
- replaces: the real curl binary and the real ByteLLM/Anthropic/OpenAI/
  Moonshot endpoints
- necessity: the assertion observes the exact argv the script hands to curl
  while a request is in flight; real provider endpoints are network/credential
  dependent and cannot be scheduled for argv inspection deterministically.
  argv at exec time is exactly what process collectors (ps) observe
- real-option: running the script against the real providers and racing
  ``ps``/eBPF capture - flaky, credential-dependent, non-deterministic
- proof-limit: proves the script never places credential material in curl argv
  and cleans up its config file; does not prove any provider accepts the
  credentials
- real-proof: scripts/verify_auth.sh against the live providers on the
  operator host (credentials required); the argv-hygiene assertion remains
  covered only by this wrapper
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bencheval.benchmark_plan import plan_control_plane
from bencheval.exceptions import AdapterFailureError

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _harbor_plan():
    return plan_control_plane(
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        runtime_id="codex-cli",
        model_id="kimi-k2.7-code",
    )


# --- F001: nested Harbor result.json must stay bound to the pinned tree -------


def test_harbor_nested_result_dir_swap_after_post_run_check_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import bencheval.terminal_bench_harbor as harbor
    from bencheval.terminal_bench_harbor import HarborCliResult, run_terminal_bench_instance

    plan = _harbor_plan()
    captured: dict[str, Path] = {}

    def runner(command, *, cwd, timeout_sec):
        out_dir = Path(command[command.index("--jobs-dir") + 1])
        # Real Harbor layout: <jobs-dir>/<job-timestamp>/result.json.
        job = out_dir / "2026-01-01__00-00-00"
        job.mkdir(parents=True)
        (job / "result.json").write_text('{"resolved": false}', encoding="utf-8")
        captured["job"] = job
        return HarborCliResult(0, "", "", 0.1, tuple(command))

    real_write = harbor.write_text_at_exclusive

    def tampering_write(dir_fd, name, text):
        if name == "stderr.log":
            # White-box hook: the post-run root identity check already passed;
            # a same-uid mutator swaps ONLY the nested job dir and plants a
            # forged PASS verdict (the reviewer's exact reproduction).
            job = captured["job"]
            job.rename(job.parent / "job-moved")
            job.mkdir()
            (job / "result.json").write_text('{"resolved": true}', encoding="utf-8")
        return real_write(dir_fd, name, text)

    monkeypatch.setattr(harbor, "write_text_at_exclusive", tampering_write)

    with pytest.raises(AdapterFailureError) as excinfo:
        run_terminal_bench_instance(
            plan=plan,
            instance_id="tb-smoke-001",
            artifacts_dir=tmp_path / "a",
            repo_root=tmp_path,
            process_runner=runner,
            timeout_sec=60,
        )

    assert excinfo.value.failure_label == "evidence_corrupt"


def test_harbor_result_symlink_at_candidate_path_fails_closed(
    tmp_path: Path,
) -> None:
    from bencheval.terminal_bench_harbor import HarborCliResult, run_terminal_bench_instance

    plan = _harbor_plan()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "result.json").write_text('{"resolved": true}', encoding="utf-8")

    def runner(command, *, cwd, timeout_sec):
        out_dir = Path(command[command.index("--jobs-dir") + 1])
        # A surviving same-uid mutator plants a symlink at the result
        # candidate path, pointing at attacker-controlled content outside the
        # pinned tree.
        (out_dir / "result.json").symlink_to(outside / "result.json")
        return HarborCliResult(0, "", "", 0.1, tuple(command))

    with pytest.raises(AdapterFailureError) as excinfo:
        run_terminal_bench_instance(
            plan=plan,
            instance_id="tb-smoke-001",
            artifacts_dir=tmp_path / "a",
            repo_root=tmp_path,
            process_runner=runner,
            timeout_sec=60,
        )

    assert excinfo.value.failure_label == "evidence_corrupt"


# --- F002: verify_auth must never place credentials in curl argv --------------


def test_verify_auth_never_exposes_credentials_in_curl_argv(tmp_path: Path) -> None:
    script = _REPO_ROOT / "scripts" / "verify_auth.sh"
    secret = "sk-round9-7f3q9Z"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    argv_log = tmp_path / "curl-argv.log"
    wrapper = bin_dir / "curl"
    wrapper.write_text(
        '#!/usr/bin/env bash\nprintf \'%s\n\' "$@" >> "${CURL_ARGV_LOG}"\nsleep 2\nexit 0\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "BYTELLM_API_KEY": secret,
        "CURL_ARGV_LOG": str(argv_log),
    }

    proc = subprocess.Popen(
        ["bash", str(script)],
        cwd=_REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Observe the curl argv while the request is still in flight (the wrapper
    # sleeps after logging, so the script is blocked inside curl_probe here).
    logged = ""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if argv_log.exists():
            logged = argv_log.read_text(encoding="utf-8")
            if logged.strip():
                break
        time.sleep(0.05)
    assert proc.poll() is None, "script finished before the in-flight observation"
    stdout, stderr = proc.communicate(timeout=15)

    assert proc.returncode == 0, (stdout, stderr)
    assert secret not in logged
    assert "Bearer" not in logged
    # No credential suffix leaks to stderr either (endpoint identity suffices).
    assert secret[-4:] not in stderr
    # The curl config file carrying the secret is removed after the run.
    lines = logged.splitlines()
    assert "-K" in lines, logged
    config_path = Path(lines[lines.index("-K") + 1])
    assert not config_path.exists()


# --- F003: report output-path errors are concise, never tracebacks ------------


def test_report_output_path_error_is_concise_without_traceback(tmp_path: Path) -> None:
    from tests.factories import make_control_plane_evidence_record

    evidence = tmp_path / "evidence.jsonl"
    evidence.write_text(
        make_control_plane_evidence_record(instance_id="tb-smoke-001").model_dump_json() + "\n",
        encoding="utf-8",
    )
    blocker = tmp_path / "blocker"
    blocker.write_text("regular file\n", encoding="utf-8")
    output = blocker / "out.md"

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "bencheval.cli",
            "report",
            str(evidence),
            "--output",
            str(output),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 1, (proc.stdout, proc.stderr)
    assert "Traceback" not in proc.stderr
    assert "error:" in proc.stderr.lower()
    assert not output.exists()
