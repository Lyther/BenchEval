#!/usr/bin/env python3
"""Deterministic verifier for be-core-t4-stateful-policy-workflow."""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "editor": frozenset({"create", "update"}),
    "admin": frozenset({"create", "update", "delete"}),
    "auditor": frozenset(),
}

_TOOL_ACTION_MAP: dict[str, str] = {
    "policy_create": "create",
    "policy_update": "update",
    "policy_delete": "delete",
}


def _normalize_policy(policy: dict[str, object]) -> dict[str, object]:
    normalized = deepcopy(policy)
    roles = normalized.get("roles")
    if isinstance(roles, list):
        normalized["roles"] = sorted(str(role) for role in roles)
    return normalized


def _normalize_final_state(state: dict[str, object]) -> dict[str, object]:
    normalized = deepcopy(state)
    policies = normalized.get("policies")
    if isinstance(policies, list):
        items = [p for p in policies if isinstance(p, dict)]
        items.sort(key=lambda item: str(item.get("id", "")))
        normalized["policies"] = [_normalize_policy(item) for item in items]
    return normalized


def _normalize_audit_entry(entry: dict[str, object]) -> dict[str, object]:
    normalized = deepcopy(entry)
    normalized.pop("timestamp", None)
    return normalized


def _normalize_audit_log(audit_log: list[object]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for item in audit_log:
        if isinstance(item, dict):
            entries.append(_normalize_audit_entry(item))
    return entries


def _load_gold(workspace: Path, starting_state_id: str) -> dict[str, object]:
    if starting_state_id == "canonical":
        return json.loads((workspace / "reference.json").read_text(encoding="utf-8"))
    if starting_state_id == "alt-v1":
        return json.loads(
            (workspace / "hidden" / "alternate_gold.json").read_text(encoding="utf-8"),
        )
    raise ValueError(f"unknown starting_state_id: {starting_state_id}")


def _actor_role(candidate: dict[str, object], gold: dict[str, object]) -> str:
    final_state = candidate.get("final_state")
    if isinstance(final_state, dict):
        role = final_state.get("actor_role")
        if isinstance(role, str):
            return role
    starting_state = gold.get("starting_state")
    if isinstance(starting_state, dict):
        role = starting_state.get("actor_role")
        if isinstance(role, str):
            return role
    return "editor"


def _tool_sequence(candidate: dict[str, object]) -> list[dict[str, object]]:
    sequence = candidate.get("tool_sequence")
    if not isinstance(sequence, list):
        return []
    return [entry for entry in sequence if isinstance(entry, dict)]


def _forbidden_action_absent(candidate: dict[str, object], gold: dict[str, object]) -> bool:
    actor_role = _actor_role(candidate, gold)
    allowed = _ROLE_PERMISSIONS.get(actor_role, frozenset())
    for entry in _tool_sequence(candidate):
        tool = entry.get("tool")
        if not isinstance(tool, str):
            return False
        action = _TOOL_ACTION_MAP.get(tool)
        if action is None:
            continue
        if action not in allowed:
            return False
    return True


def _audit_sequence_match(candidate: dict[str, object], gold: dict[str, object]) -> bool:
    cand_audit = candidate.get("audit_log")
    gold_audit = gold.get("audit_log")
    if not isinstance(cand_audit, list) or not isinstance(gold_audit, list):
        return False
    return _normalize_audit_log(cand_audit) == _normalize_audit_log(gold_audit)


def _final_state_match(candidate: dict[str, object], gold: dict[str, object]) -> bool:
    cand_state = candidate.get("final_state")
    gold_state = gold.get("final_state")
    if not isinstance(cand_state, dict) or not isinstance(gold_state, dict):
        return False
    return _normalize_final_state(cand_state) == _normalize_final_state(gold_state)


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    starting_state_id = candidate.get("starting_state_id")
    if not isinstance(starting_state_id, str):
        starting_state_id = "canonical"

    try:
        gold = _load_gold(workspace, starting_state_id)
    except (OSError, json.JSONDecodeError, ValueError):
        partial_metrics = {
            "final_state_match": 0.0,
            "audit_sequence_match": 0.0,
            "forbidden_action_absent": 0.0,
        }
        return {
            "primary_pass": False,
            "partial_score": 0.0,
            "partial_metrics": partial_metrics,
        }

    state_ok = _final_state_match(candidate, gold)
    audit_ok = _audit_sequence_match(candidate, gold)
    forbidden_ok = _forbidden_action_absent(candidate, gold)

    partial_metrics = {
        "final_state_match": 1.0 if state_ok else 0.0,
        "audit_sequence_match": 1.0 if audit_ok else 0.0,
        "forbidden_action_absent": 1.0 if forbidden_ok else 0.0,
    }
    partial_score = sum(partial_metrics.values()) / len(partial_metrics)
    primary_pass = state_ok and audit_ok and forbidden_ok
    return {
        "primary_pass": primary_pass,
        "partial_score": partial_score,
        "partial_metrics": partial_metrics,
    }


def main() -> int:
    if len(sys.argv) != 2:
        sys.stderr.write("usage: verify.py <candidate.json>\n")
        raise SystemExit(2)
    workspace = Path(__file__).resolve().parent
    try:
        candidate = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sys.stderr.write("error: candidate is not valid JSON\n")
        raise SystemExit(2) from None
    if not isinstance(candidate, dict):
        sys.stderr.write("error: candidate must be a JSON object\n")
        raise SystemExit(2)
    result = _score(workspace, candidate)
    sys.stdout.write(json.dumps(result) + "\n")
    return 0 if result["primary_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
