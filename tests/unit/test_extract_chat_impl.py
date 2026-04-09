from __future__ import annotations

from acfv.steps.extract_chat import impl


def test_summarize_messages_counts_duplicates():
    payload = [
        {"message": "wow"},
        {"message": "wow"},
        {"message": "nice"},
        {"message": ""},
    ]

    summary = impl._summarize_messages(payload)

    assert summary["message_count"] == 4
    assert summary["non_empty_messages"] == 3
    assert summary["top_messages"][0] == {"text": "wow", "count": 2}
