#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
说话人识别模块 - 从pyannote_gui_test.py提取的核心功能
"""

import os
import sys
import json
import time
import pickle
import hashlib
import tempfile
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from tqdm.auto import tqdm
from acfv.runtime.token_loader import get_hf_token

# 解决OpenMP冲突 - 必须在导入其他库之前设置
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'

# 统一 HuggingFace token 处理
HF_TOKEN_AVAILABLE = bool(get_hf_token())
if not HF_TOKEN_AVAILABLE:
    # token_loader 已记录一次警告，这里不重复
    pass

# 添加转录相关导入
try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

# 添加转录功能导入
try:
    from acfv.processing.transcribe_audio import (
        transcribe_audio_segment_safe,
        extract_audio_segment_safe,
    )
except ImportError:
    print("⚠️ transcribe_audio模块不可用")

class SpeakerDiarizationProcessor:
    """说话人识别处理器 - 独立模块版本"""
    
    def __init__(self, video_path, output_dir, progress_callback=None):
        self.video_path = video_path
        self.output_dir = output_dir
        self.progress_callback = progress_callback or self._default_progress_callback
        self.whisper_model = None
        self._should_stop = False
        
    def _default_progress_callback(self, stage, message, progress):
        """默认进度回调"""
        print(f"[{stage}] {message} - {progress}%")
    
    def stop(self):
        """停止处理"""
        self._should_stop = True
    
    def _expand_segments(self, segments, padding=0.3):
        """扩展片段边界，避免语音被切断，但保留短促声音"""
        expanded_segments = []
        for i, segment in enumerate(segments):
            new_segment = segment.copy()
            
            # 根据片段时长调整padding
            duration = segment['duration']
            if duration < 1.0:  # 短促声音（如笑声）
                # 对短声音使用较小的padding
                adjusted_padding = min(padding * 0.5, 0.2)
            else:
                # 对长声音使用正常padding
                adjusted_padding = padding
            
            new_segment['start'] = max(0, segment['start'] - adjusted_padding)
            
            if i < len(segments) - 1:
                next_start = segments[i + 1]['start']
                # 避免与下一个片段重叠
                max_end = min(segment['end'] + adjusted_padding, next_start - 0.05)
                new_segment['end'] = max_end
            else:
                new_segment['end'] = segment['end'] + adjusted_padding
            
            new_segment['duration'] = new_segment['end'] - new_segment['start']
            expanded_segments.append(new_segment)
        
        return expanded_segments

    def _merge_close_segments(self, segments, max_gap=2.0):
        """合并相近的同一说话人片段，但保留短促声音如笑声"""
        if not segments:
            return segments
        
        speaker_segments = {}
        for seg in segments:
            speaker = seg['speaker']
            if speaker not in speaker_segments:
                speaker_segments[speaker] = []
            speaker_segments[speaker].append(seg)
        
        merged_segments = []
        for speaker, segs in speaker_segments.items():
            segs.sort(key=lambda x: x['start'])
            current = None
            
            for seg in segs:
                if current is None:
                    current = seg.copy()
                else:
                    gap = seg['start'] - current['end']
                    
                    # 智能合并策略：保留短促声音
                    if gap <= max_gap:
                        # 检查是否是短促声音（如笑声）
                        is_short_sound = seg['duration'] < 1.0  # 小于1秒的声音
                        is_current_short = current['duration'] < 1.0
                        
                        # 如果两个都是短声音，或者间隔很小，则合并
                        if gap <= 0.5 or (is_short_sound and is_current_short):
                            current['end'] = seg['end']
                            current['duration'] = current['end'] - current['start']
                        else:
                            # 保存当前片段，开始新片段
                            merged_segments.append(current)
                            current = seg.copy()
                    else:
                        # 间隔太大，保存当前片段，开始新片段
                        merged_segments.append(current)
                        current = seg.copy()
            
            if current:
                merged_segments.append(current)
        
        return merged_segments

    def _load_whisper_model(self):
        """加载Whisper模型"""
        if not WHISPER_AVAILABLE:
            return None
        
        try:
            self.progress_callback("转录", "📝 加载Whisper模型...", 0)
            # 使用tiny模型以提高速度
            model = whisper.load_model("tiny")
            self.progress_callback("转录", "✅ Whisper模型加载完成", 10)
            return model
        except Exception as e:
            print(f"Whisper模型加载失败: {e}")
            return None

    def _extract_audio_from_video(self):
        """从视频中提取音频"""
        try:
            # 生成安全的文件名
            video_name = os.path.splitext(os.path.basename(self.video_path))[0]
            safe_name = "".join(c for c in video_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_name = safe_name[:30]  # 限制长度
            
            audio_path = os.path.join(self.output_dir, f"{safe_name}_audio.wav")
            
            # 使用ffmpeg提取音频
            cmd = [
                'ffmpeg', '-y',
                '-i', self.video_path,
                '-vn',  # 不包含视频
                '-acodec', 'pcm_s16le',  # 16位PCM编码
                '-ar', '16000',  # 16kHz采样率
                '-ac', '1',  # 单声道
                audio_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=300)
            
            if result.returncode == 0 and os.path.exists(audio_path):
                return audio_path
            else:
                print(f"音频提取失败: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"音频提取异常: {e}")
            return None

    def _identify_host_speaker(self, segments, speakers):
        """识别主播 - 选择说话时间最长的人"""
        if not segments or not speakers:
            return None
        
        # 统计每个说话人的总时长
        speaker_duration = {}
        for segment in segments:
            speaker = segment['speaker']
            if speaker not in speaker_duration:
                speaker_duration[speaker] = 0
            speaker_duration[speaker] += segment['duration']
        
        # 返回说话时间最长的人
        host_speaker = max(speaker_duration.items(), key=lambda x: x[1])[0]
        return host_speaker

    def _generate_host_audio(self, host_segments, audio_path):
        """生成主播音频文件"""
        if not host_segments:
            return None
        
        try:
            # 使用安全的文件名生成
            video_name = os.path.splitext(os.path.basename(self.video_path))[0]
            safe_name = "".join(c for c in video_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_name = safe_name[:20]  # 限制长度
            
            host_audio_file = os.path.join(self.output_dir, f"{safe_name}_host_audio.wav")
            
            # 创建ffmpeg过滤器字符串
            filter_parts = []
            for i, segment in enumerate(host_segments):
                start = segment['start']
                duration = segment['duration']
                filter_parts.append(f"[0:a]atrim=start={start}:duration={duration},asetpts=PTS-STARTPTS[a{i}]")
            
            # 合并所有片段
            if len(filter_parts) > 1:
                concat_inputs = ''.join([f"[a{i}]" for i in range(len(filter_parts))])
                concat_filter = f"{concat_inputs}concat=n={len(filter_parts)}:v=0:a=1[out]"
                full_filter = ';'.join(filter_parts) + ';' + concat_filter
                output_map = "[out]"
            else:
                full_filter = filter_parts[0]
                output_map = "[a0]"
            
            cmd = [
                'ffmpeg', '-y',
                '-i', audio_path,
                '-filter_complex', full_filter,
                '-map', output_map,
                host_audio_file
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=1000)
            
            if result.returncode == 0 and os.path.exists(host_audio_file):
                return host_audio_file
            else:
                print(f"音频生成失败: {result.stderr}")
                return None
                
        except Exception as e:
            print(f"音频生成异常: {e}")
            return None

    def process_video(self):
        """处理视频 - 主要流程"""
        try:
            # 检查线程是否应该停止
            if self._should_stop:
                return None
                
            self.progress_callback("初始化", "🔍 检查环境和依赖...", 5)
            
            # 检查依赖
            try:
                from pyannote.audio import Pipeline
                self.progress_callback("初始化", "✅ pyannote.audio 可用", 10)
            except ImportError as e:
                error_msg = f"pyannote.audio 未安装: {e}"
                self.progress_callback("错误", error_msg, 0)
                return None
            
            # 检查token
            if not HF_TOKEN_AVAILABLE:
                error_msg = "HuggingFace token 未配置，请设置环境变量 HUGGINGFACE_TOKEN 或 secrets/config.json"
                self.progress_callback("错误", error_msg, 0)
                return None
            
            token = os.environ.get('HUGGINGFACE_HUB_TOKEN')
            
            self.progress_callback("认证", "✅ HuggingFace认证通过", 15)
            
            # 提取音频
            self.progress_callback("提取", "🎵 从视频提取音频...", 20)
            audio_path = self._extract_audio_from_video()
            if not audio_path:
                error_msg = "音频提取失败"
                self.progress_callback("错误", error_msg, 0)
                return None
            
            self.progress_callback("提取", "✅ 音频提取完成", 30)
            
            # 说话人分离
            self.progress_callback("分离", "🎤 开始说话人分离...", 40)
            
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
                use_auth_token=token
            )
            
            # 优化参数以提高速度和识别非语音声音
            try:
                pipeline.instantiate({
                    # 优化分割参数 - 降低最小时长以捕获笑声等短声音
                    "segmentation": {
                        "min_duration": 0.1,  # 降低最小片段时长，捕获短促声音
                        "max_duration": 30.0,  # 设置最大片段时长
                        "threshold": 0.5,  # 降低阈值以捕获更多声音
                        "min_activity": 0.1  # 降低最小活动度
                    },
                    # 优化聚类参数 - 提高对非语音声音的敏感度
                    "clustering": {
                        "method": "centroid",
                        "min_cluster_size": 1,  # 降低最小聚类大小
                        "threshold": 0.25,  # 降低聚类阈值，更敏感
                        "covariance_type": "diag"  # 使用对角协方差矩阵，提高速度
                    },
                })
            except Exception as e:
                print(f"参数优化失败，使用默认参数: {e}")
            
            # 执行说话人分离
            diarization = pipeline(audio_path)
            
            # 提取片段信息
            segments = []
            speakers = set()
            
            for turn, _, speaker in diarization.itertracks(yield_label=True):
                segment = {
                    'start': turn.start,
                    'end': turn.end,
                    'duration': turn.end - turn.start,
                    'speaker': speaker
                }
                segments.append(segment)
                speakers.add(speaker)
            
            self.progress_callback("分离", f"✅ 说话人分离完成，识别到 {len(speakers)} 个说话人", 60)
            
            # 扩展和合并片段
            self.progress_callback("处理", "🔧 优化片段边界...", 65)
            expanded_segments = self._expand_segments(segments)
            merged_segments = self._merge_close_segments(expanded_segments)
            
            # 识别主播
            self.progress_callback("识别", "🎯 识别主播...", 70)
            host_speaker = self._identify_host_speaker(merged_segments, speakers)
            
            if host_speaker:
                self.progress_callback("识别", f"✅ 主播识别完成: {host_speaker}", 75)
                
                # 提取主播片段
                host_segments = [seg for seg in merged_segments if seg['speaker'] == host_speaker]
                
                # 生成主播音频
                self.progress_callback("生成", "🎵 生成主播音频...", 80)
                host_audio_path = self._generate_host_audio(host_segments, audio_path)
                
                # 准备结果
                result = {
                    'video_path': self.video_path,
                    'audio_path': audio_path,
                    'host_speaker': host_speaker,
                    'host_audio_path': host_audio_path,
                    'all_segments': merged_segments,
                    'host_segments': host_segments,
                    'speakers': list(speakers),
                    'total_speakers': len(speakers),
                    'total_segments': len(merged_segments),
                    'host_segments_count': len(host_segments),
                    'processing_time': datetime.now().isoformat()
                }
                
                self.progress_callback("完成", "✅ 处理完成", 100)
                return result
            else:
                error_msg = "无法识别主播"
                self.progress_callback("错误", error_msg, 0)
                return None
                
        except Exception as e:
            error_msg = f"处理失败: {e}"
            self.progress_callback("错误", error_msg, 0)
            print(f"处理异常: {e}")
            return None

def process_video_with_speaker_diarization(video_path, output_dir, progress_callback=None):
    """便捷函数：处理视频并返回说话人识别结果"""
    processor = SpeakerDiarizationProcessor(video_path, output_dir, progress_callback)
    return processor.process_video()

if __name__ == "__main__":
    print("🎤 说话人识别模块")
    print("使用方法: python speaker_diarization_module.py") 