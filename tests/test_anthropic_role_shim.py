"""Anthropic role shim tests."""

from __future__ import annotations

from bencheval.anthropic_role_shim import normalize_anthropic_payload


def test_normalize_payload_without_system_role_is_unchanged() -> None:
    payload = {
        "model": "glm-5.1",
        "messages": [{"role": "user", "content": "hello"}],
    }

    normalized = normalize_anthropic_payload(payload)

    assert normalized == payload
    assert normalized is not payload


def test_normalize_system_role_message_to_top_level_system() -> None:
    payload = {
        "model": "glm-5.1",
        "messages": [
            {"role": "system", "content": "be concise"},
            {"role": "user", "content": "hello"},
        ],
    }

    normalized = normalize_anthropic_payload(payload)

    assert normalized == {
        "model": "glm-5.1",
        "system": "be concise",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_normalize_appends_existing_system_prompt() -> None:
    payload = {
        "model": "glm-5.1",
        "system": "existing",
        "messages": [
            {"role": "system", "content": [{"type": "text", "text": "extra"}]},
            {"role": "user", "content": "hello"},
        ],
    }

    normalized = normalize_anthropic_payload(payload)

    assert normalized["system"] == "existing\n\nextra"
    assert normalized["messages"] == [{"role": "user", "content": "hello"}]
