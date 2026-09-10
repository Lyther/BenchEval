"""Pure actor (runtime / native agent) binding DTO, digest, and resolvers
(architecture §23.6, roadmap CF2).

An actor binding names *which* Harbor-native implementation a plan launches
and with which declared, non-secret configuration. It returns data only: no
Harbor import, subprocess, credential, or scoring rule lives here.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bencheval.model_binding import canonical_sha256

if TYPE_CHECKING:
    from bencheval.agent_registry import AgentProfile
    from bencheval.domain import RuntimeProfile

ACTOR_BINDING_SCHEMA = "actor-binding-v1"
ActorKind = Literal["runtime", "agent"]
KwargValue = str | int | float | bool

_IMPORT_PATH = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
)
_KWARG_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# A kwarg *word* (underscore-separated) that names a credential; counts such as
# ``max_thinking_tokens`` are ordinary settings and stay allowed.
_CREDENTIAL_WORDS = frozenset(
    {
        "key",
        "apikey",
        "token",
        "secret",
        "password",
        "passwd",
        "credential",
        "credentials",
        "auth",
        "authorization",
        "bearer",
    }
)
# Model/provider routing and launch lifecycle parameters are owned by the
# confirmed model binding and the adapter; profile kwargs cannot override them.
RESERVED_NATIVE_KWARGS: frozenset[str] = frozenset(
    {
        "model_name",
        "api_base",
        "logs_dir",
        "extra_env",
        "llm_backend",
        "llm_kwargs",
        "llm_call_kwargs",
        "model_info",
        "mcp_servers",
        "skills_dir",
        "logger",
        "version",
    }
)


def validate_native_kwargs(kwargs: Mapping[str, object]) -> None:
    """Reject credential-like, reserved, malformed, or non-finite native kwargs."""
    for key, value in kwargs.items():
        if not _KWARG_KEY.match(key):
            raise ValueError(f"kwarg name {key!r} is not a plain identifier")
        if key in RESERVED_NATIVE_KWARGS:
            raise ValueError(
                f"kwarg {key!r} is reserved for the confirmed model binding and launch; "
                "it cannot be set from a profile",
            )
        if any(word in _CREDENTIAL_WORDS for word in key.split("_")):
            raise ValueError(f"kwarg {key!r} names a credential; use the launch environment")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"kwarg {key!r} must be a finite number")
        if isinstance(value, str) and (
            not value or value != value.strip() or any(ord(c) < 32 for c in value)
        ):
            raise ValueError(
                f"kwarg {key!r} must be a non-empty single-line string "
                "without surrounding whitespace"
            )


class ActorBinding(BaseModel):
    """Frozen, non-secret launch identity of one runtime or native agent profile."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["actor-binding-v1"] = ACTOR_BINDING_SCHEMA
    actor_kind: ActorKind
    actor_id: str = Field(min_length=1)
    # Exactly one selector: an upstream Harbor agent name or an operator-installed
    # ``module.path:ClassName`` implementing Harbor's existing interface.
    harbor_agent: str | None = None
    import_path: str | None = None
    install_recipe: str | None = None
    agent_version_pin: str | None = None
    setup_timeout_multiplier: int | None = Field(default=None, ge=1, le=64)
    kwargs: dict[str, KwargValue] = Field(default_factory=dict)
    # Declared version/source identity of the implementation (e.g. the pinned
    # Harbor distribution that ships the built-in agent).
    source: str | None = None
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _well_formed(self) -> ActorBinding:
        if (self.harbor_agent is None) == (self.import_path is None):
            raise ValueError("exactly one of harbor_agent or import_path must be set")
        if self.import_path is not None and not _IMPORT_PATH.match(self.import_path):
            raise ValueError(f"import_path {self.import_path!r} is not module.path:ClassName")
        validate_native_kwargs(self.kwargs)
        if self.sha256 != actor_binding_sha256(self):
            raise ValueError("actor binding sha256 does not match its content")
        return self


def actor_binding_sha256(binding: ActorBinding) -> str:
    """Canonical digest (:func:`bencheval.model_binding.canonical_sha256`) over present fields."""
    return canonical_sha256(binding.model_dump(mode="json", exclude={"sha256"}, exclude_none=True))


def build_actor_binding(**fields: object) -> ActorBinding:
    """Construct a digest-bound binding from plain fields (the resolvers' only exit)."""
    draft = ActorBinding.model_construct(
        schema_version=ACTOR_BINDING_SCHEMA, sha256="sha256:" + "0" * 64, **fields
    )
    return ActorBinding(**fields, sha256=actor_binding_sha256(draft))


def actor_binding_for_runtime(profile: RuntimeProfile) -> ActorBinding:
    """Resolve a runtime profile's closed Harbor driver binding into an actor binding."""
    from bencheval.exceptions import BenchEvalError

    harbor = profile.launch.harbor
    if harbor is None:
        raise BenchEvalError(
            f"runtime {profile.runtime.id!r} declares no launch.harbor binding; "
            "a runtime without a native driver binding cannot launch under Harbor",
        )
    return build_actor_binding(
        actor_kind="runtime",
        actor_id=profile.runtime.id,
        harbor_agent=harbor.agent,
        install_recipe=harbor.install_recipe,
        agent_version_pin=profile.versioning.agent_version_pin,
        setup_timeout_multiplier=harbor.setup_timeout_multiplier,
    )


def actor_binding_for_agent(profile: AgentProfile) -> ActorBinding:
    """Resolve a ``kind: harbor`` agent profile into an actor binding."""
    from bencheval.exceptions import BenchEvalError

    info = profile.agent
    if info.kind != "harbor":
        raise BenchEvalError(
            f"agent {info.id!r} is a legacy {info.kind!r} scaffold with no native binding",
        )
    return build_actor_binding(
        actor_kind="agent",
        actor_id=info.id,
        harbor_agent=info.harbor_agent,
        import_path=info.harbor_import_path,
        agent_version_pin=info.version_pin,
        kwargs=dict(info.kwargs),
        source=info.source,
    )


__all__ = [
    "ACTOR_BINDING_SCHEMA",
    "RESERVED_NATIVE_KWARGS",
    "ActorBinding",
    "ActorKind",
    "KwargValue",
    "actor_binding_for_agent",
    "actor_binding_for_runtime",
    "actor_binding_sha256",
    "build_actor_binding",
    "validate_native_kwargs",
]
