import os
import json
import warnings
import subprocess
import tempfile
import shutil
from pathlib import Path

# 配置GPU内存使用（兼容性设置）
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:128'
os.environ['CUDA_MEMORY_FRACTION'] = '0.9'  # 使用90%的GPU内存

# 过滤警告
warnings.filterwarnings("ignore", category=UserWarning, module="librosa")
warnings.filterwarnings("ignore", category=FutureWarning, module="librosa")

try:
    import librosa
    import numpy as np
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False

try:
    import soundfile as sf
    SOUNDFILE_AVAILABLE = True
except ImportError:
    SOUNDFILE_AVAILABLE = False

try:
    import whisper
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

from acfv.main_logging import log_info, log_error, log_debug
from acfv.runtime.storage import processing_path

def check_ffmpeg_availability():
    """检查ffmpeg是否可用"""
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, 
                              encoding='utf-8', errors='ignore', timeout=10)
        if result.returncode == 0:
            return True
    except Exception:
        pass
    return False

def get_audio_info_ffprobe(audio_path):
    """使用ffprobe获取音频信息"""
    try:
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json", 
            "-show_format", "-show_streams", str(audio_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, 
                              encoding='utf-8', errors='ignore', timeout=30)
        
        if result.returncode == 0:
            info = json.loads(result.stdout)
            
            # 获取音频流信息
            audio_stream = None
            for stream in info.get('streams', []):
                if stream.get('codec_type') == 'audio':
                    audio_stream = stream
                    break
            
            duration = float(info['format'].get('duration', 0))
            sample_rate = int(audio_stream.get('sample_rate', 16000)) if audio_stream else 16000
            channels = int(audio_stream.get('channels', 1)) if audio_stream else 1
            
            return {
                'duration': duration,
                'sample_rate': sample_rate,
                'channels': channels,
                'format': info['format'].get('format_name', 'unknown')
            }
    except Exception as e:
        log_error(f"ffprobe获取音频信息失败: {e}")
        return None

def get_audio_duration_ffmpeg_only(audio_path):
    """纯ffmpeg方式获取音频时长"""
    info = get_audio_info_ffprobe(audio_path)
    if info:
        duration = info['duration']
        log_info(f"[音频时长] {duration:.1f}秒 (采样率: {info['sample_rate']}Hz, 声道: {info['channels']})")
        return duration
    
    # 备用方法：使用librosa（仅小文件）
    try:
        file_size_gb = os.path.getsize(audio_path) / (1024**3)
        if file_size_gb <= 1 and LIBROSA_AVAILABLE:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                duration = librosa.get_duration(path=str(audio_path))
                log_info(f"[音频时长] 使用librosa获取: {duration:.1f}秒")
                return duration
    except Exception as e:
        log_debug(f"librosa备用方法失败: {e}")
    
    log_error("[音频时长] 无法获取，使用默认值")
    return 3600.0  # 默认1小时

def extract_audio_segment_ffmpeg(audio_path, start_time, end_time, output_path):
    """使用ffmpeg提取音频片段（尽可能零拷贝）"""
    try:
        duration = end_time - start_time
        
        # 优先使用输入寻址并直接复制（若源是pcm_s16le/16k/mono WAV）
        cmd = [
            "ffmpeg", "-y",
            "-hide_banner", "-loglevel", "error", "-nostdin",
            "-ss", str(start_time),  # 输入寻址更快
            "-i", str(audio_path),
            "-t", str(duration),
            # 直接输出为目标参数；若输入已是相同参数，内部将是复制
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-f", "wav",
            str(output_path)
        ]
        
        # 执行命令 - 修复编码问题
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True,
            encoding='utf-8',
            errors='ignore',  # 忽略编码错误
            timeout=300,
            check=True
        )
        
        # 检查输出文件
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            log_debug(f"[音频提取] ffmpeg成功: {start_time:.1f}-{end_time:.1f}s")
            return True
        else:
            log_error(f"[音频提取] 输出文件为空或不存在")
            return False
            
    except subprocess.TimeoutExpired:
        log_error(f"[音频提取] ffmpeg超时: {start_time}-{end_time}")
        return False
    except subprocess.CalledProcessError as e:
        log_error(f"[音频提取] ffmpeg失败: {e.stderr if e.stderr else 'unknown error'}")
        return False
    except Exception as e:
        log_error(f"[音频提取] ffmpeg异常: {e}")
        return False

def extract_audio_segment_librosa(audio_path, start_time, end_time, output_path):
    """使用librosa提取音频片段（备用方法，适合小文件）"""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            
            duration = end_time - start_time
            y, sr = librosa.load(
                str(audio_path), 
                sr=16000, 
                offset=start_time, 
                duration=duration,
                mono=True
            )
            
            # 保存音频文件
            if SOUNDFILE_AVAILABLE:
                sf.write(str(output_path), y, sr)
            else:
                # 使用scipy.io.wavfile作为备选
                try:
                    from scipy.io import wavfile
                    # 转换为int16格式
                    y_int16 = (y * 32767).astype(np.int16)
                    wavfile.write(str(output_path), sr, y_int16)
                except ImportError:
                    log_error("缺少soundfile和scipy库，无法保存音频")
                    return False
            
            log_debug(f"[音频提取] librosa成功: {start_time:.1f}-{end_time:.1f}s")
            return True
            
    except Exception as e:
        log_error(f"[音频提取] librosa失败: {e}")
        return False

def extract_audio_segment_safe(audio_path, start_time, end_time, output_path):
    """安全提取音频片段（优先ffmpeg，备选librosa）"""
    
    # 检查ffmpeg是否可用
    if not check_ffmpeg_availability():
        log_error("ffmpeg不可用，请安装ffmpeg")
        
        # 尝试使用librosa（仅适合小文件）
        file_size_gb = os.path.getsize(audio_path) / (1024**3)
        if file_size_gb <= 1 and LIBROSA_AVAILABLE:
            log_info("尝试使用librosa处理小文件...")
            return extract_audio_segment_librosa(audio_path, start_time, end_time, output_path)
        else:
            log_error("文件过大且ffmpeg不可用，无法处理")
            return False
    
    # 优先使用ffmpeg
    if extract_audio_segment_ffmpeg(audio_path, start_time, end_time, output_path):
        return True
    
    # ffmpeg失败时的备选方案
    file_size_gb = os.path.getsize(audio_path) / (1024**3)
    if file_size_gb <= 1 and LIBROSA_AVAILABLE:
        log_info("ffmpeg失败，尝试librosa备选方案...")
        return extract_audio_segment_librosa(audio_path, start_time, end_time, output_path)
    
    return False

def extract_audio_segment_enhanced(audio_path, start_time, end_time, output_path):
    """增强音频片段提取（针对低质量音频）"""
    try:
        duration = end_time - start_time
        
        # 构建增强的ffmpeg命令
        cmd = [
            "ffmpeg", "-y",  # 覆盖输出文件
            "-i", str(audio_path),
            "-ss", str(start_time),  # 开始时间
            "-t", str(duration),     # 持续时间
            "-acodec", "pcm_s16le",  # 音频编码
            "-ar", "16000",          # 采样率
            "-ac", "1",              # 单声道
            "-af", "highpass=f=50,lowpass=f=8000,volume=3.0,compand=0.3|0.3:1|1:-90/-60/-40/-20/-10/0:6:0:-90:0.2",  # 增强音频处理
            "-f", "wav",             # 输出格式
            str(output_path)
        ]
        
        # 执行命令
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True,
            encoding='utf-8',
            errors='ignore',
            timeout=600,
            check=True
        )
        
        # 检查输出文件
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            log_debug(f"[音频增强] 成功: {start_time:.1f}-{end_time:.1f}s")
            return True
        else:
            log_error(f"[音频增强] 输出文件为空或不存在")
            return False
            
    except subprocess.TimeoutExpired:
        log_error(f"[音频增强] ffmpeg超时: {start_time}-{end_time}")
        return False
    except subprocess.CalledProcessError as e:
        log_error(f"[音频增强] ffmpeg错误: {e}")
        return False
    except Exception as e:
        log_error(f"[音频增强] 未知错误: {e}")
        return False

def create_audio_segments(audio_path, segment_length=300):
    """创建音频片段列表"""
    total_duration = get_audio_duration_ffmpeg_only(audio_path)
    
    if total_duration <= 0:
        log_error("[分段] 无法获取有效的音频时长")
        return []
    
    segments = []
    current_time = 0
    segment_id = 0
    
    while current_time < total_duration:
        end_time = min(current_time + segment_length, total_duration)
        
        # 跳过太短的片段
        if end_time - current_time < 1.0:
            break
        
        segments.append({
            'id': segment_id,
            'start': current_time,
            'end': end_time,
            'duration': end_time - current_time
        })
        
        current_time = end_time
        segment_id += 1
    
    log_info(f"[分段] 创建了 {len(segments)} 个片段，总时长 {total_duration:.1f}秒")
    return segments

def transcribe_audio_segment_safe(audio_path, start_time, end_time, whisper_model):
    """安全转录音频片段"""
    temp_dir = None
    try:
        # 创建临时目录
        temp_dir = tempfile.mkdtemp(prefix="whisper_")
        temp_audio_path = os.path.join(temp_dir, f"segment_{start_time}_{end_time}.wav")
        
        # 提取音频片段
        log_debug(f"[转录] 开始提取音频片段: {start_time}-{end_time}")
        if not extract_audio_segment_safe(audio_path, start_time, end_time, temp_audio_path):
            log_error(f"[转录] 音频片段提取失败: {start_time}-{end_time}")
            return []
        log_debug(f"[转录] 音频片段提取成功: {temp_audio_path}")
        
        # 简单的音频质量检查（可选）
        try:
            import librosa
            audio_data, sr = librosa.load(temp_audio_path, sr=None)
            rms_energy = np.sqrt(np.mean(audio_data**2))
            log_debug(f"[音频质量] RMS能量: {rms_energy:.4f}, 音频长度: {len(audio_data)} 采样点")
            
            # 检查音频是否太安静
            if rms_energy < 0.001:
                log_warning(f"[音频质量] 音频太安静，可能没有语音内容，跳过该片段 {start_time}-{end_time}s")
                return []
        except Exception as e:
            log_debug(f"[音频质量] 音频质量检测失败: {e}")
        
        # 检查文件是否存在且不为空
        if not os.path.exists(temp_audio_path):
            log_error(f"[转录] 临时音频文件不存在: {temp_audio_path}")
            return []
        
        file_size = os.path.getsize(temp_audio_path)
        if file_size == 0:
            log_error(f"[转录] 临时音频文件为空: {temp_audio_path}")
            return []
        
        log_debug(f"[转录] 音频片段文件大小: {file_size} bytes")
        
        # 读取转录配置
        try:
            with settings_path("config.json").open("r", encoding="utf-8") as f:
                config_data = json.load(f)
            transcription_language = str(config_data.get("TRANSCRIPTION_LANGUAGE", "auto")).strip()
            no_speech_threshold = config_data.get("NO_SPEECH_THRESHOLD", 0.6)
            logprob_threshold = config_data.get("LOGPROB_THRESHOLD", -1.0)
        except Exception as e:
            log_debug(f"[转录] 无法读取配置，使用默认值: {e}")
            transcription_language = "auto"
            no_speech_threshold = 0.6
            logprob_threshold = -1.0

        # 使用Whisper转录
        if not WHISPER_AVAILABLE:
            log_error("[转录] Whisper不可用")
            return []

        # 验证GPU使用
        import torch
        if torch.cuda.is_available():
            log_debug(f"[转录] GPU内存使用前: {torch.cuda.memory_allocated() / 1024**2:.1f}MB")

        language_arg = None
        if transcription_language and str(transcription_language).strip().lower() not in {"auto", "default", "detect"}:
            language_arg = transcription_language
        fp16_enabled = torch.cuda.is_available()
        try:
            model_device = str(getattr(whisper_model, "device", "cuda" if torch.cuda.is_available() else "cpu"))
            fp16_enabled = fp16_enabled and model_device.startswith("cuda")
        except Exception:
            fp16_enabled = torch.cuda.is_available()

        # 按配置语言执行转录
        try:
            log_debug(f"[转录] 开始转录片段: {start_time}-{end_time} (language={language_arg or 'auto'})")
            result = whisper_model.transcribe(
                temp_audio_path,
                language=language_arg,
                initial_prompt="",
                no_speech_threshold=no_speech_threshold,
                logprob_threshold=logprob_threshold,
                word_timestamps=True,
                fp16=fp16_enabled,
            )
            log_debug(f"[转录] Whisper转录完成，结果类型: {type(result)}")
        except Exception as e:
            log_error(f"[转录] Whisper转录异常: {e}")
            # 尝试使用更简单的参数
            try:
                log_debug(f"[转录] 尝试简化参数转录...")
                result = whisper_model.transcribe(
                    temp_audio_path,
                    language=language_arg,
                    word_timestamps=True,
                    fp16=False,
                )
                log_debug(f"[转录] 简化转录完成")
            except Exception as e2:
                log_error(f"[转录] 简化转录也失败: {e2}")
                return []
        # 验证GPU使用后
        if torch.cuda.is_available():
            log_debug(f"[转录] GPU内存使用后: {torch.cuda.memory_allocated() / 1024**2:.1f}MB")
        
        # 处理转录结果
        segments = []
        if 'segments' in result:
            for seg in result['segments']:
                text = seg.get('text', '').strip()
                
                # 过滤掉默认提示文本和空文本
                if text and text != "This is English transcription content." and len(text) > 1:
                    segments.append({
                        'start': seg.get('start', 0) + start_time,  # 调整时间戳
                        'end': seg.get('end', 0) + start_time,
                        'text': text
                    })
        
        log_debug(f"[转录] 片段转录完成: {start_time}-{end_time}, {len(segments)}个有效句子")
        return segments
        
    except Exception as e:
        log_error(f"[转录] 片段转录失败 {start_time}-{end_time}: {e}")
        return []
        
    finally:
        # 清理临时文件
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                log_debug(f"清理临时目录失败: {e}")

def process_audio_segments(audio_path, output_file=None, 
                         segment_length=300, whisper_model_name="base", host_transcription_file=None):
    """
    处理音频片段（无pydub版本）
    if output_file is None:
        output_file = str(processing_path("transcription.json"))
    """
    log_info("=" * 60)
    log_info("🎤 开始音频转录处理（无pydub版本）")
    log_info("=" * 60)
    
    def should_stop():
        """检查是否应该停止处理"""
        try:
            stop_flag_file = processing_path("stop_flag.txt")
            return stop_flag_file.exists()
        except Exception:
            return False
    
    # 添加停止检查
    if should_stop():
        log_info("🛑 检测到停止信号，音频转录被中断")
        return None
    
    try:
        # 检查输入文件
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        
        file_size_gb = os.path.getsize(audio_path) / (1024**3)
        log_info(f"📁 文件大小: {file_size_gb:.2f}GB")
        
        # 停止检查
        if should_stop():
            log_info("🛑 检测到停止信号，音频转录在文件检查后被中断")
            return None
        
        # 检查必要工具
        if not check_ffmpeg_availability():
            if file_size_gb > 1:
                raise RuntimeError("处理大文件需要ffmpeg，请安装ffmpeg")
            elif not LIBROSA_AVAILABLE:
                raise RuntimeError("缺少ffmpeg和librosa，无法处理音频文件")
            else:
                log_info("⚠️ ffmpeg不可用，将使用librosa处理小文件")
        
        # 检查输出目录
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        
        # 加载Whisper模型
        if not WHISPER_AVAILABLE:
            raise ImportError("Whisper库不可用，请安装: pip install openai-whisper")
        
        # 检查GPU可用性
        import torch
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        
        # 尝试从配置读取GPU设置
        try:
            import json
            with settings_path("config.json").open("r", encoding="utf-8") as f:
                config_data = json.load(f)
            gpu_device = config_data.get("GPU_DEVICE", "cuda:0")
            enable_gpu = config_data.get("ENABLE_GPU_ACCELERATION", True)
            
            if enable_gpu and torch.cuda.is_available():
                device = gpu_device
                log_info(f"🤖 使用GPU设备: {device}")
                log_info(f"🤖 GPU信息: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A'}")
                log_info(f"🤖 GPU内存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f}GB" if torch.cuda.is_available() else 'N/A')
            else:
                device = "cpu"
                log_info(f"🤖 使用CPU设备 (GPU不可用或已禁用)")
        except Exception as e:
            log_info(f"🤖 无法读取GPU配置，使用默认设置: {device}")
        
        log_info(f"🤖 加载Whisper模型: {whisper_model_name} (设备: {device})")
        
        # 修复PyTorch版本兼容性问题
        try:
            whisper_model = whisper.load_model(whisper_model_name, device=device)
        except Exception as e:
            if "meta tensor" in str(e).lower():
                log_info("🤖 检测到PyTorch版本兼容性问题，使用to_empty()方法...")
                # 先加载到CPU，然后转移到目标设备
                whisper_model = whisper.load_model(whisper_model_name, device="cpu")
                if device != "cpu":
                    try:
                        whisper_model = whisper_model.to_empty(device=device)
                    except AttributeError:
                        # 如果to_empty不可用，使用传统方法
                        whisper_model = whisper_model.to(device)
            else:
                raise e
        
        # 配置GPU内存管理
        if device.startswith('cuda'):
            import torch
            # 设置内存分配策略
            torch.cuda.set_per_process_memory_fraction(0.9)  # 使用90%的GPU内存
            torch.cuda.empty_cache()  # 清空缓存
            
            # 显示内存信息
            total_memory = torch.cuda.get_device_properties(0).total_memory
            allocated_memory = torch.cuda.memory_allocated()
            log_info(f"🤖 GPU内存: {total_memory / 1024**3:.1f}GB (已用: {allocated_memory / 1024**3:.1f}GB)")
        
        # 验证模型是否在正确的设备上
        if hasattr(whisper_model, 'encoder'):
            model_device = next(whisper_model.encoder.parameters()).device
            log_info(f"🤖 模型实际设备: {model_device}")
            if str(model_device) != device:
                log_error(f"🤖 警告: 模型设备不匹配! 期望: {device}, 实际: {model_device}")
        
        # 创建音频片段
        log_info("📊 分析音频文件...")
        segments = create_audio_segments(audio_path, segment_length)
        
        if not segments:
            raise ValueError("无法创建音频片段")
            
        # 检查音频文件是否存在（由pipeline_backend.py已经提取）
        output_dir = os.path.dirname(output_file)
        audio_save_dir = os.path.join(output_dir, "audio")
        audio_save_path = os.path.join(audio_save_dir, "extracted_audio.wav")
        
        # 验证音频文件是否存在
        if os.path.exists(audio_save_path):
            file_size_mb = os.path.getsize(audio_save_path) / (1024 * 1024)
            log_info(f"✅ 使用已提取的音频文件: {audio_save_path} ({file_size_mb:.1f}MB)")
        else:
            log_error(f"❌ 音频文件不存在: {audio_save_path}，请确保pipeline_backend.py已正确提取音频")
            raise FileNotFoundError(f"音频文件不存在: {audio_save_path}")
        
        log_info(f"🔄 开始处理 {len(segments)} 个片段...")
        
        # 处理所有片段
        all_transcription_results = []
        
        for i, segment in enumerate(segments, 1):
            log_info(f"[{i}/{len(segments)}] 处理片段 {segment['start']:.1f}-{segment['end']:.1f}s")
            
            try:
                segment_results = transcribe_audio_segment_safe(
                    audio_path, 
                    segment['start'], 
                    segment['end'], 
                    whisper_model
                )
                
                all_transcription_results.extend(segment_results)
                
                log_info(f"✅ 片段 {i} 完成，获得 {len(segment_results)} 个句子")
                
            except Exception as e:
                log_error(f"❌ 片段 {i} 处理失败: {e}")
                continue
        
        # 保存结果
        log_info(f"💾 保存转录结果到: {output_file}")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_transcription_results, f, ensure_ascii=False, indent=2)
        
        # 如果指定了主播转录文件，保存主播专用转录结果
        if host_transcription_file:
            log_info(f"💾 保存主播转录结果到: {host_transcription_file}")
            # 对于主播音频，转录结果就是主播的转录
            host_transcription_results = all_transcription_results.copy()
            
            # 添加主播标识信息
            for result in host_transcription_results:
                result['speaker'] = 'host'
                result['is_host'] = True
            
            with open(host_transcription_file, 'w', encoding='utf-8') as f:
                json.dump(host_transcription_results, f, ensure_ascii=False, indent=2)
            
            log_info(f"📝 主播转录片段数量: {len(host_transcription_results)}")
        
        log_info("=" * 60)
        log_info(f"✅ 音频转录完成！")
        log_info(f"📝 总共获得 {len(all_transcription_results)} 个转录片段")
        log_info(f"📄 结果文件: {output_file}")
        if host_transcription_file:
            log_info(f"📄 主播转录文件: {host_transcription_file}")
        log_info("=" * 60)
        
        if not all_transcription_results:
            try:
                audio_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
            except Exception:
                audio_size_mb = -1
            log_warning(f"⚠️ 转录完成但没有得到任何文本片段，请检查音频内容或阈值设置 (audio_size_mb={audio_size_mb:.2f})")
        
        return all_transcription_results
        
    except Exception as e:
        log_error(f"❌ 音频转录失败: {e}")
        raise

def check_gpu_availability():
    """检查GPU可用性"""
    try:
        import torch
        if torch.cuda.is_available():
            log_info("✅ GPU可用")
            log_info(f"🤖 GPU设备: {torch.cuda.get_device_name(0)}")
            log_info(f"🤖 GPU内存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f}GB")
            log_info(f"🤖 CUDA版本: {torch.version.cuda}")
            
            # 显示内存配置
            log_info("🤖 GPU内存配置:")
            log_info(f"  - 专用内存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f}GB")
            log_info(f"  - 共享内存: 启用 (通过系统内存)")
            log_info(f"  - 内存分配: 90%专用 + 共享内存")
            
            return True
        else:
            log_info("❌ GPU不可用")
            return False
    except Exception as e:
        log_error(f"❌ GPU检测失败: {e}")
        return False

def monitor_gpu_memory():
    """监控GPU内存使用"""
    try:
        import torch
        if torch.cuda.is_available():
            total_memory = torch.cuda.get_device_properties(0).total_memory
            allocated_memory = torch.cuda.memory_allocated()
            reserved_memory = torch.cuda.memory_reserved()
            
            log_info(f"📊 GPU内存监控:")
            log_info(f"  - 专用内存: {total_memory / 1024**3:.1f}GB")
            log_info(f"  - 已分配: {allocated_memory / 1024**3:.1f}GB")
            log_info(f"  - 已保留: {reserved_memory / 1024**3:.1f}GB")
            log_info(f"  - 可用: {(total_memory - reserved_memory) / 1024**3:.1f}GB")
            
            # 计算使用率
            usage_percent = (reserved_memory / total_memory) * 100
            log_info(f"  - 使用率: {usage_percent:.1f}%")
            
            return {
                'total': total_memory,
                'allocated': allocated_memory,
                'reserved': reserved_memory,
                'usage_percent': usage_percent
            }
    except Exception as e:
        log_error(f"❌ GPU内存监控失败: {e}")
        return None

def install_dependencies():
    """检查并提示安装依赖"""
    missing_deps = []
    
    if not check_ffmpeg_availability():
        missing_deps.append("ffmpeg (推荐安装，处理大文件必需)")
    
    if not LIBROSA_AVAILABLE:
        missing_deps.append("librosa (pip install librosa)")
    
    if not SOUNDFILE_AVAILABLE:
        missing_deps.append("soundfile (pip install soundfile)")
    
    if not WHISPER_AVAILABLE:
        missing_deps.append("whisper (pip install openai-whisper)")
    
    if missing_deps:
        log_info("⚠️ 缺少以下依赖：")
        for dep in missing_deps:
            log_info(f"  - {dep}")
        return False
    
    log_info("✅ 所有依赖都已安装")
    
    # 检查GPU
    check_gpu_availability()
    
    return True

if __name__ == "__main__":
    import sys
    
    # 检查依赖
    if not install_dependencies():
        print("请安装缺少的依赖后重试")
        sys.exit(1)
    
    if len(sys.argv) < 2:
        print("用法: python transcribe_audio.py <音频文件路径> [输出文件路径]")
        sys.exit(1)
    
    audio_path = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else str(processing_path("transcription.json"))
    
    try:
        process_audio_segments(audio_path, output_file)
        print("转录完成！")
    except Exception as e:
        print(f"转录失败: {e}")
        sys.exit(1)
