from __future__ import annotations

import pytest

from acfv.llm.openai_client import JsonSchemaValidationError, OpenAIClientConfig, OpenAIJsonClient, parse_json_object


def test_parse_json_object_plain():
    payload = parse_json_object('{"ok": true, "value": 1}')
    assert payload["ok"] is True
    assert payload["value"] == 1


def test_parse_json_object_fenced_block():
    payload = parse_json_object("```json\n{\"items\": [1, 2]}\n```")
    assert payload["items"] == [1, 2]


def test_parse_json_object_invalid():
    with pytest.raises(JsonSchemaValidationError):
        parse_json_object("not json")


def test_local_llm_provider_is_available_without_real_api_key():
    client = OpenAIJsonClient(
        OpenAIClientConfig(
            provider="ollama",
            api_key="ollama",
            base_url="http://127.0.0.1:11434/v1",
            model="qwen2.5:7b-instruct",
        )
    )
    client._client = object()
    assert client.available is True


def test_disabled_provider_reports_clear_error():
    client = OpenAIJsonClient(OpenAIClientConfig(provider="disabled"))
    assert client.available is False
    assert client.availability_error() == "LLM provider disabled"
