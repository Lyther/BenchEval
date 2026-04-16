from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from bencheval.exceptions import ManifestError
from bencheval.manifest import load_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = REPO_ROOT / "config" / "manifests"
PRICING = REPO_ROOT / "config" / "pricing" / "2026-04-15.yaml"


def test_load_cybench_smoke_five() -> None:
    d = load_manifest(MANIFESTS / "cybench-smoke-5.txt")
    assert len(d.task_ids) == 5
    assert len(d.content_sha256) == 64
    assert int(d.content_sha256, 16) >= 0
    assert d.benchmark == "cybench-smoke-5"


def test_load_swebench_smoke_ten() -> None:
    d = load_manifest(MANIFESTS / "swebench-verified-smoke-10.txt")
    assert len(d.task_ids) == 10
    assert len(d.content_sha256) == 64
    assert d.benchmark == "swebench-verified-smoke-10"


def test_comments_and_blanks_ignored(tmp_path: Path) -> None:
    p = tmp_path / "m.txt"
    p.write_text(
        "\n# c\n  \nalpha\n# tail\nbravo\n",
        encoding="utf-8",
    )
    d = load_manifest(p)
    assert d.task_ids == ("alpha", "bravo")


def test_task_ids_sorted_lexicographically(tmp_path: Path) -> None:
    p = tmp_path / "m.txt"
    p.write_text("zebra\nalpha\nbeta\n", encoding="utf-8")
    d = load_manifest(p)
    assert d.task_ids == ("alpha", "beta", "zebra")


def test_hash_stable_under_reorder(tmp_path: Path) -> None:
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("charlie\nalpha\nbravo\n", encoding="utf-8")
    b.write_text("bravo\ncharlie\nalpha\n", encoding="utf-8")
    da = load_manifest(a)
    db = load_manifest(b)
    assert da.content_sha256 == db.content_sha256
    assert da.task_ids == db.task_ids


def test_empty_manifest_raises_manifest_error(tmp_path: Path) -> None:
    p = tmp_path / "empty.txt"
    p.write_text("# only\n\n", encoding="utf-8")
    with pytest.raises(ManifestError):
        load_manifest(p)


def test_missing_file_raises_manifest_error(tmp_path: Path) -> None:
    with pytest.raises(ManifestError):
        load_manifest(tmp_path / "nope.txt")


def test_pricing_scaffold_structure() -> None:
    text = PRICING.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["version"] == "2026-04-15"
    provs = data["providers"]
    assert {"anthropic", "openai", "moonshot"}.issubset(provs.keys())
    for key in ("anthropic", "openai", "moonshot"):
        assert "models" in provs[key]
        assert isinstance(provs[key]["models"], list)
        assert provs[key]["models"]
