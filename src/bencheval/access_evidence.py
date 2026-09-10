"""Closed effective-access facts captured by concrete adapter launches."""

from __future__ import annotations

from dataclasses import dataclass

import yaml

from bencheval.domain import (
    AccessControlSource,
    EgressControl,
    RepositoryHistory,
    RetrievalAudit,
)

_INSPECT_SWE_TASK = "inspect_evals/swe_bench"


@dataclass(frozen=True, slots=True)
class EffectiveAccessEvidence:
    access_control_source: AccessControlSource
    egress_control: EgressControl
    repository_history: RepositoryHistory
    retrieval_audit: RetrievalAudit


def model_only_access() -> EffectiveAccessEvidence:
    """Model-only calls expose no arbitrary model-controlled network or repository."""
    return EffectiveAccessEvidence(
        access_control_source="not_applicable",
        egress_control="not_applicable",
        repository_history="not_applicable",
        retrieval_audit="not_run",
    )


def harbor_uncontrolled_access() -> EffectiveAccessEvidence:
    """Harbor currently exposes no official container-egress control artifact."""
    return EffectiveAccessEvidence(
        access_control_source="none",
        egress_control="uncontrolled",
        repository_history="unknown",
        retrieval_audit="not_run",
    )


def inspect_swe_access_from_retained_config(
    *,
    task_registry_name: str,
    sandbox_type: str,
    allow_internet: bool,
    allow_internet_overridden: bool,
    compose_bytes: bytes,
) -> EffectiveAccessEvidence | None:
    """Classify launch-bound SWE config; this helper does not establish that binding."""
    if (
        task_registry_name != _INSPECT_SWE_TASK
        or sandbox_type != "docker"
        or allow_internet
        or allow_internet_overridden
    ):
        return None
    try:
        compose = yaml.safe_load(compose_bytes)
    except yaml.YAMLError:
        return None
    if not isinstance(compose, dict):
        return None
    services = compose.get("services")
    if not isinstance(services, dict):
        return None
    default_service = services.get("default")
    if not isinstance(default_service, dict):
        return None
    if set(compose) != {"services"} or set(services) != {"default"}:
        return None
    if not set(default_service) <= {"image", "command", "working_dir", "network_mode"}:
        return None
    if default_service.get("network_mode") != "none":
        return None
    return EffectiveAccessEvidence(
        access_control_source="official_default",
        egress_control="blocked",
        repository_history="unknown",
        retrieval_audit="not_run",
    )


__all__ = [
    "EffectiveAccessEvidence",
    "harbor_uncontrolled_access",
    "inspect_swe_access_from_retained_config",
    "model_only_access",
]
