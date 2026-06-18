from __future__ import annotations

from pathlib import Path

from bencheval.lifecycle import cleanup_transient_artifacts


def test_cleanup_never_leaves_transient_dirs(tmp_path: Path) -> None:
    agent = tmp_path / "agent-workspace"
    agent.mkdir()
    report = cleanup_transient_artifacts(tmp_path, policy="never", primary_pass=True)
    assert report.attempted is False
    assert report.removed_paths == ()
    assert agent.is_dir()


def test_cleanup_on_success_skips_failed_run(tmp_path: Path) -> None:
    agent = tmp_path / "agent-workspace"
    agent.mkdir()
    report = cleanup_transient_artifacts(tmp_path, policy="on-success", primary_pass=False)
    assert report.attempted is False
    assert report.removed_paths == ()
    assert agent.is_dir()


def test_cleanup_always_removes_only_known_transient_dirs(tmp_path: Path) -> None:
    agent = tmp_path / "agent-workspace"
    harbor = tmp_path / "harbor-package"
    verifier = tmp_path / "verifier.json"
    unrelated = tmp_path / "debug"
    agent.mkdir()
    harbor.mkdir()
    unrelated.mkdir()
    verifier.write_text("{}", encoding="utf-8")

    report = cleanup_transient_artifacts(tmp_path, policy="always", primary_pass=False)

    assert report.attempted is True
    assert len(report.removed_paths) == 2
    assert not agent.exists()
    assert not harbor.exists()
    assert verifier.is_file()
    assert unrelated.is_dir()


def test_cleanup_unlinks_transient_symlink_without_touching_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "agent-workspace"
    link.symlink_to(outside, target_is_directory=True)

    report = cleanup_transient_artifacts(tmp_path, policy="always", primary_pass=False)

    assert report.attempted is True
    assert report.removed_paths == (str(link.resolve(strict=False)),)
    assert not link.exists()
    assert outside.is_dir()
