from __future__ import annotations

import json
from pathlib import Path


class _DummyCfg:
    def get(self, _key, default=None):
        return default


def test_generate_semantic_subtitles_for_clips_srt(tmp_path):
    from acfv.steps.subtitle_generator.impl import generate_semantic_subtitles_for_clips

    transcription = {
        "segments": [
            {"start": 0.0, "end": 5.0, "text": "hello world."},
            {"start": 5.0, "end": 9.0, "text": "next sentence."},
        ]
    }
    transcription_path = tmp_path / "transcription.json"
    transcription_path.write_text(json.dumps(transcription), encoding="utf-8")

    clip_path = tmp_path / "clip_001_00h00m00s_0-9000.mp4"
    clip_path.write_text("", encoding="utf-8")

    written = generate_semantic_subtitles_for_clips(
        output_clips_dir=str(tmp_path),
        transcription_file=str(transcription_path),
        cfg_manager=_DummyCfg(),
        clip_paths=[str(clip_path)],
        fmt="srt",
    )

    assert written == 1
    subtitle_path = tmp_path / "clip_001_00h00m00s_0-9000.srt"
    assert subtitle_path.exists()
    assert subtitle_path.read_text(encoding="utf-8").strip()


def test_long_asr_segment_without_words_keeps_real_timing():
    from acfv.steps.subtitle_generator.impl import _build_sentence_chunks

    text = " ".join(["flight"] * 30)
    chunks = _build_sentence_chunks([{"start": 10.0, "end": 22.0, "text": text}], 10.0, 22.0)

    assert len(chunks) == 1
    assert chunks[0]["start"] == 10.0
    assert chunks[0]["end"] == 22.0
    assert chunks[0]["text"].count("\n") <= 1


def test_word_timestamps_group_on_pause_punctuation_and_clip_offset():
    from acfv.steps.subtitle_generator.impl import _build_sentence_chunks

    segment = {
        "start": 10.0,
        "end": 17.0,
        "text": "We should leave now. Wait what happened?",
        "words": [
            {"start": 10.0, "end": 10.4, "word": "We"},
            {"start": 10.45, "end": 10.9, "word": "should"},
            {"start": 10.95, "end": 11.35, "word": "leave"},
            {"start": 11.4, "end": 11.8, "word": "now."},
            {"start": 13.0, "end": 13.4, "word": "Wait"},
            {"start": 13.45, "end": 13.8, "word": "what"},
            {"start": 13.85, "end": 14.3, "word": "happened?"},
        ],
    }
    chunks = _build_sentence_chunks([segment], 10.5, 15.0)

    assert [(item["start"], item["end"]) for item in chunks] == [(10.5, 11.8), (13.0, 14.3)]
    assert all(item["end"] - item["start"] <= 4.0 for item in chunks)
    assert all(item["text"].count("\n") <= 1 for item in chunks)


def test_ass_declares_720p_design_resolution(tmp_path):
    from acfv.processing.subtitle_contract import generate_subtitle

    result = generate_subtitle({
        "segments": [{"start": 0.0, "end": 2.0, "text": "Readable caption"}],
        "format": "ass",
        "out_dir": str(tmp_path),
        "source_name": "preview",
    })
    text = Path(result["subtitle_path"]).read_text(encoding="utf-8")
    assert "PlayResX: 1280" in text
    assert "PlayResY: 720" in text
