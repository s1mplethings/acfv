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
ART_CLIPS = "Clips:files.v1"
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
    "ART_CLIPS",
    "ART_PROGRESS",
    "ART_RUN_META",
]
