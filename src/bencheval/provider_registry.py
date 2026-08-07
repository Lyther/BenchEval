"""Provider registry loader for ``config/providers/*.yaml``."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root as _repo_root

_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


@dataclass(frozen=True, slots=True)
class OpenAICompatibleLaunch:
    """Resolved child-process contract for an OpenAI-compatible provider."""

    provider_id: str
    base_url: str
    config_hash: str
    environment: dict[str, str] = field(repr=False, compare=False)


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


def _normalize_openai_base_url(raw: str, *, env_name: str) -> str:
    value = raw.strip()
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise BenchEvalError(
            f"{env_name} must be an http(s) base URL without userinfo, query, or fragment",
        )
    path = parsed.path.rstrip("/")
    if not path.endswith("/v1"):
        path = f"{path}/v1"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def resolve_openai_compatible_launch(
    provider_id: str,
    *,
    environ: Mapping[str, str] | None = None,
    require_api_key: bool = True,
) -> OpenAICompatibleLaunch:
    """Bind a provider profile to the exact environment used by OpenAI clients."""

    try:
        profile = load_provider_catalog().by_id(provider_id)
    except KeyError as e:
        raise BenchEvalError(f"unknown provider {provider_id!r}") from e
    provider = profile.provider
    if provider.kind != "openai_compatible":
        raise BenchEvalError(
            f"provider {provider_id!r} kind {provider.kind!r} is not OpenAI-compatible",
        )

    source = os.environ if environ is None else environ
    api_key = source.get(provider.api_key_env, "")
    if require_api_key and not api_key.strip():
        raise BenchEvalError(
            f"missing provider credential env {provider.api_key_env!r} for {provider_id!r}",
        )
    base_url = _normalize_openai_base_url(
        source.get(provider.base_url_env, provider.default_base_url),
        env_name=provider.base_url_env,
    )
    child_env = dict(source)
    if api_key:
        child_env["OPENAI_API_KEY"] = api_key
    child_env["OPENAI_BASE_URL"] = base_url
    config_payload = {
        "provider_id": provider_id,
        "provider_kind": provider.kind,
        "base_url": base_url,
        "api_key_env": provider.api_key_env,
    }
    config_hash = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(config_payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        ).hexdigest()
    )
    return OpenAICompatibleLaunch(
        provider_id=provider_id,
        base_url=base_url,
        config_hash=config_hash,
        environment=child_env,
    )


DEFAULT_PROVIDER_ID = "bytellm"

__all__ = [
    "DEFAULT_PROVIDER_ID",
    "OpenAICompatibleLaunch",
    "ProviderCatalog",
    "ProviderProfile",
    "default_providers_dir",
    "load_provider_catalog",
    "load_provider_profile",
    "resolve_openai_compatible_launch",
]
