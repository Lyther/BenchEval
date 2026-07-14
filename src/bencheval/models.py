from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ModelFamily(StrEnum):
    ANTHROPIC = "anthropic"
    BYTEDANCE = "bytedance"
    GOOGLE = "google"
    MINIMAX = "minimax"
    MISTRAL = "mistral"
    OPENAI = "openai"
    MOONSHOT = "moonshot"
    QWEN = "qwen"
    XAI = "xai"
    ZHIPU = "zhipu"
    LOCAL = "local"


class ManifestDigest(BaseModel):
    """Committed task manifest + cryptographic digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark: str
    manifest_path: str
    content_sha256: str = Field(min_length=64, max_length=64)
    task_ids: tuple[str, ...] = Field(min_length=1)
