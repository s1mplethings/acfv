from pydantic import BaseModel, ConfigDict, Field
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

class PipelineCfg(BaseModel):
    mode: str = "clip-workflow"
    max_clip_count: int = 10
    min_clip_segment_seconds: float = 6.0
    target_clip_duration: float = 90.0

class ProviderDomainCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    default: str = ""
    common: dict = Field(default_factory=dict)

class ProvidersCfg(BaseModel):
    model_config = ConfigDict(extra="allow")
    download: ProviderDomainCfg = ProviderDomainCfg(default="twitch-downloader")
    asr: ProviderDomainCfg = ProviderDomainCfg(default="faster-whisper")
    scene: ProviderDomainCfg = ProviderDomainCfg(default="pyscenedetect")
    ocr: ProviderDomainCfg = ProviderDomainCfg(default="rapidvideocr")
    llm: ProviderDomainCfg = ProviderDomainCfg(default="ollama")

class FeaturesCfg(BaseModel):
    enable_screen_detect: bool = False
    enable_screen_understanding: bool = False
    enable_llm_highlight: bool = False
    enable_speaker_separation: bool = False
    enable_streamer_subtitles: bool = False
    enable_subtitle_translate: bool = False
    enable_rag: bool = False

class Settings(BaseModel):
    model_config = ConfigDict(extra="allow")
    workdir: str = "runs"
    audio: AudioCfg = AudioCfg()
    scoring: ScoringCfg = ScoringCfg()
    selection: SelectionCfg = SelectionCfg()
    export: ExportCfg = ExportCfg()
    pipeline: PipelineCfg = PipelineCfg()
    providers: ProvidersCfg = ProvidersCfg()
    features: FeaturesCfg = FeaturesCfg()

    @staticmethod
    def from_yaml(path: str) -> "Settings":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return Settings(**data)
