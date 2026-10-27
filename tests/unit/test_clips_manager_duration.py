from __future__ import annotations

from acfv.processing.clip_name_parser import duration_from_clip_name


def test_duration_from_clip_name_parses_millisecond_window() -> None:
    duration = duration_from_clip_name("clip_001_00h00m00s_0-188000.mp4")
    assert duration == 188.0


def test_duration_from_clip_name_parses_second_window() -> None:
    duration = duration_from_clip_name("clip_001_0.0s-13.5s.mp4")
    assert duration == 13.5


def test_duration_from_clip_name_returns_none_for_unknown_pattern() -> None:
    assert duration_from_clip_name("example.mp4") is None
