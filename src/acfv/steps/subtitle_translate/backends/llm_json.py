from __future__ import annotations

import json
import logging
from typing import Dict, List
from urllib import request

from .base import TranslatorBackend
from ..blockify import SubtitleBlock

logger = logging.getLogger(__name__)


class LlmJsonBackend(TranslatorBackend):
    name = "llm_json"

    def __init__(self, api_url: str, api_key: str | None, model: str, timeout: float = 60.0, system_prompt: str = ""):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.system_prompt = system_prompt

    def translate_block(self, block: SubtitleBlock) -> Dict[str, str]:
        prompt = _build_prompt(block)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt or "Return JSON items with id and zh."},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        data = json.loads(raw)
        items = _extract_items(data)
        result: Dict[str, str] = {}
        for item in items:
            event_id = str(item.get("id") or "").strip()
            text = str(item.get("zh") or "").strip()
            if event_id and text:
                result[event_id] = text
        if not result:
            raise ValueError("LLM JSON backend returned no items")
        return result


def _build_prompt(block: SubtitleBlock) -> str:
    lines = [block.block_text()]
    lines.append("")
    lines.append("Return JSON: {\"items\":[{\"id\":\"0001\",\"zh\":\"...\"}, ...]}")
    return "\n".join(lines)


def _extract_items(payload: dict) -> List[dict]:
    if isinstance(payload, dict) and "items" in payload:
        return payload.get("items") or []
    if isinstance(payload, dict):
        choices = payload.get("choices") or []
        if choices:
            message = choices[0].get("message", {})
            content = message.get("content") if isinstance(message, dict) else None
            if isinstance(content, str):
                try:
                    inner = json.loads(content)
                    if isinstance(inner, dict):
                        return inner.get("items") or []
                except json.JSONDecodeError:
                    logger.warning("[subtitle_translate] LLM response content is not JSON")
    return []


__all__ = ["LlmJsonBackend"]
