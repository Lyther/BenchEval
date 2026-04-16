from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bencheval import BenchEvalError, load_pricing
from bencheval.models import ModelFamily
from bencheval.pricing import ModelPrice, PricingSheet

REPO_ROOT = Path(__file__).resolve().parents[1]
PRICING = REPO_ROOT / "config" / "pricing" / "2026-04-15.yaml"


def test_load_committed_yaml_version_and_providers() -> None:
    sheet = load_pricing(PRICING)
    assert isinstance(sheet, PricingSheet)
    assert sheet.version == "2026-04-15"
    assert {"anthropic", "openai", "moonshot"}.issubset(sheet.providers.keys())


def test_lookup_anthropic_claude_sonnet_prices() -> None:
    sheet = load_pricing(PRICING)
    mp = sheet.lookup("anthropic", "claude-sonnet-4-5")
    assert isinstance(mp, ModelPrice)
    assert mp.input_usd_per_mtok == Decimal("3.0")
    assert mp.output_usd_per_mtok == Decimal("15.0")


def test_lookup_accepts_model_family_enum() -> None:
    sheet = load_pricing(PRICING)
    a = sheet.lookup(ModelFamily.OPENAI, "gpt-4o")
    b = sheet.lookup("openai", "gpt-4o")
    assert a is not None and b is not None
    assert a == b


def test_lookup_unknown_family_returns_none() -> None:
    sheet = load_pricing(PRICING)
    assert sheet.lookup("unknown_provider", "gpt-4o") is None


def test_lookup_unknown_model_id_returns_none() -> None:
    sheet = load_pricing(PRICING)
    assert sheet.lookup("anthropic", "no-such-model") is None


def test_estimate_anthropic_exact_decimal() -> None:
    sheet = load_pricing(PRICING)
    got = sheet.estimate("anthropic", "claude-sonnet-4-5", 1_000_000, 500_000)
    assert got == Decimal("10.5")


def test_estimate_zero_tokens_returns_zero_decimal() -> None:
    sheet = load_pricing(PRICING)
    got = sheet.estimate("anthropic", "claude-sonnet-4-5", 0, 0)
    assert got == Decimal("0")


def test_estimate_moonshot_null_prices_returns_none() -> None:
    sheet = load_pricing(PRICING)
    assert sheet.estimate("moonshot", "kimi-k2-0711-preview", 1000, 1000) is None


def test_missing_file_raises_bench_eval_error(tmp_path: Path) -> None:
    with pytest.raises(BenchEvalError, match="pricing: cannot read"):
        load_pricing(tmp_path / "nope.yaml")


def test_malformed_providers_shape_raises_bench_eval_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("version: '2026-04-15'\nproviders: not-a-dict\n", encoding="utf-8")
    with pytest.raises(BenchEvalError, match="providers must be a mapping"):
        load_pricing(p)


def test_unknown_top_level_key_raises_bench_eval_error(tmp_path: Path) -> None:
    p = tmp_path / "extra.yaml"
    p.write_text(
        "version: '2026-04-15'\nproviders:\n  anthropic:\n    models: []\nextra: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(BenchEvalError, match="unknown top-level"):
        load_pricing(p)


def test_invalid_version_string_raises_bench_eval_error(tmp_path: Path) -> None:
    p = tmp_path / "rolling.yaml"
    p.write_text(
        "version: 'rolling'\nproviders:\n  anthropic:\n    models: []\n",
        encoding="utf-8",
    )
    with pytest.raises(BenchEvalError, match="invalid pricing sheet"):
        load_pricing(p)


def test_estimate_negative_tokens_raises_value_error() -> None:
    sheet = load_pricing(PRICING)
    with pytest.raises(ValueError, match="non-negative"):
        sheet.estimate("anthropic", "claude-sonnet-4-5", -1, 0)
