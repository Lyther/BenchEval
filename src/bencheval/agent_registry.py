"""Agent registry loader for ``config/agents/*.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root as _repo_root

_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


class AgentInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_ID_PATTERN)
    display_name: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    home_env: str = Field(min_length=1)
    default_relative_home: str = Field(min_length=1)
    command: tuple[str, ...] = Field(min_length=1)
    version_command: tuple[str, ...] = Field(min_length=1)
    supported_harnesses: tuple[str, ...] = Field(min_length=1)
    notes: str | None = None


class AgentProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(min_length=1)
    agent: AgentInfo
    admission: str = "draft"

    @property
    def id(self) -> str:
        return self.agent.id


class AgentCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = "0.1"
    agents: tuple[AgentProfile, ...] = Field(min_length=1)

    def by_id(self, agent_id: str) -> AgentProfile:
        for profile in self.agents:
            if profile.agent.id == agent_id:
                return profile
        raise KeyError(f"agent not found: {agent_id}")


def default_agents_dir() -> Path:
    return _repo_root() / "config" / "agents"


def load_agent_profile(path: Path | str) -> AgentProfile:
    p = Path(path).resolve()
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as e:
        raise BenchEvalError(f"cannot load agent profile {p}: {e}") from e
    if not isinstance(raw, dict):
        raise BenchEvalError(f"{p.name}: agent profile must be a YAML mapping")
    try:
        return AgentProfile.model_validate(raw)
    except ValidationError as e:
        raise BenchEvalError(f"{p.name}: {e}") from e


@lru_cache(maxsize=4)
def _load_agent_catalog_cached(dir_path_str: str) -> AgentCatalog:
    d = Path(dir_path_str)
    if not d.is_dir():
        raise BenchEvalError(f"agent profiles directory not found: {d}")
    profiles: list[AgentProfile] = []
    seen: dict[str, str] = {}
    for entry in sorted(d.iterdir()):
        if not entry.is_file() or entry.suffix.lower() not in (".yaml", ".yml"):
            continue
        profile = load_agent_profile(entry)
        aid = profile.agent.id
        if aid in seen:
            raise BenchEvalError(f"duplicate agent id {aid!r}: {seen[aid]} and {entry.name}")
        seen[aid] = entry.name
        profiles.append(profile)
    if not profiles:
        raise BenchEvalError(f"no agent profiles found under {d}")
    return AgentCatalog(agents=tuple(profiles))


def clear_agent_catalog_cache() -> None:
    _load_agent_catalog_cached.cache_clear()


def load_agent_catalog(dir_path: Path | str | None = None) -> AgentCatalog:
    d = Path(dir_path) if dir_path is not None else default_agents_dir()
    return _load_agent_catalog_cached(str(d.resolve()))


__all__ = [
    "AgentCatalog",
    "AgentProfile",
    "default_agents_dir",
    "load_agent_catalog",
    "load_agent_profile",
]
