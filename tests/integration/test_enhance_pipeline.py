"""Integration test for enhance pipeline"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_timeline_schema_validation():
    """测试timeline schema的pydantic验证"""
    from acfv.enhance.render.timeline_schema import Timeline, TimelineMeta, ROIs, ROIBox
    
    # 最小有效timeline
    timeline = Timeline(
        meta=TimelineMeta(fps=30, width=1920, height=1080, duration=10.0)
    )
    
    assert timeline.meta.fps == 30
    assert timeline.meta.schema_version == "1.0.0"
    assert timeline.subtitles == []
    assert timeline.views == []
    
    # 导出JSON
    data = timeline.to_json()
    assert "meta" in data
    assert data["meta"]["fps"] == 30
    
    # 从JSON加载
    timeline2 = Timeline.from_json(data)
    assert timeline2.meta.fps == 30


def test_timeline_with_rois():
    """测试包含ROI的timeline"""
    from acfv.enhance.render.timeline_schema import Timeline, TimelineMeta, ROIs, ROIBox
    
    timeline = Timeline(
        meta=TimelineMeta(fps=30, width=1920, height=1080, duration=10.0),
        rois=ROIs(
            PC=ROIBox(x=0, y=0, w=1280, h=720),
            V=ROIBox(x=1100, y=20, w=160, h=240)
        )
    )
    
    assert timeline.rois is not None
    assert timeline.rois.PC.w == 1280
    assert timeline.rois.V.x == 1100


def test_timeline_with_events():
    """测试包含事件的timeline"""
    from acfv.enhance.render.timeline_schema import (
        Timeline, TimelineMeta, SubtitleEvent, ViewEvent, OverlayEvent
    )
    
    timeline = Timeline(
        meta=TimelineMeta(fps=30, width=1920, height=1080, duration=10.0),
        subtitles=[
            SubtitleEvent(t0=0.0, t1=2.0, text="Hello"),
            SubtitleEvent(t0=2.5, t1=4.5, text="World"),
        ],
        views=[
            ViewEvent(t0=0.0, t1=5.0, target="FULL"),
            ViewEvent(t0=5.0, t1=10.0, target="V"),
        ],
        overlays=[
            OverlayEvent(t0=3.0, t1=5.0, asset="assets/memes/laugh.png"),
        ]
    )
    
    assert len(timeline.subtitles) == 2
    assert len(timeline.views) == 2
    assert len(timeline.overlays) == 1
    assert timeline.views[1].target == "V"


def test_enhance_cli_dry_run(tmp_path):
    """测试enhance CLI的dry-run模式"""
    # 创建临时输入视频（占位）
    input_video = tmp_path / "input.mp4"
    input_video.write_text("")
    
    output_video = tmp_path / "output.mp4"
    work_dir = tmp_path / "work"
    
    from acfv.cli.enhance import enhance_video
    
    # 模拟dry-run调用
    try:
        enhance_video(
            input_video=input_video,
            output_video=output_video,
            work_dir=work_dir,
            dry_run=True,
            profile=None,
            roi_config=None,
            style=None
        )
    except SystemExit:
        pass  # typer.Exit
    
    # 验证timeline.json生成
    timeline_path = work_dir / "timeline.json"
    assert timeline_path.exists()
    
    with open(timeline_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    assert "meta" in data
    assert data["meta"]["schema_version"] == "1.0.0"


@pytest.mark.skip(reason="完整pipeline需ASR/ROI/Render实现")
def test_enhance_full_pipeline():
    """完整enhance流水线测试（待实现）"""
    # TODO: 使用10s短视频测试完整流程
    # 1. ASR转写
    # 2. 字幕特效生成
    # 3. ROI检测
    # 4. 策略生成事件
    # 5. 渲染输出
    pass
