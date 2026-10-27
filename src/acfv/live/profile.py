from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AnalysisProfile:
    name: str
    asr: bool = True
    chat: bool = True
    scene: str = "low"
    ocr: str = "low"
    visual: str = "low"
    speaker: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROFILES = {
    "gaming": AnalysisProfile("gaming", scene="high", ocr="high", visual="medium"),
    "talking": AnalysisProfile("talking"),
    "collab": AnalysisProfile("collab", scene="low", ocr="low", visual="optional", speaker=True),
    "other": AnalysisProfile("other"),
}


def resolve_analysis_profile(metadata: dict[str, Any] | None = None, override: str = "auto") -> AnalysisProfile:
    requested = override.strip().casefold()
    if requested != "auto":
        if requested == "custom":
            return AnalysisProfile("custom")
        if requested not in PROFILES:
            raise ValueError("profile must be Auto, Gaming, Talking, Collab, Other, or Custom")
        return PROFILES[requested]
    text = " ".join(str(value) for value in (metadata or {}).values()).casefold()
    if any(token in text for token in ("collab", "多人", "guest")):
        return PROFILES["collab"]
    if any(token in text for token in ("game", "gaming", "游戏", "overwatch", "minecraft")):
        return PROFILES["gaming"]
    if any(token in text for token in ("talk", "chatting", "杂谈", "podcast")):
        return PROFILES["talking"]
    return PROFILES["other"]
