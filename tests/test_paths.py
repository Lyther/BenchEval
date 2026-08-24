"""Config root resolution for wheel-only installs."""

from __future__ import annotations

from pathlib import Path

import pytest

from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root, validate_config_bundle

# SUBSTITUTE_JUSTIFICATION
# - substitute: monkeypatched cwd/BENCHEVAL_HOME/importlib.resources and disposable config
#   trees in test_repo_root_from_bencheval_home, test_repo_root_walks_up_from_cwd,
#   test_repo_root_cwd_marker_without_bundle_raises,
#   test_repo_root_invalid_bencheval_home_raises,
#   test_validate_config_bundle_rejects_missing_models,
#   test_validate_config_bundle_rejects_missing_bfcl_supported_models,
#   test_bundled_config_root_resolves_packaged_config, and
#   test_bundled_config_root_absent_returns_none
# - replaces: process-global discovery state and installed package-resource layouts
# - necessity: mutually exclusive discovery states require isolated deterministic roots
# - real-option: mutating the operator installation is unsafe and non-isolated
# - proof-limit: proves local path/config discovery only, not wheel installation
# - real-proof: tests/test_wheel_bundle.py exercises the built wheel in a subprocess


def _write_minimal_bundle(root: Path) -> None:
    (root / "config" / "runtimes").mkdir(parents=True)
    (root / "config" / "providers").mkdir(parents=True)
    (root / "config" / "slices").mkdir(parents=True)
    (root / "config" / "benchmarks.yaml").write_text("benchmarks: []\n", encoding="utf-8")
    (root / "config" / "models.yaml").write_text("models: []\n", encoding="utf-8")
    (root / "config" / "bfcl-v4-supported-models.yaml").write_text(
        "schema_version: '0.1'\nupstream_commit: test\nbfcl_eval_version: test\nmodels: [test]\n",
        encoding="utf-8",
    )
    (root / "config" / "runtimes" / "claude-code.yaml").write_text(
        "schema_version: '0.1'\nruntime:\n  id: claude-code\n  kind: cli_agent\n",
        encoding="utf-8",
    )
    (root / "config" / "providers" / "bytellm.yaml").write_text(
        "schema_version: '0.1'\nprovider:\n  id: bytellm\n  display_name: ByteLLM\n"
        "  kind: openai_compatible\n  base_url_env: BYTELLM_BASE_URL\n"
        "  default_base_url: http://127.0.0.1:4000\n",
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


def test_validate_config_bundle_rejects_missing_models(tmp_path: Path) -> None:
    bundle = tmp_path / "no-models"
    _write_minimal_bundle(bundle)
    (bundle / "config" / "models.yaml").unlink()
    with pytest.raises(BenchEvalError, match=r"models[.]yaml"):
        validate_config_bundle(bundle)


def test_validate_config_bundle_rejects_missing_bfcl_supported_models(tmp_path: Path) -> None:
    bundle = tmp_path / "no-bfcl-models"
    _write_minimal_bundle(bundle)
    (bundle / "config" / "bfcl-v4-supported-models.yaml").unlink()
    with pytest.raises(BenchEvalError, match=r"bfcl-v4-supported-models[.]yaml"):
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
