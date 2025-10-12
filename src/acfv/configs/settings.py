from pydantic import BaseModel, Field
import yaml
from pathlib import Path

class AudioCfg(BaseModel):
    sr: int = 16000
    hop_ms: int = 10

class ScoringCfg(BaseModel):
    weights: dict = Field(default_factory=lambda: {"loudness": 0.6, "pitch_var": 0.4})

class SelectionCfg(BaseModel):
    min_gap_s: float = 8.0
    lead_s: float = 0.4
    tail_s: float = 0.6
    topk: int = 8

class ExportCfg(BaseModel):
    target_fps: int = 30
    crf: int = 20

class Settings(BaseModel):
    workdir: str = "runs"
    audio: AudioCfg = AudioCfg()
    scoring: ScoringCfg = ScoringCfg()
    selection: SelectionCfg = SelectionCfg()
    export: ExportCfg = ExportCfg()

    @staticmethod
    def from_yaml(path: str) -> "Settings":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return Settings(**data)
