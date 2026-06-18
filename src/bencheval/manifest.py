from __future__ import annotations

import hashlib
from pathlib import Path

from bencheval.exceptions import ManifestError
from bencheval.models import ManifestDigest


def read_manifest_task_ids(path: Path | str) -> tuple[str, ...]:
    """Return task ids in manifest file order, ignoring comments and blanks."""
    p = Path(path)
    try:
        raw_text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ManifestError(f"cannot decode manifest {p} as UTF-8: {e}") from e
    except OSError as e:
        raise ManifestError(f"cannot read manifest {p}: {e}") from e

    task_ids: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        task_ids.append(stripped)

    if not task_ids:
        raise ManifestError(f"manifest {p} has no task ids after stripping comments and blanks")
    return tuple(task_ids)


def load_manifest(path: Path | str) -> ManifestDigest:
    """Load a task manifest file and return sorted ids plus canonical SHA-256."""
    p = Path(path)
    benchmark = p.stem
    task_ids = read_manifest_task_ids(p)

    canonical = "\n".join(sorted(task_ids)) + "\n"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    resolved = p.resolve()

    return ManifestDigest(
        benchmark=benchmark,
        manifest_path=resolved.as_posix(),
        content_sha256=digest,
        task_ids=tuple(sorted(task_ids)),
    )
