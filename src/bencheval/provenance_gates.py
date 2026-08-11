"""Shared reject rules for provisional / uncaptured provenance labels."""

from __future__ import annotations

# Placeholder harness labels that adapters historically invented when capture failed.
_FALLBACK_HARNESS_VERSIONS: frozenset[str] = frozenset(
    {
        "swebench-native-smoke",
        "bfcl-native-smoke",
    },
)


def is_captured_axis(value: str | None) -> bool:
    """True when a provenance axis is a nonempty stripped string."""
    return isinstance(value, str) and bool(value.strip())


def is_provisional_benchmark_version(version: str | None) -> bool:
    if not is_captured_axis(version):
        return False
    assert version is not None
    return version.strip().startswith(("provisional:", "provisional/"))


def is_uncaptured_harness_version(version: str | None) -> bool:
    """True for a placeholder or mutable identity, not an installed clean revision."""
    if not is_captured_axis(version):
        return False
    assert version is not None
    marker = version.strip()
    if marker in _FALLBACK_HARNESS_VERSIONS:
        return True
    if marker.endswith("-dirty"):
        # A dirty worktree's executed bytes are not identified by the stamped
        # revision (in-checkout dependencies can differ); dirty checkouts are
        # diagnostic-only, never native/live proof.
        return True
    return marker.endswith("-smoke") and "native" in marker


def is_captured_harness_version(version: str | None) -> bool:
    """True when harness_version is a nonempty, source-owned revision (not fallback)."""
    if not is_captured_axis(version):
        return False
    return not is_uncaptured_harness_version(version)
