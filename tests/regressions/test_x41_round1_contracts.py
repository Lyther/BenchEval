"""X4.1 round-1 F001/N001 regressions: a reproduction may only display what it verified.

``study_verify`` proves a retained lock by rebuilding its report in memory and
comparing digests, then reads the written reproduction back so the operator sees
the locked report's own scores, caveats, and non-claims. Reading that path again
without binding it to the verified digest lets anything else on the host publish
a different report beside an authentic digest and ``ok: true`` — a replacement
displayed as a reproduction.

SUBSTITUTE_JUSTIFICATION
- substitute: a spawned writer process that atomically renames a prepared report
  over the reproduction path the moment the domain creates it, retried a bounded
  number of times, plus a report payload edited to carry a stronger claim
- replaces: anything else on the operator host writing that output path while the
  exclusive create is still being written and fsynced
- necessity: the window between the domain's write and the projection's read
  contains no I/O to synchronize on, so the writer cannot be steered into it
  deterministically and each attempt is classified by what the operation returned
- real-option: the rename, the bytes, the proofs, the lock, and every production
  code path are real; nothing in ``bencheval`` is patched, injected, or stubbed
- proof-limit: proves that a replaced reproduction is refused rather than
  displayed; it does not prove filesystem atomicity guarantees on every host
- real-proof: the retained X2.4 FC plumbing proofs and their lock
  (``tests/fixtures/exposure/x24fc``, dev-box-cpu, 2026-09-05), reproduced
  unchanged by the control case below
- covered tests: every test in this module
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path

from bencheval.application import OperatorOperations, StudyLockVerificationDTO
from bencheval.exceptions import BenchEvalError

_OPS = OperatorOperations()
_X24FC = Path(__file__).resolve().parents[1] / "fixtures" / "exposure" / "x24fc"
_LOCK = _X24FC / "x24fc-exposure-report.lock.json"
_RETAINED_REPORT = _X24FC / "x24fc-exposure-report.json"
# Bounded real attempts. The exclusive create publishes the path before the
# report bytes are written and fsynced, so a spinning writer lands well inside
# that window; the loop exists so a slow host cannot make the regression flaky.
_ATTEMPTS = 8


def _replace_when_created(target: str, replacement: str, ready, halt) -> None:
    """Rename a prepared report over ``target`` as soon as the path appears.

    Runs in its own process so it truly races the exclusive create rather than
    waiting for a GIL slice.
    """
    ready.set()
    while not halt.is_set():
        if os.path.exists(target):
            os.rename(replacement, target)
            return


def _digest(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _stronger_claim(payload: dict[str, object]) -> dict[str, object]:
    """The locked report with its limits removed: what a replacement would claim."""
    replaced = dict(payload)
    replaced["permitted_interpretation"] = "clean"
    replaced["forbidden_claims"] = []
    return replaced


def _verify_against_a_racing_writer(
    output: Path, replacement: Path
) -> tuple[BenchEvalError | None, StudyLockVerificationDTO | None]:
    """Reproduce the retained lock while another process replaces the output.

    Exactly one of the two results comes back. A refusal means the replacement
    won the race and the projection caught it; a returned view means the writer
    lost, and the caller checks that what it displays is the authentic report.
    """
    context = multiprocessing.get_context("spawn")
    ready, halt = context.Event(), context.Event()
    racer = context.Process(
        target=_replace_when_created,
        args=(str(output), str(replacement), ready, halt),
    )
    racer.start()
    try:
        assert ready.wait(timeout=30), "the racing writer never started"
        try:
            return None, _OPS.study_verify(
                _LOCK,
                canonical_proof=_X24FC / "canonical",
                candidate_proof=_X24FC / "candidate",
                output=output,
            )
        except BenchEvalError as exc:
            return exc, None
    finally:
        halt.set()
        racer.join(timeout=30)
        if racer.is_alive():  # pragma: no cover - the writer returns on halt
            racer.terminate()
            racer.join(timeout=30)


def test_a_replaced_reproduction_is_refused_instead_of_displayed(tmp_path: Path) -> None:
    retained = json.loads(_RETAINED_REPORT.read_text(encoding="utf-8"))
    locked_digest = json.loads(_LOCK.read_text(encoding="utf-8"))["report_sha256"]
    lock_before = _digest(_LOCK)
    report_before = _digest(_RETAINED_REPORT)

    landings = 0
    for attempt in range(_ATTEMPTS):
        workspace = tmp_path / f"attempt-{attempt}"
        workspace.mkdir()
        output = workspace / "reproduced.json"
        replacement = workspace / "replacement.json"
        replacement.write_text(
            json.dumps(_stronger_claim(retained), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        refused, view = _verify_against_a_racing_writer(output, replacement)
        if view is not None:
            # The writer lost this race, so the read saw the authentic report.
            # Displaying the replacement here would be the defect itself.
            assert view.report_payload == retained
            continue
        landings += 1
        # The refusal names the binding it enforced. Either guard may speak
        # first: X4.2 reads the reproduction through the untrusted-leaf reader,
        # which refuses an inode the replacement unlinked out from under the
        # open before the digest comparison is reached.
        assert refused is not None
        message = str(refused)
        assert "cannot read the reproduced report" in message or (
            "does not match the verified report" in message and locked_digest in message
        ), message
        # The race really happened: the path holds the replacement, and its
        # stronger claim never reached the operator.
        replaced = json.loads(output.read_text(encoding="utf-8"))
        assert replaced["permitted_interpretation"] == "clean"
        assert _digest(output) != locked_digest

    assert landings, "no attempt replaced the reproduction; the regression proved nothing"
    # The retained lock and its report are untouched by the attack and the refusal.
    assert _digest(_LOCK) == lock_before
    assert _digest(_RETAINED_REPORT) == report_before


def test_an_unraced_reproduction_still_displays_the_locked_report(tmp_path: Path) -> None:
    """Control: the digest binding must not cost the honest path its report."""
    output = tmp_path / "reproduced.json"

    view = _OPS.study_verify(
        _LOCK,
        canonical_proof=_X24FC / "canonical",
        candidate_proof=_X24FC / "candidate",
        output=output,
    )

    retained = json.loads(_RETAINED_REPORT.read_text(encoding="utf-8"))
    assert view.ok is True
    assert view.report_sha256 == _digest(output) == _digest(_RETAINED_REPORT)
    assert view.report_payload == retained
    assert view.non_claims == tuple(retained["forbidden_claims"])
    assert view.non_claims, "the locked report's non-claims must survive the reproduction"


def test_reproduction_rows_keep_one_row_per_table_key(tmp_path: Path) -> None:
    """``field`` is the table's row key: the rebuilt report must not shadow a row."""
    output = tmp_path / "reproduced.json"
    view = _OPS.study_verify(
        _LOCK,
        canonical_proof=_X24FC / "canonical",
        candidate_proof=_X24FC / "candidate",
        output=output,
    )

    rows = view.table_rows()
    keys = [row["field"] for row in rows]
    assert len(keys) == len(set(keys))
    labels = dict(zip(keys, (row["value"] for row in rows), strict=True))
    # Both identities remain visible: the lock's study and the rebuilt report's.
    assert labels["locked study"] == view.study_id
    assert labels["study"] == view.report_payload["study_id"]  # type: ignore[index]
    assert labels["report digest"] == view.report_sha256
