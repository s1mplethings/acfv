import os
import subprocess
from acfv.main_logging import log_info, log_error, log_debug, log_warning
import datetime
import json
import cv2
from acfv import config

# 语义分析相关导入
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    SEMANTIC_AVAILABLE = True
    log_info("[clip_video] 语义分析模块加载成功")
except ImportError as e:
    SEMANTIC_AVAILABLE = False
    log_error(f"[clip_video] 语义分析模块导入失败: {e}")

# 全局变量用于缓存TF-IDF向量器
_tfidf_vectorizer = None

def _probe_clip_info(output_path):
    """使用 ffprobe 检查输出文件的时长与是否包含视频流。
    返回 (has_video_stream: bool, has_audio_stream: bool, duration_seconds: float)
    """
    try:
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', '-show_streams', output_path
        ]
        pr = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='ignore', timeout=15)
        if pr.returncode != 0:
            return False, False, 0.0
        import json as _json
        info = _json.loads(pr.stdout or '{}')
        streams = info.get('streams', []) or []
        has_video = any(s.get('codec_type') == 'video' for s in streams)
        has_audio = any(s.get('codec_type') == 'audio' for s in streams)
        duration = 0.0
        try:
            duration = float((info.get('format') or {}).get('duration') or 0.0)
        except Exception:
            duration = 0.0
        return has_video, has_audio, duration
    except Exception:
        return False, False, 0.0

def cut_video_ffmpeg(input_path, output_path, start_time, duration):
    """使用FFmpeg快速切片，优先流拷贝；若检测到异常（0秒/无视频流），自动回退重编码。"""
    fast_cmd = [
        "ffmpeg", "-y",
        "-hide_banner", "-loglevel", "error", "-nostdin",
        "-ss", str(start_time),
        "-i", input_path,
        "-t", str(duration),
        "-map", "0:v:0",
        "-map", "0:a?",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "160k",
        "-movflags", "+faststart",
        output_path
    ]
    subprocess.run(fast_cmd, check=True)

    # 校验输出，避免生成0秒文件
    has_v, has_a, dur = _probe_clip_info(output_path)
    if (not has_v) or (dur <= 0.5):
        # 回退到重编码模式，确保可播放
        fallback_cmd = [
            "ffmpeg", "-y",
            "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", str(start_time),
            "-i", input_path,
            "-t", str(duration),
            "-map", "0:v:0",
            "-map", "0:a?",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "160k",
            "-fflags", "+genpts",
            "-avoid_negative_ts", "make_zero",
            "-reset_timestamps", "1",
            "-movflags", "+faststart",
            output_path
        ]
        subprocess.run(fallback_cmd, check=True)

def generate_clips_from_segments(video_path, segments, output_dir, progress_callback=None, audio_source=None):
    """从片段生成切片文件"""
    clip_files = []
    
    for i, segment in enumerate(segments):
        try:
            start_time = segment['start']
            end_time = segment['end']
            duration = end_time - start_time
            
            # 生成输出文件名
            segment_index = i + 1
            clip_filename = f"clip_{segment_index:03d}_{start_time:.1f}s-{end_time:.1f}s.mp4"
            output_path = os.path.join(output_dir, clip_filename)
            
            # 清理可能存在的旧文件
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                    log_info(f"[clip_video] 清理旧文件: {output_path}")
                except Exception as e:
                    log_warning(f"[clip_video] 清理旧文件失败: {e}")
            
            log_info(f"[clip_video] 生成切片 {i+1}/{len(segments)}: {clip_filename} ({duration:.1f}s)")
            
            # 使用快速切片函数
            try:
                cut_video_ffmpeg(video_path, output_path, start_time, duration)
                
                if os.path.exists(output_path):
                    clip_files.append(output_path)
                    log_info(f"[clip_video] 切片生成成功: {clip_filename}")
                    
                    # 更新进度
                    if progress_callback:
                        try:
                            progress_callback(i + 1, len(segments))
                        except:
                            pass
                else:
                    log_error(f"[clip_video] 切片文件未生成: {clip_filename}")
                    
            except subprocess.CalledProcessError as e:
                log_error(f"[clip_video] FFmpeg切片失败: {clip_filename}")
                log_error(f"[clip_video] FFmpeg错误: {e}")
                
        except Exception as e:
            log_error(f"[clip_video] 生成切片 {i+1} 时出错: {e}")
    
    log_info(f"[clip_video] 切片生成完成，成功生成 {len(clip_files)} 个文件")
    return clip_files

def get_video_duration(video_path):
    """获取视频时长"""
    try:
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        
        if fps > 0:
            return frame_count / fps
        return 0
    except Exception as e:
        log_error(f"[clip_video] 获取视频时长失败: {e}")
        return 0

def clip_video(video_path, analysis_file, output_dir, progress_callback=None, audio_source=None):
    """
    根据分析结果剪辑视频 - 统一使用5分钟固定模式
    
    Args:
        video_path: 视频文件路径
        analysis_file: 分析结果文件路径
        output_dir: 剪辑输出目录
        progress_callback: 进度回调函数
        audio_source: 音频源文件路径（可选，用于替换视频中的音频）
    
    Returns:
        list: 剪辑文件列表
    """
    # 读取分析结果
    try:
        with open(analysis_file, 'r', encoding='utf-8') as f:
            segments = json.load(f)
        log_info(f"[clip_video] 成功读取分析结果文件: {analysis_file}")
        log_info(f"[clip_video] 分析结果包含 {len(segments)} 个片段")
    except Exception as e:
        log_error(f"[clip_video] Error reading analysis file: {e}")
        log_error(f"[clip_video] 分析文件路径: {analysis_file}")
        log_error(f"[clip_video] 文件是否存在: {os.path.exists(analysis_file)}")
        return []

    if not segments:
        log_error("[clip_video] No segments to clip")
        log_error(f"[clip_video] 分析结果为空，文件: {analysis_file}")
        return []
        
    # 检查视频文件是否存在
    if not os.path.exists(video_path):
        log_error(f"[clip_video] Video file not found: {video_path}")
        return []

    # 测试ffmpeg是否可用
    try:
        test_result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, timeout=10)
        if test_result.returncode != 0:
            log_error("[clip_video] ffmpeg不可用")
            return []
        log_info("[clip_video] ffmpeg可用")
    except Exception as e:
        log_error(f"[clip_video] ffmpeg测试失败: {e}")
        return []
        
    # 获取视频总时长
    video_duration = get_video_duration(video_path)
    if video_duration <= 0:
        log_error("[clip_video] Could not determine video duration")
        return []

    log_info(f"[clip_video] Video duration: {video_duration:.1f}s")
    
    # 统一使用固定5分钟模式
    log_info("[clip_video] 统一使用固定5分钟切片模式")
    processed_segments = []
    segment_duration = 300.0  # 5分钟
    
    for i, segment in enumerate(segments):
        start_time = segment['start']
        end_time = segment['end']
        
        # 计算这个片段跨越的5分钟区间
        start_5min = int(start_time // segment_duration) * segment_duration
        end_5min = int(end_time // segment_duration + 1) * segment_duration
        
        # 为每个5分钟区间创建片段
        for j in range(int(start_5min // segment_duration), int(end_5min // segment_duration) + 1):
            segment_start = j * segment_duration
            segment_end = (j + 1) * segment_duration
            
            # 只保留在视频时长范围内的片段
            if segment_start < video_duration:
                segment_end = min(segment_end, video_duration)
                
                # 计算这个5分钟区间的平均分数
                overlap_start = max(start_time, segment_start)
                overlap_end = min(end_time, segment_end)
                overlap_duration = max(0, overlap_end - overlap_start)
                
                if overlap_duration > 0:
                    # 按重叠时长加权计算分数
                    weight = overlap_duration / (end_time - start_time)
                    weighted_score = segment.get('score', 0) * weight
                    
                    # 检查是否已存在这个5分钟区间
                    existing_segment = None
                    for existing in processed_segments:
                        if abs(existing['start'] - segment_start) < 1.0:
                            existing_segment = existing
                            break
                    
                    if existing_segment:
                        # 合并分数
                        existing_segment['score'] = max(existing_segment['score'], weighted_score)
                        existing_segment['text'] += ' ' + segment.get('text', '')
                    else:
                        # 创建新的5分钟片段
                        new_segment = {
                            'start': segment_start,
                            'end': segment_end,
                            'score': weighted_score,
                            'text': segment.get('text', ''),
                            'fixed_5min': True,
                            'original_segments': [segment]
                        }
                        processed_segments.append(new_segment)
    
    # 按开始时间排序
    processed_segments.sort(key=lambda x: x['start'])
    log_info(f"[clip_video] 固定5分钟模式完成，共生成 {len(processed_segments)} 个片段")
    
    # 保存处理计划
    plan_file = os.path.join(output_dir, "clip_plan.json")
    plan_data = {
        "mode": "fixed_5min",
        "segment_duration": 300.0,
        "segments": processed_segments,
        "video_duration": video_duration,
        "total_segments": len(processed_segments)
    }
    
    with open(plan_file, 'w', encoding='utf-8') as f:
        json.dump(plan_data, f, ensure_ascii=False, indent=2)
    
    log_info(f"[clip_video] 切片计划已保存到: {plan_file}")
    
    # 直接进入切片生成阶段
    return generate_clips_from_segments(video_path, processed_segments, output_dir, progress_callback, audio_source)
