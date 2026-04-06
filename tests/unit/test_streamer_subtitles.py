from __future__ import annotations

import json
from pathlib import Path


def test_streamer_subtitles_export(tmp_path: Path):
    from acfv.steps.subtitle_generator.streamer_subtitles import run_generate_streamer_subtitles

    run_dir = tmp_path / "run_001"
    work_dir = run_dir / "work"
    speaker_dir = work_dir / "speaker_separation"
    speaker_dir.mkdir(parents=True)

    transcription = {
        "segments": [
            {"start": 0.0, "end": 1.0, "text": "hello world"},
            {"start": 1.0, "end": 2.0, "text": "more text"},
        ]
    }
    (work_dir / "transcription.json").write_text(json.dumps(transcription), encoding="utf-8")

    speaker_result = {
        "host_speaker": "SPEAKER_00",
        "segments": [
            {"speaker": "SPEAKER_00", "start": 0.0, "end": 2.0, "duration": 2.0},
        ],
    }
    (speaker_dir / "speaker_separation_result.json").write_text(
        json.dumps(speaker_result), encoding="utf-8"
    )

    result = run_generate_streamer_subtitles(run_dir)
    assert result["status"] == "ok"
    assert (work_dir / "subtitles_streamer.srt").exists()
    assert (work_dir / "subtitles_streamer.ass").exists()
