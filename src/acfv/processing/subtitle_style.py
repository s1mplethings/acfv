from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pysubs2


def apply_style_preset(in_path: str | Path, preset_name: str, out_ass: str | Path, presets_path: str | Path, overrides: dict[str, Any] | None = None) -> Path:
    source = Path(presets_path)
    presets = json.loads(source.read_text(encoding="utf-8")) if source.is_file() else {}
    preset = presets.get(preset_name) or presets.get("clean") or {}
    subtitles = pysubs2.load(str(in_path))
    style = subtitles.styles.get("Default") or pysubs2.SSAStyle()
    subtitles.styles["Default"] = style
    for key, value in {**preset, **(overrides or {})}.items():
        if key in {"bold", "italic", "underline", "strikeout"}:
            value = -1 if bool(value) else 0
        if key in {"primarycolor", "outlinecolor", "backcolor"} and isinstance(value, (list, tuple)):
            value = pysubs2.Color(*[int(item) for item in value])
        if hasattr(style, key):
            setattr(style, key, value)
    output = Path(out_ass)
    output.parent.mkdir(parents=True, exist_ok=True)
    subtitles.save(str(output))
    return output
