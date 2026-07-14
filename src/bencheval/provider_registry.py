"""Provider registry loader for ``config/providers/*.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root as _repo_root

_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class ProviderInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_ID_PATTERN)
    display_name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    base_url_env: str = Field(min_length=1)
    default_base_url: str = Field(min_length=1)
    api_key_env: str = Field(min_length=1)
    notes: str | None = None


class ProviderProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(min_length=1)
    provider: ProviderInfo
    admission: str = "draft"

    @property
    def id(self) -> str:
        return self.provider.id


class ProviderCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "0.1"
    providers: tuple[ProviderProfile, ...] = Field(min_length=1)

    def by_id(self, provider_id: str) -> ProviderProfile:
        for profile in self.providers:
            if profile.provider.id == provider_id:
                return profile
        raise KeyError(f"provider not found: {provider_id}")


def default_providers_dir() -> Path:
    return _repo_root() / "config" / "providers"


def load_provider_profile(path: Path | str) -> ProviderProfile:
    p = Path(path).resolve()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise BenchEvalError(f"cannot load provider profile {p}: {e}") from e
    if not isinstance(raw, dict):
        raise BenchEvalError(f"{p.name}: provider profile must be a YAML mapping")
    try:
        return ProviderProfile.model_validate(raw)
    except ValidationError as e:
        raise BenchEvalError(f"{p.name}: {e}") from e


@lru_cache(maxsize=4)
def _load_provider_catalog_cached(dir_path_str: str) -> ProviderCatalog:
    d = Path(dir_path_str)
    if not d.is_dir():
        raise BenchEvalError(f"provider profiles directory not found: {d}")
    profiles: list[ProviderProfile] = []
    seen: dict[str, str] = {}
    for entry in sorted(d.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in (".yaml", ".yml"):
            continue
        profile = load_provider_profile(entry)
        pid = profile.provider.id
        if pid in seen:
            raise BenchEvalError(f"duplicate provider id {pid!r}: {seen[pid]} and {entry.name}")
        seen[pid] = entry.name
        profiles.append(profile)
    if not profiles:
        raise BenchEvalError(f"no provider profiles found under {d}")
    return ProviderCatalog(providers=tuple(profiles))


def clear_provider_catalog_cache() -> None:
    _load_provider_catalog_cached.cache_clear()


def load_provider_catalog(dir_path: Path | str | None = None) -> ProviderCatalog:
    d = Path(dir_path) if dir_path is not None else default_providers_dir()
    return _load_provider_catalog_cached(str(d.resolve()))


DEFAULT_PROVIDER_ID = "bytellm"

__all__ = [
    "DEFAULT_PROVIDER_ID",
    "ProviderCatalog",
    "ProviderProfile",
    "default_providers_dir",
    "load_provider_catalog",
    "load_provider_profile",
]
