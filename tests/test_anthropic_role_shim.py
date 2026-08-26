"""Anthropic role shim tests."""

from __future__ import annotations

import json

from bencheval.anthropic_role_shim import _forward_headers, normalize_anthropic_payload


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


def test_normalize_developer_role_in_responses_input() -> None:
    payload = {
        "model": "kimi-k2.7-code",
        "input": [
            {"role": "developer", "content": "follow the repo"},
            {"role": "user", "content": "fix git"},
        ],
    }

    normalized = normalize_anthropic_payload(payload)

    assert normalized["input"] == [
        {"role": "system", "content": "follow the repo"},
        {"role": "user", "content": "fix git"},
    ]
    assert "developer" not in json.dumps(normalized)


def test_normalize_developer_role_input_text_blocks() -> None:
    payload = {
        "model": "kimi-k2.7-code",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "follow the repo"}],
            },
            {"role": "user", "content": "fix git"},
        ],
    }

    normalized = normalize_anthropic_payload(payload)

    assert normalized["input"][0]["role"] == "system"
    assert normalized["input"][0]["content"] == [
        {"type": "input_text", "text": "follow the repo"},
    ]
    assert "developer" not in json.dumps(normalized)


def test_normalize_string_input_is_unchanged() -> None:
    payload = {"model": "kimi-k2.7-code", "input": "just a string"}

    normalized = normalize_anthropic_payload(payload)

    assert normalized["input"] == "just a string"


def test_normalize_developer_message_like_system_role() -> None:
    payload = {
        "model": "kimi-k2.7-code",
        "messages": [
            {"role": "developer", "content": "follow the repo"},
            {"role": "user", "content": "hello"},
        ],
    }

    normalized = normalize_anthropic_payload(payload)

    assert normalized["system"] == "follow the repo"
    assert normalized["messages"] == [{"role": "user", "content": "hello"}]


def test_forward_headers_inject_auth_without_preserving_host() -> None:
    headers = _forward_headers(
        {
            "host": "container.local",
            "Authorization": "Bearer dummy",
            "x-api-key": "dummy",
            "accept-encoding": "gzip",
        },
        auth_token="real-token",
    )

    assert headers["Authorization"] == "Bearer real-token"
    assert headers["x-api-key"] == "real-token"
    assert headers["content-type"] == "application/json"
    assert headers["accept-encoding"] == "identity"
    assert "host" not in {k.lower(): v for k, v in headers.items()}
