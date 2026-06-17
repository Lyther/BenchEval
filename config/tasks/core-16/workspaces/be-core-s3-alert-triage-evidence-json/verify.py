#!/usr/bin/env python3
"""Deterministic verifier for be-core-s3-alert-triage-evidence-json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_DISPOSITIONS = frozenset({"true_positive", "false_positive", "needs_review"})
_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
_REQUIRED_FIELDS = ("alert_id", "disposition", "severity", "evidence_ids")


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _prompt_alert_ids(workspace: Path) -> set[str]:
    report = _load_json(workspace / "alert_report.json")
    if not isinstance(report, dict):
        return set()
    alerts = report.get("alerts")
    if not isinstance(alerts, list):
        return set()
    ids: set[str] = set()
    for alert in alerts:
        if isinstance(alert, dict) and isinstance(alert.get("alert_id"), str):
            ids.add(alert["alert_id"])
    return ids


def _hidden_alert_ids(workspace: Path) -> set[str]:
    full = _load_json(workspace / "verifier_only" / "alert_report_full.json")
    if not isinstance(full, dict):
        return set()
    alerts = full.get("alerts")
    if not isinstance(alerts, list):
        return set()
    full_ids: set[str] = set()
    for alert in alerts:
        if isinstance(alert, dict) and isinstance(alert.get("alert_id"), str):
            full_ids.add(alert["alert_id"])
    return full_ids - _prompt_alert_ids(workspace)


def _gold_by_alert_id(workspace: Path) -> dict[str, dict[str, object]]:
    gold = _load_json(workspace / "verifier_only" / "gold_labels.json")
    if not isinstance(gold, dict):
        return {}
    verdicts = gold.get("verdicts")
    if not isinstance(verdicts, list):
        return {}
    by_id: dict[str, dict[str, object]] = {}
    for verdict in verdicts:
        if isinstance(verdict, dict) and isinstance(verdict.get("alert_id"), str):
            by_id[verdict["alert_id"]] = verdict
    return by_id


def _evidence_id_map(workspace: Path) -> dict[str, str]:
    raw = _load_json(workspace / "verifier_only" / "evidence_id_map.json")
    if not isinstance(raw, dict):
        return {}
    mapping: dict[str, str] = {}
    for alias, canonical in raw.items():
        if isinstance(alias, str) and isinstance(canonical, str):
            mapping[alias] = canonical
    return mapping


def _normalize_evidence_ids(
    evidence_ids: object,
    id_map: dict[str, str],
) -> tuple[list[str] | None, int]:
    if not isinstance(evidence_ids, list):
        return None, 1
    canonical_values = set(id_map.values())
    normalized: list[str] = []
    unsupported = 0
    for item in evidence_ids:
        if not isinstance(item, str):
            return None, 1
        if item in id_map:
            normalized.append(id_map[item])
        elif item in canonical_values:
            normalized.append(item)
        else:
            unsupported += 1
    return sorted(set(normalized)), unsupported


def _validate_verdict_shape(verdict: object) -> tuple[dict[str, object] | None, int]:
    if not isinstance(verdict, dict):
        return None, 1
    missing = [field for field in _REQUIRED_FIELDS if field not in verdict]
    if missing:
        return None, len(missing)
    alert_id = verdict.get("alert_id")
    disposition = verdict.get("disposition")
    severity = verdict.get("severity")
    if not isinstance(alert_id, str) or not alert_id:
        return None, 1
    if disposition not in _DISPOSITIONS:
        return None, 1
    if severity not in _SEVERITIES:
        return None, 1
    if not isinstance(verdict.get("evidence_ids"), list):
        return None, 1
    return verdict, 0


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    verdicts = candidate.get("verdicts")
    if not isinstance(verdicts, list):
        verdicts = []

    prompt_ids = _prompt_alert_ids(workspace)
    hidden_ids = _hidden_alert_ids(workspace)
    gold = _gold_by_alert_id(workspace)
    id_map = _evidence_id_map(workspace)

    unsupported_claims = 0
    schema_failures = 0
    parsed: dict[str, dict[str, object]] = {}

    for verdict in verdicts:
        parsed_verdict, missing_count = _validate_verdict_shape(verdict)
        if parsed_verdict is None:
            schema_failures += missing_count or 1
            continue
        alert_id = str(parsed_verdict["alert_id"])
        if alert_id in parsed:
            schema_failures += 1
            continue
        parsed[alert_id] = parsed_verdict

    candidate_ids = set(parsed)
    unsupported_claims += len(candidate_ids & hidden_ids)
    if candidate_ids != prompt_ids:
        unsupported_claims += len(candidate_ids - prompt_ids) + len(prompt_ids - candidate_ids)

    label_matches = 0
    evidence_matches = 0
    label_total = len(gold)
    evidence_total = len(gold)

    for alert_id, expected in gold.items():
        actual = parsed.get(alert_id)
        if actual is None:
            continue
        disposition_ok = actual.get("disposition") == expected.get("disposition")
        severity_ok = actual.get("severity") == expected.get("severity")
        if disposition_ok and severity_ok:
            label_matches += 1

        expected_ids, expected_unsupported = _normalize_evidence_ids(
            expected.get("evidence_ids"),
            id_map,
        )
        actual_ids, actual_unsupported = _normalize_evidence_ids(
            actual.get("evidence_ids"),
            id_map,
        )
        unsupported_claims += actual_unsupported
        if expected_unsupported:
            schema_failures += expected_unsupported
        if actual_ids is not None and expected_ids is not None and actual_ids == expected_ids:
            evidence_matches += 1

    label_accuracy = label_matches / label_total if label_total else 0.0
    evidence_id_accuracy = evidence_matches / evidence_total if evidence_total else 0.0
    unsupported_claim_count = float(unsupported_claims + schema_failures)

    schema_valid = (
        schema_failures == 0
        and unsupported_claims == 0
        and candidate_ids == prompt_ids
        and len(verdicts) == len(prompt_ids)
    )

    partial_metrics = {
        "label_accuracy": label_accuracy,
        "evidence_id_accuracy": evidence_id_accuracy,
        "unsupported_claim_count": min(unsupported_claim_count, 1.0)
        if unsupported_claim_count > 0
        else 0.0,
    }

    primary_pass = schema_valid and label_accuracy == 1.0 and evidence_id_accuracy == 1.0
    partial_score = sum(partial_metrics.values()) / len(partial_metrics)

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
