import json
from bs4 import BeautifulSoup
from transformers import pipeline
from acfv import config
import re
from main_logging import log_info, log_error

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
        if not local_model_path:
            # 使用 huggingface 默认模型；避免直接抛出 attribute error
            local_model_path = "distilbert-base-uncased-finetuned-sst-2-english"
            log_info(f"[chat] LOCAL_EMOTION_MODEL_PATH 未设置，使用默认模型: {local_model_path}")
        # 设备获取（优先 config.LLM_DEVICE，再使用 config_manager 或 0）
        device_id = 0
        try:
            device_id = getattr(config, 'LLM_DEVICE', 0)
        except Exception:
            try:
                from acfv.config import config_manager
                device_id = config_manager.get('LLM_DEVICE', 0)
            except Exception:
                device_id = 0
        try:
            sentiment_pipeline = pipeline(
                "sentiment-analysis",
                model=local_model_path,
                tokenizer=local_model_path,
                device=device_id
            )
        except Exception as model_err:
            log_error(f"[chat] 加载情感模型失败({model_err})，回退到伪 neutral 评分")
            sentiment_pipeline = None

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