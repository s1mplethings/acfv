from acfv.config._config_impl import ConfigManager
from acfv.modular.plugins.transcribe_audio import spec as transcribe_spec


def test_default_config_prefers_medium_and_120s_chunks():
    defaults = ConfigManager().get_default_config()

    assert defaults["WHISPER_MODEL"] == "medium"
    assert defaults["SEGMENT_LENGTH"] == 120


def test_transcribe_plugin_defaults_match_runtime_recommendation():
    assert transcribe_spec.default_params["whisper_model"] == "medium"
    assert transcribe_spec.default_params["segment_length"] == 120
