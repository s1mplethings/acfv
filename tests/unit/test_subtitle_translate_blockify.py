from acfv.steps.subtitle_translate.blockify import SubtitleEvent, build_blocks


def test_build_blocks_respects_gap_and_duration():
    events = [
        SubtitleEvent(event_id="0001", start_ms=0, end_ms=1000, text="hello", index=0),
        SubtitleEvent(event_id="0002", start_ms=1100, end_ms=2000, text="world", index=1),
        SubtitleEvent(event_id="0003", start_ms=5000, end_ms=6000, text="later", index=2),
    ]
    blocks = build_blocks(events, max_duration_sec=5.0, max_chars=50, max_gap_sec=0.6, min_items=1)
    assert len(blocks) == 2
    assert blocks[0].ids == ["0001", "0002"]
    assert blocks[1].ids == ["0003"]
