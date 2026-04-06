import os
import subprocess
from pathlib import Path
from acfv.main_logging import log_info, log_error, log_debug, log_warning
import datetime
import json
from acfv import config
from typing import List, Dict, Any

MIN_CLIP_SEGMENT_SECONDS = 6.0
MIN_CLIP_DURATION_SEC = 240.0  # 4 分钟
PREF_CLIP_DURATION_SEC = 270.0  # 4.5 分钟
MAX_CLIP_DURATION_SEC = 300.0  # 5 分钟
NAMING_POLICY = "clip_{rank:03d}_{HHhMMmSSs}_{start_ms}-{end_ms}.mp4"


def _normalize_segments_data(data: Any) -> List[Dict[str, Any]]:
    """Accept contract segments (ms) or legacy seconds list; return list with start/end/score in seconds."""
    segments: List[Dict[str, Any]] = []
    sort_policy = None
    if isinstance(data, dict) and "segments" in data:
        units = str(data.get("units") or "").lower()
        raw_list = data.get("segments") or []
        sort_policy = str(data.get("sort") or "")
    else:
        raw_list = data if isinstance(data, list) else []
        units = "sec"

    for seg in raw_list:
        if not isinstance(seg, dict):
            continue
        start = seg.get("start")
        end = seg.get("end")
        if start is None and "start_ms" in seg:
            try:
                start = float(seg.get("start_ms", 0)) / (1000.0 if units in ("ms", "", None) else 1.0)
                end = float(seg.get("end_ms", 0)) / (1000.0 if units in ("ms", "", None) else 1.0)
            except Exception:
                continue
        try:
            start_f = float(start)
            end_f = float(end if end is not None else 0.0)
        except Exception:
            continue
        if end_f <= start_f:
            continue
        score_val = seg.get("score", seg.get("interest_score", seg.get("rating", 0.0)))
        try:
            score = float(score_val or 0.0)
        except Exception:
            score = 0.0
        reason_tags = seg.get("reason_tags") if isinstance(seg.get("reason_tags"), list) else []
        text_val = (seg.get("text") or seg.get("utterance") or "").strip()
        segments.append(
            {
                "start": max(0.0, start_f),
                "end": max(0.0, end_f),
                "score": score,
                "reason_tags": reason_tags,
                "text": text_val,
            }
        )

    if sort_policy == "score_desc_start_ms_asc_end_ms_asc":
        segments.sort(key=lambda s: (-s.get("score", 0.0), s["start"], s["end"]))
    else:
        segments.sort(key=lambda s: (s["start"], s["end"]))

    # 详细输出每个片段的兴趣分数与区间，便于终端排障
    if segments:
        log_info(f"[clip_video] 片段列表（共 {len(segments)} 个）：")
        for idx, seg in enumerate(segments, 1):
            tags = ",".join(seg.get("reason_tags") or []) or "-"
            text_hint = (seg.get("text") or "")[:40].replace("\n", " ")
            log_info(
                f"[clip_video]   #{idx:03d} {seg['start']:.2f}s-{seg['end']:.2f}s "
                f"score={seg.get('score', 0):.4f} tags={tags} text='{text_hint}'"
            )
    return segments

def _get_min_clip_segment_seconds() -> float:
    cm = getattr(config, "config_manager", None)
    try:
        if cm is None:
            return float(MIN_CLIP_SEGMENT_SECONDS)
        value = cm.get("MIN_CLIP_SEGMENT_SECONDS", None)
        if value is None:
            value = cm.get("MIN_INTEREST_SEGMENT_DURATION", None)
        if value is None:
            return float(MIN_CLIP_SEGMENT_SECONDS)
        return float(value)
    except (TypeError, ValueError):
        return float(MIN_CLIP_SEGMENT_SECONDS)
from typing import List, Dict, Any

# 可选依赖：cv2
try:
    import cv2
    CV2_AVAILABLE = True
    log_info("[clip_video] OpenCV模块加载成功")
except ImportError as e:
    CV2_AVAILABLE = False
    log_warning(f"[clip_video] OpenCV模块导入失败: {e}")
    log_info("[clip_video] 将使用替代方法处理视频信息")

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
            
            # 生成输出文件名（符合 spec：clip_{rank}_{HHhMMmSSs}_{start_ms}-{end_ms}.mp4）
            segment_index = i + 1
            start_ms = int(round(start_time * 1000))
            end_ms = int(round(end_time * 1000))
            # 带上高光起点的可读时间戳，保持可预测命名
            hh = int(start_time // 3600)
            mm = int((start_time % 3600) // 60)
            ss = int(start_time % 60)
            t_label = f"{hh:02d}h{mm:02d}m{ss:02d}s"
            clip_filename = NAMING_POLICY.format(
                rank=segment_index, HHhMMmSSs=t_label, start_ms=start_ms, end_ms=end_ms
            )
            output_path = os.path.join(output_dir, clip_filename)
            # 保留 .mp4 扩展，避免 ffmpeg 无法识别输出格式
            tmp_output_path = os.path.join(
                output_dir, f"{Path(clip_filename).stem}.tmp{Path(clip_filename).suffix}"
            )
            
            # 清理可能存在的旧文件
            for stale in (output_path, tmp_output_path):
                if os.path.exists(stale):
                    try:
                        os.remove(stale)
                        log_info(f"[clip_video] 清理旧文件: {stale}")
                    except Exception as e:
                        log_warning(f"[clip_video] 清理旧文件失败: {e}")
            
            log_info(
                f"[clip_video] 生成切片 {i+1}/{len(segments)}: {clip_filename} "
                f"({duration:.1f}s) score={segment.get('score', 0):.4f} "
                f"tags={','.join(segment.get('reason_tags') or []) or '-'}"
            )
            
            # 使用快速切片函数
            try:
                # 先写入临时文件，再原子 rename，避免半写文件
                cut_video_ffmpeg(video_path, tmp_output_path, start_time, duration)
                if os.path.exists(tmp_output_path):
                    try:
                        os.replace(tmp_output_path, output_path)
                    except Exception:
                        # 如果 rename 失败，尝试复制后删除
                        import shutil
                        shutil.copy2(tmp_output_path, output_path)
                        os.remove(tmp_output_path)
                
                if os.path.exists(output_path):
                    clip_files.append(output_path)
                    size_mb = os.path.getsize(output_path) / (1024 * 1024)
                    log_info(f"[clip_video] 切片生成成功: {clip_filename} ({size_mb:.2f} MB)")
                    try:
                        report_path = os.path.join(output_dir, f"{Path(clip_filename).stem}.report.json")
                        report_payload = {
                            "clip_path": output_path,
                            "start": start_time,
                            "end": end_time,
                            "duration_sec": duration,
                            "score": float(segment.get("score", 0.0)),
                            "score_base": segment.get("score_base"),
                            "score_scale": segment.get("score_scale"),
                            "overlap_count": segment.get("overlap_count"),
                            "text": segment.get("text", ""),
                            "reason_tags": segment.get("reason_tags") or [],
                            "analysis_rank": segment.get("analysis_rank"),
                            "selection_mode": segment.get("selection_mode"),
                            "selection_reason": segment.get("selection_reason"),
                            "source_start": segment.get("source_start"),
                            "source_end": segment.get("source_end"),
                            "source_duration": segment.get("source_duration"),
                        }
                        with open(report_path, "w", encoding="utf-8") as f:
                            json.dump(report_payload, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        log_warning(f"[clip_video] 写入切片报告失败: {e}")
                     
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
    log_info(f"[clip_video] 启动剪辑 | video={video_path} analysis={analysis_file} out_dir={output_dir} audio_source={audio_source or '-'}")

    # 读取分析结果
    try:
        with open(analysis_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        segments = _normalize_segments_data(raw)
        log_info(f"[clip_video] 成功读取分析结果文件: {analysis_file}")
        log_info(f"[clip_video] 分析结果包含 {len(segments)} 个片段")
        semantic_policy = raw.get("policy") if isinstance(raw, dict) else None
        semantic_mode = bool(isinstance(semantic_policy, dict) and semantic_policy.get("target_duration_ms") is not None)
    except Exception as e:
        log_error(f"[clip_video] Error reading analysis file: {e}")
        log_error(f"[clip_video] 分析文件路径: {analysis_file}")
        log_error(f"[clip_video] 文件是否存在: {os.path.exists(analysis_file)}")
        return []
    else:
        if 'semantic_mode' not in locals():
            semantic_mode = False

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
    log_info(f"[clip_video] 目标切片窗口: min={MIN_CLIP_DURATION_SEC:.1f}s pref={PREF_CLIP_DURATION_SEC:.1f}s max={MAX_CLIP_DURATION_SEC:.1f}s")
    
    # 🆕 调试：检查传入的segments数据
    log_info(f"[clip_video] 收到 {len(segments)} 个片段")
    
    # 🆕 过滤无效片段
    valid_segments = []
    min_seg_seconds = _get_min_clip_segment_seconds()
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

        if end - start < min_seg_seconds:
            log_warning(
                f"[clip_video] 跳过过短片段 {i+1}: 持续时间={end-start:.1f}s (<{min_seg_seconds:.1f}s)"
            )
            continue

        valid_segments.append(seg)
        label = ""
        if seg.get("reason_tags"):
            label = f" tags={','.join(seg.get('reason_tags'))}"
        elif seg.get("text"):
            label = f" text={seg.get('text')[:30]}"
        log_info(f"[clip_video] 有效片段 {len(valid_segments)}: {start:.1f}s-{end:.1f}s, 评分={score:.3f}{label}")
    
    if len(valid_segments) == 0:
        log_error("[clip_video] ❌ 没有有效的片段数据！")
        return []
        
    log_info(f"[clip_video] 过滤后剩余 {len(valid_segments)} 个有效片段")
    segments = valid_segments  # 使用过滤后的片段
    
    cm = getattr(config, "config_manager", None)

    def _float_config(name, fallback):
        try:
            if cm is None:
                return float(fallback)
            value = cm.get(name, fallback)
            return float(value)
        except (TypeError, ValueError):
            return float(fallback)

    # 先设默认值，防止异常路径导致未赋值
    min_target = MIN_CLIP_DURATION_SEC
    pref_target = PREF_CLIP_DURATION_SEC
    max_target = MAX_CLIP_DURATION_SEC
    try:
        min_target_cfg = _float_config("MIN_TARGET_CLIP_DURATION", MIN_CLIP_DURATION_SEC)
        pref_target_cfg = _float_config("TARGET_CLIP_DURATION", max(min_target_cfg, PREF_CLIP_DURATION_SEC))
        max_target_cfg = _float_config("MAX_TARGET_CLIP_DURATION", max(pref_target_cfg, MAX_CLIP_DURATION_SEC))

        min_target = max(MIN_CLIP_DURATION_SEC, min_target_cfg)
        pref_target = max(PREF_CLIP_DURATION_SEC, pref_target_cfg, min_target)
        max_target = max(MAX_CLIP_DURATION_SEC, max_target_cfg, pref_target)
    except Exception as e:
        log_warning(f"[clip_video] 读取剪辑目标时长配置失败，使用默认 240/270/300s: {e}")

    if semantic_mode:
        log_info("[clip_video] 使用语义合并窗口（保留原始时长，非固定窗口）")
    else:
        # 基于分析排名生成固定窗口（约3-5分钟）切片
        log_info(
            f"[clip_video] 使用分析排名生成固定窗口切片 (min={min_target:.1f}s pref={pref_target:.1f}s max={max_target:.1f}s)"
        )

    context_extend = max(0.0, _float_config("CLIP_CONTEXT_EXTEND", 15.0))
    merge_threshold = max(0.0, _float_config("CLIP_MERGE_THRESHOLD", 10.0))
    coverage_ratio = _float_config("CLIP_COVERAGE_RATIO", 0.6)
    coverage_ratio = min(max(coverage_ratio, 0.0), 1.0)

    try:
        max_clips = int(cm.get("MAX_CLIP_COUNT", len(segments)) or len(segments))
    except Exception:
        max_clips = len(segments)

    processed_segments = []

    def _highlight_already_covered(start, end):
        highlight_len = max(1e-6, end - start)
        for existing in processed_segments:
            ext_start = existing['start'] - merge_threshold
            ext_end = existing['end'] + merge_threshold
            if start >= ext_start and end <= ext_end:
                return True
            overlap = max(0.0, min(existing['end'], end) - max(existing['start'], start))
            if overlap / highlight_len >= coverage_ratio:
                return True
        return False

    def _build_window(base_start, base_end):
        base_start = max(0.0, float(base_start))
        base_end = min(float(base_end), video_duration)
        if base_end - base_start <= 0:
            return base_start, base_end

        window_min = min(min_target, video_duration) if video_duration > 0 else min_target
        desired = max(window_min, pref_target, (base_end - base_start) + 2 * context_extend)
        desired = min(desired, max_target, video_duration if video_duration > 0 else desired)
        if desired < (base_end - base_start):
            desired = min(max_target, max(base_end - base_start, window_min))

        center = (base_start + base_end) / 2.0
        half = desired / 2.0
        start = center - half
        end = center + half

        if start < 0:
            shift = -start
            start = 0.0
            end = min(video_duration, end + shift)
        if end > video_duration:
            shift = end - video_duration
            end = video_duration
            start = max(0.0, start - shift)

        # Ensure minimum duration if possible
        def _extend_to(length):
            nonlocal start, end
            target = min(length, video_duration)
            while (end - start) + 1e-6 < target:
                deficit = target - (end - start)
                before = min(deficit / 2.0, start)
                start -= before
                deficit -= before
                after = min(deficit, video_duration - end)
                end += after
                deficit -= after
                if deficit <= 1e-6:
                    break
                # 尝试再次从两端补齐
                if start > 0 and deficit > 1e-6:
                    extra = min(deficit, start)
                    start -= extra
                    deficit -= extra
                if end < video_duration and deficit > 1e-6:
                    extra = min(deficit, video_duration - end)
                    end += extra
                    deficit -= extra
                if deficit <= 1e-6:
                    break
                # 无法继续扩展
                break

        _extend_to(window_min)
        if (end - start) < desired:
            _extend_to(desired)

        # Clamp to max duration while keeping highlight inside
        actual = end - start
        if actual > max_target:
            excess = actual - max_target
            slack_before = max(0.0, (base_start - start))
            reduce_before = min(slack_before, excess / 2.0)
            start += reduce_before
            excess -= reduce_before
            slack_after = max(0.0, (end - base_end))
            reduce_after = min(slack_after, excess)
            end -= reduce_after
            excess -= reduce_after
            if excess > 1e-6:
                center = (base_start + base_end) / 2.0
                start = max(0.0, center - max_target / 2.0)
                end = min(video_duration, start + max_target)
                if end - start < max_target and start > 0:
                    start = max(0.0, end - max_target)

        # Final guard to ensure the original highlight stays covered
        if start > base_start:
            start = max(0.0, base_start)
        if end < base_end:
            end = min(video_duration, base_end)

        return start, end

    if semantic_mode:
        for idx, seg in enumerate(segments):
            if len(processed_segments) >= max_clips:
                break
            clip_start = float(seg.get('start', 0.0))
            clip_end = float(seg.get('end', 0.0))
            duration = clip_end - clip_start
            if duration <= 1.0:
                log_warning(f"[clip_video] 跳过时长不足的语义窗口 #{idx+1}: {duration:.1f}s")
                continue
            processed_segments.append(
                {
                    'start': clip_start,
                    'end': clip_end,
                    'score': float(seg.get('score', 0.0)),
                    'text': seg.get('text', ''),
                    'analysis_rank': idx + 1,
                    'source_start': clip_start,
                    'source_end': clip_end,
                    'source_duration': max(0.0, duration),
                    'selection_mode': "semantic_windows",
                    'selection_reason': "semantic_similarity_window",
                }
            )
            log_info(
                f"[clip_video] 语义窗口 #{len(processed_segments)}: {clip_start:.1f}-{clip_end:.1f}s "
                f"(≈{duration/60:.2f}min, score={seg.get('score', 0)})"
            )
    else:
        for idx, seg in enumerate(segments):
            if len(processed_segments) >= max_clips:
                break

            base_start = float(seg.get('start', 0.0))
            base_end = float(seg.get('end', 0.0))
            if base_end - base_start <= 0:
                log_warning(f"[clip_video] 跳过长度异常的片段 #{idx+1}")
                continue

            if _highlight_already_covered(base_start, base_end):
                log_info(f"[clip_video] 片段 #{idx+1} 已包含在之前的窗口中，跳过重复")
                continue

            clip_start, clip_end = _build_window(base_start, base_end)
            duration = clip_end - clip_start
            if duration <= 1.0:
                log_warning(f"[clip_video] 跳过时长不足的窗口 #{idx+1}: {duration:.1f}s")
                continue

            processed_segments.append({
                'start': clip_start,
                'end': clip_end,
                'score': float(seg.get('score', 0.0)),
                'text': seg.get('text', ''),
                'analysis_rank': idx + 1,
                'source_start': base_start,
                'source_end': base_end,
                'source_duration': max(0.0, base_end - base_start),
                'selection_mode': "score_ranked_fixed",
                'selection_reason': "top_score_ranked_window",
            })
            log_info(f"[clip_video] 生成窗口 #{len(processed_segments)} "
                     f"来自排名#{idx+1}: {clip_start:.1f}-{clip_end:.1f}s "
                     f"(≈{duration/60:.2f}min, score={seg.get('score', 0)})")

    if not processed_segments:
        log_error("[clip_video] ❌ 未能生成任何符合条件的切片窗口")
        return []

    log_info(f"[clip_video] 计划切片总数: {len(processed_segments)} / 请求上限 {max_clips}")
    for i, ps in enumerate(processed_segments, 1):
        log_info(
            f"[clip_video] 计划#{i:03d} window={ps['start']:.2f}-{ps['end']:.2f}s "
            f"len={ps['end']-ps['start']:.2f}s score={ps.get('score',0):.4f} "
            f"from src {ps['source_start']:.2f}-{ps['source_end']:.2f}s"
        )
    
    # 保存处理计划
    plan_file = os.path.join(output_dir, "clip_plan.json")
    plan_data = {
        "mode": "semantic_windows" if semantic_mode else "score_ranked_fixed",
        "min_sec": min_target,
        "preferred_sec": pref_target,
        "max_sec": max_target,
        "context_extend": context_extend,
        "coverage_ratio": coverage_ratio,
        "merge_threshold": merge_threshold,
        "naming_policy": NAMING_POLICY,
        "segments": processed_segments,
        "video_duration": video_duration,
        "total_segments": len(processed_segments)
    }
    
    with open(plan_file, 'w', encoding='utf-8') as f:
        json.dump(plan_data, f, ensure_ascii=False, indent=2)
    
    log_info(f"[clip_video] 切片计划已保存到: {plan_file}")
    
    # 直接进入切片生成阶段
    clip_files = generate_clips_from_segments(video_path, processed_segments, output_dir, progress_callback, audio_source)

    # 汇总输出
    log_info(f"[clip_video] 切片任务完成: 成功 {len(clip_files)} / 计划 {len(processed_segments)}")
    for i, path in enumerate(clip_files, 1):
        size_mb = os.path.getsize(path) / (1024 * 1024) if os.path.exists(path) else 0
        log_info(f"[clip_video] 成品#{i:03d} {path} ({size_mb:.2f} MB)")

    return clip_files


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
