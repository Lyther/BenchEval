from __future__ import annotations


def test_init_reexports_load_manifest() -> None:
    from bencheval.init import load_manifest
    from bencheval.manifest import load_manifest as load_manifest_direct

    assert load_manifest is load_manifest_direct
