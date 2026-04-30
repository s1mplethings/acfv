from __future__ import annotations

from typing import Any

from .config import provider_settings


ASR_PROVIDER_DEFAULT = "faster-whisper"


def resolve_asr_profile(config_manager: Any) -> dict[str, Any]:
    profile = provider_settings(
        config_manager,
        "asr",
        default_provider=ASR_PROVIDER_DEFAULT,
        legacy={
            "WHISPER_ENGINE": "provider",
            "WHISPER_MODEL": "model",
            "HF_WHISPER_MODEL": "hf_model",
            "TRANSCRIPTION_LANGUAGE": "language",
            "SEGMENT_LENGTH": "segment_length",
        },
    )
    provider = str(profile.get("provider") or ASR_PROVIDER_DEFAULT).strip().lower()
    model = str(profile.get("model") or profile.get("model_size") or "medium").strip()
    hf_model = str(profile.get("hf_model") or profile.get("huggingface_model") or "openai/whisper-medium").strip()
    language = str(profile.get("language") or "").strip().lower() or None
    device = str(profile.get("device") or "auto").strip().lower()
    segment_length = profile.get("segment_length", 120)
    try:
        segment_length = max(1, int(segment_length))
    except Exception:
        segment_length = 120
    return {
        "provider": provider,
        "model": model,
        "hf_model": hf_model,
        "language": None if language in {"", "auto", "detect", "default"} else language,
        "device": device,
        "segment_length": segment_length,
    }


__all__ = ["ASR_PROVIDER_DEFAULT", "resolve_asr_profile"]
