"""X4.2 regressions: the reproduction read-back cannot be made to hang or follow a link.

X4.1 bound the displayed reproduction to the digest the verifier proved, which
closed the replacement hole (`tests/regressions/test_x41_round1_contracts.py`
still owns that case). The read itself was still an ordinary open, so a path
swapped to a FIFO after the exclusive write blocked the operator's request
before any digest could be checked, and a symlink at that path was followed.
Both now go through the repository's untrusted-leaf reader: no follow, no
block, single-link regular files only, with the digest check unchanged.

SUBSTITUTE_JUSTIFICATION
- substitute: a parent process that renames a FIFO, a symlink, or a second link
  to a planted report over the reproduction path the moment the operation's exclusive create
  publishes it, while the operation runs in a spawned child under a deadline
- replaces: anything else on the operator host substituting that path between
  the domain's write and the projection's read
- necessity: the window contains no I/O to synchronize on, so the substitution
  cannot be steered into it deterministically; running the operation in a child
  under a deadline is also what makes a blocking read observable as a failure
  instead of a hung suite
- real-option: the FIFO, the symlink, the rename, the proofs, the lock, and
  every production code path are real; nothing in ``bencheval`` is patched
- proof-limit: proves that a substituted special file or link is refused
  promptly and that an untouched reproduction still renders; it does not prove
  filesystem atomicity guarantees on every host
- real-proof: the retained X2.4 FC plumbing proofs and lock
  (``tests/fixtures/exposure/x24fc``), reproduced unchanged by the control case
- covered tests: every test in this module
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
from pathlib import Path

import pytest

from bencheval.application import OperatorOperations
from bencheval.exceptions import BenchEvalError

_X24FC = Path(__file__).resolve().parents[1] / "fixtures" / "exposure" / "x24fc"
_LOCK = _X24FC / "x24fc-exposure-report.lock.json"
_RETAINED_REPORT = _X24FC / "x24fc-exposure-report.json"
# A read that follows the substituted path has no reason to return, so the
# deadline is what turns "blocked" into a failure rather than a hung suite.
_DEADLINE_SECONDS = 20.0
_ATTEMPTS = 8


def _reproduce(output: str, results: object) -> None:
    """Run the real operation in its own process and report what it did."""
    try:
        view = OperatorOperations().study_verify(
            _LOCK,
            canonical_proof=_X24FC / "canonical",
            candidate_proof=_X24FC / "candidate",
            output=Path(output),
        )
    except BenchEvalError as exc:
        results.put(("refused", str(exc)))
    except BaseException as exc:  # pragma: no cover - a typed refusal is the contract
        results.put(("raised", f"{type(exc).__name__}: {exc}"))
    else:
        results.put(("rendered", json.dumps(view.report_payload, sort_keys=True)))


def _stronger_claim(workspace: Path) -> Path:
    """A real report whose limits have been stripped: what a substitution shows."""
    payload = json.loads(_RETAINED_REPORT.read_text(encoding="utf-8"))
    payload["permitted_interpretation"] = "clean"
    payload["forbidden_claims"] = []
    planted = workspace / "planted.json"
    planted.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return planted


def _substitute(kind: str, workspace: Path) -> Path:
    """Build the entry this process renames over the freshly written report.

    Every kind resolves to content the operator must not be shown, so a read
    that follows or accepts it is caught by what it displays, not only by the
    digest check that already stands behind it.
    """
    if kind == "fifo":
        target = workspace / "fifo"
        os.mkfifo(target)
        return target
    if kind == "symlink":
        target = workspace / "link"
        target.symlink_to(_stronger_claim(workspace))
        return target
    target = workspace / "hardlink"
    os.link(_stronger_claim(workspace), target)
    return target


def _race(kind: str, workspace: Path) -> tuple[str, str] | None:
    """Reproduce the lock while this process substitutes the output path.

    Returns the child's outcome, or ``None`` when the substitution lost the race
    and the child rendered the authentic report.
    """
    output = workspace / "reproduced.json"
    replacement = _substitute(kind, workspace)
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    child = context.Process(target=_reproduce, args=(str(output), results))
    child.start()
    substituted = False
    try:
        while child.is_alive() and not substituted:
            if output.exists():
                os.rename(replacement, output)
                substituted = True
        outcome = results.get(timeout=_DEADLINE_SECONDS)
    except Exception as exc:  # an empty queue means the read never returned
        child.terminate()
        child.join(timeout=_DEADLINE_SECONDS)
        raise AssertionError(
            f"the reproduction read never returned with a {kind} at the output path: {exc}",
        ) from exc
    finally:
        child.join(timeout=_DEADLINE_SECONDS)
        if child.is_alive():  # pragma: no cover - only reached if the read blocked
            child.terminate()
            child.join(timeout=_DEADLINE_SECONDS)
    if not substituted:
        return None
    return outcome


@pytest.mark.parametrize("kind", ["fifo", "symlink", "hardlink"])
def test_a_substituted_reproduction_path_is_refused_promptly(kind: str, tmp_path: Path) -> None:
    """A special file, a link, or a shared inode at the output refuses inside the deadline."""
    retained = json.loads(_RETAINED_REPORT.read_text(encoding="utf-8"))
    substitutions = 0
    for attempt in range(_ATTEMPTS):
        workspace = tmp_path / f"{kind}-{attempt}"
        workspace.mkdir()
        outcome = _race(kind, workspace)
        if outcome is None:
            continue
        state, detail = outcome
        if state == "rendered":
            # The substitution landed after the read; the operator still saw the
            # authentic report, which is the only acceptable rendering.
            assert json.loads(detail) == retained
            continue
        substitutions += 1
        assert state == "refused", detail
        assert "cannot read the reproduced report" in detail

    assert substitutions, f"no attempt substituted a {kind}; the regression proved nothing"


def test_a_report_that_is_not_the_verified_one_is_refused_by_digest(tmp_path: Path) -> None:
    """The stricter open is added to the digest check, not substituted for it.

    The race above can be refused by either guard depending on when the
    substitution lands, so the digest comparison is pinned here directly: an
    ordinary, single-link, perfectly readable report is still refused when it is
    not the report the verifier proved.
    """
    from bencheval.application.operations import _verified_report

    planted = _stronger_claim(tmp_path)
    retained_digest = json.loads(_LOCK.read_text(encoding="utf-8"))["report_sha256"]

    with pytest.raises(BenchEvalError) as refused:
        _verified_report(planted, expected_sha256=retained_digest)

    message = str(refused.value)
    assert "does not match the verified report" in message
    assert retained_digest in message
    # The honest case still returns the parsed report.
    assert _verified_report(
        _RETAINED_REPORT,
        expected_sha256=retained_digest,
    ) == json.loads(_RETAINED_REPORT.read_text(encoding="utf-8"))


def test_an_untouched_reproduction_still_renders(tmp_path: Path) -> None:
    """Control: the stricter read must not cost an honest reproduction its report."""
    output = tmp_path / "reproduced.json"

    view = OperatorOperations().study_verify(
        _LOCK,
        canonical_proof=_X24FC / "canonical",
        candidate_proof=_X24FC / "candidate",
        output=output,
    )

    retained = json.loads(_RETAINED_REPORT.read_text(encoding="utf-8"))
    digest = f"sha256:{hashlib.sha256(output.read_bytes()).hexdigest()}"
    assert view.ok is True
    assert view.report_payload == retained
    assert view.report_sha256 == digest
    assert view.non_claims == tuple(retained["forbidden_claims"])
