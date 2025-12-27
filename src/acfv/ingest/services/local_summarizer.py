from __future__ import annotations

import json
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Dict, Iterable, List, Optional, Tuple

try:
    from acfv.config._config_impl import config_manager
except Exception:  # pragma: no cover - config optional
    config_manager = None

log = logging.getLogger(__name__)

_FILLER_ZH = {
    "啊", "呃", "嗯", "哈哈", "笑死", "卧槽", "草", "呜呜", "诶", "额",
    "呐", "嘛", "吧", "呀", "哎", "唉", "欸", "嗯嗯", "啊啊", "哇", "嘿",
}
_FILLER_EN = {
    "uh", "um", "erm", "like", "you know", "kinda", "sorta", "lol", "lmao",
    "hmm", "ah", "oh", "hey", "ha", "haha",
}
_STOP_ZH = {
    "的", "了", "是", "我", "你", "他", "她", "它", "我们", "你们", "他们",
    "啊", "吗", "呀", "吧", "就", "都", "和", "与", "在", "有", "也", "很",
}
_STOP_EN = {
    "and", "the", "with", "this", "that", "what", "you", "have", "for", "but",
    "are", "was", "when", "where", "how", "just", "like", "get", "got",
    "i", "me", "my", "we", "our", "us", "your", "youre", "im", "ive",
    "so", "thank", "thanks", "much",
}


def _cfg_value(key: str, default):
    if config_manager is not None:
        val = config_manager.get(key, None)
        if val is not None:
            return val
    return os.getenv(key, default)


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _resolve_device() -> int:
    if config_manager is not None and not config_manager.get("ENABLE_GPU_ACCELERATION", True):
        return -1
    device_id = _to_int(_cfg_value("LLM_DEVICE", 0), 0)
    if device_id < 0:
        return -1
    try:
        import torch
    except Exception:
        return -1
    if not torch.cuda.is_available():
        return -1
    return device_id


def _detect_zh(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _remove_fillers(text: str, is_zh: bool) -> str:
    if not text:
        return ""
    cleaned = text
    if is_zh:
        for word in _FILLER_ZH:
            cleaned = cleaned.replace(word, " ")
    for phrase in _FILLER_EN:
        cleaned = re.sub(rf"\b{re.escape(phrase)}\b", " ", cleaned, flags=re.IGNORECASE)
    return _collapse_ws(cleaned)


def _split_sentences(text: str, is_zh: bool) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[。！？!?；;:\n]+", text)
    parts = [p.strip() for p in parts if p and p.strip()]
    if len(parts) > 1:
        return parts
    if len(text) <= 120:
        return [text.strip()]
    chunks: List[str] = []
    step = 80 if is_zh else 100
    for i in range(0, len(text), step):
        chunk = text[i:i + step].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _dedupe_segments(segments: List[str]) -> List[str]:
    deduped: List[str] = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        if deduped:
            prev = deduped[-1]
            if _similar(prev.lower(), seg.lower()) >= 0.9:
                continue
        deduped.append(seg)
    return deduped


def clean_transcript(text: str) -> str:
    text = _collapse_ws(text)
    if not text:
        return ""
    is_zh = _detect_zh(text)
    text = _remove_fillers(text, is_zh)
    segments = _split_sentences(text, is_zh)
    segments = _dedupe_segments(segments)
    joiner = "。 " if is_zh else ". "
    return joiner.join(segments).strip()


class _LocalPipeline:
    def __init__(self, model_name: str, device_id: int) -> None:
        self.model_name = model_name
        self.device_id = device_id
        self.pipeline = None
        self.task = ""

    def _ensure(self) -> None:
        if self.pipeline is not None:
            return
        from transformers import pipeline
        try:
            self.pipeline = pipeline("text2text-generation", model=self.model_name, device=self.device_id)
            self.task = "text2text-generation"
        except Exception:
            self.pipeline = pipeline("text-generation", model=self.model_name, device=self.device_id)
            self.task = "text-generation"

    def generate(self, prompt: str, max_new_tokens: int, temperature: float, top_p: float, repeat_penalty: float) -> str:
        self._ensure()
        do_sample = temperature > 0
        kwargs = {
            "max_new_tokens": max_new_tokens,
            "do_sample": do_sample,
            "temperature": temperature,
            "top_p": top_p,
            "repetition_penalty": repeat_penalty,
            "truncation": True,
        }
        output = self.pipeline(prompt, **kwargs)
        if not output:
            return ""
        text = output[0].get("generated_text") or output[0].get("summary_text") or ""
        if self.task == "text-generation" and text.startswith(prompt):
            text = text[len(prompt):]
        return text.strip()


_PIPELINE: Optional[_LocalPipeline] = None


def _get_pipeline() -> _LocalPipeline:
    global _PIPELINE
    if _PIPELINE is None:
        model = str(_cfg_value("LOCAL_SUMMARY_MODEL", "google/flan-t5-small")).strip()
        device = _resolve_device()
        _PIPELINE = _LocalPipeline(model, device)
    return _PIPELINE


def _build_event_prompt(cleaned: str, context: str, is_zh: bool) -> str:
    if is_zh:
        prompt = (
            "你在总结一段视频切片的口语转写。请抽取 3-6 条关键事件，"
            "每条包含：主体 + 动作 + 结果（可选时间/原因）。\n"
            "规则：忽略口头语/语气词/重复，不要列关键词堆，不要空泛形容词。\n"
            "输出格式：\n事件:\n- 事件1\n- 事件2\n"
        )
        if context:
            prompt += f"\n补充上下文: {context}\n"
        prompt += f"\n转写文本:\n{cleaned}\n"
        return prompt
    prompt = (
        "You are summarizing a spoken transcript. Extract 3-6 key events.\n"
        "Each event must include: subject + action + result (optional time/reason).\n"
        "Ignore filler words/repetition. Do not output keyword lists.\n"
        "Output format:\nEvents:\n- Event 1\n- Event 2\n"
    )
    if context:
        prompt += f"\nExtra context: {context}\n"
    prompt += f"\nTranscript:\n{cleaned}\n"
    return prompt


def _build_summary_prompt(events: List[str], context: str, is_zh: bool) -> str:
    events_block = "\n".join(f"- {e}" for e in events if e)
    if is_zh:
        prompt = (
            "基于事件列表生成最终输出：\n"
            "1) 一句话总结（<=30字，完整句子，包含关键动作/结果）\n"
            "2) 关键事件（3-6条；主体+动作+结果）\n"
            "3) 标签（3-5个；主题名词短语，不含口头语）\n"
            "规则：同义不重复；信息不足写“信息不足：xxx”。\n"
        )
        if context:
            prompt += f"\n补充上下文: {context}\n"
        prompt += f"\n事件列表:\n{events_block}\n"
        return prompt
    prompt = (
        "Based on the event list, produce:\n"
        "1) One-sentence summary (<=30 words, full sentence, key action/result)\n"
        "2) Key events (3-6; subject+action+result)\n"
        "3) Tags (3-5 short noun phrases)\n"
        "Rules: no repetition; if info is missing, say 'Missing: ...'.\n"
    )
    if context:
        prompt += f"\nExtra context: {context}\n"
    prompt += f"\nEvent list:\n{events_block}\n"
    return prompt


def _parse_events(text: str) -> List[str]:
    events: List[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("-", "•", "*")):
            events.append(line.lstrip("-•* ").strip())
            continue
        if re.match(r"^\d+[).、]\s*", line):
            events.append(re.sub(r"^\d+[).、]\s*", "", line).strip())
    return [e for e in events if e]


def _parse_summary_output(text: str) -> Tuple[str, List[str], List[str]]:
    summary = ""
    events: List[str] = []
    tags: List[str] = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines:
        if line.startswith(("1)", "1.", "1、")) or line.startswith("一句话总结"):
            summary = re.sub(r"^1[).、]\s*", "", line).replace("一句话总结", "").strip("：: ")
        if line.startswith(("2)", "2.", "2、")) or line.startswith("关键事件"):
            continue
        if line.startswith(("3)", "3.", "3、")) or line.startswith("标签") or line.lower().startswith("tags"):
            tag_line = line
            tag_line = tag_line.replace("标签", "").replace("Tags", "").replace("tags", "")
            tag_line = tag_line.strip("：: ")
            if tag_line:
                tags.extend([t.strip() for t in re.split(r"[，,、/| ]+", tag_line) if t.strip()])
            continue
        if line.startswith(("-", "•", "*")):
            events.append(line.lstrip("-•* ").strip())
    if not summary and lines:
        summary = lines[0]
    return summary, events, tags


def _fallback_tags(cleaned: str, is_zh: bool) -> List[str]:
    tokens = re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}", cleaned.lower())
    stop = _STOP_ZH if is_zh else _STOP_EN
    freq: Dict[str, int] = {}
    for tok in tokens:
        if tok in stop:
            continue
        freq[tok] = freq.get(tok, 0) + 1
    return [t for t, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]]


def _has_repetition(text: str) -> bool:
    tokens = re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}", text.lower())
    freq: Dict[str, int] = {}
    for tok in tokens:
        freq[tok] = freq.get(tok, 0) + 1
    return any(count > 3 for count in freq.values())


def _needs_retry(summary: str, tags: List[str], raw: str) -> bool:
    if not summary or len(summary) < 6:
        return True
    if len(tags) < 3:
        return True
    if _has_repetition(raw):
        return True
    return False


def summarize_local(text: str, context: str = "") -> Dict[str, object]:
    cleaned = clean_transcript(text)
    if not cleaned:
        return {"summary_text": "", "events": [], "tags": [], "raw_answer": "", "error": "empty_input"}

    is_zh = _detect_zh(cleaned)
    max_input = _to_int(_cfg_value("LOCAL_SUMMARY_MAX_INPUT_CHARS", 4000), 4000)
    if len(cleaned) > max_input:
        cleaned = cleaned[:max_input]

    max_new = _to_int(_cfg_value("LOCAL_SUMMARY_MAX_NEW_TOKENS", 256), 256)
    temperature = _to_float(_cfg_value("LOCAL_SUMMARY_TEMPERATURE", 0.2), 0.2)
    top_p = _to_float(_cfg_value("LOCAL_SUMMARY_TOP_P", 0.9), 0.9)
    repeat_penalty = _to_float(_cfg_value("LOCAL_SUMMARY_REPEAT_PENALTY", 1.15), 1.15)

    llm = _get_pipeline()

    event_prompt = _build_event_prompt(cleaned, context, is_zh)
    event_output = llm.generate(event_prompt, max_new, temperature, top_p, repeat_penalty)
    events = _parse_events(event_output)
    if not events:
        events = _split_sentences(cleaned, is_zh)[:3]

    summary_prompt = _build_summary_prompt(events, context, is_zh)
    summary_output = llm.generate(summary_prompt, max_new, temperature, top_p, repeat_penalty)
    summary, event_lines, tags = _parse_summary_output(summary_output)
    if event_lines:
        events = event_lines
    if not tags:
        tags = _fallback_tags(cleaned, is_zh)

    if _needs_retry(summary, tags, summary_output):
        retry_prefix = "你上一版总结失败原因：重复或空泛。请重新输出，更具体。" if is_zh else (
            "Previous summary failed due to repetition/vagueness. Rewrite with concrete actions."
        )
        retry_prompt = retry_prefix + "\n" + summary_prompt
        retry_output = llm.generate(retry_prompt, max_new, temperature, top_p, repeat_penalty)
        retry_summary, retry_events, retry_tags = _parse_summary_output(retry_output)
        if retry_summary:
            summary = retry_summary
            summary_output = retry_output
        if retry_events:
            events = retry_events
        if retry_tags:
            tags = retry_tags

    return {
        "summary_text": summary,
        "summary": summary,
        "events": events,
        "tags": tags,
        "cleaned_text": cleaned,
        "raw_answer": summary_output,
        "model": getattr(llm, "model_name", ""),
    }


def stream_summary_local(text: str, context: str = "") -> Iterable[str]:
    result = summarize_local(text, context=context)
    yield json.dumps(result, ensure_ascii=False)
