import os

# 设置环境变量避免多线程冲突
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

# 如果使用torch
try:
    import torch
    torch.set_num_threads(1)
except ImportError:
    pass

import json
from pathlib import Path
from acfv import config
from acfv.main_logging import log_debug, log_info, log_error, log_warning
import math
import datetime
import time
import threading
import subprocess
import hashlib
import tempfile
import concurrent.futures
from functools import lru_cache
import multiprocessing as mp
import shutil

from acfv.runtime.storage import processing_path, settings_path

# 占位，避免未调用导入时变量未定义
np = None
faiss = None
TfidfVectorizer = None
pickle = None
AudioSegment = None
librosa = None
nltk = None
SentimentIntensityAnalyzer = None

# 延迟导入重库
def import_heavy_libraries():
    """延迟导入重库"""
    global np, faiss, TfidfVectorizer, pickle, AudioSegment, librosa, nltk, SentimentIntensityAnalyzer
    
    try:
        import numpy as np
    except ImportError:
        log_error("numpy导入失败")
        np = None
    
    try:
        import faiss
    except ImportError:
        log_error("faiss导入失败")
        faiss = None
    
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
    except ImportError:
        log_error("sklearn导入失败")
        TfidfVectorizer = None
    
    try:
        import pickle
    except ImportError:
        log_error("pickle导入失败")
        pickle = None
    
    try:
        from pydub import AudioSegment
    except ImportError:
        log_error("pydub导入失败")
        AudioSegment = None
    
    try:
        import librosa
    except ImportError:
        log_error("librosa导入失败")
        librosa = None
    
    try:
        import nltk
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
    except ImportError:
        log_error("nltk导入失败")
        nltk = None
        SentimentIntensityAnalyzer = None

# 尝试导入RAG向量数据库
try:
    from acfv.rag_vector_database import RAGVectorDatabase
    RAG_DATABASE_AVAILABLE = True
except ImportError as e:
    log_info(f"RAG向量数据库不可用: {e}")
    RAG_DATABASE_AVAILABLE = False

# 尝试导入tqdm，如果不可用则使用简单进度显示
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False

# GPU加速相关导入
try:
    import torch
    import torch.nn.functional as F
    from torch.cuda.amp import autocast
    from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
    GPU_AVAILABLE = torch.cuda.is_available()
except ImportError as e:
    log_error(f"[analyze_data] GPU库导入失败: {e}")
    GPU_AVAILABLE = False
    torch = None

# 延迟初始化VADER词库
sid = None

def init_vader():
    """延迟初始化VADER情感分析"""
    global sid
    if sid is None:
        try:
            import_heavy_libraries()
            if SentimentIntensityAnalyzer:
                sid = SentimentIntensityAnalyzer()
            else:
                log_error("[analyze_data] VADER情感分析库不可用")
        except:
            try:
                if nltk:
                    nltk.download('vader_lexicon')
                    sid = SentimentIntensityAnalyzer()
            except:
                log_error("[analyze_data] VADER情感分析库初始化失败")
                sid = None

# ============================================================================
# 断点续传系统
# ============================================================================

class CheckpointManager:
    """断点续传管理器"""
    
    def __init__(self, base_dir=None):
        if base_dir is None:
            base_dir = str(processing_path())
        self.base_dir = base_dir
        self.checkpoint_file = os.path.join(base_dir, "analysis_checkpoint.json")
        self.metadata_file = os.path.join(base_dir, "analysis_metadata.json")
        self.backup_dir = os.path.join(base_dir, "checkpoints_backup")
        
        # 确保目录存在
        os.makedirs(base_dir, exist_ok=True)
        os.makedirs(self.backup_dir, exist_ok=True)
    
    def has_checkpoint(self):
        """检查是否存在检查点"""
        return os.path.exists(self.checkpoint_file) and os.path.exists(self.metadata_file)
    
    def get_checkpoint_info(self):
        """获取检查点信息"""
        if not self.has_checkpoint():
            return None
        
        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint_data = json.load(f)
            
            return {
                'metadata': metadata,
                'processed_count': len(checkpoint_data.get('processed_segments', [])),
                'total_count': metadata.get('total_segments', 0),
                'last_save_time': metadata.get('last_save_time', ''),
                'video_path': metadata.get('video_path', ''),
                'config_hash': metadata.get('config_hash', '')
            }
        except Exception as e:
            log_error(f"[检查点] 读取检查点信息失败: {e}")
            return None
    
    def save_checkpoint(self, processed_segments, metadata, current_index):
        """保存检查点"""
        try:
            # 备份现有检查点
            if self.has_checkpoint():
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_checkpoint = os.path.join(self.backup_dir, f"checkpoint_{timestamp}.json")
                backup_metadata = os.path.join(self.backup_dir, f"metadata_{timestamp}.json")
                
                try:
                    shutil.copy2(self.checkpoint_file, backup_checkpoint)
                    shutil.copy2(self.metadata_file, backup_metadata)
                except:
                    pass  # 备份失败不影响主流程
            
            # 更新元数据
            metadata.update({
                'last_save_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'current_index': current_index,
                'processed_count': len(processed_segments)
            })
            
            # 保存检查点数据
            checkpoint_data = {
                'processed_segments': processed_segments,
                'current_index': current_index,
                'save_time': time.time()
            }
            
            # 原子写入（先写临时文件，再重命名）
            temp_checkpoint = self.checkpoint_file + ".tmp"
            temp_metadata = self.metadata_file + ".tmp"
            
            with open(temp_checkpoint, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, ensure_ascii=False, indent=2)
            
            with open(temp_metadata, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            
            # 原子重命名
            os.replace(temp_checkpoint, self.checkpoint_file)
            os.replace(temp_metadata, self.metadata_file)
            
            log_info(f"[检查点] 已保存检查点: {len(processed_segments)}/{metadata.get('total_segments', 0)} 片段")
            return True
            
        except Exception as e:
            log_error(f"[检查点] 保存检查点失败: {e}")
            return False
    
    def load_checkpoint(self):
        """加载检查点"""
        if not self.has_checkpoint():
            return None, None
        
        try:
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint_data = json.load(f)
            
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            processed_segments = checkpoint_data.get('processed_segments', [])
            current_index = checkpoint_data.get('current_index', 0)
            
            log_info(f"[检查点] 已加载检查点: {len(processed_segments)} 个已处理片段，从第 {current_index} 个继续")
            return processed_segments, metadata
            
        except Exception as e:
            log_error(f"[检查点] 加载检查点失败: {e}")
            return None, None
    
    def clear_checkpoint(self):
        """清理检查点文件"""
        try:
            if os.path.exists(self.checkpoint_file):
                os.remove(self.checkpoint_file)
            if os.path.exists(self.metadata_file):
                os.remove(self.metadata_file)
            log_info("[检查点] 检查点文件已清理")
        except Exception as e:
            log_error(f"[检查点] 清理检查点失败: {e}")
    
    def create_metadata(self, video_path, transcription_file, chat_file, config_params):
        """创建元数据"""
        config_hash = hashlib.md5(json.dumps(config_params, sort_keys=True).encode()).hexdigest()
        
        return {
            'video_path': video_path,
            'transcription_file': transcription_file,
            'chat_file': chat_file,
            'config_hash': config_hash,
            'config_params': config_params,
            'start_time': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'total_segments': 0  # 将在处理时更新
        }
    
    def is_config_compatible(self, current_config, saved_metadata):
        """检查配置是否兼容"""
        if not saved_metadata:
            return False
        
        current_hash = hashlib.md5(json.dumps(current_config, sort_keys=True).encode()).hexdigest()
        saved_hash = saved_metadata.get('config_hash', '')
        
        return current_hash == saved_hash

# 全局检查点管理器
checkpoint_manager = CheckpointManager()

# ============================================================================
# 🚀 超快特征提取器 - 解决27秒/片段的问题
# ============================================================================

class UltraFastExtractor:
    """超快特征提取器 - 一次性加载音频，预计算所有特征"""
    
    def __init__(self, video_path, max_workers=4):
        self.video_path = video_path
        self.max_workers = max_workers
        import_heavy_libraries()
        if librosa is None or np is None:
            log_error("❌ [超快提取器] 依赖缺失（librosa/np），回退到简化模式")
            self.use_fallback = True
            self.full_audio = None
            return
        
        log_info("🚀 [超快提取器] 初始化...")
        start_time = time.time()
        
        try:
            # 关键优化1：一次性加载完整音频文件到内存
            log_info("🔄 [超快提取器] 预加载完整音频文件 (优先 soundfile 后端)...")
            try:
                self.full_audio, self.sr = librosa.load(
                    video_path, sr=22050, backend="soundfile", mono=True, dtype="float32"
                )
                backend_used = "soundfile"
            except Exception as e:
                log_warning(f"[超快提取器] soundfile 后端失败: {e}; 改用默认 audioread")
                self.full_audio, self.sr = librosa.load(
                    video_path, sr=22050, mono=True, dtype="float32"
                )
                backend_used = "audioread"
            self.duration = len(self.full_audio) / self.sr
            load_time = time.time() - start_time
            log_info(f"✅ [超快提取器] 音频已预加载: {self.duration:.1f}s, 耗时: {load_time:.1f}s, backend={backend_used}")
            
            # 关键优化2：预计算整个音频的频谱特征
            log_info("🔄 [超快提取器] 预计算全局音频特征...")
            self._precompute_global_features()
            
            total_time = time.time() - start_time
            log_info(f"✅ [超快提取器] 初始化完成，总耗时: {total_time:.1f}s")
            
        except Exception as e:
            log_error(f"❌ [超快提取器] 初始化失败: {e}")
            # 回退到简单模式
            self.full_audio = None
            self.use_fallback = True
    
    def _precompute_global_features(self):
        """预计算整个音频的特征，避免重复计算"""
        try:
            hop_length = 512
            n_fft = 1024
            
            # 计算整个音频的STFT（最耗时的操作）
            self.stft = librosa.stft(self.full_audio, hop_length=hop_length, n_fft=n_fft)
            self.magnitude = np.abs(self.stft)
            
            # 预计算常用特征
            self.spectral_flatness = librosa.feature.spectral_flatness(S=self.magnitude)[0]
            self.zero_crossing_rate = librosa.feature.zero_crossing_rate(
                self.full_audio, hop_length=hop_length
            )[0]
            self.rms_energy = librosa.feature.rms(y=self.full_audio, hop_length=hop_length)[0]
            
            # 时间轴转换
            self.feature_times = librosa.frames_to_time(
                np.arange(len(self.spectral_flatness)), 
                sr=self.sr, hop_length=hop_length
            )
            
            log_info(f"🔢 [超快提取器] 预计算特征维度: {len(self.spectral_flatness)} 帧")
            self.use_fallback = False
            
        except Exception as e:
            log_error(f"❌ [超快提取器] 预计算失败: {e}")
            self.use_fallback = True
    
    def extract_music_features_optimized(self, start_sec, end_sec):
        """优化的音乐特征提取 - 从预计算结果中切片"""
        if hasattr(self, 'use_fallback') and self.use_fallback:
            return self._fallback_music_features(start_sec, end_sec)
        
        try:
            # 找到对应的特征帧索引
            start_frame = np.searchsorted(self.feature_times, start_sec)
            end_frame = np.searchsorted(self.feature_times, end_sec)
            
            if start_frame >= end_frame or end_frame > len(self.feature_times):
                return 0.0
            
            # 直接从预计算特征中切片 (毫秒级操作!)
            segment_spectral_flatness = self.spectral_flatness[start_frame:end_frame]
            segment_zcr = self.zero_crossing_rate[start_frame:end_frame]
            
            # 快速统计计算
            if len(segment_spectral_flatness) == 0 or len(segment_zcr) == 0:
                return 0.0
                
            spectral_flatness_mean = np.mean(segment_spectral_flatness)
            zcr_mean = np.mean(segment_zcr)
            
            # 音乐概率计算
            music_prob = spectral_flatness_mean * 0.6 + (1 - zcr_mean) * 0.4
            return float(np.clip(music_prob, 0, 1))
            
        except Exception as e:
            log_debug(f"音乐特征提取失败 {start_sec}-{end_sec}: {e}")
            return 0.0
    
    def extract_volume_features_optimized(self, start_sec, end_sec):
        """优化的音量特征提取 - 从预计算结果中切片"""
        if hasattr(self, 'use_fallback') and self.use_fallback:
            return self._fallback_volume_features(start_sec, end_sec)
        
        try:
            # 找到对应的特征帧索引
            start_frame = np.searchsorted(self.feature_times, start_sec)
            end_frame = np.searchsorted(self.feature_times, end_sec)
            
            if start_frame >= end_frame or end_frame > len(self.feature_times):
                return -100.0
            
            # 直接从预计算特征中切片
            segment_rms = self.rms_energy[start_frame:end_frame]
            
            if len(segment_rms) == 0:
                return -100.0
            
            rms_mean = np.mean(segment_rms)
            
            if rms_mean > 0:
                db_value = 20 * np.log10(rms_mean)
                return float(max(db_value, -100.0))
            else:
                return -100.0
                
        except Exception as e:
            log_debug(f"音量计算失败: {e}")
            return -100.0
    
    def _fallback_music_features(self, start_sec, end_sec):
        """回退方法 - 简单估算"""
        return 0.3  # 默认中等音乐概率
    
    def _fallback_volume_features(self, start_sec, end_sec):
        """回退方法 - 简单估算"""
        return -30.0  # 默认音量
    
    def batch_extract_features(self, segments_batch):
        """批量提取特征 - 超快版本"""
        if not segments_batch:
            return []
        
        results = []
        
        if hasattr(self, 'use_fallback') and self.use_fallback:
            # 回退模式
            for seg_info in segments_batch:
                results.append({
                    'music_probability': 0.3,
                    'loud_db': -30.0
                })
            return results
        
        try:
            # 向量化批量处理
            starts = np.array([seg['start'] for seg in segments_batch])
            ends = np.array([seg['end'] for seg in segments_batch])
            
            # 批量查找帧索引
            start_frames = np.searchsorted(self.feature_times, starts)
            end_frames = np.searchsorted(self.feature_times, ends)
            
            for i, (start_frame, end_frame) in enumerate(zip(start_frames, end_frames)):
                if start_frame >= end_frame or end_frame > len(self.feature_times):
                    results.append({'music_probability': 0.0, 'loud_db': -100.0})
                    continue
                
                # 直接切片计算（超快！）
                sf_segment = self.spectral_flatness[start_frame:end_frame]
                zcr_segment = self.zero_crossing_rate[start_frame:end_frame]
                rms_segment = self.rms_energy[start_frame:end_frame]
                
                # 快速统计
                sf_mean = np.mean(sf_segment) if len(sf_segment) > 0 else 0
                zcr_mean = np.mean(zcr_segment) if len(zcr_segment) > 0 else 0
                rms_mean = np.mean(rms_segment) if len(rms_segment) > 0 else 0
                
                music_prob = np.clip(sf_mean * 0.6 + (1 - zcr_mean) * 0.4, 0, 1)
                loud_db = 20 * np.log10(rms_mean) if rms_mean > 0 else -100.0
                loud_db = max(loud_db, -100.0)
                
                results.append({
                    'music_probability': float(music_prob),
                    'loud_db': float(loud_db)
                })
            
            return results
            
        except Exception as e:
            log_error(f"批量特征提取失败: {e}")
            # 回退到简单结果
            return [
                {'music_probability': 0.3, 'loud_db': -30.0} 
                for _ in segments_batch
            ]

def ultra_fast_parallel_extraction(feature_extractor, all_segments, max_workers=4, 
                                  checkpoint_interval=10, progress_callback=None):
    """超快并行特征提取 - 替换原来的慢速版本"""
    log_info(f"⚡ [超快并行] 开始超快特征提取: {len(all_segments)} 个片段")
    
    start_time = time.time()
    
    # 检查是否是超快提取器
    if isinstance(feature_extractor, UltraFastExtractor):
        # 使用超快提取器，不需要复杂的并行处理
        batch_size = 100  # 批次处理
        all_features = []
        processed_count = 0
        
        if TQDM_AVAILABLE:
            progress_bar = tqdm(total=len(all_segments), desc="⚡超快特征提取", unit="seg")
        
        for i in range(0, len(all_segments), batch_size):
            batch = all_segments[i:i + batch_size]
            batch_features = feature_extractor.batch_extract_features(batch)
            all_features.extend(batch_features)
            processed_count += len(batch)
            
            if TQDM_AVAILABLE:
                progress_bar.update(len(batch))
            
            # 发送进度回调
            if progress_callback:
                try:
                    progress_callback("⚡超快特征计算", processed_count, len(all_segments), 
                                    f"已处理 {processed_count}/{len(all_segments)} 个片段")
                except:
                    pass
        
        if TQDM_AVAILABLE:
            progress_bar.close()
        
        elapsed = time.time() - start_time
        speed = len(all_segments) / elapsed if elapsed > 0 else float('inf')
        log_info(f"⚡ [超快并行] 完成! 耗时: {elapsed:.1f}s, 速度: {speed:.0f} 片段/秒")
        
        return all_features
    
    else:
        # 回退到原来的方法
        log_info("🔄 [超快并行] 回退到标准并行处理...")
        return parallel_feature_extraction_with_checkpoint_original(
            feature_extractor, all_segments, max_workers, checkpoint_interval, progress_callback
        )

# 保留原来的并行处理函数作为备用
def parallel_feature_extraction_with_checkpoint_original(feature_extractor, all_segments, max_workers=4, 
                                                        checkpoint_interval=10, progress_callback=None):
    """原来的并行特征提取函数 - 作为备用"""
    log_info(f"[标准并行] 开始标准并行特征提取，使用 {max_workers} 个进程")
    
    batch_size = max(1, len(all_segments) // (max_workers * 2))
    batches = [all_segments[i:i + batch_size] for i in range(0, len(all_segments), batch_size)]
    
    all_features = []
    processed_count = 0
    
    if TQDM_AVAILABLE:
        progress_bar = tqdm(total=len(all_segments), desc="标准特征提取", unit="seg")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_batch = {
            executor.submit(feature_extractor.batch_extract_features, batch): (i, batch) 
            for i, batch in enumerate(batches)
        }
        
        for future in concurrent.futures.as_completed(future_to_batch):
            batch_index, batch = future_to_batch[future]
            try:
                batch_features = future.result()
                all_features.extend(batch_features)
                processed_count += len(batch)
                
                if TQDM_AVAILABLE:
                    progress_bar.update(len(batch))
                
                # 发送进度回调
                if progress_callback:
                    try:
                        progress_callback("特征计算", processed_count, len(all_segments), 
                                        f"已处理 {processed_count}/{len(all_segments)} 个片段")
                    except:
                        pass
                        
            except Exception as e:
                log_error(f"[标准并行] 批次 {batch_index} 处理失败: {e}")
                all_features.extend([
                    {'music_probability': 0.0, 'loud_db': -100.0} 
                    for _ in batch
                ])
                
                if TQDM_AVAILABLE:
                    progress_bar.update(len(batch))
    
    if TQDM_AVAILABLE:
        progress_bar.close()
    
    log_info(f"[标准并行] 标准并行特征提取完成，处理了 {len(all_features)} 个片段")
    return all_features

# 兼容原接口的函数别名
parallel_feature_extraction_with_checkpoint = ultra_fast_parallel_extraction

# ============================================================================
# 优化的文本分析器
# ============================================================================

class OptimizedTextAnalyzer:
    """优化的文本分析器 - 减少GPU模型重复加载"""

    def __init__(self, device=None):
        self.device = device
        self.model_loaded = False
        self.sentiment_pipeline = None

        # 尝试预加载GPU模型
        if device and torch and GPU_AVAILABLE:
            self._try_load_gpu_model()

    def _try_load_gpu_model(self):
        """尝试预加载情感分析模型（优先GPU，失败则CPU）"""
        try:
            log_info("🔄 [文本分析器] 预加载情感分析模型...")

            device_id = self.device.index if self.device and getattr(self.device, 'type', None) == 'cuda' else -1
            stable_model = "cardiffnlp/twitter-roberta-base-sentiment-latest"

            try:
                self.sentiment_pipeline = pipeline(
                    "sentiment-analysis",
                    model=stable_model,
                    device=device_id,
                    batch_size=16,
                    truncation=True,
                    max_length=128,
                    return_all_scores=False,
                )
            except Exception:
                log_info("🔄 [文本分析器] 切换为CPU加载...")
                self.sentiment_pipeline = pipeline(
                    "sentiment-analysis",
                    model=stable_model,
                    device=-1,
                    batch_size=8,
                    truncation=True,
                    max_length=128,
                )

            self.model_loaded = True
            log_info("✅ [文本分析器] 模型已预加载")
        except Exception as e:
            log_error(f"⚠️ [文本分析器] 模型加载失败: {e}")
            self.model_loaded = False

# ============================================================================
# ACFV 兼容导出（模块级函数）
# ============================================================================

def _write_acfv_exports(output_dir, ratings_data, selected_segments):
    """写出与 ACFV 风格兼容的导出文件。

    输出:
    - acfv_ratings.jsonl: 每行一个片段，包含 start/end/score/text/file
    - acfv_selected.json: 选择的片段列表 clips：[...]
    """
    try:
        os.makedirs(output_dir, exist_ok=True)

        # 1) 全量评分 JSONL（便于外部工具消费）
        acfv_ratings_path = os.path.join(output_dir, 'acfv_ratings.jsonl')
        with open(acfv_ratings_path, 'w', encoding='utf-8') as f:
            for file_name, data in ratings_data.items():
                rec = {
                    'file': file_name,
                    'start': float(data.get('start', 0.0)),
                    'end': float(data.get('end', 0.0)),
                    'duration': float(data.get('duration', 0.0)),
                    'score': float(data.get('rating', 0.0)),
                    'text': data.get('text', ''),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # 2) 已选片段 JSON（Top-N）
        acfv_selected_path = os.path.join(output_dir, 'acfv_selected.json')
        clips = []
        for i, seg in enumerate(selected_segments, 1):
            s = float(seg.get('start', 0.0))
            e = float(seg.get('end', 0.0))
            name = f"clip_{i:03d}_{s:.1f}s-{e:.1f}s.mp4"
            clips.append({
                'index': i,
                'file': name,
                'start': s,
                'end': e,
                'duration': max(0.0, e - s),
                'score': float(seg.get('score', 0.0)),
                'text': seg.get('text', ''),
            })
        with open(acfv_selected_path, 'w', encoding='utf-8') as f:
            json.dump({'clips': clips, 'count': len(clips)}, f, ensure_ascii=False, indent=2)

        log_info(f"✅ ACFV兼容导出完成: {acfv_ratings_path}, {acfv_selected_path}")
    except Exception as e:
        log_error(f"❌ 写入 ACFV 兼容导出失败: {e}")

# 全局文本分析器实例
_global_text_analyzer = None

def get_text_analyzer(device=None):
    """获取全局文本分析器实例"""
    global _global_text_analyzer
    if _global_text_analyzer is None:
        _global_text_analyzer = OptimizedTextAnalyzer(device)
    return _global_text_analyzer

# ============================================================================
# 基础函数（保持不变）
# ============================================================================

def load_gui_config():
    """从GUI配置文件加载配置 (settings/config.json)"""
    config = {
        "WHISPER_MODEL": "small",
        "GPU_DEVICE": "cuda:0",
        "ENABLE_GPU_ACCELERATION": True,
        "LLM_DEVICE": 0,
        "CHAT_DENSITY_WEIGHT": 0.3,
        "CHAT_SENTIMENT_WEIGHT": 0.4,
        "VIDEO_EMOTION_WEIGHT": 0.3,
        "AUDIO_TARGET_BONUS": 1.0,
        "TEXT_TARGET_BONUS": 1.0,
        "INTEREST_SCORE_THRESHOLD": 0.5,
        "LOCAL_EMOTION_MODEL_PATH": "",
        "VIDEO_EMOTION_MODEL_PATH": "",
        "VIDEO_EMOTION_SEGMENT_LENGTH": 4.0,
        "ENABLE_VIDEO_EMOTION": False,
        "MAX_CLIP_COUNT": 10,
        "CLIPS_BASE_DIR": "clips",
        "MAX_WORKERS": 4,
    }
    config_file = settings_path("config.json")
    try:
        if config_file.exists():
            with config_file.open("r", encoding="utf-8") as f:
                gui_config = json.load(f)
            config.update(gui_config)
    except Exception as e:
        log_error(f"[配置] 加载GUI配置失败，使用默认配置: {e}")

    return config

def write_progress_file(stage, current, total, message=""):
    """写入进度文件，供GUI读取进度信息"""
    try:
        if str(os.environ.get("ACFV_DISABLE_PROGRESS_FILE", "")).lower() in ("1", "true", "yes"):
            return
        progress_file = processing_path("analysis_progress.json")
        progress_file.parent.mkdir(parents=True, exist_ok=True)

        progress_data = {
            "stage": stage,
            "current": current,
            "total": total,
            "message": message,
            "timestamp": time.time(),
            "percentage": (current / total * 100) if total > 0 else 0,
        }

        with progress_file.open("w", encoding="utf-8") as f:
            json.dump(progress_data, f, ensure_ascii=False)
    except Exception as e:
        log_error(f"[进度文件] 写入失败: {e}")

def get_optimal_device(device_preference=None):
    """获取最优设备"""
    config = load_gui_config()
    
    if device_preference and torch:
        if isinstance(device_preference, str):
            wants_cuda = device_preference.strip().lower().startswith("cuda")
        else:
            wants_cuda = torch and isinstance(device_preference, torch.device) and device_preference.type == "cuda"
        if wants_cuda and not torch.cuda.is_available():
            log_warning("[设备管理] CUDA 不可用，改用 CPU")
        else:
            try:
                if isinstance(device_preference, str):
                    device = torch.device(device_preference)
                else:
                    device = device_preference
                test_tensor = torch.tensor([1.0]).to(device)
                del test_tensor
                if device.type == 'cuda':
                    torch.cuda.empty_cache()
                return device
            except Exception as e:
                log_error(f"[设备管理] 指定设备不可用: {e}")
    
    try:
        gui_device = config.get("GPU_DEVICE", "cuda:0")
        enable_gpu = config.get("ENABLE_GPU_ACCELERATION", True)
        
        if enable_gpu and gui_device != "cpu" and torch and torch.cuda.is_available():
            device = torch.device(gui_device)
            test_tensor = torch.tensor([1.0]).to(device)
            del test_tensor
            torch.cuda.empty_cache()
            log_info(f"[设备管理] 使用GPU设备: {device}")
            return device
        if enable_gpu and gui_device != "cpu" and torch and not torch.cuda.is_available():
            log_warning("[设备管理] CUDA 不可用，改用 CPU")
    except Exception as e:
        log_error(f"[设备管理] GPU设备不可用: {e}")
    
    return torch.device("cpu") if torch else None

def get_video_path():
    """安全地获取视频路径"""
    video_path_file = processing_path("selected_video.txt")
    
    if not video_path_file.exists():
        log_error(f"[视频路径] 视频路径文件不存在: {video_path_file}")
        return None
        
    try:
        with open(video_path_file, 'r', encoding='utf-8') as f:
            video_path = f.read().strip()
            
        if not os.path.exists(video_path):
            log_error(f"[视频路径] 视频文件不存在: {video_path}")
            return None
            
        log_info(f"[视频路径] 视频路径: {video_path}")
        return video_path
    except Exception as e:
        log_error(f"[视频路径] 读取失败: {e}")
        return None

def emotion_avg(records, seg_start, seg_end):
    """计算区间内情绪分值的时间加权平均"""
    if not records:
        return 0.0
        
    num = den = 0.0
    for r in records:
        try:
            r_start = float(r.get('start', 0))
            r_end = float(r.get('end', 0))
            r_score = float(r.get('score', 0))
            
            overlap = max(0, min(seg_end, r_end) - max(seg_start, r_start))
            if overlap > 0:
                num += overlap * r_score
                den += overlap
        except (ValueError, TypeError):
            continue
    
    return num / den if den > 0 else 0.0

def vader_interest_score(text):
    """使用VADER评估文本的情感强度作为兴趣分数"""
    if not text or not isinstance(text, str) or text.isspace():
        return 0.0
    
    # 延迟初始化VADER
    init_vader()
    
    if not sid:
        return 0.0
    
    try:
        sentiment_scores = sid.polarity_scores(text)
        interest_intensity = abs(sentiment_scores['compound'])
        emotional_content = sentiment_scores['pos'] + sentiment_scores['neg']
        interest_score = (interest_intensity * 0.7) + (emotional_content * 0.3)
        return min(max(interest_score, 0.0), 1.0)
    except Exception as e:
        log_error(f"[VADER] 情感分析失败: {e}")
        return 0.0

def normalize_transcription_data(data):
    """标准化转录结构为包含 start/end/text 的列表"""
    if not data:
        return []

    if isinstance(data, dict):
        for key in ("segments", "chunks", "results", "data"):
            value = data.get(key)
            if isinstance(value, list):
                data = value
                break
        else:
            if all(k in data for k in ("start", "end", "text")):
                data = [data]
            else:
                return []

    if not isinstance(data, list):
        return []

    normalized = []
    for item in data:
        if not isinstance(item, dict):
            continue

        record = dict(item)
        start = record.get("start")
        end = record.get("end")
        text = record.get("text")

        if (start is None or end is None):
            ts = record.get("timestamp")
            if isinstance(ts, (list, tuple)) and len(ts) == 2:
                start, end = ts
        if (start is None or end is None):
            ts = record.get("timestamps")
            if isinstance(ts, (list, tuple)) and len(ts) == 2:
                start, end = ts
        if start is None:
            start = record.get("start_time")
        if end is None:
            end = record.get("end_time")

        if text is None:
            text = (
                record.get("transcript")
                or record.get("sentence")
                or record.get("label")
                or record.get("content")
                or record.get("utterance")
            )

        try:
            start = float(start) if start is not None else None
            end = float(end) if end is not None else None
        except (TypeError, ValueError):
            start = None
            end = None

        if start is None or end is None:
            continue

        if text is None:
            text = ""
        if not isinstance(text, str):
            text = str(text)

        record["start"] = start
        record["end"] = end
        record["text"] = text
        normalized.append(record)

    return normalized

def validate_json_structure(data, is_chat=False):
    """验证JSON数据结构是否符合预期"""
    if not isinstance(data, list):
        return False
    if not data:
        return True
        
    sample_size = min(5, len(data))
    for i in range(sample_size):
        item = data[i]
        if not isinstance(item, dict):
            return False
            
        if is_chat:
            if 'message' not in item or 'timestamp' not in item:
                return False
        else:
            if 'text' not in item or 'start' not in item or 'end' not in item:
                return False
                
    return True

def compute_chat_density(chat_data, start, end):
    """统计时间段内的聊天条数"""
    if not chat_data:
        return 0
    count = sum(1 for c in chat_data if start <= float(c.get("timestamp", 0)) <= end)
    return count


def merge_short_segments(segments, min_duration=5.0, max_gap=1.0):
    """将过短的相邻转录片段合并，避免后续出现超短候选"""
    if not segments:
        return []
    try:
        min_duration = max(0.0, float(min_duration))
        max_gap = max(0.0, float(max_gap))
    except Exception:
        min_duration = 5.0
        max_gap = 1.0

    merged = []
    current = None

    for seg in sorted(segments, key=lambda s: float(s.get("start", 0))):
        try:
            s = float(seg.get("start", 0.0))
            e = float(seg.get("end", 0.0))
        except Exception:
            continue
        if e <= s:
            continue
        text = seg.get("text", "")
        if not isinstance(text, str):
            text = str(text)

        if current is None:
            current = {"start": s, "end": e, "text": text}
            continue

        gap = max(0.0, s - current["end"])
        curr_len = current["end"] - current["start"]
        seg_len = e - s

        # 合并条件：间隔可接受，且任一片段时长低于阈值
        if gap <= max_gap and (curr_len < min_duration or seg_len < min_duration):
            current["end"] = max(current["end"], e)
            combined_text = (current.get("text", "") + " " + text).strip()
            current["text"] = combined_text
        else:
            merged.append(current)
            current = {"start": s, "end": e, "text": text}

    if current:
        merged.append(current)

    return merged

def compute_chat_sentiment_strength(chat_data, start, end):
    """计算时间段内聊天情感得分绝对值的平均"""
    if not chat_data:
        return 0.0
    scores = [
        abs(c.get("sentiment", {}).get("score", 0))
        for c in chat_data
        if start <= float(c.get("timestamp", 0)) <= end
        and isinstance(c.get("sentiment", {}).get("score"), (int, float))
    ]
    return sum(scores) / len(scores) if scores else 0.0

def compute_relative_interest_score(all_scores, score):
    """对分数进行标准化"""
    if not all_scores:
        return 0.0
    
    # 延迟导入numpy
    import_heavy_libraries()
    if np is None:
        # 如果numpy不可用，使用简单计算
        if not all_scores:
            return 0.0
        mean = sum(all_scores) / len(all_scores)
        variance = sum((x - mean) ** 2 for x in all_scores) / len(all_scores)
        std = variance ** 0.5
        return (score - mean) / std if std > 0 else score
    
    arr = np.array(all_scores, dtype=float)
    mean = arr.mean() if arr.size else 0.0
    std = arr.std() if arr.size else 0.0
    return (score - mean) / std if std > 0 else score

def load_video_emotion_data(video_emotion_file):
    """加载视频情绪数据"""
    if not video_emotion_file or not os.path.exists(video_emotion_file):
        log_info(f"[视频情绪] 视频情绪文件不存在: {video_emotion_file}")
        return []
        
    try:
        with open(video_emotion_file, 'r', encoding='utf-8') as f:
            emotion_data = json.load(f)
            
        if not isinstance(emotion_data, list):
            log_error(f"[视频情绪] 情绪数据格式无效")
            return []
            
        log_info(f"[视频情绪] 已加载 {len(emotion_data)} 条情绪记录")
        return emotion_data
        
    except Exception as e:
        log_error(f"[视频情绪] 加载失败: {e}")
        return []

def batch_sentiment_analysis(texts, device=None):
    """批量情感分析 - 优化版本"""
    if not texts:
        return []
    
    # 获取全局文本分析器
    text_analyzer = get_text_analyzer(device)
    
    if not torch or not GPU_AVAILABLE or not device or device.type == 'cpu':
        log_info(f"[情感分析] 使用VADER快速分析 {len(texts)} 个文本")
        return [vader_interest_score(text) for text in texts]
    
    if text_analyzer.model_loaded and text_analyzer.sentiment_pipeline:
        try:
            log_info(f"[GPU情感分析] 开始GPU批量分析: {len(texts)}个文本")
            
            batch_size = 32
            all_scores = []
            
            for i in range(0, len(texts), batch_size):
                batch_texts = texts[i:i + batch_size]
                results = text_analyzer.sentiment_pipeline(batch_texts)
                
                batch_scores = []
                for result in results:
                    if isinstance(result, dict):
                        score = result.get('score', 0.5)
                    elif isinstance(result, list) and result:
                        score = max(r.get('score', 0) for r in result)
                    else:
                        score = 0.5
                    batch_scores.append(score)
                
                all_scores.extend(batch_scores)
            
            log_info(f"[GPU情感分析] GPU批量分析完成")
            return all_scores
            
        except Exception as e:
            log_error(f"[GPU情感分析] GPU分析失败，回退到VADER: {e}")
    else:
        log_info(f"[情感分析] 模型未加载，使用VADER快速分析")
    
    # 回退到VADER
    return [vader_interest_score(text) for text in texts]

# ============================================================================
# 带断点续传的主要接口 - 使用超快特征提取器
# ============================================================================

def check_and_prompt_resume():
    """检查并提示是否恢复之前的分析"""
    if not checkpoint_manager.has_checkpoint():
        return False
    
    checkpoint_info = checkpoint_manager.get_checkpoint_info()
    if not checkpoint_info:
        return False
    
    log_info("=" * 60)
    log_info("🔍 发现未完成的分析任务")
    log_info("=" * 60)
    log_info(f"📹 视频文件: {os.path.basename(checkpoint_info['video_path'])}")
    log_info(f"📊 进度: {checkpoint_info['processed_count']}/{checkpoint_info['total_count']} 片段")
    log_info(f"⏰ 上次保存: {checkpoint_info['last_save_time']}")
    log_info(f"💾 完成度: {checkpoint_info['processed_count']/checkpoint_info['total_count']*100:.1f}%")
    log_info("=" * 60)
    
    return True

def analyze_data_with_checkpoint(chat_file, transcription_file, output_file, 
                                video_emotion_file=None, video_emotion_weight=0.3, 
                                top_n=None, enable_video_emotion=None, device='cuda:0',
                                progress_callback=None, resume_checkpoint=None):
    """
    带断点续传的主要分析函数 - 统一使用5分钟固定模式
    """
    log_info("=" * 80)
    log_info("🚀 开始视频内容分析 (语义可变时长+非重叠 优化版)")
    log_info("=" * 80)
    
    start_time = time.time()
    
    # 加载GUI配置
    config = load_gui_config()
    
    # 使用GUI配置填充参数
    if top_n is None:
        top_n = config.get("MAX_CLIP_COUNT", 10)
    if enable_video_emotion is None:
        enable_video_emotion = config.get("ENABLE_VIDEO_EMOTION", False)
    if video_emotion_weight is None:
        video_emotion_weight = config.get("VIDEO_EMOTION_WEIGHT", 0.3)
    


    max_workers = config.get("MAX_WORKERS", 4)
    checkpoint_interval = config.get("CHECKPOINT_INTERVAL", 10)
    
    # 启用超快模式
    enable_ultra_fast = config.get("ENABLE_ULTRA_FAST", True)
    
    # RAG设置
    rag_enable = bool(config.get("RAG_ENABLE", False))
    rag_weight = float(config.get("RAG_WEIGHT", 0.2))
    rag_db_path = config.get("RAG_DB_PATH", "rag_database.json")
    # 兼容：若配置使用默认文件名但真实文件位于 data/ 目录，则自动回退
    try:
        if not os.path.isabs(rag_db_path) and not os.path.exists(rag_db_path):
            # 常见候选
            acfv_root = Path(__file__).resolve().parents[2]
            candidates = [
                os.path.join("data", "rag_database.json"),
                str(acfv_root / "data" / "rag_database.json"),
            ]
            for c in candidates:
                if os.path.exists(c):
                    log_info(f"[RAG] 检测到候选数据库: {c} (原路径 {rag_db_path} 不存在，自动采用)")
                    rag_db_path = c
                    break
    except Exception:
        pass
    rag_db = None
    if rag_enable:
        try:
            from acfv.rag_vector_database import RAGVectorDatabase
            rag_dir = os.path.dirname(os.path.abspath(rag_db_path))
            if rag_dir and not os.path.exists(rag_dir):
                os.makedirs(rag_dir, exist_ok=True)
            rag_db = RAGVectorDatabase(database_path=rag_db_path)
            log_info(f"[RAG] 已启用，数据库: {rag_db_path}, 权重: {rag_weight}")
        except Exception as e:
            log_warning(f"[RAG] 启用失败，将忽略RAG加成: {e}")
            rag_enable = False

    # 获取最优设备
    optimal_device = get_optimal_device(device)
    
    # 创建当前配置的元数据
    current_config = {
        'video_emotion_weight': video_emotion_weight,
        'top_n': top_n,
        'enable_video_emotion': enable_video_emotion,


        'max_workers': max_workers
    }
    
    video_path = get_video_path()
    if not video_path:
        log_error("❌ 无法获取有效的视频路径")
        return []
    
    # 检查是否恢复检查点
    should_resume = False
    processed_segments = []
    start_index = 0
    
    if resume_checkpoint is None:
        # 自动检测
        should_resume = checkpoint_manager.has_checkpoint()
    elif resume_checkpoint:
        # 强制恢复
        should_resume = checkpoint_manager.has_checkpoint()
    else:
        # 强制重新开始
        checkpoint_manager.clear_checkpoint()
        should_resume = False
    
    if should_resume:
        loaded_segments, saved_metadata = checkpoint_manager.load_checkpoint()
        
        if loaded_segments and saved_metadata:
            # 检查配置兼容性
            if checkpoint_manager.is_config_compatible(current_config, saved_metadata):
                processed_segments = loaded_segments
                start_index = saved_metadata.get('current_index', 0)
                log_info(f"✅ 恢复检查点: 从第 {start_index} 个片段继续，已完成 {len(processed_segments)} 个")
            else:
                log_info("⚠️ 配置已更改，重新开始分析")
                checkpoint_manager.clear_checkpoint()
                should_resume = False
        else:
            log_error("❌ 检查点数据损坏，重新开始分析")
            checkpoint_manager.clear_checkpoint()
            should_resume = False
    
    log_info(f"📋 分析参数:")
    log_info(f"   - 恢复模式: {'✅ 继续之前的分析' if should_resume else '🆕 重新开始'}")
    log_info(f"   - 计算设备: {optimal_device}")

    log_info(f"   - 检查点间隔: 每 {checkpoint_interval} 个片段")
    log_info(f"   - 并行工作数: {max_workers}")
    
    write_progress_file("初始化", 0, 10, "开始视频内容分析...")
    
    try:
        # 第1阶段：数据加载和验证
        write_progress_file("数据加载", 1, 10, "加载转录和弹幕数据...")
        
        # 检查弹幕文件
        has_chat = os.path.exists(chat_file) and os.path.getsize(chat_file) > 10
        log_info(f"📺 弹幕文件: {'✅ 存在' if has_chat else '❌ 不存在'}")
        
        # 加载转录数据
        try:
            with open(transcription_file, 'r', encoding='utf-8') as f:
                transcription_raw = json.load(f)
            transcription_data = normalize_transcription_data(transcription_raw)
            log_info(f"🎤 转录数据: ✅ 已加载 {len(transcription_data)} 个片段")
            
            if not validate_json_structure(transcription_data, is_chat=False):
                log_error("❌ 转录数据结构无效")
                raise RuntimeError("invalid transcription structure")
            if not transcription_data:
                try:
                    file_size = os.path.getsize(transcription_file)
                except Exception:
                    file_size = -1
                log_error(f"⚠️ 转录数据为空，终止分析 (file_size={file_size} bytes, path={transcription_file})")
                raise RuntimeError(f"empty transcription ({file_size} bytes) at {transcription_file}")
        except Exception as e:
            log_error(f"❌ 转录文件加载失败: {e}")
            raise
        
        # 加载弹幕数据
        chat_data = []
        if has_chat:
            try:
                with open(chat_file, 'r', encoding='utf-8') as f:
                    chat_data = json.load(f)
                
                if not validate_json_structure(chat_data, is_chat=True):
                    log_error("❌ 弹幕数据结构无效")
                    has_chat = False
                else:
                    log_info(f"💬 弹幕数据: ✅ 已加载 {len(chat_data)} 条弹幕")
            except Exception as e:
                log_error(f"❌ 弹幕文件加载失败: {e}")
                has_chat = False
        
        # 加载视频情绪数据
        video_emotion_data = []
        has_video_emotion = False
        if enable_video_emotion and video_emotion_file:
            video_emotion_data = load_video_emotion_data(video_emotion_file)
            has_video_emotion = len(video_emotion_data) > 0
        
        if not enable_video_emotion:
            video_emotion_weight = 0.0
        
        log_info(f"🧠 视频情绪数据: {'✅ 已加载' if has_video_emotion else '❌ 无数据'}")
        
        # 第2阶段：数据预处理
        write_progress_file("数据预处理", 2, 10, "准备片段数据...")
        
        # 准备有效片段
        valid_segments = []
        texts_for_analysis = []
        
        for seg in transcription_data:
            start = float(seg.get('start', 0))
            end = float(seg.get('end', 0))
            text = seg.get('text', '')
            
            if not text or not isinstance(text, str):
                text = "无文本内容"
            
            valid_segments.append({
                'start': start,
                'end': end,
                'text': text
            })
            texts_for_analysis.append(text)
        
        log_info(f"📊 有效片段: ✅ {len(valid_segments)}个")

        # 合并过短的相邻片段，避免出现超短候选导致后续被丢弃
        min_seg_dur = config.get("MIN_INTEREST_SEGMENT_DURATION", 5.0)
        merge_gap = config.get("MERGE_SHORT_SEGMENT_GAP", 1.0)
        try:
            min_seg_dur = float(min_seg_dur)
            merge_gap = float(merge_gap)
        except Exception:
            min_seg_dur = 5.0
            merge_gap = 1.0

        merged_segments = merge_short_segments(valid_segments, min_seg_dur, merge_gap)
        if merged_segments:
            if len(merged_segments) != len(valid_segments):
                log_info(f"🧩 合并短片段: {len(valid_segments)} -> {len(merged_segments)} (min={min_seg_dur}s, gap={merge_gap}s)")
            valid_segments = merged_segments
            texts_for_analysis = [seg.get('text', '') for seg in valid_segments]
        
        # 验证：确保每个原始转录片段都会被处理
        log_info(f"🔍 验证: 原始转录数据有 {len(transcription_data)} 个片段")
        log_info(f"🔍 验证: 准备分析 {len(valid_segments)} 个有效片段")
        if len(valid_segments) != len(transcription_data):
            log_info(f"⚠️  注意: 有效片段数量与原始数量不一致!")
        
        # 创建或更新元数据
        if not should_resume:
            metadata = checkpoint_manager.create_metadata(video_path, transcription_file, chat_file, current_config)
            metadata['total_segments'] = len(valid_segments)
        else:
            # 使用已保存的元数据
            _, metadata = checkpoint_manager.load_checkpoint()
            metadata.update(current_config)
        
        # 第3阶段：AI情感分析（如果需要）
        if not should_resume or start_index == 0:
            write_progress_file("情感分析", 3, 10, "进行AI情感分析...")
            
            sentiment_start = time.time()
            interest_scores = batch_sentiment_analysis(texts_for_analysis, optimal_device)
            sentiment_time = time.time() - sentiment_start
            
            log_info(f"🧠 情感分析: ✅ 完成 {len(interest_scores)} 个分数计算 (耗时: {sentiment_time:.1f}s)")
        else:
            log_info("🧠 情感分析: ⏭️ 跳过（使用缓存结果）")
            interest_scores = [0.5] * len(texts_for_analysis)  # 占位符，实际从检查点加载
        
        # 第4阶段：🚀 超快特征计算
        write_progress_file("⚡超快特征计算", 4, 10, "使用超快特征提取器...")
        
        feature_start = time.time()
        
        # 只处理未完成的片段
        remaining_segments = valid_segments[start_index:]
        log_info(f"🔄 需要处理的剩余片段: {len(remaining_segments)}")
        
        if remaining_segments:
            if enable_ultra_fast:
                # 🚀 使用超快特征提取器
                log_info("⚡ 启动超快特征提取器...")
                feature_extractor = UltraFastExtractor(video_path, max_workers=max_workers)
            else:
                # 使用标准提取器（已移除，这里用超快版本作为备用）
                log_info("📊 启动标准特征提取器...")
                feature_extractor = UltraFastExtractor(video_path, max_workers=max_workers)
            
            # 超快并行提取音视频特征
            remaining_features = ultra_fast_parallel_extraction(
                feature_extractor, remaining_segments, max_workers, 
                checkpoint_interval, progress_callback
            )
        else:
            remaining_features = []
        
        feature_time = time.time() - feature_start
        speed = len(remaining_segments) / feature_time if feature_time > 0 and remaining_segments else 0
        log_info(f"⚡ 超快特征计算: ✅ 完成 {len(remaining_features)} 个新片段 (耗时: {feature_time:.1f}s, 速度: {speed:.1f} 片段/秒)")
        
        # 第5阶段：增量分数计算并保存检查点
        write_progress_file("分数计算", 5, 10, "增量计算综合兴趣分数...")
        
        all_segments = processed_segments.copy()  # 从检查点恢复的片段
        
        # 处理剩余片段
        for idx, seg_info in enumerate(remaining_segments):
            actual_idx = start_index + idx
            start = seg_info['start']
            end = seg_info['end']
            text = seg_info['text']
            
            # 获取音视频特征
            if idx < len(remaining_features):
                audio_feature = remaining_features[idx]
            else:
                audio_feature = {'music_probability': 0.0, 'loud_db': -100.0}
            
            music_probability = audio_feature['music_probability']
            loud_db = audio_feature['loud_db']
            
            # 情感分数
            if actual_idx < len(interest_scores):
                interest_score = interest_scores[actual_idx]
            else:
                interest_score = vader_interest_score(text)
            
            # 视频情绪分数
            vid_emo = 0.0
            if has_video_emotion:
                vid_emo = emotion_avg(video_emotion_data, start, end)
            
            # 计算综合分数
            if has_chat:
                density = compute_chat_density(chat_data, start, end)
                sentiment = compute_chat_sentiment_strength(chat_data, start, end)
                
                music_penalty = 1.0 - music_probability * 0.6
                
                score = (
                    config.get("CHAT_DENSITY_WEIGHT", 0.3) * density +
                    config.get("CHAT_SENTIMENT_WEIGHT", 0.4) * sentiment +
                    config.get("TEXT_TARGET_BONUS", 1.0) * interest_score +
                    video_emotion_weight * vid_emo
                ) * music_penalty
                
                # RAG先验加成（基于已收藏/高评分切片的相似度）
                rag_prior = 0.0
                if rag_enable and rag_db:
                    try:
                        rag_prior = float(rag_db.calculate_similarity_score(text))
                    except Exception:
                        rag_prior = 0.0

                info = {
                    'start': start, 'end': end, 'density': density, 'sentiment': sentiment,
                    'interest_score': interest_score, 'video_emotion': vid_emo,
                    'music_probability': music_probability, 'score': score,
                    'text': text, 'loud_db': loud_db,
                    'rag_prior': rag_prior
                }
            else:
                music_penalty = 1.0 - music_probability * 0.7
                
                score = (
                    interest_score * config.get("TEXT_TARGET_BONUS", 1.0) + 
                    video_emotion_weight * vid_emo
                ) * music_penalty
                
                # RAG先验加成
                rag_prior = 0.0
                if rag_enable and rag_db:
                    try:
                        rag_prior = float(rag_db.calculate_similarity_score(text))
                    except Exception:
                        rag_prior = 0.0

                info = {
                    'start': start, 'end': end, 'interest_score': interest_score,
                    'video_emotion': vid_emo, 'music_probability': music_probability,
                    'score': score, 'text': text, 'no_chat': True, 'loud_db': loud_db,
                    'rag_prior': rag_prior
                }
            
            # 应用RAG权重加成
            if rag_enable and info.get('rag_prior', 0.0) > 0:
                info['score'] += rag_weight * info['rag_prior']

            # 短文本惩罚
            word_count = len(text.split())
            if word_count < 5:
                info['score'] *= 0.7
            
            if info['score'] <= 0:
                info['score'] = 0.01
            
            all_segments.append(info)
            
            # 定期保存检查点
            if (idx + 1) % checkpoint_interval == 0:
                current_index = start_index + idx + 1
                log_info(f"💾 保存检查点: {len(all_segments)}/{len(valid_segments)} 片段")
                checkpoint_manager.save_checkpoint(all_segments, metadata, current_index)
                
                # 发送进度回调
                if progress_callback:
                    try:
                        progress_callback("分数计算", len(all_segments), len(valid_segments), 
                                        f"已完成 {len(all_segments)}/{len(valid_segments)} 片段")
                    except:
                        pass
        
        # 保存最终检查点
        if remaining_segments:
            checkpoint_manager.save_checkpoint(all_segments, metadata, len(valid_segments))
        
        # 音量归一化和惩罚
        write_progress_file("音量处理", 6, 10, "音量归一化处理...")
        
        loud_vals = [s.get('loud_db', -100.0) for s in all_segments]
        if loud_vals:
            max_loud = max(loud_vals)
            min_loud = min(loud_vals)
            
            for s in all_segments:
                vol_norm = 0.0
                if max_loud > min_loud:
                    vol_norm = (s.get('loud_db', -100.0) - min_loud) / (max_loud - min_loud)
                    
                if s.get('music_probability', 0) > 0.7:
                    penalty = 1.0 - vol_norm * 0.5
                else:
                    penalty = 0.5 + vol_norm ** 2 * 0.5
                    
                s['score'] *= penalty
                s['volume_penalty'] = penalty
        
        # 更新分数并计算相对分数
        all_scores = [seg.get('score', 0) for seg in all_segments]
        for seg in all_segments:
            seg['relative_score'] = compute_relative_interest_score(all_scores, seg['score'])
        
        log_info(f"📈 分数统计: 最小={min(all_scores):.3f}, 最大={max(all_scores):.3f}, 平均={np.mean(all_scores):.3f}")
        
        # 第6阶段：智能过滤和排序（语义可变时长，不使用固定5分钟）
        write_progress_file("智能过滤", 7, 10, "过滤和排序片段...")
        
        # 辅助函数：按评分贪心挑选“严格不重叠”片段
        def _select_top_non_overlapping(candidates, max_count, buffer_sec=0.0):
            try:
                # 先按评分降序，再按时长降序，尽量优先选择高分且更长的片段
                sorted_by_score = sorted(
                    candidates,
                    key=lambda x: (float(x.get('score', 0.0)), float(x.get('end', 0.0)) - float(x.get('start', 0.0))),
                    reverse=True
                )
                selected = []
                for seg in sorted_by_score:
                    s = float(seg.get('start', 0.0))
                    e = float(seg.get('end', 0.0))
                    if e <= s:
                        continue
                    no_conflict = True
                    for chosen in selected:
                        cs = float(chosen.get('start', 0.0))
                        ce = float(chosen.get('end', 0.0))
                        # 判断是否有重叠（含缓冲）
                        if not (e <= cs - buffer_sec or s >= ce + buffer_sec):
                            no_conflict = False
                            break
                    if no_conflict:
                        selected.append(seg)
                        if len(selected) >= max_count:
                            break
                return selected
            except Exception as _e:
                log_warning(f"[选择] 非重叠选择失败，使用原始Top-N: {_e}")
                return sorted(candidates, key=lambda x: x.get('score', 0), reverse=True)[:max_count]

        def _fill_to_target(selected: list, pool: list, target: int) -> list:
            """若非重叠挑选数量不足，允许轻度重叠补齐到期望数量。"""
            if target <= 0:
                return selected
            existing_ids = {id(s) for s in selected}
            for seg in pool:
                if id(seg) in existing_ids:
                    continue
                selected.append(seg)
                existing_ids.add(id(seg))
                if len(selected) >= target:
                    break
            return selected

        min_required = max(5, top_n)  # 至少尝试输出 5 个高光

        if not has_chat:
            # 无弹幕模式的过滤
            old_count = len(all_segments)
            all_segments = [seg for seg in all_segments if seg.get('music_probability', 0) < 0.95]
            new_count = len(all_segments)
            log_info(f"🎵 音乐过滤: {old_count} → {new_count} (移除 {old_count - new_count} 个)")
            
            threshold = 0.2
            old_count = len(all_segments)
            filtered_segments = [seg for seg in all_segments if seg.get('relative_score', 0) > threshold]
            new_count = len(filtered_segments)
            log_info(f"📊 分数过滤: {old_count} → {new_count} (阈值: {threshold})")
            
            buffer_sec = float(config.get("NON_OVERLAP_BUFFER_SECONDS", 0.0)) if isinstance(config.get("NON_OVERLAP_BUFFER_SECONDS", 0.0), (int, float)) else 0.0
            candidates = filtered_segments if len(filtered_segments) >= 1 else all_segments
            candidates_sorted = sorted(candidates, key=lambda x: x.get('score', 0), reverse=True)
            top_pool = candidates_sorted[: max(top_n * 5, top_n)]
            top_segments = _select_top_non_overlapping(top_pool, top_n, buffer_sec=buffer_sec)
            if len(top_segments) < top_n:
                log_warning(f"[选择] 非重叠约束下仅选出 {len(top_segments)}/{top_n} 个片段")
            if len(top_segments) < min_required:
                target = min(min_required, len(candidates_sorted))
                top_segments = _fill_to_target(top_segments, candidates_sorted, target)
                log_info(f"[选择] 放宽重叠补齐到 {len(top_segments)}/{target}")
        else:
            # 有弹幕模式的过滤
            old_count = len(all_segments)
            filtered_segments = [seg for seg in all_segments if seg.get('music_probability', 0) < 0.95]
            new_count = len(filtered_segments)
            log_info(f"🎵 音乐过滤: {old_count} → {new_count}")
            
            buffer_sec = float(config.get("NON_OVERLAP_BUFFER_SECONDS", 0.0)) if isinstance(config.get("NON_OVERLAP_BUFFER_SECONDS", 0.0), (int, float)) else 0.0
            candidates = filtered_segments if len(filtered_segments) >= 1 else all_segments
            candidates_sorted = sorted(candidates, key=lambda x: x.get('score', 0), reverse=True)
            top_pool = candidates_sorted[: max(top_n * 5, top_n)]
            top_segments = _select_top_non_overlapping(top_pool, top_n, buffer_sec=buffer_sec)
            if len(top_segments) < top_n:
                log_warning(f"[选择] 非重叠约束下仅选出 {len(top_segments)}/{top_n} 个片段")
            if len(top_segments) < min_required:
                target = min(min_required, len(candidates_sorted))
                top_segments = _fill_to_target(top_segments, candidates_sorted, target)
                log_info(f"[选择] 放宽重叠补齐到 {len(top_segments)}/{target}")
        
        # 确保有结果
        if not top_segments and all_segments:
            log_info("🔄 紧急回退：使用所有片段中的最高分")
            top_segments = sorted(all_segments, key=lambda x: x.get('score', 0), reverse=True)[:min(top_n, len(all_segments))]
        
        log_info(f"🎯 最终选择: ✅ {len(top_segments)} 个高兴趣片段")
        
        # 🆕 详细显示Top片段信息（显示更多片段）
        log_info("📊 详细片段信息:")
        for i, seg in enumerate(top_segments[:min(20, len(top_segments))], 1):
            score = seg.get('score', 0)
            music_prob = seg.get('music_probability', 0)
            text_preview = seg.get('text', '')[:50] + "..." if len(seg.get('text', '')) > 50 else seg.get('text', '')
            log_info(f"   #{i:2d}: {seg['start']:.1f}-{seg['end']:.1f}s, "
                    f"分数={score:.3f}, 音乐概率={music_prob:.2f}, "
                    f"文本=\"{text_preview}\"")
        
        if len(top_segments) > 20:
            log_info(f"   ... 还有 {len(top_segments) - 20} 个片段未显示")
        
        # 🆕 统计评分分布
        scores = [seg.get('score', 0) for seg in top_segments]
        if scores:
            avg_score = sum(scores) / len(scores)
            max_score = max(scores)
            min_score = min(scores)
            log_info(f"📈 评分统计: 最高={max_score:.3f}, 最低={min_score:.3f}, 平均={avg_score:.3f}")
        
        # 第7阶段：结果保存（语义自适应片段，不再强制5分钟）
        write_progress_file("保存结果", 8, 10, "保存分析结果...")

        output_dir = os.path.dirname(output_file)
        os.makedirs(output_dir, exist_ok=True)

        # 基于语义评分的可变时长片段：直接使用 top_segments
        # 构建 ratings.json（供管理页与外部工具使用）
        ratings_data = {}
        for i, seg in enumerate(top_segments, 1):
            s = float(seg.get('start', 0.0))
            e = float(seg.get('end', 0.0))
            name = f"clip_{i:03d}_{s:.1f}s-{e:.1f}s.mp4"
            ratings_data[name] = {
                'rating': round(float(seg.get('score', 0.0)), 2),
                'start': s,
                'end': e,
                'duration': max(0.0, e - s),
                'text': seg.get('text', ''),
                'semantic_variable': True,
                'segment_index': i
            }

        try:
            ratings_file = os.path.join(os.path.dirname(output_file), 'ratings.json')
            with open(ratings_file, 'w', encoding='utf-8') as f:
                json.dump(ratings_data, f, ensure_ascii=False, indent=4)
            log_info(f"✅ 语义自适应 ratings.json 已保存: {ratings_file}")
        except Exception as e:
            log_error(f"❌ ratings.json 保存失败: {e}")

        # ACFV 兼容导出：使用 top_segments 与 ratings_data
        try:
            _write_acfv_exports(os.path.dirname(output_file), ratings_data, top_segments)
        except Exception as e:
            log_error(f"❌ ACFV导出失败: {e}")

        # 保存最终结果（top_segments）
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(top_segments, f, ensure_ascii=False, indent=4)
            log_info(f"✅ 最终结果已保存: {output_file}")
        except Exception as e:
            log_error(f"❌ 最终结果保存失败: {e}")

        # 可选：将用户手动评分的正反馈切片写入RAG数据库（仅启用时）
        try:
            if rag_enable and rag_db and ratings_data:
                base_dir = os.path.dirname(output_file)
                from acfv.runtime.storage import resolve_run_clips_dir
                # 将Top片段写入RAG库（使用ratings.json中的文本与评分）
                for name, rec in ratings_data.items():
                    if float(rec.get('rating', 0.0)) > 0:
                        clips_dir = resolve_run_clips_dir(Path(base_dir))
                        clip_path = os.path.join(str(clips_dir), name)
                        rag_db.add_liked_clip_vector(
                            clip_path=clip_path,
                            transcript_text=rec.get('text', ''),
                            video_name=os.path.basename(os.path.dirname(base_dir)),
                            clip_start_time=float(rec.get('start', 0.0)),
                            clip_end_time=float(rec.get('end', 0.0)),
                            user_rating=int(round(float(rec.get('rating', 0.0))*5)) if isinstance(rec.get('rating', 0.0), (int, float)) else 5
                        )
                # 补全向量
                try:
                    created = rag_db.ensure_embeddings()
                    log_info(f"[RAG] 本次新增向量: {created}")
                except Exception:
                    pass
        except Exception as e:
            log_warning(f"[RAG] 写入用户评分切片失败（不影响流程）: {e}")

        # 保存分析报告
        try:
            interest_txt = os.path.splitext(output_file)[0] + '.txt'
            with open(interest_txt, 'w', encoding='utf-8') as f:
                f.write("High-Interest Segments (超快优化版)\n")
                f.write("=" * 80 + "\n")
                f.write(f"恢复模式: {'✅ 继续之前的分析' if should_resume else '🆕 重新开始'}\n")
                f.write(f"超快模式: {'✅ 启用' if enable_ultra_fast else '❌ 禁用'}\n")
                f.write(f"处理片段: {len(all_segments)} 个\n")
                f.write(f"最终选择: {len(top_segments)} 个\n")
                f.write(f"特征计算速度: {speed:.1f} 片段/秒\n")
                f.write("-" * 80 + "\n")
                f.write(f"{'Idx':<5}{'Start':<10}{'End':<10}{'Score':<10}{'MusicProb':<12}{'Text':<30}\n")
                f.write("-" * 80 + "\n")
                for i, seg in enumerate(top_segments, 1):
                    music_prob = seg.get('music_probability', 0.0)
                    f.write(
                        f"{i:<5}"
                        f"{seg['start']:<10.1f}"
                        f"{seg['end']:<10.1f}"
                        f"{seg['score']:<10.2f}"
                        f"{music_prob:<12.2f}"
                        f"{seg.get('text', '')[:30]}\n"
                    )
            log_info("✅ 分析报告已保存")
        except Exception as e:
            log_error(f"❌ 分析报告保存失败: {e}")

        # 第8阶段：清理资源
        write_progress_file("清理资源", 9, 10, "清理临时资源...")

        # 清理检查点文件（成功完成后）
        checkpoint_manager.clear_checkpoint()
        log_info("🧹 检查点文件已清理")

        # GPU内存清理
        if torch and optimal_device and optimal_device.type == 'cuda':
            try:
                torch.cuda.empty_cache()
                log_info("✅ GPU内存清理完成")
            except Exception:
                pass

        # 清理进度文件
        try:
            progress_file = processing_path("analysis_progress.json")
            if progress_file.exists():
                progress_file.unlink()
        except Exception:
            pass

        write_progress_file("完成", 10, 10, "视频内容分析完成")

        # 完成统计
        total_time = time.time() - start_time
        log_info("=" * 80)
        log_info("🎉 视频内容分析完成! (超快优化版)")
        log_info(f"📊 统计信息:")
        log_info(f"   - 恢复模式: {'✅ 继续之前的分析' if should_resume else '🆕 重新开始'}")
        log_info(f"   - 处理片段数: {len(all_segments)}")
        log_info(f"   - 最终选择: {len(top_segments)}")
        log_info(f"   - 总耗时: {total_time:.1f}秒")
        log_info(f"   - 平均每片段: {total_time/len(remaining_segments if remaining_segments else [1]):.3f}秒")
        log_info(f"   - 特征计算速度: {speed:.1f} 片段/秒")
        log_info(f"   - 结果文件: {output_file}")
        log_info("=" * 80)

        return top_segments
        
    except KeyboardInterrupt:
        log_info("⏸️ 用户中断分析，保存当前进度...")
        
        # 保存中断时的检查点
        if 'all_segments' in locals() and 'metadata' in locals():
            current_index = len(all_segments)
            checkpoint_manager.save_checkpoint(all_segments, metadata, current_index)
            log_info(f"💾 中断检查点已保存: {len(all_segments)} 个片段")
        
        write_progress_file("中断", 0, 10, "用户中断分析，已保存进度")
        return []
        
    except Exception as e:
        log_error(f"❌ 分析过程发生错误: {e}")
        write_progress_file("错误", 0, 10, f"分析失败: {str(e)}")
        import traceback
        traceback.print_exc()
        raise

# 兼容原接口
def analyze_data(chat_file, transcription_file, output_file, 
                video_emotion_file=None, video_emotion_weight=0.3, 
                top_n=None, enable_video_emotion=None, device='cuda:0',
                progress_callback=None):
    """
    主要分析函数 - 兼容原接口，自动检测断点续传
    """
    return analyze_data_with_checkpoint(
        chat_file, transcription_file, output_file,
        video_emotion_file, video_emotion_weight,
        top_n, enable_video_emotion, device,
        progress_callback, resume_checkpoint=None  # 自动检测
    )

def analyze_data_with_checkpoint_new(video_clips_dir, config_manager, resume_mode=None, progress_callback=None):
    """
    新的分析函数，接受视频剪辑目录和配置管理器
    
    Args:
        video_clips_dir: 视频剪辑目录
        config_manager: 配置管理器
        resume_mode: 恢复模式 (None=自动检测, True=继续, False=重新开始)
        progress_callback: 进度回调函数 (stage_name, substage_index, progress)
    
    Returns:
        dict: 分析结果
    """
    log_info("=" * 80)
    log_info("🚀 开始视频内容分析 (集成版)")
    log_info("=" * 80)
    
    def update_progress(substage_index, progress):
        """内部进度更新函数"""
        if progress_callback:
            try:
                progress_callback("内容分析", substage_index, progress)
            except Exception as e:
                log_info(f"进度更新失败: {e}")
    
    def should_stop():
        """检查是否应该停止处理"""
        try:
            stop_flag_file = processing_path("stop_flag.txt")
            return stop_flag_file.exists()
        except Exception:
            return False
    
    # 添加停止检查
    if should_stop():
        log_info("🛑 检测到停止信号，分析被中断")
        return None
    
    # 🆕 子阶段0: 关键词提取 - 初始化
    update_progress(0, 0.0)
    
    start_time = time.time()
    
    # 从配置管理器获取参数
    data_dir = os.path.join(video_clips_dir, "data")
    chat_file = os.path.join(data_dir, "chat_with_emotes.json")
    transcription_file = os.path.join(data_dir, "transcription.json")
    host_transcription_file = os.path.join(data_dir, "host_transcription.json")
    video_emotion_file = os.path.join(data_dir, "video_emotion_4s.json")
    analysis_output = os.path.join(data_dir, "high_interest_segments.json")
    
    # 检查是否有主播转录文件，优先使用主播转录
    use_host_transcription = False
    if os.path.exists(host_transcription_file) and os.path.getsize(host_transcription_file) > 10:
        log_info(f"🎯 发现主播转录文件，将使用主播转录进行兴趣判断: {host_transcription_file}")
        transcription_file = host_transcription_file
        use_host_transcription = True
    else:
        log_info(f"📝 使用完整转录文件进行兴趣判断: {transcription_file}")
        use_host_transcription = False
    
    # 停止检查
    if should_stop():
        log_info("🛑 检测到停止信号，分析在文件检查后被中断")
        return None
    
    # 🆕 文件检查完成
    update_progress(0, 0.3)
    
    # 获取配置参数
    top_n = int(config_manager.get("MAX_CLIP_COUNT") or 10)
    enable_video_emotion = config_manager.get("ENABLE_VIDEO_EMOTION", False)
    video_emotion_weight = float(config_manager.get("VIDEO_EMOTION_WEIGHT") or 0.3)
    device = config_manager.get("GPU_DEVICE") or "cuda:0"
    
    # 🆕 参数加载完成
    update_progress(0, 0.6)
    
    # 检查是否恢复检查点
    should_resume = False
    if resume_mode is None:
        # 自动检测
        should_resume = checkpoint_manager.has_checkpoint()
    elif resume_mode:
        # 强制恢复
        should_resume = checkpoint_manager.has_checkpoint()
    else:
        # 强制重新开始
        checkpoint_manager.clear_checkpoint()
        should_resume = False
    
    # 🆕 关键词提取完成
    update_progress(0, 1.0)
    
    log_info(f"📋 分析参数:")
    log_info(f"   - 视频目录: {video_clips_dir}")
    log_info(f"   - 恢复模式: {'✅ 继续之前的分析' if should_resume else '🆕 重新开始'}")
    log_info(f"   - 计算设备: {device}")
    log_info(f"   - 最大切片数: {top_n}")
    log_info(f"   - 视频情绪分析: {'✅ 启用' if enable_video_emotion else '❌ 禁用'}")
    log_info(f"   - 转录类型: {'🎯 主播转录' if use_host_transcription else '📝 完整转录'}")
    
    # 🆕 子阶段1: 兴趣评分 - 开始
    update_progress(1, 0.0)
    
    try:
        # 调用原有的分析函数，同时传递自定义的进度回调
        def detailed_progress_callback(current, total, detail=""):
            """详细进度回调"""
            if total > 0:
                progress = current / total
                update_progress(1, progress)  # 兴趣评分阶段
        
        result = analyze_data_with_checkpoint(
            chat_file=chat_file,
            transcription_file=transcription_file,
            output_file=analysis_output,
            video_emotion_file=video_emotion_file if enable_video_emotion else None,
            video_emotion_weight=video_emotion_weight,
            top_n=top_n,
            enable_video_emotion=enable_video_emotion,
            device=device,
            progress_callback=detailed_progress_callback,  # 🆕 传递进度回调
            resume_checkpoint=should_resume
        )
        
        # 🆕 兴趣评分完成
        update_progress(1, 1.0)
        
        # 🆕 子阶段2: 片段排序
        update_progress(2, 0.0)
        
        processing_time = time.time() - start_time
        log_info(f"✅ 分析完成，耗时: {processing_time:.1f}秒")
        
        # 🆕 片段排序完成
        update_progress(2, 1.0)
        
        return {
            "success": True,
            "segments": result,
            "processing_time": processing_time,
            "output_file": analysis_output
        }
        
    except Exception as e:
        log_error(f"❌ 分析失败: {e}")
        import traceback
        log_error(f"❌ 分析失败详细错误: {traceback.format_exc()}")
        raise  # 重新
