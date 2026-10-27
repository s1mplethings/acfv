from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_contract_inputs_cover_required_fields():
    text = _read("specs/modules/transcribe_audio/contract_input.md")
    for key in ["source_path", "model_size", "output_format", "ValidationError"]:
        assert key in text, f"{key} must be documented in contract_input"
    assert "ffprobe" in text or "ffmpeg" in text, "external dependency expectations should be noted"


def test_contract_output_has_schema_and_determinism():
    text = _read("specs/modules/transcribe_audio/contract_output.md")
    for key in ["schema_version", "segments", "排序", "确定性"]:
        assert key in text, f"{key} must appear in contract_output"
    assert "start" in text and "end" in text, "segment timing fields must be present"


def test_contract_output_mentions_subtitles():
    text = _read("specs/modules/transcribe_audio/contract_output.md")
    assert "srt" in text.lower(), "SRT output must be mentioned"
    assert "golden" in text.lower(), "golden snapshot guidance should be present"
