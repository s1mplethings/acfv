from __future__ import annotations
import os, json, subprocess
from typing import Optional, Dict, Any, List

from acfv.main_logging import log_info, log_error, log_warning
from acfv.processing.extract_chat import extract_chat
from acfv.processing.analyze_data import init_vader
from acfv.arc.services.scoring import (
    compute_chat_density, vader_interest_score,
    compute_relative_interest_score, score_segment
)
from acfv.processing.clip_video import cut_video_ffmpeg
from acfv.runtime.storage import processing_path

# Defaults (can be overridden by providing Settings instance in StageContext under 'settings')
DEFAULT_CHAT_OUTPUT = str(processing_path("chat_with_emotes.json"))
DEFAULT_SEGMENTS_OUTPUT = str(processing_path("high_interest_segments.json"))
DEFAULT_CLIPS_DIR = str(processing_path("output_clips"))

class StageContext(dict):
    """Mutable dict passed between stages."""
    pass

class BaseStage:
    name: str = "base"
    def run(self, ctx: StageContext) -> None:  # pragma: no cover
        raise NotImplementedError

class ValidateStage(BaseStage):
    name = "validate"
    def run(self, ctx: StageContext) -> None:
        video = ctx.get("video_path")
        chat_html = ctx.get("chat_html")
        if not video or not os.path.isfile(video):
            raise FileNotFoundError(f"视频文件不存在: {video}")
        if chat_html and not os.path.isfile(chat_html):
            log_warning(f"聊天文件缺失, 忽略: {chat_html}")
            ctx["chat_html"] = None
        os.makedirs("processing", exist_ok=True)
        log_info("[validate] 输入检查完成")

class ChatExtractStage(BaseStage):
    name = "chat_extract"
    def run(self, ctx: StageContext) -> None:
        chat_html = ctx.get("chat_html")
        settings = ctx.get('settings')
        chat_out = getattr(settings, 'chat_output', DEFAULT_CHAT_OUTPUT) if settings else DEFAULT_CHAT_OUTPUT
        if not chat_html:
            with open(chat_out, "w", encoding="utf-8") as f:
                json.dump([], f)
            ctx["chat_json"] = chat_out
            log_info("[chat] 无聊天输入, 写入空文件")
            return
        try:
            extract_chat(chat_html, chat_out)
            ctx["chat_json"] = chat_out
            log_info("[chat] 提取完成")
        except Exception as e:
            log_error(f"[chat] 提取失败: {e}, 写入空文件继续")
            with open(chat_out, "w", encoding="utf-8") as f:
                json.dump([], f)
            ctx["chat_json"] = chat_out

class AnalyzeStage(BaseStage):
    name = "analyze"
    def run(self, ctx: StageContext) -> None:
        video = ctx["video_path"]
        chat_json = ctx.get("chat_json")
        settings = ctx.get('settings')
        try:
            init_vader()
        except Exception:
            log_warning("[analyze] VADER 初始化失败")

        duration = probe_duration(video)
        # candidate raw windows (finer) -> score -> pick top
        window = getattr(settings, 'segment_window', 20.0)
        total_windows = int(duration // window) or 1
        chat_data: List[Dict[str, Any]] = []
        if chat_json and os.path.isfile(chat_json):
            try:
                with open(chat_json, 'r', encoding='utf-8') as f:
                    chat_data = json.load(f)
            except Exception:
                chat_data = []
        weights = getattr(settings, 'weights', {
            'CHAT_DENSITY_WEIGHT': 0.3,
            'CHAT_SENTIMENT_WEIGHT': 0.4,
            'VIDEO_EMOTION_WEIGHT': 0.3,
        })
        scored: List[Dict[str, Any]] = []
        all_scores: List[float] = []
        for i in range(total_windows):
            start = i * window
            end = min(start + window, duration)
            density = compute_chat_density(chat_data, start, end)
            # sentiment proxy: average word interest of concatenated messages
            messages = [m.get('message','') for m in chat_data if start <= m.get('timestamp',0) < end]
            combined = ' '.join(messages)[:500]
            sentiment = vader_interest_score(combined)
            video_emotion = 0.0  # placeholder until emotion model integrated
            raw_score = score_segment(density, sentiment, video_emotion, weights)
            all_scores.append(raw_score)
            scored.append({'start': start, 'end': end, 'raw_score': raw_score, 'chat_density': density, 'sentiment': sentiment})

        # compute relative scores & select top segments
        for seg in scored:
            seg['score'] = compute_relative_interest_score(all_scores, seg['raw_score'])

        # select top N unique non-overlapping segments
        top_n = min(getattr(settings, 'top_segments', 10), len(scored))
        scored.sort(key=lambda s: s['score'], reverse=True)
        selected: List[Dict[str, Any]] = []
        used_ranges: List[tuple] = []
        for seg in scored:
            if len(selected) >= top_n:
                break
            rng = (seg['start'], seg['end'])
            if any(not (rng[1] <= r[0] or rng[0] >= r[1]) for r in used_ranges):
                continue
            used_ranges.append(rng)
            selected.append({'start': seg['start'], 'end': seg['end'], 'score': seg['score']})

        segments_out = getattr(settings, 'analysis_output', DEFAULT_SEGMENTS_OUTPUT) if settings else DEFAULT_SEGMENTS_OUTPUT
        with open(segments_out, 'w', encoding='utf-8') as f:
            json.dump(selected, f, ensure_ascii=False, indent=2)
        ctx['segments'] = selected
        ctx['segments_file'] = segments_out
        log_info(f"[analyze] 选出 {len(selected)} 段 (窗口总数 {total_windows})")

class ClipStage(BaseStage):
    name = "clip"
    def run(self, ctx: StageContext) -> None:
        video = ctx["video_path"]
        segments = ctx.get("segments", [])
        settings = ctx.get('settings')
        clips_dir = getattr(settings, 'output_clips_dir', DEFAULT_CLIPS_DIR) if settings else DEFAULT_CLIPS_DIR
        os.makedirs(clips_dir, exist_ok=True)
        clip_files: List[str] = []
        for i, seg in enumerate(segments):
            out_name = f"clip_{i+1:03d}.mp4"
            out_path = os.path.join(clips_dir, out_name)
            try:
                cut_video_ffmpeg(video, out_path, seg['start'], max(0.1, seg['end'] - seg['start']))
                clip_files.append(out_path)
            except Exception as e:
                log_error(f"[clip] 片段 {i+1} 失败: {e}")
        ctx["clips_dir"] = clips_dir
        ctx["clips"] = clip_files
        log_info(f"[clip] 已生成 {len(clip_files)} 个剪辑")

class Pipeline:
    def __init__(self, stages: List[BaseStage]):
        self.stages = stages

    def run(self, initial: StageContext, progress_cb=None) -> StageContext:
        ctx = initial
        total = len(self.stages)
        for idx, stage in enumerate(self.stages, start=1):
            if progress_cb:
                progress_cb(stage.name, idx-1, total, "开始")
            stage.run(ctx)
            if progress_cb:
                progress_cb(stage.name, idx, total, "完成")
        return ctx

# helper

def probe_duration(video_path: str) -> float:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "json", video_path]
        pr = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if pr.returncode == 0:
            data = json.loads(pr.stdout or '{}')
            return float((data.get('format') or {}).get('duration') or 0.0)
    except Exception:
        pass
    return 600.0

__all__ = [
    'StageContext','BaseStage','ValidateStage','ChatExtractStage','AnalyzeStage','ClipStage','Pipeline'
]
