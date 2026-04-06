from __future__ import annotations

from pathlib import Path


def test_apply_style_preset(tmp_path: Path):
    try:
        import pysubs2
    except Exception:
        import pytest

        pytest.skip("pysubs2 not available")

    from acfv.processing.subtitle_style import apply_style_preset

    subs = pysubs2.SSAFile()
    subs.append(pysubs2.SSAEvent(start=0, end=1000, text="hello"))
    input_srt = tmp_path / "sample.srt"
    subs.save(str(input_srt))

    presets = tmp_path / "presets.json"
    presets.write_text(
        '{"clean": {"fontname": "Arial", "fontsize": 24, "outline": 2, "shadow": 1}}',
        encoding="utf-8",
    )

    out_ass = tmp_path / "styled.ass"
    result = apply_style_preset(input_srt, "clean", out_ass, presets)
    assert result.exists()
    content = result.read_text(encoding="utf-8")
    assert "Style:" in content
