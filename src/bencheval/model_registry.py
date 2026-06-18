"""Model registry loader for ``config/models.yaml`` (non-secret metadata only)."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bencheval.exceptions import BenchEvalError
from bencheval.models import ModelFamily
from bencheval.paths import repo_root as _repo_root


class ModelRegistryEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    family: ModelFamily
    display_name: str = Field(min_length=1)
    provider_route: str | None = None
    context_limit_tokens: int | None = Field(default=None, ge=1)


class ModelRegistry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: int = Field(ge=1, default=1)
    models: tuple[ModelRegistryEntry, ...] = Field(default_factory=tuple)

    def by_id(self, model_id: str) -> ModelRegistryEntry:
        for entry in self.models:
            if entry.id == model_id:
                return entry
        raise KeyError(f"model not found: {model_id}")


def default_models_path() -> Path:
    return _repo_root() / "config" / "models.yaml"


def load_model_registry(path: Path | str | None = None) -> ModelRegistry:
    p = Path(path) if path is not None else default_models_path()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8-sig"))
    except OSError as e:
        raise BenchEvalError(f"cannot read model registry {p}: {e}") from e
    except yaml.YAMLError as e:
        raise BenchEvalError(f"{p.name}: invalid YAML: {e}") from e
    if raw is None:
        raw = {"models": []}
    if not isinstance(raw, dict):
        raise BenchEvalError(f"{p.name}: model registry must be a YAML mapping")
    try:
        return ModelRegistry.model_validate(raw)
    except ValidationError as e:
        raise BenchEvalError(f"{p.name}: {e}") from e


__all__ = [
    "ModelRegistry",
    "ModelRegistryEntry",
    "default_models_path",
    "load_model_registry",
]
