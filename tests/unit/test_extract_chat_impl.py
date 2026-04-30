from __future__ import annotations

import json

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


def test_extract_chat_parses_html_without_sentiment_pipeline(tmp_path, monkeypatch):
    html_path = tmp_path / "chat.html"
    out_path = tmp_path / "chat.json"
    html_path.write_text(
        (
            '<html><body>'
            '<pre class="comment-root">[0:00:11] '
            '<a href="https://twitch.tv/tester"><span class="comment-author">tester</span></a>'
            '<span class="comment-message">: hello chat </span></pre>'
            '<pre class="comment-root">[0:00:14] '
            '<a href="https://twitch.tv/tester2"><span class="comment-author">tester2</span></a>'
            '<span class="comment-message">: pog </span></pre>'
            '</body></html>'
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(impl, "_bool_config", lambda name, default=False: False)

    impl.extract_chat(str(html_path), str(out_path))

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(payload) == 2
    assert payload[0]["author"] == "tester"
    assert payload[0]["message"] == ": hello chat"
    assert payload[0]["timestamp"] == 11.0
    assert payload[0]["sentiment"] == {"label": "neutral", "score": 0}
