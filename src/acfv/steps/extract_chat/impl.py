import json
from pathlib import Path
from bs4 import BeautifulSoup
from transformers import pipeline
from acfv import config
import re
from acfv.main_logging import log_info, log_error, log_warning


def _resolve_device_id(device_id):
    try:
        import torch
    except Exception:
        return -1

    if isinstance(device_id, str):
        text = device_id.strip().lower()
        if text == "cpu":
            return -1
        if text.startswith("cuda"):
            if not torch.cuda.is_available():
                return -1
            parts = text.split(":", 1)
            if len(parts) == 2 and parts[1].isdigit():
                return int(parts[1])
            return 0
        try:
            return int(text)
        except Exception:
            return -1

    if isinstance(device_id, int):
        if device_id >= 0 and not torch.cuda.is_available():
            return -1
        return device_id

    return -1

def _maybe_hf_model_id(model_path):
    if not model_path:
        return None
    try:
        for part in Path(str(model_path)).parts:
            if part.startswith("models--"):
                slug = part[len("models--"):]
                if "--" in slug:
                    return slug.replace("--", "/")
    except Exception:
        return None
    return None


def _is_explicit_cpu_device(value):
    if isinstance(value, int):
        return value < 0
    if isinstance(value, str):
        return value.strip().lower() in {"cpu", "-1"}
    return False

def _build_sentiment_pipeline(model_path, device_id):
    model_id = _maybe_hf_model_id(model_path)
    if model_id:
        try:
            return pipeline(
                "sentiment-analysis",
                model=model_id,
                tokenizer=model_id,
                device=device_id
            )
        except Exception as model_id_err:
            log_warning(f"[chat] 模型ID加载失败({model_id_err})，回退到本地路径")
    try:
        return pipeline(
            "sentiment-analysis",
            model=model_path,
            tokenizer=model_path,
            device=device_id
        )
    except Exception as model_err:
        log_error(f"[chat] 加载情感模型失败({model_err})，尝试兼容加载")
        # 尝试忽略尺寸不匹配（部分本地模型可能配置不一致）
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            tokenizer = AutoTokenizer.from_pretrained(model_path)
            model = AutoModelForSequenceClassification.from_pretrained(
                model_path,
                ignore_mismatched_sizes=True
            )
            return pipeline(
                "sentiment-analysis",
                model=model,
                tokenizer=tokenizer,
                device=device_id
            )
        except Exception as ignore_err:
            log_error(f"[chat] 忽略尺寸加载失败: {ignore_err}")

        model_id = _maybe_hf_model_id(model_path)
        if model_id:
            try:
                from transformers import AutoTokenizer, AutoModelForSequenceClassification
                tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
                model = AutoModelForSequenceClassification.from_pretrained(
                    model_id,
                    ignore_mismatched_sizes=True,
                    local_files_only=True
                )
                return pipeline(
                    "sentiment-analysis",
                    model=model,
                    tokenizer=tokenizer,
                    device=device_id
                )
            except Exception:
                try:
                    tokenizer = AutoTokenizer.from_pretrained(model_id)
                    model = AutoModelForSequenceClassification.from_pretrained(
                        model_id,
                        ignore_mismatched_sizes=True
                    )
                    return pipeline(
                        "sentiment-analysis",
                        model=model,
                        tokenizer=tokenizer,
                        device=device_id
                    )
                except Exception as model_id_err:
                    log_error(f"[chat] 兼容模型ID加载失败: {model_id_err}")

        # 回退到默认模型
        fallback_model = "distilbert-base-uncased-finetuned-sst-2-english"
        if model_path != fallback_model:
            try:
                log_info(f"[chat] 回退到默认模型: {fallback_model}")
                return pipeline(
                    "sentiment-analysis",
                    model=fallback_model,
                    tokenizer=fallback_model,
                    device=device_id
                )
            except Exception as fallback_err:
                log_error(f"[chat] 回退模型加载失败: {fallback_err}")
        return None

def convert_timestamp_to_seconds(timestamp):
    """
    将形如 "[0:00:11]" 的时间戳转换为总秒数（float）。
    """
    match = re.match(r'\[(\d+):(\d+):(\d+)\]', timestamp)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        total_seconds = hours * 3600 + minutes * 60 + seconds
        return float(total_seconds)
    else:
        return 0.0

def extract_chat(input_file, output_file):
    """
    从 HTML 中提取聊天弹幕，并使用 transformers 的情感分析模型进行打分，
    最终将结果保存为 JSON 文件。
    """
    log_info(f"Extracting chat from {input_file}")
    try:
        with open(input_file, 'r', encoding='utf-8') as file:
            soup = BeautifulSoup(file, 'html.parser')
        # 安全获取本地模型路径 & 设备，缺失时使用默认模型 (distilbert-base-uncased-finetuned-sst-2-english)
        try:
            local_model_path = getattr(config, 'LOCAL_EMOTION_MODEL_PATH', None)
        except Exception:
            local_model_path = None
        # 某些版本 config 是一个包，实际值在 config.config_manager
        if not local_model_path:
            try:
                from acfv.config import config_manager
                local_model_path = config_manager.get('LOCAL_EMOTION_MODEL_PATH', '').strip()
            except Exception:
                local_model_path = None
        if isinstance(local_model_path, str):
            local_model_path = local_model_path.strip()
        if not local_model_path:
            # 使用 huggingface 默认模型；避免直接抛出 attribute error
            local_model_path = "distilbert-base-uncased-finetuned-sst-2-english"
            log_info(f"[chat] LOCAL_EMOTION_MODEL_PATH 未设置，使用默认模型: {local_model_path}")
        # 设备获取（优先 config.LLM_DEVICE，再使用 config_manager 或 0）
        device_setting = None
        try:
            device_setting = getattr(config, 'LLM_DEVICE', None)
        except Exception:
            try:
                from acfv.config import config_manager
                device_setting = config_manager.get('LLM_DEVICE', None)
            except Exception:
                device_setting = None
        if device_setting is None:
            device_setting = 0
        device_id = _resolve_device_id(device_setting)

        enable_gpu = None
        use_gpu = None
        gpu_device_setting = None
        try:
            enable_gpu = getattr(config, 'ENABLE_GPU_ACCELERATION', None)
            use_gpu = getattr(config, 'USE_GPU', None)
            gpu_device_setting = getattr(config, 'GPU_DEVICE', None)
        except Exception:
            pass
        try:
            from acfv.config import config_manager
            if enable_gpu is None:
                enable_gpu = config_manager.get('ENABLE_GPU_ACCELERATION', True)
            if use_gpu is None:
                use_gpu = config_manager.get('USE_GPU', True)
            if not gpu_device_setting:
                gpu_device_setting = config_manager.get('GPU_DEVICE', None)
        except Exception:
            pass
        if enable_gpu is None:
            enable_gpu = True
        if use_gpu is None:
            use_gpu = True

        if not enable_gpu or not use_gpu:
            device_id = -1
        elif device_id < 0 and not _is_explicit_cpu_device(device_setting):
            fallback_device = gpu_device_setting or "cuda:0"
            device_id = _resolve_device_id(fallback_device)
            if device_id < 0:
                log_warning("[chat] GPU 不可用，情感分析将使用 CPU")
        sentiment_pipeline = _build_sentiment_pipeline(local_model_path, device_id)
        if sentiment_pipeline is None:
            log_error("[chat] 情感模型不可用，回退到伪 neutral 评分")

        chat_data = []
        for comment in soup.find_all('pre', class_='comment-root'):
            timestamp_str = comment.contents[0].strip() if comment.contents else ''
            timestamp = convert_timestamp_to_seconds(timestamp_str)
            author = comment.find('span', class_='comment-author')
            author_name = author.text.strip() if author else 'Anonymous'
            message = comment.find('span', class_='comment-message')
            message_text = message.text.strip() if message else ''
            emote = comment.find('img', class_='emote-image')
            emote_title = emote['title'] if emote else ''
            if sentiment_pipeline and message_text:
                try:
                    sentiment = sentiment_pipeline(message_text)[0]
                except Exception as inf_err:
                    log_error(f"[chat] 单条情感推理失败: {inf_err}")
                    sentiment = {"label": "neutral", "score": 0}
            else:
                sentiment = {"label": "neutral", "score": 0}
            chat_data.append({
                "timestamp": timestamp,
                "author": author_name,
                "message": message_text,
                "emote": emote_title,
                "sentiment": sentiment
            })

        log_info(f"Extracted {len(chat_data)} chat messages")
        with open(output_file, 'w', encoding='utf-8') as outfile:
            json.dump(chat_data, outfile, ensure_ascii=False, indent=4)
        log_info(f"Chat data saved to {output_file}")

    except Exception as e:
        # 之前直接 raise 导致并行阶段整体标记失败；改为写出一个空文件保证后续流程继续
        log_error(f"Error extracting chat: {e}")
        try:
            with open(output_file, 'w', encoding='utf-8') as outfile:
                json.dump([], outfile, ensure_ascii=False, indent=2)
            log_info(f"[chat] 由于错误写出空聊天文件: {output_file}")
        except Exception:
            pass
        # 不再向上抛出，让管道使用 has_chat_json=False 分支
        return []
