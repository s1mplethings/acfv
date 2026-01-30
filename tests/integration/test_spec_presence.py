from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_clip_pipeline_inputs_outputs():
    text_in = _read("specs/modules/clip_pipeline/contract_input.md")
    text_out = _read("specs/modules/clip_pipeline/contract_output.md")
    for key in ["url", "out_dir", "cfg", "model_size", "selection.strategy"]:
        assert key in text_in, f"{key} must be documented for clip_pipeline input"
    for key in ["schema_version", "clips", "subtitles", "segments_json", "确定性", "排序"]:
        assert key in text_out, f"{key} must be in clip_pipeline output contract"


def test_clip_pipeline_failure_paths_documented():
    spec = _read("specs/modules/clip_pipeline/spec.md")
    assert "下载失败" in spec, "download failure path should be documented"
    assert "非零" in spec or "返回码" in spec, "failure should return non-zero"


def test_stream_monitor_inputs_outputs():
    text_in = _read("specs/modules/stream_monitor/contract_input.md")
    text_out = _read("specs/modules/stream_monitor/contract_output.md")
    for key in ["targets", "interval_sec", "output_dir", "chat.enabled"]:
        assert key in text_in, f"{key} must be documented for stream_monitor input"
    for key in ["schema_version", "recordings", "chat", "log_path", "命名"]:
        assert key in text_out, f"{key} must be in stream_monitor output contract"


def test_stream_monitor_chat_requirement():
    spec = _read("specs/modules/stream_monitor/spec.md")
    assert "chat" in spec.lower(), "chat handling must be described"
    assert "时间戳" in spec, "naming/ordering with timestamp should be present"


def test_render_clips_inputs_outputs():
    text_in = _read("specs/modules/render_clips/contract_input.md")
    text_out = _read("specs/modules/render_clips/contract_output.md")
    for key in ["source_path", "segments", "codec", "subtitle.enabled"]:
        assert key in text_in, f"{key} must be documented for render_clips input"
    for key in ["schema_version", "clips", "subtitles", "thumbnails", "确定性"]:
        assert key in text_out, f"{key} must be in render_clips output contract"


def test_render_clips_failure_paths_documented():
    spec = _read("specs/modules/render_clips/spec.md")
    assert "ffmpeg" in spec.lower(), "ffmpeg dependency should be documented"
    assert "返回非零" in spec or "错误" in spec, "failure path should be stated"


def test_twitch_downloader_inputs_outputs():
    text_in = _read("specs/modules/twitch_downloader/contract_input.md")
    text_out = _read("specs/modules/twitch_downloader/contract_output.md")
    for key in ["url", "out_dir", "retries", "client_id", "token"]:
        assert key in text_in, f"{key} must be documented for twitch_downloader input"
    for key in ["schema_version", "video_path", "chat_path", "命名"]:
        assert key in text_out, f"{key} must be in twitch_downloader output contract"


def test_twitch_downloader_failure_paths_documented():
    spec = _read("specs/modules/twitch_downloader/spec.md")
    assert "重试" in spec, "retry strategy must be documented"
    assert "返回非零" in spec or "stderr" in spec.lower(), "failure reporting should be present"


def test_extract_audio_inputs_outputs():
    text_in = _read("specs/modules/extract_audio/contract_input.md")
    text_out = _read("specs/modules/extract_audio/contract_output.md")
    for key in ["source_path", "sample_rate", "channels"]:
        assert key in text_in, f"{key} must be documented for extract_audio input"
    for key in ["schema_version", "audio_path", "sample_rate", "命名"]:
        assert key in text_out, f"{key} must be in extract_audio output contract"


def test_extract_audio_failure_paths_documented():
    spec = _read("specs/modules/extract_audio/spec.md")
    assert "ffmpeg" in spec.lower(), "ffmpeg dependency should be documented"
    assert "返回非零" in spec or "错误" in spec, "failure path should be stated"


def test_extract_chat_inputs_outputs():
    text_in = _read("specs/modules/extract_chat/contract_input.md")
    text_out = _read("specs/modules/extract_chat/contract_output.md")
    for key in ["url", "recording_dir", "out_dir", "retries"]:
        assert key in text_in, f"{key} must be documented for extract_chat input"
    for key in ["schema_version", "chat_path", "messages", "时间戳"]:
        assert key in text_out, f"{key} must be in extract_chat output contract"


def test_extract_chat_failure_paths_documented():
    spec = _read("specs/modules/extract_chat/spec.md")
    assert "重试" in spec, "retry strategy must be documented"
    assert "返回码" in spec or "stderr" in spec, "failure reporting should mention return code"


def test_selection_inputs_outputs():
    text_in = _read("specs/modules/selection/contract_input.md")
    text_out = _read("specs/modules/selection/contract_output.md")
    for key in ["segments", "strategy", "topk", "min_score"]:
        assert key in text_in, f"{key} must be documented for selection input"
    for key in ["schema_version", "candidates", "排序", "score"]:
        assert key in text_out, f"{key} must be in selection output contract"


def test_selection_failure_paths_documented():
    spec = _read("specs/modules/selection/spec.md")
    assert "过滤" in spec or "阈值" in spec, "filtering rules should be stated"
    assert "报错" in spec or "非法" in spec, "invalid config should be mentioned"


def test_merge_segments_inputs_outputs():
    text_in = _read("specs/modules/merge_segments/contract_input.md")
    text_out = _read("specs/modules/merge_segments/contract_output.md")
    for key in ["segments", "merge_gap_sec", "max_merged_duration"]:
        assert key in text_in, f"{key} must be documented for merge_segments input"
    for key in ["schema_version", "merged_segments", "排序"]:
        assert key in text_out, f"{key} must be in merge_segments output contract"


def test_merge_segments_failure_paths_documented():
    spec = _read("specs/modules/merge_segments/spec.md")
    assert "超长" in spec or "max_merged_duration" in spec, "long merge handling should be documented"
    assert "报错" in spec or "错误" in spec, "invalid inputs should be mentioned"


def test_subtitle_generator_inputs_outputs():
    text_in = _read("specs/modules/subtitle_generator/contract_input.md")
    text_out = _read("specs/modules/subtitle_generator/contract_output.md")
    for key in ["segments", "format", "time_offset_sec"]:
        assert key in text_in, f"{key} must be documented for subtitle_generator input"
    for key in ["schema_version", "subtitle_path", "format", "命名"]:
        assert key in text_out, f"{key} must be in subtitle_generator output contract"


def test_subtitle_generator_failure_paths_documented():
    spec = _read("specs/modules/subtitle_generator/spec.md")
    assert "报错" in spec or "错误" in spec, "invalid inputs should be mentioned"
    assert "时间" in spec, "time offset/ordering should be documented"
