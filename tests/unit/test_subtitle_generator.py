from __future__ import annotations

import json


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
