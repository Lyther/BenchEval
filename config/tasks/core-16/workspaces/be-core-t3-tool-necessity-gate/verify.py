#!/usr/bin/env python3
"""Deterministic verifier for be-core-t3-tool-necessity-gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ALLOWED_TOOLS = frozenset({"mock_lookup", "mock_calendar"})


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_schema(candidate: dict[str, object]) -> bool:
    use_tool = candidate.get("use_tool")
    if not isinstance(use_tool, bool):
        return False

    tool_call = candidate.get("tool_call")
    answer = candidate.get("answer")
    has_tool_call = tool_call is not None
    has_answer = answer is not None

    if use_tool:
        if not has_tool_call or has_answer:
            return False
        if not isinstance(tool_call, dict):
            return False
        tool = tool_call.get("tool")
        arguments = tool_call.get("arguments")
        if not isinstance(tool, str) or tool not in _ALLOWED_TOOLS:
            return False
        return isinstance(arguments, dict)

    if has_tool_call or not has_answer:
        return False
    return isinstance(answer, dict)


def _gold_use_tool(gold: dict[str, object]) -> bool:
    return gold.get("use_tool") is True


def _candidate_use_tool(candidate: dict[str, object]) -> bool:
    return candidate.get("use_tool") is True


def _necessity_confusion(
    candidate: dict[str, object],
    gold: dict[str, object],
) -> tuple[bool, bool, bool, bool]:
    gold_positive = _gold_use_tool(gold)
    cand_positive = _candidate_use_tool(candidate)
    tp = gold_positive and cand_positive
    fp = (not gold_positive) and cand_positive
    fn = gold_positive and (not cand_positive)
    tn = (not gold_positive) and (not cand_positive)
    return tp, fp, fn, tn


def _tool_call_match(candidate: dict[str, object], gold: dict[str, object]) -> bool:
    if not _gold_use_tool(gold):
        return True
    if not _candidate_use_tool(candidate):
        return False
    gold_call = gold.get("tool_call")
    cand_call = candidate.get("tool_call")
    if not isinstance(gold_call, dict) or not isinstance(cand_call, dict):
        return False
    return cand_call == gold_call


def _answer_match(candidate: dict[str, object], gold: dict[str, object]) -> bool:
    if _gold_use_tool(gold):
        return True
    if _candidate_use_tool(candidate):
        return False
    return candidate.get("answer") == gold.get("answer")


def _matches_gold(candidate: dict[str, object], gold: dict[str, object]) -> bool:
    if not _validate_schema(candidate):
        return False
    tp, fp, fn, _tn = _necessity_confusion(candidate, gold)
    if not (tp or (not fp and not fn)):
        return False
    if _gold_use_tool(gold):
        return _tool_call_match(candidate, gold)
    return _answer_match(candidate, gold)


def _load_hidden_variants(workspace: Path) -> list[dict[str, object]]:
    payload = _load_json(workspace / "hidden_variants.json")
    if not isinstance(payload, dict):
        return []
    variants = payload.get("variants")
    if not isinstance(variants, list):
        return []
    return [entry for entry in variants if isinstance(entry, dict)]


def _aggregate_necessity_metrics(
    pairs: list[tuple[dict[str, object], dict[str, object]]],
) -> tuple[float, float]:
    tp = fp = fn = 0
    for candidate, gold in pairs:
        variant_tp, variant_fp, variant_fn, _variant_tn = _necessity_confusion(candidate, gold)
        tp += int(variant_tp)
        fp += int(variant_fp)
        fn += int(variant_fn)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    return precision, recall


def _hidden_gold_labels(workspace: Path) -> list[dict[str, object]]:
    labels: list[dict[str, object]] = []
    for entry in _load_hidden_variants(workspace):
        gold = entry.get("gold")
        if isinstance(gold, dict):
            labels.append(gold)
    return labels


def _expected_variant_ids(workspace: Path) -> list[str]:
    ids: list[str] = []
    for entry in _load_hidden_variants(workspace):
        variant_id = entry.get("variant_id")
        gold = entry.get("gold")
        if isinstance(variant_id, str) and isinstance(gold, dict):
            ids.append(variant_id)
    return ids


def _variant_responses(candidate: dict[str, object]) -> dict[str, dict[str, object]] | None:
    raw = candidate.get("variant_responses")
    if not isinstance(raw, dict):
        return None
    responses: dict[str, dict[str, object]] = {}
    for variant_id, payload in raw.items():
        if not isinstance(variant_id, str) or not isinstance(payload, dict):
            return None
        responses[variant_id] = payload
    return responses


def _score(workspace: Path, candidate: dict[str, object]) -> dict[str, object]:
    expected_ids = _expected_variant_ids(workspace)
    responses = _variant_responses(candidate)
    schema_valid = responses is not None and set(responses) == set(expected_ids)
    if schema_valid and responses is not None:
        schema_valid = all(_validate_schema(response) for response in responses.values())

    pairs: list[tuple[dict[str, object], dict[str, object]]] = []
    variant_matches = 0
    if schema_valid and responses is not None:
        for entry in _load_hidden_variants(workspace):
            variant_id = entry.get("variant_id")
            gold = entry.get("gold")
            if not isinstance(variant_id, str) or not isinstance(gold, dict):
                continue
            response = responses[variant_id]
            pairs.append((response, gold))
            if _matches_gold(response, gold):
                variant_matches += 1

    necessity_precision = 0.0
    necessity_recall = 0.0
    if schema_valid and pairs:
        necessity_precision, necessity_recall = _aggregate_necessity_metrics(pairs)

    tool_call_ok = (
        schema_valid and pairs and all(_tool_call_match(response, gold) for response, gold in pairs)
    )
    variant_coverage = (
        (variant_matches / len(expected_ids)) if expected_ids and schema_valid else 0.0
    )

    partial_metrics = {
        "schema_valid": 1.0 if schema_valid else 0.0,
        "necessity_precision": necessity_precision,
        "necessity_recall": necessity_recall,
        "tool_call_match": 1.0 if tool_call_ok else 0.0,
        "variant_coverage": variant_coverage,
    }
    partial_score = sum(partial_metrics.values()) / len(partial_metrics)

    primary_pass = (
        schema_valid
        and bool(expected_ids)
        and variant_matches == len(expected_ids)
        and necessity_precision == 1.0
        and necessity_recall == 1.0
    )

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
