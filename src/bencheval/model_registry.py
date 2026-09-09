"""Model registry loader for ``config/models.yaml`` (non-secret metadata only)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bencheval.exceptions import BenchEvalError
from bencheval.models import ModelFamily
from bencheval.paths import repo_root as _repo_root

BfclBindingMode = Literal["upstream", "configured"]
# The only handler key CF1 maps (in code) to the pinned BFCL
# ``OpenAICompletionsHandler`` with ``is_fc_model=True``. YAML never names Python.
BfclHandlerKey = Literal["openai_completions_fc"]


class BfclBackendBinding(BaseModel):
    """How a logical model reaches the pinned BFCL ``MODEL_CONFIG_MAPPING``.

    ``upstream`` reuses an existing pinned key (``registry_id``, default the
    logical id). ``configured`` generates one registration in a run-owned copy
    and must state its handler key and normalization flag explicitly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: BfclBindingMode
    registry_id: str | None = Field(default=None, min_length=1)
    handler: BfclHandlerKey | None = None
    underscore_to_dot: bool | None = None

    @model_validator(mode="after")
    def _mode_fields(self) -> Self:
        if self.mode == "configured":
            if self.handler is None:
                raise ValueError("configured bfcl binding requires an explicit handler key")
            if self.underscore_to_dot is None:
                raise ValueError("configured bfcl binding requires explicit underscore_to_dot")
        elif self.handler is not None or self.underscore_to_dot is not None:
            raise ValueError(
                "upstream bfcl binding reuses the pinned registration; "
                "handler and underscore_to_dot are not configurable",
            )
        return self


class BackendBindings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bfcl: BfclBackendBinding | None = None


class ModelRegistryEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    family: ModelFamily
    display_name: str = Field(min_length=1)
    provider_route: str | None = None
    context_limit_tokens: int | None = Field(default=None, ge=1)
    # Exact vendor API model name. Absent on legacy rows, whose adapters keep
    # sending the logical id verbatim (no suffix-stripping heuristics).
    api_model: str | None = Field(default=None, min_length=1)
    backend_bindings: BackendBindings | None = None
    # Descriptive provenance retained in a configured BFCL registration; when
    # absent the registration names the provider endpoint and marks
    # organization/license unknown rather than inventing them.
    reference_url: str | None = Field(default=None, min_length=1)
    organization: str | None = Field(default=None, min_length=1)
    license: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _configured_requires_api_model(self) -> Self:
        bfcl = self.backend_bindings.bfcl if self.backend_bindings is not None else None
        if bfcl is not None and bfcl.mode == "configured" and self.api_model is None:
            raise ValueError(
                f"model {self.id!r}: a configured bfcl binding requires an explicit api_model",
            )
        return self


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
    "BackendBindings",
    "BfclBackendBinding",
    "BfclBindingMode",
    "BfclHandlerKey",
    "ModelRegistry",
    "ModelRegistryEntry",
    "default_models_path",
    "load_model_registry",
]
