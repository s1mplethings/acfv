"""Internal pipeline controller integrating existing processing modules.

Stages (initial minimal version):
 1. Validate inputs (video path, chat html optional)
 2. Extract chat (if html provided)
 3. Analyze interest (simplified placeholder -> segments)
 4. Generate clips (ffmpeg cut)

Future expansion:
 - Replace simple segments with analyze_data scoring selection
 - Integrate transcription & emotion modules
 - Add checkpoint resume, RAG enrichment
"""
from __future__ import annotations

import os
import json
from typing import Callable, List, Dict, Any, Optional

from acfv.main_logging import log_info, log_error, log_warning

from acfv.processing.extract_chat import extract_chat
from acfv.processing.analyze_data import init_vader  # ensure sentiment runtime
from acfv.runtime.storage import processing_path

ProgressCallback = Callable[[str, int, int, str], None]

SEGMENTS_OUTPUT = str(processing_path("high_interest_segments.json"))
CHAT_OUTPUT = str(processing_path("chat_with_emotes.json"))
CLIPS_DIR = str(processing_path("output_clips"))

class PipelineController:
    def __init__(self, progress_callback: Optional[ProgressCallback] = None):
        self.progress_callback = progress_callback
        processing_path().mkdir(parents=True, exist_ok=True)

    def _emit(self, stage: str, current: int, total: int, message: str = ""):
        if self.progress_callback:
            try:
                self.progress_callback(stage, current, total, message)
            except Exception:
                pass
        log_info(f"[{stage}] {current}/{total} {message}")

    def run(self, video_path: str, chat_html_path: Optional[str] = None) -> Dict[str, Any]:
        self._emit("validate", 0, 1, "检查输入")
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"视频不存在: {video_path}")
        if chat_html_path and not os.path.isfile(chat_html_path):
            log_warning(f"聊天文件不存在，忽略: {chat_html_path}")
            chat_html_path = None
        self._emit("validate", 1, 1, "输入就绪")

        chat_json_path = CHAT_OUTPUT
        if chat_html_path:
            self._emit("chat_extract", 0, 1, "提取聊天")
            try:
                extract_chat(chat_html_path, chat_json_path)
            except Exception as e:
                log_error(f"聊天提取失败: {e}")
                with open(chat_json_path, "w", encoding="utf-8") as f:
                    json.dump([], f)
            self._emit("chat_extract", 1, 1, "聊天完成")
        else:
            with open(chat_json_path, "w", encoding="utf-8") as f:
                json.dump([], f)

        self._emit("analyze", 0, 4, "初始化分析")
        try:
            init_vader()
        except Exception:
            log_warning("VADER 初始化失败，继续")
        segments = self._simple_segment_strategy(video_path, chat_json_path)
        self._emit("analyze", 3, 4, f"生成 {len(segments)} 段")
        with open(SEGMENTS_OUTPUT, "w", encoding="utf-8") as f:
            json.dump(segments, f, ensure_ascii=False, indent=2)
        self._emit("analyze", 4, 4, "分析完成")

        self._emit("clip", 0, len(segments) or 1, "开始剪辑")
        os.makedirs(CLIPS_DIR, exist_ok=True)
        clip_files: List[str] = []
        for i, seg in enumerate(segments):
            try:
                out_name = f"clip_{i+1:03d}.mp4"
                out_path = os.path.join(CLIPS_DIR, out_name)
                start = seg["start"]
                end = seg["end"]
                duration = max(0.1, end - start)
                from acfv.processing.clip_video import cut_video_ffmpeg
                cut_video_ffmpeg(video_path, out_path, start, duration)
                clip_files.append(out_path)
            except Exception as e:
                log_error(f"剪辑片段失败 {i+1}: {e}")
            self._emit("clip", i+1, len(segments) or 1, f"完成 {i+1}/{len(segments)}")

        return {
            "segments_file": SEGMENTS_OUTPUT,
            "chat_file": chat_json_path,
            "clips_dir": CLIPS_DIR,
            "clips": clip_files,
        }

    def _simple_segment_strategy(self, video_path: str, chat_json_path: str) -> List[Dict[str, Any]]:
        import subprocess, json as _json
        try:
            cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "json", video_path]
            pr = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            duration = 0.0
            if pr.returncode == 0:
                data = _json.loads(pr.stdout or '{}')
                duration = float((data.get('format') or {}).get('duration') or 0.0)
        except Exception:
            duration = 0.0
        if duration <= 0:
            duration = 600.0
        segment_len = 30.0
        max_segments = int(min(duration // segment_len, 10)) or 5
        segments: List[Dict[str, Any]] = []
        for i in range(max_segments):
            start = i * segment_len
            end = min(start + segment_len, duration)
            segments.append({"start": start, "end": end, "score": 0.5})
        return segments

__all__ = ["PipelineController"]
