"""Typed loader for config/pricing/*.yaml; not a CLI."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bencheval.exceptions import BenchEvalError
from bencheval.models import ModelFamily


class ModelPrice(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    input_usd_per_mtok: Decimal | None
    output_usd_per_mtok: Decimal | None


class PricingSheet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    providers: dict[str, list[ModelPrice]]

    def lookup(self, family: str | ModelFamily, model_id: str) -> ModelPrice | None:
        key = str(family)
        rows = self.providers.get(key)
        if rows is None:
            return None
        for mp in rows:
            if mp.id == model_id:
                return mp
        return None

    def estimate(
        self,
        family: str | ModelFamily,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Decimal | None:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        mp = self.lookup(family, model_id)
        if mp is None:
            return None
        if mp.input_usd_per_mtok is None or mp.output_usd_per_mtok is None:
            return None
        mtok = Decimal(1_000_000)
        return (
            Decimal(input_tokens) * mp.input_usd_per_mtok / mtok
            + Decimal(output_tokens) * mp.output_usd_per_mtok / mtok
        )


def _flatten_providers(raw: dict[str, object]) -> dict[str, list[ModelPrice]]:
    out: dict[str, list[ModelPrice]] = {}
    for family, blob in raw.items():
        if not isinstance(blob, dict) or "models" not in blob:
            raise BenchEvalError(
                f"pricing: provider {family!r} must be a mapping with a 'models' list",
            )
        models_raw = blob["models"]
        if not isinstance(models_raw, list):
            raise BenchEvalError(f"pricing: provider {family!r} 'models' must be a list")
        models: list[ModelPrice] = []
        for m in models_raw:
            try:
                models.append(ModelPrice.model_validate(m))
            except ValidationError as e:
                raise BenchEvalError(f"pricing: invalid model entry: {e}") from e
        out[family] = models
    return out


def _coerce_version_str(value: object) -> str:
    if isinstance(value, str):
        return value
    raise BenchEvalError("pricing: version must be a string (YYYY-MM-DD)")


def load_pricing(path: Path | str) -> PricingSheet:
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise BenchEvalError(f"pricing: cannot read {p}: {e}") from e
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise BenchEvalError(f"pricing: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise BenchEvalError("pricing: pricing YAML must be a mapping at top level")
    extra = set(data.keys()) - {"version", "providers"}
    if extra:
        raise BenchEvalError(f"pricing: unknown top-level keys: {sorted(extra)}")
    if "version" not in data or "providers" not in data:
        raise BenchEvalError("pricing: pricing YAML must contain version and providers")
    version_raw = data["version"]
    version = _coerce_version_str(version_raw)
    providers_raw = data["providers"]
    if not isinstance(providers_raw, dict):
        raise BenchEvalError("pricing: providers must be a mapping")
    flat = _flatten_providers(providers_raw)
    try:
        return PricingSheet(version=version, providers=flat)
    except ValidationError as e:
        raise BenchEvalError(f"pricing: invalid pricing sheet: {e}") from e
