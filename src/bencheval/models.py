from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ModelFamily(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    MOONSHOT = "moonshot"
    LOCAL = "local"


class ManifestDigest(BaseModel):
    """Committed task manifest + cryptographic digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark: str
    manifest_path: str
    content_sha256: str = Field(min_length=64, max_length=64)
    task_ids: tuple[str, ...] = Field(min_length=1)
