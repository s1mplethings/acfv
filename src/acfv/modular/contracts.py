from __future__ import annotations

ART_VIDEO = "VideoSource:local.v1"
ART_CHAT_SOURCE = "ChatSource:html.v1"
ART_CHAT_LOG = "ChatLog:json.v1"
ART_AUDIO = "Audio:extracted.v1"
ART_TRANSCRIPT = "Transcript:whisper_json.v1"
ART_VIDEO_EMOTION = "VideoEmotion:segments.v1"
ART_SPEAKER_RESULT = "SpeakerSeparation:result.v1"
ART_AUDIO_HOST = "Audio:host.v1"
ART_AUDIO_VIDEO_SPEECH = "Audio:video_speech.v1"
ART_AUDIO_GAME = "Audio:game.v1"
ART_AUDIO_LABELS = "AudioLabels:json.v1"
ART_SEGMENTS = "Segments:analysis.v1"
ART_SEGMENTS_SEMANTIC = "Segments:semantic_merge.v1"
ART_SEGMENTS_LLM = "Segments:llm_highlight.v1"
ART_SCREEN_FRAMES = "ScreenFrames:keyframes.v1"
ART_SCREEN_WINDOWS = "ScreenWindows:timeline.v1"
ART_SCREEN_CONTEXT = "ScreenContext:timeline.v1"
ART_CLIPS = "Clips:files.v1"
ART_SUBTITLES_STREAMER = "Subtitles:streamer.v1"
ART_SUBTITLES_TRANSLATED = "Subtitles:translated.v1"
ART_PROGRESS = "Progress:stage.v1"
ART_RUN_META = "Run:meta.v1"

__all__ = [
    "ART_VIDEO",
    "ART_CHAT_SOURCE",
    "ART_CHAT_LOG",
    "ART_AUDIO",
    "ART_TRANSCRIPT",
    "ART_VIDEO_EMOTION",
    "ART_SPEAKER_RESULT",
    "ART_AUDIO_HOST",
    "ART_AUDIO_VIDEO_SPEECH",
    "ART_AUDIO_GAME",
    "ART_AUDIO_LABELS",
    "ART_SEGMENTS",
    "ART_SEGMENTS_SEMANTIC",
    "ART_SEGMENTS_LLM",
    "ART_SCREEN_FRAMES",
    "ART_SCREEN_WINDOWS",
    "ART_SCREEN_CONTEXT",
    "ART_CLIPS",
    "ART_SUBTITLES_STREAMER",
    "ART_SUBTITLES_TRANSLATED",
    "ART_PROGRESS",
    "ART_RUN_META",
]
