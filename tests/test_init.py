from __future__ import annotations

from bencheval.init import load_manifest
from bencheval.manifest import load_manifest as load_manifest_direct


def test_init_reexports_load_manifest() -> None:
    assert load_manifest is load_manifest_direct
