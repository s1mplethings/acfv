from __future__ import annotations

import pytest

from acfv.llm.openai_client import JsonSchemaValidationError, parse_json_object


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
