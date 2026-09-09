"""Agent registry loader for ``config/agents/*.yaml``."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bencheval.actor_binding import validate_native_kwargs
from bencheval.exceptions import BenchEvalError
from bencheval.paths import repo_root as _repo_root

_ID_PATTERN = r"^[a-z0-9][a-z0-9-]*$"
AgentAdmission = Literal["scaffold", "draft", "admitted"]


_IMPORT_PATH_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
AgentKwargValue = str | int | float | bool


class ExternalCliAgentInfo(BaseModel):
    """Legacy non-authoritative external CLI scaffold (never scored)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_ID_PATTERN)
    display_name: str = Field(min_length=1)
    kind: Literal["external_cli"]
    home_env: str = Field(min_length=1)
    default_relative_home: str = Field(min_length=1)
    command: tuple[str, ...] = Field(min_length=1)
    version_command: tuple[str, ...] = Field(min_length=1)
    supported_harnesses: tuple[str, ...] = Field(min_length=1)
    notes: str | None = None


class HarborAgentInfo(BaseModel):
    """Native Harbor agent binding (architecture §23.6): exactly one selector.

    ``harbor_agent`` is an upstream agent name; ``harbor_import_path`` is an
    operator-installed ``module.path:ClassName`` implementing Harbor's existing
    ``BaseAgent`` interface. ``kwargs`` are typed, non-secret native kwargs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=_ID_PATTERN)
    display_name: str = Field(min_length=1)
    kind: Literal["harbor"]
    harbor_agent: str | None = Field(default=None, pattern=_ID_PATTERN)
    harbor_import_path: str | None = Field(default=None, pattern=_IMPORT_PATH_PATTERN)
    # Typed, non-secret native kwargs (Harbor ``--agent-kwarg``); routing and
    # credential parameters are refused (``actor_binding.validate_native_kwargs``).
    kwargs: dict[str, AgentKwargValue] = Field(default_factory=dict)
    # Implementation version expected back in the trial result's ``agent_info``.
    version_pin: str = Field(min_length=1)
    # Declared version/source identity of the implementation.
    source: str = Field(min_length=1)
    supported_harnesses: tuple[str, ...] = Field(min_length=1)
    notes: str | None = None

    @model_validator(mode="after")
    def _one_selector(self) -> HarborAgentInfo:
        if (self.harbor_agent is None) == (self.harbor_import_path is None):
            raise ValueError("exactly one of harbor_agent or harbor_import_path must be set")
        validate_native_kwargs(self.kwargs)
        return self


AgentInfo = Annotated[ExternalCliAgentInfo | HarborAgentInfo, Field(discriminator="kind")]


class AgentProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str = Field(min_length=1)
    agent: AgentInfo
    admission: AgentAdmission = "draft"

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


def resolve_launchable_agent(
    agent_id: str, *, catalog: AgentCatalog | None = None, diagnostic: bool = False
) -> AgentProfile:
    """Admission gate shared by planner, executor, CLI, and console.

    Admitted profiles launch. A *draft* native (``kind: harbor``) profile is a
    known wired candidate and launches only as explicit diagnostic evidence.
    Scaffold profiles (legacy external CLI, MOMO) never launch.
    """
    agents = catalog if catalog is not None else load_agent_catalog()
    profile = agents.by_id(agent_id)
    if profile.admission == "admitted":
        return profile
    if profile.admission == "draft" and profile.agent.kind == "harbor":
        if diagnostic:
            return profile
        raise BenchEvalError(
            f"agent {profile.id!r} is a draft native profile; it runs only as explicit "
            "diagnostic evidence (pass --diagnostic) until its own official-score proof admits it",
        )
    raise BenchEvalError(
        f"agent {profile.id!r} is a {profile.admission} profile; "
        "only admitted agents can produce a plan or launch",
    )


def require_admitted_agent(agent_id: str, *, catalog: AgentCatalog | None = None) -> AgentProfile:
    """Return ``agent_id`` only when it is an admitted execution profile."""
    agents = catalog if catalog is not None else load_agent_catalog()
    profile = agents.by_id(agent_id)
    if profile.admission != "admitted":
        raise BenchEvalError(
            f"agent {profile.id!r} is a {profile.admission} profile; "
            "only admitted agents can produce a plan or launch",
        )
    return profile


__all__ = [
    "AgentAdmission",
    "AgentCatalog",
    "AgentInfo",
    "AgentProfile",
    "ExternalCliAgentInfo",
    "HarborAgentInfo",
    "default_agents_dir",
    "load_agent_catalog",
    "load_agent_profile",
    "require_admitted_agent",
    "resolve_launchable_agent",
]
