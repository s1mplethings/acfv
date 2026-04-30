from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from acfv.providers import provider_settings

logger = logging.getLogger(__name__)


class JsonSchemaValidationError(ValueError):
    pass


@dataclass
class OpenAIClientConfig:
    provider: str = "disabled"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout: float = 60.0
    max_retries: int = 2
    prefer_responses_api: bool = True

    @classmethod
    def from_sources(
        cls,
        *,
        config_manager: Any = None,
        model: str | None = None,
        prefix: str | None = None,
    ) -> "OpenAIClientConfig":
        prefix_key = (prefix or "").strip().upper()

        def _cfg(name: str, default: Any = "") -> Any:
            if config_manager is None:
                return default
            try:
                return config_manager.get(name, default)
            except TypeError:
                return config_manager.get(name) if config_manager.get(name) is not None else default
            except Exception:
                return default

        def _pick(explicit: str | None, cfg_keys: Sequence[str], env_keys: Sequence[str], default: str = "") -> str:
            if explicit:
                return str(explicit).strip()
            for key in cfg_keys:
                value = _cfg(key, "")
                if value not in (None, ""):
                    return str(value).strip()
            for key in env_keys:
                value = os.getenv(key, "")
                if value:
                    return value.strip()
            return default

        model_keys = [f"{prefix_key}_MODEL"] if prefix_key else []
        api_key_keys = [f"{prefix_key}_API_KEY"] if prefix_key else []
        base_url_keys = [f"{prefix_key}_BASE_URL"] if prefix_key else []
        common_model_keys = ["LLM_MODEL", "OPENAI_MODEL"]
        common_api_keys = ["LLM_API_KEY", "OPENAI_API_KEY"]
        common_base_url_keys = ["LLM_BASE_URL", "OPENAI_BASE_URL"]
        provider_profile = provider_settings(
            config_manager,
            "llm",
            default_provider="disabled",
            legacy={
                "LLM_PROVIDER": "provider",
                "LLM_API_KEY": "api_key",
                "LLM_BASE_URL": "base_url",
                "LLM_MODEL": "model",
                "OPENAI_API_KEY": "api_key",
                "OPENAI_BASE_URL": "base_url",
                "OPENAI_MODEL": "model",
            },
        )
        provider = str(provider_profile.get("provider") or "disabled").strip().lower()
        provider_model = str(provider_profile.get("model") or "").strip()
        provider_base_url = str(provider_profile.get("base_url") or "").strip()
        provider_api_key = str(provider_profile.get("api_key") or "").strip()

        if prefix_key:
            prefix_profile = provider_settings(
                config_manager,
                "llm",
                default_provider=provider or "disabled",
                legacy={
                    f"{prefix_key}_PROVIDER": "provider",
                    f"{prefix_key}_API_KEY": "api_key",
                    f"{prefix_key}_BASE_URL": "base_url",
                    f"{prefix_key}_MODEL": "model",
                },
            )
            prefix_provider = str(prefix_profile.get("provider") or "").strip().lower()
            if prefix_provider:
                provider = prefix_provider
            provider_model = str(prefix_profile.get("model") or provider_model).strip()
            provider_base_url = str(prefix_profile.get("base_url") or provider_base_url).strip()
            provider_api_key = str(prefix_profile.get("api_key") or provider_api_key).strip()

        return cls(
            provider=provider or "disabled",
            api_key=_pick(
                provider_api_key or None,
                api_key_keys + common_api_keys,
                common_api_keys,
                default="ollama" if provider in {"ollama", "vllm", "openai-compatible", "local-openai"} else "",
            ),
            base_url=_pick(
                provider_base_url or None,
                base_url_keys + common_base_url_keys,
                common_base_url_keys,
                default="http://127.0.0.1:11434/v1" if provider == "ollama" else "",
            ),
            model=_pick(
                model or provider_model or None,
                model_keys + common_model_keys,
                common_model_keys,
                default="qwen2.5:7b-instruct" if provider == "ollama" else "",
            ),
            timeout=float(_pick(None, ["OPENAI_TIMEOUT_SEC"], ["OPENAI_TIMEOUT_SEC"], default="60") or 60.0),
            max_retries=int(_pick(None, ["OPENAI_MAX_RETRIES"], ["OPENAI_MAX_RETRIES"], default="2") or 2),
            prefer_responses_api=str(
                _pick(None, ["OPENAI_PREFER_RESPONSES"], ["OPENAI_PREFER_RESPONSES"], default="true")
            ).strip().lower()
            not in {"0", "false", "no", "off"},
        )


def parse_json_object(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise JsonSchemaValidationError("empty LLM output")

    candidates = [text]
    if "```" in text:
        for marker in ("```json", "```JSON", "```"):
            if marker in text:
                parts = text.split(marker)
                for chunk in parts[1:]:
                    chunk = chunk.split("```", 1)[0].strip()
                    if chunk:
                        candidates.append(chunk)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        candidates.append(text[start : end + 1])

    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except Exception:
            continue
        if isinstance(value, dict):
            return value
    raise JsonSchemaValidationError("LLM output is not a JSON object")


def _default_validator(payload: Dict[str, Any]) -> Dict[str, Any]:
    return payload


class OpenAIJsonClient:
    def __init__(self, config: OpenAIClientConfig):
        self.config = config
        self._client = None
        self._client_error: Exception | None = None
        self._lazy_init()

    def _lazy_init(self) -> None:
        if self._client is not None or self._client_error is not None:
            return
        if self.config.provider in {"", "disabled", "none", "off"}:
            self._client_error = RuntimeError("LLM provider disabled")
            return
        try:
            from openai import OpenAI

            api_key = self.config.api_key or "ollama"
            kwargs: Dict[str, Any] = {"api_key": api_key}
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            if self.config.max_retries >= 0:
                kwargs["max_retries"] = self.config.max_retries
            if self.config.timeout:
                kwargs["timeout"] = self.config.timeout
            self._client = OpenAI(**kwargs)
        except Exception as exc:  # pragma: no cover - defensive on runtime env
            self._client_error = exc

    @property
    def available(self) -> bool:
        if self._client is None:
            return False
        if not self.config.model:
            return False
        if self.config.provider in {"ollama", "vllm", "openai-compatible", "local-openai"}:
            return bool(self.config.base_url)
        return bool(self.config.api_key)

    def availability_error(self) -> str | None:
        if self.config.provider in {"", "disabled", "none", "off"}:
            return "LLM provider disabled"
        if self.config.provider in {"ollama", "vllm", "openai-compatible", "local-openai"}:
            if not self.config.base_url:
                return "missing LLM base_url for local provider"
            if not self.config.model:
                return "missing LLM model for local provider"
            return str(self._client_error) if self._client_error else None
        if self.config.api_key:
            return str(self._client_error) if self._client_error else None
        return "missing LLM_API_KEY/OPENAI_API_KEY"

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        validator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
        schema: Optional[Dict[str, Any]] = None,
        images: Optional[Iterable[Dict[str, str]]] = None,
        temperature: float = 0.1,
    ) -> Dict[str, Any]:
        if not self.available:
            raise RuntimeError(self.availability_error() or "OpenAI client unavailable")

        validate = validator or _default_validator
        last_error: Exception | None = None
        image_items = list(images or [])

        for attempt in range(max(1, self.config.max_retries + 1)):
            try:
                raw = self._call(system_prompt, user_prompt, schema=schema, images=image_items, temperature=temperature)
                payload = parse_json_object(raw)
                return validate(payload)
            except Exception as exc:
                last_error = exc
                logger.warning("[openai_client] JSON completion failed attempt=%s err=%s", attempt + 1, exc)
                if attempt + 1 >= max(1, self.config.max_retries + 1):
                    break
                time.sleep(min(4.0, 0.8 * (2**attempt)))
        raise RuntimeError(f"LLM JSON completion failed: {last_error}")

    def _call(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: Optional[Dict[str, Any]],
        images: List[Dict[str, str]],
        temperature: float,
    ) -> str:
        assert self._client is not None
        if not images and self.config.prefer_responses_api:
            try:
                return self._call_responses(system_prompt, user_prompt, schema=schema, temperature=temperature)
            except Exception as exc:
                logger.info("[openai_client] responses API unavailable, fallback to chat: %s", exc)
        return self._call_chat(system_prompt, user_prompt, schema=schema, images=images, temperature=temperature)

    def _call_responses(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: Optional[Dict[str, Any]],
        temperature: float,
    ) -> str:
        assert self._client is not None
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
            ],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        if schema:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "acfv_response",
                    "schema": schema,
                    "strict": False,
                }
            }
        response = self._client.responses.create(**kwargs)
        output_text = getattr(response, "output_text", "") or ""
        if output_text:
            return output_text
        output = getattr(response, "output", None) or []
        chunks: List[str] = []
        for item in output:
            for content in getattr(item, "content", []) or []:
                text_obj = getattr(content, "text", None)
                if isinstance(text_obj, str) and text_obj:
                    chunks.append(text_obj)
        if chunks:
            return "\n".join(chunks)
        raise RuntimeError("responses API returned no text")

    def _call_chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        schema: Optional[Dict[str, Any]],
        images: List[Dict[str, str]],
        temperature: float,
    ) -> str:
        assert self._client is not None
        user_content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
        for image in images:
            mime = image.get("mime_type") or "image/jpeg"
            b64 = image.get("data_base64") or ""
            if not b64:
                continue
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            )
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content if images else user_prompt},
            ],
            "temperature": temperature,
        }
        if schema:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            completion = self._client.chat.completions.create(**kwargs)
        except Exception:
            kwargs.pop("response_format", None)
            completion = self._client.chat.completions.create(**kwargs)
        choices = getattr(completion, "choices", None) or []
        if not choices:
            raise RuntimeError("chat completion returned no choices")
        message = choices[0].message
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "\n".join(parts)
        raise RuntimeError("chat completion returned no content")


def get_default_client(*, config_manager: Any = None, model: str | None = None, prefix: str | None = None) -> OpenAIJsonClient:
    return OpenAIJsonClient(OpenAIClientConfig.from_sources(config_manager=config_manager, model=model, prefix=prefix))


__all__ = [
    "JsonSchemaValidationError",
    "OpenAIClientConfig",
    "OpenAIJsonClient",
    "get_default_client",
    "parse_json_object",
]
