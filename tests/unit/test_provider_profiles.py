from __future__ import annotations

from acfv.providers import resolve_asr_profile, resolve_nested_value, resolve_ocr_profile, resolve_scene_profile


class _Cfg:
    def __init__(self, payload: dict):
        self.payload = payload

    def get(self, key, default=None):
        return self.payload.get(key, default)


def test_resolve_nested_value_supports_dotted_yaml():
    cfg = _Cfg({"providers": {"asr": {"default": "whisperx", "whisperx": {"model": "large-v3"}}}})
    assert resolve_nested_value(cfg, "providers.asr.default") == "whisperx"
    assert resolve_nested_value(cfg, "providers.asr.whisperx.model") == "large-v3"


def test_resolve_asr_profile_prefers_provider_yaml():
    cfg = _Cfg(
        {
            "providers": {
                "asr": {
                    "default": "whisperx",
                    "common": {"segment_length": 90, "language": "ja"},
                    "whisperx": {"model": "large-v3"},
                }
            }
        }
    )
    profile = resolve_asr_profile(cfg)
    assert profile["provider"] == "whisperx"
    assert profile["model"] == "large-v3"
    assert profile["segment_length"] == 90
    assert profile["language"] == "ja"


def test_resolve_scene_and_ocr_profiles_merge_legacy_keys():
    cfg = _Cfg({"ENABLE_SCREEN_DETECT": True, "SCREEN_ENABLE_OCR": False})
    scene = resolve_scene_profile(cfg)
    ocr = resolve_ocr_profile(cfg)
    assert scene["enabled"] is True
    assert ocr["enabled"] is False
