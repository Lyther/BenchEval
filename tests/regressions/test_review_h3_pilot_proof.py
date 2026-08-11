"""H3: the live pilot must not report success from failure-only evidence.

Covers the new ``bencheval.live_proof`` qualification module directly (real
JSONL files in ``tmp_path``) and the real ``scripts/run-live-pilot-matrix.sh``
end-to-end via PATH shim commands.

SUBSTITUTE_JUSTIFICATION
- substitute: the PATH stub commands (uv/docker/harbor/bfcl/mini-extra) written by
  ``_write_shim_dir`` below; the stub ``uv`` delegates every invocation to the real
  ``uv`` except the single ``bencheval run`` call it emulates with a row writer.
- replaces: real docker/harbor/bfcl binaries, a provider credential, and charged
  benchmark execution on the dev-box.
- necessity: the assertion targets the pilot's qualification logic (does the script
  refuse failure-only evidence / accept qualified evidence); real native execution
  is unavailable and nondeterministic in a test env and would charge a provider.
- real-option: running the actual live pilot on the dev-box — environment-gated
  (Docker daemon + provider credential) and not deterministic for CI.
- proof-limit: does not prove native harness integration or real scoring; only that
  failure-only evidence is rejected and qualified evidence is accepted by the
  script's gates.
- real-proof: scripts/run-live-pilot-matrix.sh on a live dev-box (P3 live proof),
  currently BLOCKED on Docker daemon + provider credential.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bencheval.domain import VerifierIntegrityLabel
from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink, read_evidence_jsonl
from bencheval.live_proof import qualify_lane, shared_eligible_instances

_TS = datetime(2026, 8, 6, tzinfo=UTC)
_TB_KWARGS = {
    "benchmark_id": "terminal-bench",
    "slice_id": "smoke-5",
    "require_runtime": True,
}


def _record(
    *,
    instance_id: str,
    failure_class: str | None = None,
    artifact_paths: list[str] | None = None,
    verifier_log_path: str | None = None,
    runtime_id: str | None = "claude-code",
    runtime_version: str | None = "claude@test",
    runtime_config_hash: str | None = "sha256:test-config",
    benchmark_id: str | None = "terminal-bench",
    benchmark_version: str | None = "tb-2.0",
    slice_id: str | None = "smoke-5",
    provider_id: str | None = "bytellm",
    provider_config_hash: str | None = "sha256:bytellm-test",
    adapter_id: str | None = "terminal-bench-harbor",
    harness_kind: str | None = "harbor",
    harness_version: str | None = "harbor@test",
    verifier_integrity_label: VerifierIntegrityLabel | None = "native",
    attempt_validity: str | None = "valid",
    counts_toward_pass_at_k: bool | None = True,
) -> EvidenceRecord:
    primary_pass = failure_class is None
    return EvidenceRecord(
        run_id="lane-run",
        task_id=instance_id,
        model_id="kimi-k2.7-code",
        execution_profile="E2",
        backend="harbor",
        primary_pass=primary_pass,
        partial_score=1.0 if primary_pass else 0.0,
        cost_usd=0.0,
        latency_sec=1.0,
        failure_labels=[] if failure_class is None else [failure_class],
        artifact_paths=list(artifact_paths or []),
        verifier_log_path=verifier_log_path,
        created_at=_TS,
        benchmark_id=benchmark_id,
        benchmark_version=benchmark_version,
        slice_id=slice_id,
        adapter_id=adapter_id,
        harness_kind=harness_kind,
        harness_version=harness_version,
        runtime_id=runtime_id,
        runtime_version=runtime_version,
        runtime_config_hash=runtime_config_hash,
        provider_id=provider_id,
        provider_config_hash=provider_config_hash,
        instance_id=instance_id,
        interpretation_label="adapter_smoke",
        verifier_integrity_label=verifier_integrity_label,
        failure_class=failure_class,
        attempt_validity=attempt_validity,
        counts_toward_pass_at_k=counts_toward_pass_at_k,
    )


def _write_jsonl(path: Path, records: list[EvidenceRecord]) -> Path:
    sink = JsonlEvidenceSink()
    for record in records:
        sink.append_jsonl(path, record)
    return path


def _touch(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("artifact\n", encoding="utf-8")
    return str(path)


def _failure_rows(count: int, *, log: Path) -> list[EvidenceRecord]:
    """Mirror control_plane_executor._record_instance_failure: infra rows keep
    attempt_validity/counts_toward_pass_at_k null, so only the failure_class gate
    can reject them."""
    return [
        _record(
            instance_id=f"inst-{i:02d}",
            failure_class="runtime_launch_failure",
            verifier_log_path=_touch(log),
            attempt_validity=None,
            counts_toward_pass_at_k=None,
        )
        for i in range(count)
    ]


def _native_row(instance_id: str, *, artifact: Path) -> EvidenceRecord:
    return _record(
        instance_id=instance_id,
        artifact_paths=[_touch(artifact)],
        verifier_log_path=_touch(artifact.parent / "verifier.log"),
    )


def test_qualify_lane_rejects_failure_only_rows(tmp_path: Path) -> None:
    evidence = _write_jsonl(
        tmp_path / "evidence.jsonl",
        _failure_rows(5, log=tmp_path / "adapter_failure.json"),
    )

    q = qualify_lane(evidence, expected_instances=5, **_TB_KWARGS)

    assert not q.ok
    assert q.row_count == 5
    assert q.eligible_rows == ()
    assert any("eligible" in r.lower() and "native" in r.lower() for r in q.reasons)


def test_qualify_lane_rejects_mixed_rows_below_expected_eligible(tmp_path: Path) -> None:
    """F005: one eligible native row among expected_instances is not enough."""
    rows = _failure_rows(4, log=tmp_path / "adapter_failure.json")
    rows.append(_native_row("inst-native", artifact=tmp_path / "raw" / "result.json"))
    evidence = _write_jsonl(tmp_path / "evidence.jsonl", rows)

    q = qualify_lane(evidence, expected_instances=5, **_TB_KWARGS)

    assert not q.ok
    assert [r.instance_id for r in q.eligible_rows] == ["inst-native"]
    assert any("eligible" in r.lower() for r in q.reasons)


def test_qualify_lane_accepts_full_native_cohort(tmp_path: Path) -> None:
    rows = [
        _native_row(f"inst-{i:02d}", artifact=tmp_path / f"raw-{i}" / "result.json")
        for i in range(5)
    ]
    evidence = _write_jsonl(tmp_path / "evidence.jsonl", rows)

    q = qualify_lane(evidence, expected_instances=5, **_TB_KWARGS)

    assert q.ok
    assert len(q.eligible_rows) == 5


def test_qualify_lane_rejects_infra_failure_classes(tmp_path: Path) -> None:
    infra = [
        "harness_failure",
        "runtime_launch_failure",
        "runtime_wall_clock_timeout",
        "runtime_no_progress_stall",
        "materialization_failure",
        "adapter_error",
        "remote_infra_failure",
    ]
    log = _touch(tmp_path / "adapter_failure.json")
    for failure_class in infra:
        rows = [
            _record(
                instance_id=f"inst-{i:02d}",
                failure_class=failure_class,
                verifier_log_path=log,
            )
            for i in range(5)
        ]
        evidence = _write_jsonl(tmp_path / f"evidence-{failure_class}.jsonl", rows)
        q = qualify_lane(evidence, expected_instances=5, **_TB_KWARGS)
        assert not q.ok, failure_class


def test_qualify_lane_rejects_pass_at_k_ineligible_rows(tmp_path: Path) -> None:
    rows = [
        _record(
            instance_id=f"inst-{i:02d}",
            artifact_paths=[_touch(tmp_path / f"raw-{i}" / "result.json")],
            verifier_log_path=_touch(tmp_path / f"raw-{i}" / "verifier.log"),
            attempt_validity="invalid",
            counts_toward_pass_at_k=False,
        )
        for i in range(5)
    ]
    evidence = _write_jsonl(tmp_path / "evidence.jsonl", rows)

    q = qualify_lane(evidence, expected_instances=5, **_TB_KWARGS)

    assert not q.ok
    assert any("eligible" in r.lower() for r in q.reasons)


def test_qualify_lane_rejects_short_record_count(tmp_path: Path) -> None:
    rows = [
        _native_row(f"inst-{i:02d}", artifact=tmp_path / f"raw-{i}" / "result.json")
        for i in range(4)
    ]
    evidence = _write_jsonl(tmp_path / "evidence.jsonl", rows)

    q = qualify_lane(evidence, expected_instances=5, **_TB_KWARGS)

    assert not q.ok
    assert any("4/5" in r or "expected" in r.lower() for r in q.reasons)


def test_qualify_lane_rejects_missing_artifact(tmp_path: Path) -> None:
    rows = [
        _record(
            instance_id=f"inst-{i:02d}",
            artifact_paths=[str(tmp_path / "does-not-exist" / "result.json")],
            verifier_log_path=str(tmp_path / "does-not-exist" / "verifier.log"),
        )
        for i in range(5)
    ]
    evidence = _write_jsonl(tmp_path / "evidence.jsonl", rows)

    q = qualify_lane(evidence, expected_instances=5, **_TB_KWARGS)

    assert not q.ok
    assert any("artifact" in r.lower() for r in q.reasons)


def test_qualify_lane_resolves_repo_root_relative_artifacts(tmp_path: Path) -> None:
    _touch(tmp_path / "results" / "raw" / "run" / "result.json")
    rows = [
        _record(
            instance_id=f"inst-{i:02d}",
            artifact_paths=["results/raw/run/result.json"],
            verifier_log_path="results/raw/run/result.json",
        )
        for i in range(5)
    ]
    evidence = _write_jsonl(tmp_path / "evidence.jsonl", rows)

    q = qualify_lane(evidence, expected_instances=5, repo_root=tmp_path, **_TB_KWARGS)

    assert q.ok


@pytest.mark.parametrize(
    "axis",
    [
        "benchmark_version",
        "provider_id",
        "provider_config_hash",
        "adapter_id",
        "harness_kind",
        "harness_version",
    ],
)
def test_qualify_lane_rejects_null_provenance_axis(tmp_path: Path, axis: str) -> None:
    rows = [
        _record(
            instance_id=f"inst-{i:02d}",
            artifact_paths=[_touch(tmp_path / f"raw-{i}" / "result.json")],
            **{axis: None},
        )
        for i in range(5)
    ]
    evidence = _write_jsonl(tmp_path / "evidence.jsonl", rows)

    q = qualify_lane(evidence, expected_instances=5, **_TB_KWARGS)

    assert not q.ok
    assert any("provenance" in r.lower() for r in q.reasons)


def test_qualify_lane_rejects_wrong_slice_identity(tmp_path: Path) -> None:
    rows = [
        _record(
            instance_id=f"inst-{i:02d}",
            slice_id="other-slice",
            artifact_paths=[_touch(tmp_path / f"raw-{i}" / "result.json")],
        )
        for i in range(5)
    ]
    evidence = _write_jsonl(tmp_path / "evidence.jsonl", rows)

    q = qualify_lane(evidence, expected_instances=5, **_TB_KWARGS)

    assert not q.ok
    assert any("identity" in r.lower() for r in q.reasons)


def test_qualify_lane_runtime_lane_requires_runtime_id(tmp_path: Path) -> None:
    rows = [
        _record(
            instance_id=f"inst-{i:02d}",
            runtime_id=None,
            artifact_paths=[_touch(tmp_path / f"raw-{i}" / "result.json")],
        )
        for i in range(5)
    ]
    evidence = _write_jsonl(tmp_path / "evidence.jsonl", rows)

    q = qualify_lane(evidence, expected_instances=5, **_TB_KWARGS)

    assert not q.ok
    # A model-only lane (no --require-runtime) accepts the same rows.
    q_model_only = qualify_lane(
        evidence,
        expected_instances=5,
        benchmark_id="terminal-bench",
        slice_id="smoke-5",
        require_runtime=False,
    )
    assert q_model_only.ok


def test_shared_eligible_instances_intersects_eligible_only(tmp_path: Path) -> None:
    rows_a = [
        _native_row("shared-1", artifact=tmp_path / "a1" / "result.json"),
        _record(
            instance_id="shared-2",
            failure_class="runtime_launch_failure",
            verifier_log_path=_touch(tmp_path / "a2" / "adapter_failure.json"),
            attempt_validity=None,
            counts_toward_pass_at_k=None,
        ),
        _native_row("only-a", artifact=tmp_path / "a3" / "result.json"),
    ]
    rows_b = [
        _native_row("shared-1", artifact=tmp_path / "b1" / "result.json"),
        _native_row("shared-2", artifact=tmp_path / "b2" / "result.json"),
    ]
    path_a = _write_jsonl(tmp_path / "a.jsonl", rows_a)
    path_b = _write_jsonl(tmp_path / "b.jsonl", rows_b)

    assert shared_eligible_instances(path_a, path_b) == {"shared-1"}


# ---------------------------------------------------------------------------
# Behavioral: the real pilot script end-to-end (PATH shim; see header block).
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PILOT_SCRIPT = _REPO_ROOT / "scripts" / "run-live-pilot-matrix.sh"
_PILOT_GLOBS = (
    "tb-claude-code-*",
    "tb-codex-cli-*",
    "bfcl-smoke5-*",
    "swe-smoke10-*",
    "tb-runtime-*",
)
_RESULTS_SUBDIRS = ("evidence", "raw", "reports", "bundles", "preflight", "compare")

_FAKE_RUN_PY = '''\
"""Emulated `bencheval run` for the H3 regression test (see SUBSTITUTE_JUSTIFICATION)."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from bencheval.evidence import EvidenceRecord, JsonlEvidenceSink

# benchmark -> (adapter_id, harness_kind, backend, execution_profile)
_LANES = {
    "terminal-bench": ("terminal-bench-harbor", "harbor", "harbor", "E2"),
    "bfcl-v4": ("bfcl", "bfcl-native", "inspect", "E0"),
    "swe-bench-verified": ("swebench", "swebench-native", "inspect", "E1"),
}


def _rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(resolved)


def _parse(argv: list[str]) -> dict[str, str | None]:
    parsed: dict[str, str | None] = {
        "target": None,
        "output": None,
        "artifacts_dir": None,
        "runtime": None,
        "model": None,
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "-y":
            i += 1
            continue
        if arg in ("--output", "--artifacts-dir", "--runtime", "--model"):
            parsed[arg[2:].replace("-", "_")] = argv[i + 1]
            i += 2
            continue
        if parsed["target"] is None and not arg.startswith("-"):
            parsed["target"] = arg
        i += 1
    return parsed


def _row(
    *,
    scenario: str,
    benchmark: str,
    slice_id: str,
    runtime: str | None,
    model: str,
    instance_id: str,
    index: int,
    artifacts_dir: Path,
    run_id: str,
) -> EvidenceRecord:
    adapter_id, harness_kind, backend, profile = _LANES[benchmark]
    instance_dir = artifacts_dir / instance_id
    instance_dir.mkdir(parents=True, exist_ok=True)
    if scenario == "qualified":
        primary_pass = index % 2 == 0
        failure_class = None if primary_pass else "model_wrong_solution"
        result = instance_dir / "result.json"
        result.write_text(json.dumps({"resolved": primary_pass}) + "\\n", encoding="utf-8")
        stdout_log = instance_dir / "stdout.log"
        stdout_log.write_text("fake native run\\n", encoding="utf-8")
        artifact_paths = [_rel(result), _rel(stdout_log)]
        verifier_log_path = _rel(result)
        attempt_validity: str | None = "valid"
        counts: bool | None = True
        harness_version: str | None = "fake-harness@1"
        verifier_integrity_label: str | None = "native"
        runtime_version: str | None = f"{runtime}@fake" if runtime else None
        runtime_config_hash: str | None = f"sha256:{runtime}-fake" if runtime else None
    else:
        primary_pass = False
        failure_class = "runtime_launch_failure"
        log = instance_dir / "adapter_failure.json"
        log.write_text(json.dumps({"failure_label": failure_class}) + "\\n", encoding="utf-8")
        artifact_paths = []
        verifier_log_path = _rel(log)
        attempt_validity = None
        counts = None
        harness_version = None
        verifier_integrity_label = None
        runtime_version = None
        runtime_config_hash = None
    return EvidenceRecord(
        run_id=run_id,
        task_id=instance_id,
        model_id=model,
        execution_profile=profile,
        backend=backend,
        primary_pass=primary_pass,
        partial_score=1.0 if primary_pass else 0.0,
        cost_usd=0.0,
        latency_sec=0.5,
        failure_labels=[] if failure_class is None else [failure_class],
        artifact_paths=artifact_paths,
        verifier_log_path=verifier_log_path,
        created_at=datetime.now(tz=UTC),
        benchmark_id=benchmark,
        benchmark_version="fake-v1",
        slice_id=slice_id,
        adapter_id=adapter_id,
        harness_kind=harness_kind,
        harness_version=harness_version,
        runtime_id=runtime,
        runtime_kind="cli_agent" if runtime else None,
        runtime_version=runtime_version,
        runtime_config_hash=runtime_config_hash,
        provider_id="bytellm",
        provider_config_hash="sha256:bytellm-fake",
        instance_id=instance_id,
        interpretation_label="adapter_smoke",
        verifier_integrity_label=verifier_integrity_label,
        failure_class=failure_class,
        attempt_validity=attempt_validity,
        counts_toward_pass_at_k=counts,
    )


def main(argv: list[str]) -> int:
    parsed = _parse(argv)
    assert parsed["target"] and parsed["output"] and parsed["artifacts_dir"]
    benchmark, slice_id = parsed["target"].split("/", 1)
    count = 10 if benchmark == "swe-bench-verified" else 5
    scenario = os.environ.get("BENCHEVAL_FAKE_RUN_SCENARIO", "failure")
    artifacts_dir = Path(parsed["artifacts_dir"])
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    output_path = Path(parsed["output"])
    run_id = output_path.stem
    sink = JsonlEvidenceSink()
    for index in range(count):
        row = _row(
            scenario=scenario,
            benchmark=benchmark,
            slice_id=slice_id,
            runtime=parsed["runtime"],
            model=parsed["model"] or "kimi-k2.7-code",
            instance_id=f"{benchmark}-inst-{index:02d}",
            index=index,
            artifacts_dir=artifacts_dir,
            run_id=run_id,
        )
        sink.append_jsonl(Path(parsed["output"]), row)
    # Match the real CLI boundary: a native model_wrong_solution row makes the
    # aggregate run exit nonzero even though the lane remains proof-eligible.
    return 1 if scenario == "qualified" else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
'''


def _write_shim_dir(shim_dir: Path, *, real_uv: str) -> None:
    shim_dir.mkdir(parents=True, exist_ok=True)
    fake_run = shim_dir / "fake_bencheval_run.py"
    fake_run.write_text(_FAKE_RUN_PY, encoding="utf-8")
    stubs = {
        "uv": f"""#!/usr/bin/env bash
set -euo pipefail
if [[ ${{1:-}} == "run" && ${{2:-}} == "--no-sync" && \\
    ${{3:-}} == "bencheval" && ${{4:-}} == "run" ]]; then
  exec "{sys.executable}" "{fake_run}" "${{@:5}}"
fi
exec "{real_uv}" "$@"
""",
        "docker": """#!/usr/bin/env bash
exit 0
""",
        "harbor": """#!/usr/bin/env bash
if [[ ${1:-} == "--version" ]]; then
  printf 'harbor 0.2.0-stub\\n'
fi
exit 0
""",
        "bfcl": """#!/usr/bin/env bash
if [[ ${1:-} == "models" ]]; then
  printf 'kimi-k2.7-code\\n'
fi
exit 0
""",
        "mini-extra": """#!/usr/bin/env bash
exit 0
""",
    }
    for name, body in stubs.items():
        path = shim_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)


def _pilot_artifacts() -> set[Path]:
    found: set[Path] = set()
    for sub in _RESULTS_SUBDIRS:
        for pattern in _PILOT_GLOBS:
            found.update((_REPO_ROOT / "results" / sub).glob(pattern))
    return found


@pytest.fixture
def pilot_workspace(tmp_path: Path) -> Path:
    # These tests run the real pilot script against the repository-global
    # results/ tree; serialize across concurrent pytest processes with an
    # interprocess lock so same-second pilot stamps cannot collide. The lock
    # lives outside the checkout — it is coordination, never repository content.
    lock_path = Path(tempfile.gettempdir()) / "bencheval-pilot-test.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        before = _pilot_artifacts()
        shim_dir = tmp_path / "shim"
        real_uv = shutil.which("uv")
        assert real_uv, "uv must be on PATH to run the pilot regression test"
        _write_shim_dir(shim_dir, real_uv=real_uv)
        yield shim_dir
        for path in _pilot_artifacts() - before:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _run_pilot(shim_dir: Path, *, scenario: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{shim_dir}:/usr/bin:/bin",
        "BENCHEVAL_PILOT_MODEL": "kimi-k2.7-code",
        "BYTELLM_API_KEY": "bencheval-h3-test-dummy-key",
        "BENCHEVAL_FAKE_RUN_SCENARIO": scenario,
    }
    return subprocess.run(
        ["bash", str(_PILOT_SCRIPT)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=600,
    )


def test_pilot_rejects_failure_only_evidence(pilot_workspace: Path) -> None:
    proc = _run_pilot(pilot_workspace, scenario="failure")
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0
    assert "minimum proof: ok" not in combined.lower()


def test_pilot_accepts_qualified_native_evidence(pilot_workspace: Path) -> None:
    proc = _run_pilot(pilot_workspace, scenario="qualified")
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 0, combined
    assert "Live pilot minimum proof: OK" in combined
    assert "shared eligible instances" in combined
    stamp_match = re.search(r"stamp=([0-9TZ]+)", combined, flags=re.IGNORECASE)
    assert stamp_match is not None, combined
    stamp = stamp_match.group(1)
    evidence_path = _REPO_ROOT / "results" / "evidence" / f"tb-claude-code-{stamp}.jsonl"
    rows = read_evidence_jsonl(evidence_path)
    assert rows
    assert all(row.interpretation_label == "adapter_smoke" for row in rows)
    assert "scored bfcl" not in combined.lower()
