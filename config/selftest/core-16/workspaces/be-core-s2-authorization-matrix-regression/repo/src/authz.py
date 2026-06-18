"""Role-based authorization for internal resources."""

from __future__ import annotations

_ROLES = frozenset({"viewer", "editor", "admin"})
_RESOURCES = frozenset({"document", "settings", "audit_log"})
_ACTIONS = frozenset({"read", "write", "delete"})

# Regression: several tuples drifted from the approved matrix.
_PERMS: dict[tuple[str, str, str], bool] = {
    ("viewer", "read", "document"): True,
    ("viewer", "delete", "document"): True,
    ("editor", "read", "document"): True,
    ("editor", "write", "document"): True,
    ("editor", "read", "settings"): False,
    ("admin", "read", "document"): True,
    ("admin", "write", "document"): True,
    ("admin", "delete", "document"): True,
    ("admin", "read", "settings"): True,
    ("admin", "write", "settings"): True,
    ("admin", "delete", "settings"): True,
    ("admin", "read", "audit_log"): False,
    ("admin", "write", "audit_log"): True,
}


def can(role: str, action: str, resource: str) -> bool:
    if role not in _ROLES or action not in _ACTIONS or resource not in _RESOURCES:
        return False
    return _PERMS.get((role, action, resource), False)
