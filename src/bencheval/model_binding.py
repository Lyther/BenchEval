"""Pure model/provider/native binding resolution (architecture §23.3, roadmap CF1.1).

This module returns data, never a client, subprocess, or credential: a binding
names the logical model ID, the exact vendor API model name, the provider route
and its protocol, the public endpoint identity, and (when declared) the BFCL
native registry binding. Provider credentials are resolved only at launch by
``provider_registry.resolve_openai_compatible_launch``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bencheval.model_registry import ModelRegistry
from bencheval.provider_registry import ProviderCatalog

MODEL_BINDING_SCHEMA = "model-binding-v1"
# CF1 supports exactly one transport protocol; a provider profile with any
# other ``kind`` is a typed compatibility error, not an invented SDK namespace.
SUPPORTED_PROVIDER_KINDS: frozenset[str] = frozenset({"openai_compatible"})
UNKNOWN_PROVENANCE = "unknown"

BfclBindingMode = Literal["upstream", "configured"]
BfclHandlerKey = Literal["openai_completions_fc"]


class ResolvedBfclBinding(BaseModel):
    """BFCL native registry binding after defaults are applied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: BfclBindingMode
    # Key in the pinned (or configured) ``MODEL_CONFIG_MAPPING``; defaults to the logical id.
    registry_id: str = Field(min_length=1)
    handler: BfclHandlerKey | None = None
    underscore_to_dot: bool | None = None
    # Descriptive provenance rendered into a configured registration (and thus
    # part of its digest and the effective harness identity), fixed at plan time.
    display_name: str | None = None
    reference_url: str | None = None
    organization: str | None = None
    license: str | None = None


class ModelBinding(BaseModel):
    """Frozen, non-secret launch contract for one logical model on one provider route."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["model-binding-v1"] = MODEL_BINDING_SCHEMA
    model_id: str = Field(min_length=1)
    api_model: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)
    provider_kind: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    bfcl: ResolvedBfclBinding | None = None
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _digest_matches(self) -> ModelBinding:
        if self.sha256 != model_binding_sha256(self):
            raise ValueError("model binding sha256 does not match its content")
        return self


def canonical_sha256(payload: Mapping[str, object]) -> str:
    """Frozen canonical digest contract shared by every binding snapshot.

    Canonical form: compact (``,``/``:`` separators), key-sorted JSON of the
    payload with the *top-level* ``sha256`` (the snapshot's own digest) and
    every ``None`` value at any depth omitted, so a field added later as
    optional does not change the digest of a snapshot retained before it
    existed (absent and null are the same statement). Nested members named
    ``sha256`` are ordinary data and stay covered. This is the only
    compatibility claim: a draft that was hashed with explicit ``null`` members
    is a different, unsupported format.
    """
    body = {key: value for key, value in payload.items() if key != "sha256"}
    text = json.dumps(_without_none(body), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _without_none(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _without_none(item) for key, item in value.items() if item is not None}
    if isinstance(value, list | tuple):
        return [_without_none(item) for item in value]
    return value


def model_binding_sha256(binding: ModelBinding) -> str:
    """Canonical digest over every present field except ``sha256`` (:func:`canonical_sha256`)."""
    return canonical_sha256(binding.model_dump(mode="json", exclude={"sha256"}, exclude_none=True))


def resolve_model_binding(
    model_id: str,
    provider_id: str | None = None,
    *,
    models: ModelRegistry | None = None,
    providers: ProviderCatalog | None = None,
    environ: Mapping[str, str] | None = None,
) -> ModelBinding:
    """Resolve a logical model on a provider route into a :class:`ModelBinding`.

    - ``api_model`` is the registry's explicit ``api_model`` or, for legacy rows
      without one, the logical id verbatim (no suffix-stripping heuristics).
    - ``provider_kind`` must be in :data:`SUPPORTED_PROVIDER_KINDS`.
    - ``base_url`` is the provider's public endpoint: the declared
      ``base_url_env`` override from ``environ`` when present, else
      ``default_base_url``; never a credential.
    - ``bfcl`` mirrors the registry's ``backend_bindings.bfcl`` with
      ``registry_id`` defaulted to the logical id; absent when undeclared.
    """
    from bencheval.exceptions import BenchEvalError
    from bencheval.model_registry import load_model_registry
    from bencheval.provider_registry import (
        DEFAULT_PROVIDER_ID,
        load_provider_catalog,
        public_base_url,
    )

    registry = models if models is not None else load_model_registry()
    catalog = providers if providers is not None else load_provider_catalog()
    model_key = model_id.strip()
    try:
        entry = registry.by_id(model_key)
    except KeyError as e:
        raise BenchEvalError(f"unknown model {model_key!r}") from e
    route = (provider_id or entry.provider_route or DEFAULT_PROVIDER_ID).strip()
    if entry.provider_route is not None and entry.provider_route != route:
        raise BenchEvalError(
            f"model {model_key!r} is routed to provider {entry.provider_route!r}, not {route!r}",
        )
    try:
        profile = catalog.by_id(route)
    except KeyError as e:
        raise BenchEvalError(f"unknown provider {route!r}") from e
    kind = profile.provider.kind
    if kind not in SUPPORTED_PROVIDER_KINDS:
        raise BenchEvalError(
            f"provider {route!r} kind {kind!r} is not a supported protocol; "
            f"supported: {sorted(SUPPORTED_PROVIDER_KINDS)}",
        )
    base_url = public_base_url(profile, environ)
    declared = entry.backend_bindings.bfcl if entry.backend_bindings is not None else None
    bfcl = None
    if declared is not None:
        configured = declared.mode == "configured"
        bfcl = ResolvedBfclBinding(
            mode=declared.mode,
            registry_id=declared.registry_id or model_key,
            handler=declared.handler,
            underscore_to_dot=declared.underscore_to_dot,
            display_name=entry.display_name if configured else None,
            # Absent provenance names the public endpoint and stays "unknown";
            # nothing is invented about vendor or licensing.
            reference_url=(entry.reference_url or base_url) if configured else None,
            organization=(entry.organization or UNKNOWN_PROVENANCE) if configured else None,
            license=(entry.license or UNKNOWN_PROVENANCE) if configured else None,
        )
    fields = {
        "model_id": model_key,
        "api_model": entry.api_model or model_key,
        "provider_id": route,
        "provider_kind": kind,
        "base_url": base_url,
        "bfcl": bfcl,
    }
    draft = ModelBinding.model_construct(
        schema_version=MODEL_BINDING_SCHEMA, **fields, sha256="sha256:" + "0" * 64
    )
    return ModelBinding(**fields, sha256=model_binding_sha256(draft))


def require_snapshot_endpoint(binding: ModelBinding | None, *, base_url: str) -> None:
    """Fail closed when the launch endpoint is not the confirmed public endpoint.

    The snapshot froze the endpoint at confirmation; an environment override
    that changed since then would be a silent late substitution.
    """
    from bencheval.exceptions import BenchEvalError

    if binding is not None and binding.base_url != base_url:
        raise BenchEvalError(
            f"provider {binding.provider_id!r} endpoint {base_url!r} is not the confirmed "
            f"binding endpoint {binding.base_url!r}; re-plan before launching",
        )


__all__ = [
    "MODEL_BINDING_SCHEMA",
    "SUPPORTED_PROVIDER_KINDS",
    "UNKNOWN_PROVENANCE",
    "BfclBindingMode",
    "BfclHandlerKey",
    "ModelBinding",
    "ResolvedBfclBinding",
    "canonical_sha256",
    "model_binding_sha256",
    "require_snapshot_endpoint",
    "resolve_model_binding",
]
