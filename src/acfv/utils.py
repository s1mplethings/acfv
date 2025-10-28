# utils.py - 工具函数模块

import os
import json
import pickle
import logging
import re
import unicodedata

# 条件导入，避免NumPy兼容性问题
try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    print("警告: faiss模块导入失败，相关功能将不可用")

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False
    print("警告: numpy模块导入失败，相关功能将不可用")

# sklearn导入移到函数内部，避免NumPy兼容性问题
SKLEARN_AVAILABLE = None


def _get_sklearn():
    """延迟导入sklearn，避免NumPy兼容性问题"""
    global SKLEARN_AVAILABLE
    if SKLEARN_AVAILABLE is None:
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer
            SKLEARN_AVAILABLE = TfidfVectorizer
        except ImportError as e:
            SKLEARN_AVAILABLE = False
            print(f"警告: sklearn模块导入失败: {e}")
    return SKLEARN_AVAILABLE

def filter_meaningless_content(data, is_chat=False):
    """
    过滤无意义内容
    
    Args:
        data: 要过滤的数据列表
        is_chat: 是否为聊天数据
    
    Returns:
        过滤后的数据列表
    """
    if not data:
        return []
    
    filtered = []
    for item in data:
        if is_chat:
            # 弹幕过滤：过滤太短的消息
            message = item.get('message', '')
            if len(message.strip()) >= 2:
                filtered.append(item)
        else:
            # 转录过滤：过滤太短的文本
            text = item.get('text', '')
            if len(text.strip()) >= 3:
                filtered.append(item)
    
    return filtered

def build_content_index(segments, weights=None):
    """
    构建内容索引
    
    Args:
        segments: 片段列表，每个片段包含text字段
        weights: 可选的权重列表，与有效文本一一对应，用于按权重缩放向量
    
    Returns:
        tuple: (faiss_index, vectorizer, texts) 或 (None, None, [])
    """
    try:
        if not segments:
            return None, None, []
        
        # 提取文本，并同步筛选对应的权重
        texts = []
        filtered_weights = [] if weights is not None else None
        for i, seg in enumerate(segments):
            text = seg.get('text', '')
            if text and text.strip():
                texts.append(text)
                if filtered_weights is not None:
                    try:
                        filtered_weights.append(float(weights[i]))
                    except Exception:
                        filtered_weights.append(1.0)
        
        if not texts:
            return None, None, []
        
        # 检查依赖模块是否可用
        sklearn_vectorizer = _get_sklearn()
        if not sklearn_vectorizer:
            logging.warning("sklearn不可用，无法构建内容索引")
            return None, None, []
            
        if not NUMPY_AVAILABLE:
            logging.warning("numpy不可用，无法构建内容索引")
            return None, None, []
            
        if not FAISS_AVAILABLE:
            logging.warning("faiss不可用，无法构建内容索引")
            return None, None, []
        
        # 创建TF-IDF向量器
        vectorizer = sklearn_vectorizer(
            max_features=1000,
            stop_words='english',
            ngram_range=(1, 2)
        )
        
        # 向量化
        tfidf_matrix = vectorizer.fit_transform(texts)
        
        # 创建FAISS索引
        if tfidf_matrix.shape[0] > 0:
            # 转换为dense numpy数组
            dense_matrix = tfidf_matrix.toarray().astype('float32')
            
            # 按权重缩放
            if filtered_weights is not None and len(filtered_weights) == dense_matrix.shape[0]:
                w = np.asarray(filtered_weights, dtype='float32')
                # 避免全零或负数
                w = np.clip(w, 0.0, None)
                # 若全为0，则退化为1
                if np.all(w == 0):
                    w = np.ones_like(w, dtype='float32')
                # 归一化到[0,1]
                max_w = float(np.max(w)) if float(np.max(w)) > 0 else 1.0
                w = w / max_w
                dense_matrix = dense_matrix * w[:, None]
            
            # 创建FAISS索引
            dimension = dense_matrix.shape[1]
            index = faiss.IndexFlatIP(dimension)  # 内积索引
            index.add(dense_matrix)
            
            return index, vectorizer, texts
        else:
            return None, None, []
            
    except Exception as e:
        logging.error(f"构建内容索引失败: {e}")
        return None, None, []

def save_content_index(index, vectorizer, index_dir):
    """
    保存内容索引到文件
    
    Args:
        index: FAISS索引对象
        vectorizer: TF-IDF向量器
        index_dir: 索引保存目录
    
    Returns:
        bool: 保存是否成功
    """
    if not FAISS_AVAILABLE:
        logging.warning("faiss不可用，无法保存内容索引")
        return False
        
    try:
        os.makedirs(index_dir, exist_ok=True)
        
        # 保存FAISS索引
        index_file = os.path.join(index_dir, "content_index.faiss")
        faiss.write_index(index, index_file)
        
        # 保存向量器
        vectorizer_file = os.path.join(index_dir, "vectorizer.pkl")
        with open(vectorizer_file, 'wb') as f:
            pickle.dump(vectorizer, f)
        
        return True
    except Exception as e:
        logging.error(f"保存内容索引失败: {e}")
        return False

def load_content_index(index_dir):
    """
    从文件加载内容索引
    
    Args:
        index_dir: 索引文件目录
    
    Returns:
        tuple: (faiss_index, vectorizer) 或 (None, None)
    """
    if not FAISS_AVAILABLE:
        logging.warning("faiss不可用，无法加载内容索引")
        return None, None
        
    try:
        index_file = os.path.join(index_dir, "content_index.faiss")
        vectorizer_file = os.path.join(index_dir, "vectorizer.pkl")
        
        if not os.path.exists(index_file) or not os.path.exists(vectorizer_file):
            return None, None
        
        # 加载FAISS索引
        index = faiss.read_index(index_file)
        
        # 加载向量器
        with open(vectorizer_file, 'rb') as f:
            vectorizer = pickle.load(f)
        
        return index, vectorizer
    except Exception as e:
        logging.error(f"加载内容索引失败: {e}")
        return None, None

def format_time_duration(seconds):
    """
    将秒数格式化为时长字符串
    
    Args:
        seconds: 秒数
    
    Returns:
        str: 格式化的时长字符串 (如: "1:23:45" 或 "12:34")
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    else:
        return f"{m}:{s:02d}"

def ensure_directory_exists(directory_path):
    """
    确保目录存在，如果不存在则创建
    
    Args:
        directory_path: 目录路径
    
    Returns:
        bool: 目录是否存在或创建成功
    """
    try:
        os.makedirs(directory_path, exist_ok=True)
        return True
    except Exception as e:
        logging.error(f"创建目录失败: {directory_path}, 错误: {e}")
        return False

def safe_json_load(file_path, default=None):
    """
    安全地加载JSON文件
    
    Args:
        file_path: JSON文件路径
        default: 加载失败时的默认值
    
    Returns:
        加载的数据或默认值
    """
    if default is None:
        default = {}
    
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return default
    except Exception as e:
        logging.error(f"加载JSON文件失败: {file_path}, 错误: {e}")
        return default

def safe_json_save(data, file_path):
    """
    安全地保存JSON文件
    
    Args:
        data: 要保存的数据
        file_path: JSON文件路径
    
    Returns:
        bool: 保存是否成功
    """
    try:
        # 确保目录存在
        directory = os.path.dirname(file_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logging.error(f"保存JSON文件失败: {file_path}, 错误: {e}")
        return False

# ------------------ 文本清洗（英文化）工具 ------------------
EN_WORD_RE = re.compile(r"[a-zA-Z]+(?:'[a-zA-Z]+)?")

def sanitize_english_text(text: str,
                           keep_basic_punct: bool = True,
                           collapse_repeats: bool = True,
                           max_repeat: int = 4,
                           min_token_len: int = 2) -> str:
    """将模型/多语混杂转录文本清洗为英文可检索内容。

    处理步骤：
      1. Unicode 归一化 (NFKC)
      2. 去除控制字符 / 全角空白
      3. 提取英文单词 (允许内部撇号)，可选保留 .,!?: 这些标点
      4. 过滤太短 token
      5. 折叠连续重复 token (超过 max_repeat 次)
      6. 返回用空格拼接的英文序列；若为空，原样返回裁剪版

    Args:
        text: 原始文本
        keep_basic_punct: 是否保留基础英文标点
        collapse_repeats: 是否折叠重复单词
        max_repeat: 同一单词连续允许的最大重复次数
        min_token_len: 过滤的最小 token 长度
    """
    if not text:
        return ''
    try:
        # 归一化
        t = unicodedata.normalize('NFKC', text)
        # 去除奇怪的分隔符 / 波浪线 / 重复 ~
        t = t.replace('\u3000', ' ')
        t = re.sub(r"[~`^_]{2,}", " ", t)
        # 去除控制字符
        t = ''.join(ch if ch.isprintable() else ' ' for ch in t)
        # 提取英文单词
        words = EN_WORD_RE.findall(t)
        if min_token_len > 1:
            words = [w for w in words if len(w) >= min_token_len]
        if not words:
            # 尝试简单英文字符过滤
            fallback = re.sub(r"[^a-zA-Z0-9\s]+", " ", t).strip()
            return fallback
        # 折叠连续重复
        if collapse_repeats:
            collapsed = []
            last = None
            cnt = 0
            for w in words:
                wl = w.lower()
                if wl == last:
                    cnt += 1
                    if cnt <= max_repeat:
                        collapsed.append(w)
                else:
                    last = wl
                    cnt = 1
                    collapsed.append(w)
            words = collapsed
        cleaned = ' '.join(words)
        if keep_basic_punct:
            # 保留句末标点（简单规则：如果原文对应片段末尾有 .!?）
            if text.rstrip()[-1:] in '.!?':
                cleaned = cleaned.rstrip() + text.rstrip()[-1]
        return cleaned.strip()
    except Exception as e:
        logging.debug(f"sanitize_english_text 失败: {e}")
        try:
            return re.sub(r"[^a-zA-Z0-9\s]+", " ", text).strip()
        except Exception:
            return text[:200]

def get_video_stats(video_path):
    """
    获取视频的统计信息
    
    Args:
        video_path: 视频目录路径
    
    Returns:
        tuple: (切片数量, 平均评分)
    """
    clip_count = 0
    rating_sum = 0
    rating_count = 0
    
    # 检查评分文件
    rating_file = os.path.join(video_path, "ratings.json")
    ratings = safe_json_load(rating_file, {})
    
    for clip_name, data in ratings.items():
        rating = data.get("rating", 0)
        if rating > 0:
            rating_sum += rating
            rating_count += 1
    
    # 计算MP4文件数量
    try:
        for file in os.listdir(video_path):
            if file.lower().endswith('.mp4'):
                clip_count += 1
    except Exception as e:
        logging.error(f"统计视频文件失败: {video_path}, 错误: {e}")
    
    # 平均评分
    avg_rating = round(rating_sum / rating_count, 1) if rating_count > 0 else 0.0
    
    return clip_count, avg_rating

def extract_time_from_clip_filename(filename):
    """
    从切片文件名提取时间信息
    
    Args:
        filename: 文件名
    
    Returns:
        tuple: (开始时间, 结束时间)
    """
    start_time = 0
    end_time = 0
    try:
        if filename.startswith("clip_"):
            parts = filename.replace('.mp4', '').split('_')
            if len(parts) >= 3:
                start_time = float(parts[1])
                end_time = float(parts[2])
    except Exception:
        pass
    return start_time, end_time

def get_video_duration_cv2(video_path):
    """
    使用OpenCV获取视频时长
    
    Args:
        video_path: 视频文件路径
    
    Returns:
        float: 视频时长（秒）
    """
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps if fps > 0 else 0
        cap.release()
        return duration
    except Exception as e:
        logging.error(f"获取视频时长失败: {video_path}, 错误: {e}")
        return 0

def cleanup_empty_directories(base_path):
    """
    清理空目录
    
    Args:
        base_path: 基础路径
    
    Returns:
        int: 清理的目录数量
    """
    cleaned_count = 0
    try:
        for root, dirs, files in os.walk(base_path, topdown=False):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    # 如果目录为空，删除它
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        cleaned_count += 1
                        logging.info(f"删除空目录: {dir_path}")
                except Exception as e:
                    logging.error(f"删除目录失败: {dir_path}, 错误: {e}")
    except Exception as e:
        logging.error(f"清理目录失败: {base_path}, 错误: {e}")
    
    return cleaned_count

def validate_config_paths(config_manager):
    """
    验证配置中的路径是否有效
    
    Args:
        config_manager: 配置管理器
    
    Returns:
        list: 无效路径列表
    """
    invalid_paths = []
    
    path_configs = [
        "twitch_download_folder",  # 移除 CLIPS_BASE_DIR，不自动创建
        "LOCAL_EMOTION_MODEL_PATH",
        "VIDEO_EMOTION_MODEL_PATH"
    ]
    
    for config_key in path_configs:
        path = config_manager.get(config_key)
        if path and not os.path.exists(path):
            # 对于目录，尝试创建
            if config_key in ["twitch_download_folder"]:
                try:
                    os.makedirs(path, exist_ok=True)
                except Exception:
                    invalid_paths.append((config_key, path))
            else:
                # 对于文件，直接标记为无效
                invalid_paths.append((config_key, path))
    
    return invalid_paths
