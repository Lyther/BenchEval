"""Exclusive run-output ownership helpers (evidence + artifact trees)."""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bencheval.exceptions import BenchEvalError

# Authoritative score/verdict filenames adapters may consume from a prior run.
AUTHORITATIVE_ARTIFACT_NAMES: frozenset[str] = frozenset(
    {
        "verifier.json",
        "result.json",
        "verdict.json",
        "official_scores.json",
        "gpqa_summary.json",
        "hle_summary.json",
    },
)


def _is_symlink_path(path: Path) -> bool:
    try:
        return stat.S_ISLNK(os.lstat(path).st_mode)
    except OSError:
        return False


def reject_symlink_path(path: Path, *, role: str) -> None:
    """Fail closed when ``path`` itself is a symlink (do not follow)."""
    if _is_symlink_path(path):
        raise BenchEvalError(f"{role} must not be a symlink: {path}")


@dataclass(frozen=True, slots=True)
class _EvidenceReservation:
    descriptor: int
    identity: tuple[int, int]


# Open file descriptions reserved via claim_exclusive_evidence_path, keyed by
# absolute lexical path. Keeping the original descriptor open is essential:
# Linux may immediately recycle an unlinked inode number, so a bare (dev, ino)
# tuple cannot distinguish the reserved file from a remove-and-recreate attack.
_RESERVED_EVIDENCE_FILES: dict[str, _EvidenceReservation] = {}

_CLAIM_MARKER_NAME = ".bencheval-run-claim"


def _evidence_registry_key(path: Path) -> str:
    return os.path.abspath(path.expanduser())


def reserved_evidence_inode(path: Path) -> tuple[int, int] | None:
    """Return the ``(st_dev, st_ino)`` recorded when ``path`` was reserved."""
    reservation = _RESERVED_EVIDENCE_FILES.get(_evidence_registry_key(path))
    return None if reservation is None else reservation.identity


def _reserved_path_identity_error(
    target: Path,
    reservation: _EvidenceReservation,
) -> str | None:
    try:
        current = os.lstat(target)
        held = os.fstat(reservation.descriptor)
    except OSError as e:
        return f"cannot inspect reserved evidence output {target}: {e}"
    current_identity = (current.st_dev, current.st_ino)
    held_identity = (held.st_dev, held.st_ino)
    if (
        not stat.S_ISREG(current.st_mode)
        or current_identity != reservation.identity
        or held_identity != reservation.identity
    ):
        return f"evidence output replaced after exclusive reservation: {target}"
    return None


def append_reserved_evidence(path: Path, payload: bytes) -> bool:
    """Append bytes through the held reservation descriptor when one exists.

    The lexical path must name the held inode both before and after the write.
    A same-uid mutator can therefore make the run fail, but can never redirect
    BenchEval's bytes into its replacement file.
    """
    target = Path(_evidence_registry_key(path))
    reservation = _RESERVED_EVIDENCE_FILES.get(str(target))
    if reservation is None:
        return False
    identity_error = _reserved_path_identity_error(target, reservation)
    if identity_error is not None:
        raise BenchEvalError(identity_error)
    remaining = memoryview(payload)
    try:
        while remaining:
            written = os.write(reservation.descriptor, remaining)
            if written <= 0:
                raise OSError("short write to reserved evidence output")
            remaining = remaining[written:]
    except OSError as e:
        raise BenchEvalError(f"cannot append reserved evidence output {target}: {e}") from e
    identity_error = _reserved_path_identity_error(target, reservation)
    if identity_error is not None:
        raise BenchEvalError(identity_error)
    return True


def release_evidence_reservation(path: Path) -> None:
    """Close and drop the reservation for ``path`` after all appends complete.

    Without an explicit release the registry would grow for the process
    lifetime; callers release at the end of each run (finally), and releasing
    an unreserved path is a no-op.
    """
    reservation = _RESERVED_EVIDENCE_FILES.pop(_evidence_registry_key(path), None)
    if reservation is None:
        return
    try:
        os.close(reservation.descriptor)
    except OSError as e:
        raise BenchEvalError(f"cannot release evidence reservation for {path}: {e}") from e


def claim_exclusive_evidence_path(path: Path) -> None:
    """Atomically reserve a missing evidence JSONL path for one run.

    The created file descriptor remains open until
    ``release_evidence_reservation`` so later appends stay bound to the exact
    file object that won the atomic claim (see ``JsonlEvidenceSink``).
    """
    target = path.expanduser()
    registry_key = _evidence_registry_key(target)
    if registry_key in _RESERVED_EVIDENCE_FILES:
        raise BenchEvalError(
            f"evidence output is already reserved by this process: {target}",
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise BenchEvalError(
            f"cannot create evidence output parent {target.parent}: {e}",
        ) from e

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(target, flags, 0o600)
    except FileExistsError as e:
        raise BenchEvalError(
            f"evidence output already exists (exclusive write required): {target}",
        ) from e
    except OSError as e:
        raise BenchEvalError(f"cannot reserve evidence output {target}: {e}") from e
    try:
        identity = os.fstat(descriptor)
    except OSError as e:
        os.close(descriptor)
        raise BenchEvalError(f"cannot inspect reserved evidence output {target}: {e}") from e
    _RESERVED_EVIDENCE_FILES[registry_key] = _EvidenceReservation(
        descriptor=descriptor,
        identity=(identity.st_dev, identity.st_ino),
    )


def _write_claim_marker(target: Path) -> None:
    marker = target / _CLAIM_MARKER_NAME
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(marker, flags, 0o600)
    except FileExistsError as e:
        raise BenchEvalError(
            f"run artifacts directory already claimed (exclusive run ownership required): {target}",
        ) from e
    except OSError as e:
        raise BenchEvalError(f"cannot claim run artifacts directory {target}: {e}") from e
    stamp = f"pid={os.getpid()} claimed_at={datetime.now(UTC).isoformat()}\n"
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(stamp)


def claim_exclusive_run_artifacts(path: Path) -> bool:
    """Claim a run-artifacts directory exclusively; reject symlink roots.

    Returns True only when this call created the directory. An existing
    directory is accepted only when it is empty apart from a prior claim
    marker; the atomic ``O_EXCL`` marker creation is the mutual-exclusion
    primitive, so two claims can never own the same tree.
    """
    target = path.expanduser()
    created = False
    if target.exists():
        reject_symlink_path(target, role="run artifacts directory")
        if not target.is_dir():
            raise BenchEvalError(f"run artifacts path exists but is not a directory: {target}")
        for entry in target.iterdir():
            if entry.name != _CLAIM_MARKER_NAME:
                raise BenchEvalError(
                    "run artifacts directory is not empty "
                    f"(exclusive run ownership required): {target}",
                )
    else:
        target.mkdir(parents=True, exist_ok=False)
        created = True
    _write_claim_marker(target)
    return created


def claim_exclusive_run_outputs(*, evidence_path: Path, artifacts_path: Path) -> None:
    """Claim an artifacts tree and atomically reserve its paired evidence file."""
    artifacts_created = claim_exclusive_run_artifacts(artifacts_path)
    try:
        claim_exclusive_evidence_path(evidence_path)
    except BenchEvalError:
        marker = artifacts_path.expanduser() / _CLAIM_MARKER_NAME
        try:
            marker.unlink()
        except OSError:
            pass
        if artifacts_created:
            try:
                artifacts_path.expanduser().rmdir()
            except OSError:
                pass
        raise


def prepare_instance_artifacts_dir(
    instance_dir: Path,
    *,
    clear_names: frozenset[str] = AUTHORITATIVE_ARTIFACT_NAMES,
) -> Path:
    """Create an instance dir and clear authoritative leftover score artifacts."""
    reject_symlink_path(instance_dir, role="instance artifacts directory")
    if instance_dir.exists() and not instance_dir.is_dir():
        raise BenchEvalError(f"instance artifacts path is not a directory: {instance_dir}")
    instance_dir.mkdir(parents=True, exist_ok=True)
    reject_symlink_path(instance_dir, role="instance artifacts directory")
    for name in sorted(clear_names):
        target = instance_dir / name
        if not target.exists() and not _is_symlink_path(target):
            continue
        if _is_symlink_path(target) or target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
    return instance_dir


def open_owned_dir_fd(path: Path, *, role: str) -> int:
    """Open ``path`` as a directory and return an anchoring file descriptor.

    BenchEval-owned writes beneath ``path`` must be anchored to the returned
    descriptor (see ``write_text_at_exclusive``): a pathname merely *looked at*
    proves nothing against a same-uid mutator. Symlink paths are rejected
    without following, the directory is created when missing, and the symlink
    check is repeated after ``mkdir`` so a swapped path never becomes the
    anchor. All filesystem failures surface as BenchEvalError (carrying the
    original OSError as ``__cause__``): adapters and the CLI catch nothing else.
    """
    reject_symlink_path(path, role=role)
    if path.exists() and not path.is_dir():
        raise BenchEvalError(f"{role} is not a directory: {path}")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise BenchEvalError(f"cannot create {role} {path}: {e}") from e
    reject_symlink_path(path, role=role)
    try:
        return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as e:
        raise BenchEvalError(f"cannot open {role} {path}: {e}") from e


def _validate_dirfd_relative_name(name: str) -> None:
    if "/" in name or name in ("", ".", ".."):
        raise BenchEvalError(f"unsafe dirfd-relative file name: {name!r}")


def _exclusive_recreate_fd(dir_fd: int, name: str) -> int:
    _validate_dirfd_relative_name(name)
    try:
        os.unlink(name, dir_fd=dir_fd)
    except FileNotFoundError:
        pass
    except OSError as e:
        # e.g. a directory squatting at the target name (IsADirectoryError /
        # EPERM): surface tampering as BenchEvalError, never a raw traceback.
        raise BenchEvalError(f"cannot replace dirfd-relative entry {name!r}: {e}") from e
    try:
        return os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o644,
            dir_fd=dir_fd,
        )
    except OSError as e:
        # e.g. ENOENT when a mutator unlinked the anchored directory mid-run,
        # EEXIST losing the unlink->open race, ELOOP on a swapped symlink.
        raise BenchEvalError(f"cannot create dirfd-relative file {name!r}: {e}") from e


def write_text_at_exclusive(dir_fd: int, name: str, text: str) -> None:
    """Write ``name`` relative to an open directory fd, replacing attacker entries.

    A same-uid mutator may leave a symlink, hard link, or forged file at this
    name. Unlinking first removes only the directory entry — a hard-linked
    victim inode is never opened, truncated, or unlinked — and the exclusive
    recreate guarantees a fresh BenchEval-owned inode. Combined with the dirfd
    anchor, our bytes can only land in the approved directory. All filesystem
    failures surface as BenchEvalError (original OSError as ``__cause__``).
    """
    fd = _exclusive_recreate_fd(dir_fd, name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
    except OSError as e:
        raise BenchEvalError(f"cannot write dirfd-relative file {name!r}: {e}") from e


def write_bytes_at_exclusive(dir_fd: int, name: str, data: bytes) -> None:
    """Bytes variant of ``write_text_at_exclusive`` (same anchoring contract)."""
    fd = _exclusive_recreate_fd(dir_fd, name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
    except OSError as e:
        raise BenchEvalError(f"cannot write dirfd-relative file {name!r}: {e}") from e


def dir_identity_error(dir_fd: int, path: Path, *, role: str) -> str | None:
    """None when ``path`` still names the inode pinned by ``dir_fd``.

    A same-uid mutator can rename an approved directory and recreate the path
    (plain directory or symlink) carrying forged content. The dirfd pins the
    inode BenchEval approved; the pathname must still resolve to that same
    inode before any path beneath it is returned as evidence.
    """
    held = os.fstat(dir_fd)
    try:
        current = os.lstat(path)
    except OSError:
        return f"{role} vanished during execution: {path}"
    if stat.S_ISLNK(current.st_mode):
        return f"{role} replaced by symlink during execution: {path}"
    if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino):
        return f"{role} replaced during execution: {path}"
    return None


__all__ = [
    "AUTHORITATIVE_ARTIFACT_NAMES",
    "append_reserved_evidence",
    "claim_exclusive_evidence_path",
    "claim_exclusive_run_artifacts",
    "claim_exclusive_run_outputs",
    "dir_identity_error",
    "open_owned_dir_fd",
    "prepare_instance_artifacts_dir",
    "reject_symlink_path",
    "release_evidence_reservation",
    "reserved_evidence_inode",
    "write_bytes_at_exclusive",
    "write_text_at_exclusive",
]
