import os
import subprocess
from main_logging import log_info, log_error, log_debug, log_warning
import datetime
import json
from acfv import config

# 可选依赖：cv2
try:
    import cv2
    CV2_AVAILABLE = True
    log_info("[clip_video] OpenCV模块加载成功")
except ImportError as e:
    CV2_AVAILABLE = False
    log_warning(f"[clip_video] OpenCV模块导入失败: {e}")
    log_info("[clip_video] 将使用替代方法处理视频信息")

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
            
            # 🆕 验证片段数据
            if start_time >= end_time:
                log_error(f"[clip_video] ❌ 片段 {i+1} 数据异常: start={start_time:.1f}s >= end={end_time:.1f}s")
                log_error(f"[clip_video] 跳过异常片段: {segment}")
                continue
                
            if duration <= 0:
                log_error(f"[clip_video] ❌ 片段 {i+1} 持续时间异常: {duration:.1f}s")
                continue
            
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
    根据分析结果剪辑视频 - 基于语义的自适应分段（不强制固定5分钟）
    
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
    
    # 🆕 调试：检查传入的segments数据
    log_info(f"[clip_video] 收到 {len(segments)} 个片段")
    
    # 🆕 过滤无效片段
    valid_segments = []
    for i, seg in enumerate(segments):
        start = seg.get('start', 0)
        end = seg.get('end', 0)
        score = seg.get('score', 0)
        
        # 检查片段有效性
        if start >= end:
            log_warning(f"[clip_video] 跳过无效片段 {i+1}: start({start}) >= end({end})")
            continue
            
        if score <= 0:
            log_warning(f"[clip_video] 跳过低分片段 {i+1}: score={score}")
            continue
            
        if end - start < 5:  # 少于5秒的片段
            log_warning(f"[clip_video] 跳过过短片段 {i+1}: 持续时间={end-start:.1f}s")
            continue
            
        valid_segments.append(seg)
        log_info(f"[clip_video] 有效片段 {len(valid_segments)}: {start:.1f}s-{end:.1f}s, 评分={score:.3f}")
    
    if len(valid_segments) == 0:
        log_error("[clip_video] ❌ 没有有效的片段数据！")
        return []
        
    log_info(f"[clip_video] 过滤后剩余 {len(valid_segments)} 个有效片段")
    segments = valid_segments  # 使用过滤后的片段
    
    # 语义相近聚合为自适应切片
    log_info("[clip_video] 启用语义自适应分段模式")

    def _simple_tokenize(text: str):
        import re
        text = (text or "").lower()
        text = re.sub(r"[^\w\u4e00-\u9fa5]+", " ", text)
        return [tok for tok in text.split() if len(tok) > 1]

    def _cosine_dict(a: dict, b: dict):
        if not a or not b:
            return 0.0
        import math
        dot = 0.0
        for k, v in a.items():
            if k in b:
                dot += v * b[k]
        na = math.sqrt(sum(v*v for v in a.values()))
        nb = math.sqrt(sum(v*v for v in b.values()))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)

    def _vectorize_texts(texts):
        """返回 (vectors, method)；优先TF-IDF，失败则稀疏计数向量"""
        try:
            global _tfidf_vectorizer
            if SEMANTIC_AVAILABLE:
                if _tfidf_vectorizer is None:
                    _tfidf_vectorizer = TfidfVectorizer(max_features=5000)
                mat = _tfidf_vectorizer.fit_transform(texts)
                return mat, 'tfidf'
        except Exception as e:
            log_warning(f"[clip_video] TF-IDF向量化失败，将使用简易向量: {e}")
        # fallback: 计数向量
        from collections import Counter
        vecs = [Counter(_simple_tokenize(t)) for t in texts]
        return vecs, 'bow'

    # 按开始时间排序
    segments.sort(key=lambda s: (float(s.get('start', 0.0)), -float(s.get('score', 0.0))))
    texts = [s.get('text', '') for s in segments]
    vecs, method = _vectorize_texts(texts)
    log_info(f"[clip_video] 语义向量方式: {method}")

    # 从配置读取阈值
    try:
        cm = config.config_manager
        min_sec = float(cm.get("MIN_CLIP_DURATION", 60.0))
        sim_threshold = float(cm.get("SEMANTIC_SIMILARITY_THRESHOLD", 0.75))
        max_gap = float(cm.get("SEMANTIC_MAX_TIME_GAP", 60.0))
        # 上限为最小时长的3倍，防止过长
        max_sec = max(min_sec * 3.0, min_sec + 1.0)
    except Exception:
        min_sec = 60.0
        max_sec = 180.0
        sim_threshold = 0.18
        max_gap = 90.0

    processed_segments = []
    cur_start = None
    cur_end = None
    cur_score = 0.0
    cur_texts = []
    cur_indices = []

    def _flush_block():
        nonlocal cur_start, cur_end, cur_score, cur_texts, cur_indices
        if cur_start is None:
            return
        processed_segments.append({
            'start': max(0.0, cur_start),
            'end': min(video_duration, cur_end),
            'score': cur_score,
            'text': ' '.join(cur_texts),
            'semantic_approx_5min': True,
            'original_indices': cur_indices[:]
        })
        cur_start = None
        cur_end = None
        cur_score = 0.0
        cur_texts = []
        cur_indices = []

    for idx, seg in enumerate(segments):
        s = float(seg.get('start', 0.0))
        e = float(seg.get('end', 0.0))
        sc = float(seg.get('score', 0.0))
        txt = seg.get('text', '')
        if cur_start is None:
            cur_start, cur_end = s, e
            cur_score = sc
            cur_texts = [txt]
            cur_indices = [idx]
            continue
        # 与上一段的间隔
        gap = s - cur_end
        # 相似度（与上一段比较或与当前块末段比较）
        similar = True
        try:
            if method == 'tfidf':
                # 取本段与上段tfidf相似度
                import numpy as np
                last_idx = cur_indices[-1]
                sim = float(cosine_similarity(vecs[last_idx], vecs[idx])[0][0])
            else:
                from collections import Counter
                last_idx = cur_indices[-1]
                sim = _cosine_dict(vecs[last_idx], vecs[idx])
            similar = sim >= sim_threshold
        except Exception:
            similar = True

        new_dur = (max(cur_end, e) - cur_start)
        # 自适应规则：
        # - 时间间隔过大 -> 结块
        # - 达到上限 -> 结块
        # - 已达到最小时长且语义不相似 -> 结块
        if (gap > max_gap) or (new_dur >= max_sec) or ((new_dur >= min_sec) and (not similar)):
            # 若当前块不足最小长度，尽量并入当前段再切
            if (cur_end - cur_start) < min_sec and (new_dur <= max_sec):
                # 并入
                cur_end = max(cur_end, e)
                cur_score = max(cur_score, sc)
                cur_texts.append(txt)
                cur_indices.append(idx)
            else:
                _flush_block()
                cur_start, cur_end = s, e
                cur_score = sc
                cur_texts = [txt]
                cur_indices = [idx]
        else:
            # 并入当前块
            cur_end = max(cur_end, e)
            cur_score = max(cur_score, sc)
            cur_texts.append(txt)
            cur_indices.append(idx)

    _flush_block()

    # 约束到视频范围，并过滤异常
    processed_segments = [p for p in processed_segments if (p['end'] - p['start']) > 1.0 and p['start'] < video_duration]
    processed_segments.sort(key=lambda x: x['start'])
    log_info(f"[clip_video] 语义分段完成，共生成 {len(processed_segments)} 个片段")
    
    # 保存处理计划
    plan_file = os.path.join(output_dir, "clip_plan.json")
    plan_data = {
        "mode": "semantic_variable",
        "min_sec": min_sec,
        "max_sec": max_sec,
        "sim_threshold": sim_threshold,
        "max_gap": max_gap,
        "segments": processed_segments,
        "video_duration": video_duration,
        "total_segments": len(processed_segments)
    }
    
    with open(plan_file, 'w', encoding='utf-8') as f:
        json.dump(plan_data, f, ensure_ascii=False, indent=2)
    
    log_info(f"[clip_video] 切片计划已保存到: {plan_file}")
    
    # 直接进入切片生成阶段
    return generate_clips_from_segments(video_path, processed_segments, output_dir, progress_callback, audio_source)


def extend_segment(segment, context_extend, video_duration):
    """扩展片段前后文"""
    try:
        start = segment['start']
        end = segment['end']
        
        # 向前扩展
        new_start = max(0, start - context_extend)
        # 向后扩展
        new_end = min(video_duration, end + context_extend)
        
        # 更新片段
        segment['start'] = new_start
        segment['end'] = new_end
        
        log_debug(f"[clip_video] 扩展片段: {start:.1f}-{end:.1f}s -> {new_start:.1f}-{new_end:.1f}s")
        return segment
        
    except Exception as e:
        log_error(f"[clip_video] 扩展片段失败: {e}")
        return segment


def ensure_min_duration(segments_data, min_duration, video_duration):
    """确保片段达到最小时长"""
    try:
        processed_segments = []
        
        for segment in segments_data:
            start = segment['start']
            end = segment['end']
            current_duration = end - start
            
            if current_duration < min_duration:
                # 计算需要扩展的总时长
                extend_total = min_duration - current_duration
                extend_each = extend_total / 2  # 前后各扩展一半
                
                # 计算新的开始和结束时间
                new_start = max(0, start - extend_each)
                new_end = min(video_duration, end + extend_each)
                
                # 如果前面无法扩展足够，后面多扩展一些
                if new_start == 0:
                    new_end = min(video_duration, start + min_duration)
                # 如果后面无法扩展足够，前面多扩展一些
                elif new_end == video_duration:
                    new_start = max(0, end - min_duration)
                
                segment['start'] = new_start
                segment['end'] = new_end
                
                log_debug(f"[clip_video] 扩展片段至最小时长: {start:.1f}-{end:.1f}s ({current_duration:.1f}s) -> {new_start:.1f}-{new_end:.1f}s ({new_end - new_start:.1f}s)")
            
            processed_segments.append(segment)
        
        return processed_segments
        
    except Exception as e:
        log_error(f"[clip_video] 确保最小时长失败: {e}")
        return segments_data
