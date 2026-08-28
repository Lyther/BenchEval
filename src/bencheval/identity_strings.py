"""Captured benchmark identity strings for the pinned catalog identities.

Each builder derives the immutable, non-provisional identity stamped into
evidence from the catalog ``identity:`` block (see ``benchmark_registry``).
Digests are truncated to 16 hex chars, matching the ``_hle_scripts_digest``
precedent. These strings are *derived* from config; the adapters prove the
local bytes actually match the pins before capturing them (runtime
verification), so a captured string is evidence, not a claim.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from bencheval.benchmark_registry import (
    BenchmarkIdentity,
    BfclPackageDataIdentity,
    HfDatasetSnapshotIdentity,
    InspectEvalsCsvIdentity,
)

SHORT_DIGEST_HEX = 16

_SHA256_PREFIX = "sha256:"


def short_digest(sha256_pin: str) -> str:
    """First 16 hex chars of a ``sha256:<64-hex>`` pin (or a bare hex digest)."""
    return sha256_pin.removeprefix(_SHA256_PREFIX)[:SHORT_DIGEST_HEX]


def combined_data_sha256(files: Mapping[str, str]) -> str:
    """One digest binding a pinned file set.

    A single-file pin binds that file's own 64-hex digest directly (the HLE
    shape). Multi-file sets hash the sorted ``"<relpath>:<sha256:...>"`` lines
    so the identity is order-independent and covers both names and bytes.
    """
    if len(files) == 1:
        return next(iter(files.values())).removeprefix(_SHA256_PREFIX)
    lines = [f"{relpath}:{digest}\n" for relpath, digest in sorted(files.items())]
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def gpqa_benchmark_identity(identity: InspectEvalsCsvIdentity) -> str:
    """``gpqa-diamond@inspect-evals-<dist>+eval-<task-version>+csv-<short-sha>``."""
    return (
        f"gpqa-diamond@{identity.package}-{identity.package_version}"
        f"+eval-{identity.eval_version}+csv-{short_digest(identity.sha256)}"
    )


def swebench_benchmark_identity(identity: HfDatasetSnapshotIdentity) -> str:
    """``swe-bench-verified@<short-revision>+data-<short-sha>``."""
    return (
        f"swe-bench-verified@{identity.revision[:SHORT_DIGEST_HEX]}"
        f"+data-{combined_data_sha256(identity.files)[:SHORT_DIGEST_HEX]}"
    )


def hle_benchmark_identity(identity: HfDatasetSnapshotIdentity) -> str:
    """``hle@<short-revision>+data-<short-sha>``; the repo stays in metadata."""
    return (
        f"hle@{identity.revision[:SHORT_DIGEST_HEX]}"
        f"+data-{combined_data_sha256(identity.files)[:SHORT_DIGEST_HEX]}"
    )


def bfcl_benchmark_identity(identity: BfclPackageDataIdentity) -> str:
    """``bfcl-v4@bfcl-eval-<version>+data-<short-combined-sha>``."""
    return (
        f"bfcl-v4@bfcl-eval-{identity.bfcl_eval_version}"
        f"+data-{combined_data_sha256(identity.files)[:SHORT_DIGEST_HEX]}"
    )


def file_sha256(path: Path) -> str:
    """Streamed sha256 hex digest of a local file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def catalog_benchmark_identity(benchmark_id: str) -> BenchmarkIdentity | None:
    """The catalog's pinned identity for ``benchmark_id``, or None when unpinned."""
    from bencheval.benchmark_registry import load_benchmark_catalog

    return load_benchmark_catalog().by_id_or_alias(benchmark_id).identity
