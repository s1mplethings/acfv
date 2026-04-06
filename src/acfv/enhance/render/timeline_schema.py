"""Timeline schema - 统一时间轴事件定义"""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class ROIBox(BaseModel):
    """ROI边界框"""
    x: int = Field(..., description="左上角X坐标（像素）")
    y: int = Field(..., description="左上角Y坐标（像素）")
    w: int = Field(..., description="宽度（像素）")
    h: int = Field(..., description="高度（像素）")


class TimelineMeta(BaseModel):
    """时间轴元数据"""
    fps: float = Field(..., description="帧率")
    width: int = Field(..., description="视频宽度")
    height: int = Field(..., description="视频高度")
    duration: float = Field(..., description="视频时长（秒）")
    schema_version: str = Field(default="1.0.0", description="Schema版本")


class ROIs(BaseModel):
    """ROI区域定义"""
    PC: ROIBox | None = Field(None, description="电脑画面区域")
    V: ROIBox | None = Field(None, description="VTuber小窗区域")


class SubtitleEvent(BaseModel):
    """字幕事件"""
    t0: float = Field(..., description="开始时间（秒）")
    t1: float = Field(..., description="结束时间（秒）")
    text: str = Field(..., description="字幕文本")
    style: str = Field(default="Default", description="样式名称")


class SubtitleFXEvent(BaseModel):
    """字幕特效事件"""
    t0: float = Field(..., description="开始时间（秒）")
    t1: float = Field(..., description="结束时间（秒）")
    fx: Literal["POP", "COLOR", "SHAKE"] = Field(..., description="特效类型")
    scope: Literal["word", "phrase"] = Field(default="word", description="作用范围")
    match: str = Field(..., description="匹配文本")


class ViewEvent(BaseModel):
    """视角切换事件"""
    t0: float = Field(..., description="开始时间（秒）")
    t1: float = Field(..., description="结束时间（秒）")
    target: Literal["FULL", "PC", "V"] = Field(..., description="目标视角")
    zoom: float = Field(default=1.0, description="缩放比例")
    smooth: bool = Field(default=True, description="平滑过渡")


class OverlayEvent(BaseModel):
    """贴图叠加事件"""
    t0: float = Field(..., description="开始时间（秒）")
    t1: float = Field(..., description="结束时间（秒）")
    asset: str = Field(..., description="素材路径")
    pos: tuple[int, int] = Field(default=(10, 10), description="位置(x,y)")
    scale: float = Field(default=1.0, description="缩放比例")
    anim: str | None = Field(None, description="动画类型（可选）")


class SFXEvent(BaseModel):
    """音效事件"""
    t0: float = Field(..., description="开始时间（秒）")
    t1: float = Field(..., description="结束时间（秒）")
    asset: str = Field(..., description="音效文件路径")
    gain_db: float = Field(default=0.0, description="音量增益（dB）")


class Timeline(BaseModel):
    """完整时间轴"""
    meta: TimelineMeta
    rois: ROIs | None = None
    subtitles: list[SubtitleEvent] = Field(default_factory=list)
    subtitle_fx: list[SubtitleFXEvent] = Field(default_factory=list)
    views: list[ViewEvent] = Field(default_factory=list)
    overlays: list[OverlayEvent] = Field(default_factory=list)
    sfx: list[SFXEvent] = Field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        """导出为JSON字典"""
        return self.model_dump(exclude_none=True)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Timeline:
        """从JSON字典加载"""
        return cls.model_validate(data)


__all__ = ["Timeline", "TimelineMeta", "ROIs", "ROIBox",
           "SubtitleEvent", "SubtitleFXEvent", "ViewEvent",
           "OverlayEvent", "SFXEvent"]
