"""Config root resolution for wheel-only installs."""

from __future__ import annotations

from pathlib import Path

import pytest

from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root, validate_config_bundle


def _write_minimal_bundle(root: Path) -> None:
    (root / "config" / "runtimes").mkdir(parents=True)
    (root / "config" / "slices").mkdir(parents=True)
    (root / "config" / "manifests").mkdir(parents=True)
    (root / "config" / "benchmarks.yaml").write_text("benchmarks: []\n", encoding="utf-8")
    (root / "config" / "runtimes" / "native-api.yaml").write_text(
        "schema_version: '0.1'\nruntime:\n  id: native-api\n  kind: api_client\n",
        encoding="utf-8",
    )
    (root / "config" / "slices" / "smoke.yaml").write_text(
        "schema_version: '0.1'\nslice:\n  id: smoke\n  benchmark_id: bfcl-v4\n",
        encoding="utf-8",
    )


def test_repo_root_from_bencheval_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bundle = tmp_path / "bundle"
    _write_minimal_bundle(bundle)
    nowhere = tmp_path / "nowhere"
    nowhere.mkdir()
    monkeypatch.chdir(nowhere)
    monkeypatch.setenv("BENCHEVAL_HOME", str(bundle))
    assert repo_root() == bundle.resolve()


def test_repo_root_walks_up_from_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "project"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    _write_minimal_bundle(root)
    monkeypatch.delenv("BENCHEVAL_HOME", raising=False)
    monkeypatch.chdir(nested)
    assert repo_root() == root.resolve()


def test_repo_root_cwd_marker_without_bundle_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "thin"
    nested = root / "sub"
    nested.mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config" / "benchmarks.yaml").write_text("benchmarks: []\n", encoding="utf-8")
    monkeypatch.delenv("BENCHEVAL_HOME", raising=False)
    monkeypatch.chdir(nested)
    with pytest.raises(BenchEvalError, match="missing required directory"):
        repo_root()


def test_validate_config_bundle_rejects_benchmarks_only(tmp_path: Path) -> None:
    bundle = tmp_path / "thin"
    (bundle / "config").mkdir(parents=True)
    (bundle / "config" / "benchmarks.yaml").write_text("benchmarks: []\n", encoding="utf-8")
    with pytest.raises(BenchEvalError, match="missing required directory"):
        validate_config_bundle(bundle)


def test_validate_config_bundle_rejects_empty_runtimes(tmp_path: Path) -> None:
    bundle = tmp_path / "noruntime"
    _write_minimal_bundle(bundle)
    for f in (bundle / "config" / "runtimes").glob("*.yaml"):
        f.unlink()
    with pytest.raises(BenchEvalError, match="runtime profile"):
        validate_config_bundle(bundle)


def test_validate_config_bundle_rejects_empty_slices(tmp_path: Path) -> None:
    bundle = tmp_path / "noslices"
    _write_minimal_bundle(bundle)
    for f in (bundle / "config" / "slices").glob("*.yaml"):
        f.unlink()
    with pytest.raises(BenchEvalError, match="slice manifest"):
        validate_config_bundle(bundle)


def test_repo_root_invalid_bencheval_home_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bad = tmp_path / "empty"
    bad.mkdir()
    monkeypatch.setenv("BENCHEVAL_HOME", str(bad))
    with pytest.raises(BenchEvalError, match="missing marker"):
        repo_root()


def test_bundled_config_root_resolves_packaged_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F003: config packaged inside the wheel (``bencheval/_bundled``) is discoverable
    via importlib.resources with no checkout and no BENCHEVAL_HOME."""
    import importlib.resources

    from bencheval import paths

    pkg_dir = tmp_path / "site" / "bencheval"
    _write_minimal_bundle(pkg_dir / "_bundled")
    monkeypatch.setattr(importlib.resources, "files", lambda pkg: pkg_dir)
    assert paths._bundled_config_root() == (pkg_dir / "_bundled").resolve()


def test_bundled_config_root_absent_returns_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib.resources

    from bencheval import paths

    pkg_dir = tmp_path / "site" / "bencheval"
    pkg_dir.mkdir(parents=True)  # no _bundled subtree
    monkeypatch.setattr(importlib.resources, "files", lambda pkg: pkg_dir)
    assert paths._bundled_config_root() is None
