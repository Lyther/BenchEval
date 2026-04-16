from __future__ import annotations

import hashlib
from pathlib import Path

from bencheval.exceptions import ManifestError
from bencheval.models import ManifestDigest


def load_manifest(path: Path | str) -> ManifestDigest:
    """Load a task manifest file and return ids plus canonical SHA-256.

    Canonical bytes: ``sorted(task_ids)``, joined with ``\\n``, plus a trailing ``\\n``,
    encoded as UTF-8. Comments and blank lines do not affect the hash.
    """
    p = Path(path)
    benchmark = p.stem
    try:
        raw_text = p.read_text(encoding="utf-8")
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

    canonical = "\n".join(sorted(task_ids)) + "\n"
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    resolved = p.resolve()

    return ManifestDigest(
        benchmark=benchmark,
        manifest_path=resolved.as_posix(),
        content_sha256=digest,
        task_ids=tuple(sorted(task_ids)),
    )
