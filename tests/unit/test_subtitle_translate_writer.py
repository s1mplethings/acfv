from pathlib import Path

import pytest

pysubs2 = pytest.importorskip("pysubs2")

from acfv.steps.subtitle_translate.blockify import SubtitleEvent
from acfv.steps.subtitle_translate.writer import write_translated


def _make_srt(path: Path) -> None:
    subs = pysubs2.SSAFile()
    subs.events = [
        pysubs2.SSAEvent(start=0, end=1000, text="hello"),
        pysubs2.SSAEvent(start=1000, end=2000, text="world"),
    ]
    subs.save(str(path))


def test_write_translated_srt(tmp_path):
    source = tmp_path / "src.srt"
    _make_srt(source)
    events = [
        SubtitleEvent(event_id="0001", start_ms=0, end_ms=1000, text="hello", index=0),
        SubtitleEvent(event_id="0002", start_ms=1000, end_ms=2000, text="world", index=1),
    ]
    translations = {"0001": "你好", "0002": "世界"}
    out_path = tmp_path / "out.srt"
    write_translated(source, events, translations, out_path, bilingual=False)
    out = pysubs2.load(str(out_path))
    assert out.events[0].text == "你好"
    assert out.events[1].text == "世界"
