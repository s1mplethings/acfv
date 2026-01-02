# config.py

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict

from acfv.runtime.storage import ensure_runtime_dirs, processing_path, settings_path

class ConfigManager:
    """配置管理器 - 单例模式"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """初始化配置管理器"""
        self.config: Dict[str, Any] = {}
        ensure_runtime_dirs()
        self.config_file = str(settings_path("config.json"))
        self._migrate_legacy_config()
        self._load_config()

    def _migrate_legacy_config(self) -> None:
        """迁移旧版 config.txt / config/config.txt 到新的 settings 目录。"""
        target = Path(self.config_file)
        if target.exists():
            return
        legacy_candidates = [
            Path("config.txt"),
            Path(__file__).resolve().parent / "config" / "config.txt",
            Path(__file__).resolve().parent / "config.txt",
        ]
        for candidate in legacy_candidates:
            if candidate.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copyfile(candidate, target)
                    logging.info("ℹ️ 已迁移旧配置文件 %s -> %s", candidate, target)
                except OSError as exc:
                    logging.warning("⚠️ 迁移配置文件失败 (%s): %s", candidate, exc)
                break
        
    def _load_config(self) -> None:
        """加载配置文件"""
        try:
            defaults = self.get_default_config()
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if not isinstance(loaded, dict):
                    loaded = {}
                merged = defaults.copy()
                merged.update(loaded)
                missing_keys = [k for k in defaults.keys() if k not in loaded]
                self.config = merged
                if missing_keys:
                    self.save_config()
                    logging.info(f"[config] added default keys: {', '.join(missing_keys)}")
                else:
                    logging.info(f"[config] loaded config file: {self.config_file}")
            else:
                self.config = defaults
                self.save_config()
                logging.info('[config] created default config file')
        except Exception as e:
            logging.error(f'加载配置文件失败: {e}')
            self.config = self.get_default_config()

    def get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        proc = processing_path
        return {
            "VIDEO_FILE": "",
            "CHAT_FILE": "",
            "CHAT_OUTPUT": str(proc("chat_with_emotes.json")),
            "TRANSCRIPTION_OUTPUT": str(proc("transcription.json")),
            "ANALYSIS_OUTPUT": str(proc("high_interest_segments.json")),
            "OUTPUT_CLIPS_DIR": str(proc("output_clips")),
            "CLIPS_BASE_DIR": "clips",
            "MAX_CLIP_COUNT": 10,
            "WHISPER_MODEL": "medium",
            "LLM_DEVICE": 0,
            "CHAT_DENSITY_WEIGHT": 0.2,
            "CHAT_SENTIMENT_WEIGHT": 0.3,
            "VIDEO_EMOTION_WEIGHT": 0.6,
            "AUDIO_TARGET_BONUS": 1.0,
            "TEXT_TARGET_BONUS": 1.0,
            "INTEREST_SCORE_THRESHOLD": 0.1,
            "MIN_TARGET_CLIP_DURATION": 180.0,
            "TARGET_CLIP_DURATION": 240.0,
            "MAX_TARGET_CLIP_DURATION": 300.0,
            "RAG_ENABLE": True,
            "RAG_WEIGHT": 0.2,
            "RAG_DB_PATH": str(processing_path("rag_database.json")),
            "RAG_SIMILARITY_WEIGHT": 0.2,
            "TWITCH_DOWNLOADER_PATH": "",
            "TWITCH_DOWNLOADER_AUTO_INSTALL": True,
            "LOCAL_EMOTION_MODEL_PATH": "",
            "VIDEO_EMOTION_MODEL_PATH": "",
            "VIDEO_EMOTION_SEGMENT_LENGTH": 4.0,
            "ENABLE_VIDEO_EMOTION": False,
            "twitch_client_id": "",
            "twitch_oauth_token": "",
            "twitch_username": "",
            "twitch_download_folder": "./data/twitch",
            "replay_download_folder": "./data/twitch",
            "CHECKPOINT_INTERVAL": 10,
            "MAX_WORKERS": 8,
            "GPU_DEVICE": "cuda:0",
            "ENABLE_GPU_ACCELERATION": True,
            "FORCE_SEMANTIC_SEGMENT": True,
            "MIN_CLIP_DURATION": 60.0,
            "CLIP_CONTEXT_EXTEND": 15.0,
            "MERGE_NEARBY_CLIPS": True,
            "CLIP_MERGE_THRESHOLD": 10.0,
            "ENABLE_SEMANTIC_MERGE": True,
            "SEMANTIC_SIMILARITY_THRESHOLD": 0.75,
            "SEMANTIC_MAX_TIME_GAP": 60.0,
            "PARALLEL_TRANSCRIPTION": True,
            "MAX_TRANSCRIPTION_WORKERS": 12,
            "SEGMENT_LENGTH": 60,
            "USE_GPU": True,
            "ENABLE_CACHE": True,
            "CACHE_DIR": "cache",
            "ENABLE_FAST_MODE": False,
            "ENABLE_SPEAKER_SEPARATION": True,
            "SPEAKER_SEPARATION_TIMEOUT": 1800,
            "HOST_AUDIO_FILE": "",
            "output_clips_folder": "./data/clips",
            "FORCE_RETRANSCRIPTION": False,
            "TRANSCRIPTION_LANGUAGE": "en",
            "TRANSCRIPTION_QUALITY": "high",
            "AUDIO_ENHANCEMENT": False,
            "NO_SPEECH_THRESHOLD": 0.6,
            "LOGPROB_THRESHOLD": -1.0,
            "PROGRESS_UPDATE_INTERVAL": 0.5,
            "LOG_LEVEL": "INFO",
            "APP_ICON_PATH": "acfv.png",
            "START_IN_TRAY": True,
            # UI/性能相关：允许在问题定位时禁用视频缩略图加载
            "DISABLE_VIDEO_THUMBNAILS": False,
            # Twitch 页面缩略图并发与开关
            "DISABLE_TWITCH_THUMBNAILS": False,
            "TWITCH_THUMBNAIL_CONCURRENCY": 6,
            "HUGGINGFACE_TOKEN": "",  # 新增：可通过设置界面直接写入
            "SUMMARY_BACKEND": "local",
            "LOCAL_SUMMARY_MODEL": "google/gemma-3-4b-it",
            "RAG_TOPIC_LLM_MODEL": "google/gemma-3-4b-it",
            "RAG_CLIPS_DB_ENABLE": True,
            "RAG_CLIPS_DB_PATH": "rag_store/clips.db",
            "RAG_IMPORT_DEFAULT_RATING": 5,
            "LOCAL_SUMMARY_MAX_NEW_TOKENS": 256,
            "LOCAL_SUMMARY_TEMPERATURE": 0.2,
            "LOCAL_SUMMARY_TOP_P": 0.9,
            "LOCAL_SUMMARY_REPEAT_PENALTY": 1.15,
            "LOCAL_SUMMARY_MAX_INPUT_CHARS": 4000,
        }
    
    def save_config(self) -> bool:
        """保存配置到文件"""
        try:
            Path(self.config_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            logging.info(f"已保存配置文件: {self.config_file}")
            return True
        except Exception as e:
            logging.error(f"保存配置文件失败: {e}")
            return False
    
    def save(self, file_path=None) -> bool:
        """兼容旧接口，保存配置到指定文件（默认config.txt）"""
        if file_path is None:
            file_path = self.config_file
        try:
            Path(file_path).parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            logging.info(f"已保存配置文件: {file_path}")
            return True
        except Exception as e:
            logging.error(f"保存配置文件失败: {e}")
            return False
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项"""
        return self.config.get(key, default)

    def _sync_hf_token(self, token: Any) -> None:
        """同步 HuggingFace token 到相关环境变量，便于依赖库立即可用。"""
        token_str = str(token or "").strip()
        env_keys = (
            "HUGGINGFACE_TOKEN",
            "HUGGINGFACE_HUB_TOKEN",
            "HUGGING_FACE_HUB_TOKEN",
            "HF_TOKEN",
        )
        if token_str:
            for name in env_keys:
                os.environ[name] = token_str
        else:
            for name in env_keys:
                os.environ.pop(name, None)

    def set(self, key: str, value: Any, *, persist: bool = False) -> None:
        """设置配置项并可选立即保存。

        默认仅更新内存中的配置，调用方可在批量更新后显式调用 save/save_config。
        若设置 HuggingFace token，会自动同步到常见的环境变量名称。
        """
        if key == "HUGGINGFACE_TOKEN" and isinstance(value, str):
            value = value.strip()
        self.config[key] = value
        if key == "HUGGINGFACE_TOKEN":
            self._sync_hf_token(value)
        if persist:
            self.save_config()
    
    def update(self, config_dict: Dict[str, Any]) -> None:
        """更新多个配置项"""
        self.config.update(config_dict)
        
    def validate_config(self) -> bool:
        """验证配置是否有效"""
        required_fields = ["OUTPUT_CLIPS_DIR", "MAX_CLIP_COUNT"]
        for field in required_fields:
            if not self.config.get(field):
                logging.warning(f"缺少必要的配置项: {field}")
                return False
        return True

# 创建全局配置管理器实例
config_manager = ConfigManager()

# 兼容旧版本的函数
def get_config():
    """获取配置 - 兼容旧版本"""
    return config_manager.config

def load_config():
    """加载配置 - 兼容旧版本"""
    config_manager._load_config()
    return config_manager.config

def save_config():
    """保存配置 - 兼容旧版本"""
    return config_manager.save_config()

# 为了向后兼容，添加模块级别的配置属性访问
class ConfigModule:
    """配置模块代理，允许模块级别的配置访问"""
    def __init__(self, original_module):
        # 保留原模块的所有属性
        self.__dict__.update(original_module.__dict__)
        
    def __getattr__(self, name):
        # 如果是原模块的属性，直接返回
        if name in self.__dict__:
            return self.__dict__[name]
        # 否则从配置管理器获取
        return config_manager.get(name)
    
    def __setattr__(self, name, value):
        # 如果是配置项，设置到配置管理器
        if name in ['config_manager', 'ConfigManager', 'get_config', 'load_config', 'save_config'] or name.startswith('_'):
            self.__dict__[name] = value
        else:
            config_manager.set(name, value, persist=True)

import sys
# 将当前模块替换为配置代理，但保留原有功能
original_module = sys.modules[__name__]
sys.modules[__name__] = ConfigModule(original_module)
