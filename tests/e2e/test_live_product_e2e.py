from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from acfv.clips import ClipService
from acfv.conversation import GroundedConversationService, LIVE_NO_EVIDENCE_ANSWER
from acfv.feedback import FeedbackService
from acfv.library import FeedbackDecision, LibraryService, RecordingStatus, StreamLibraryBridge
from acfv.live import LiveProcessingService
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex, SearchScope


class _ImmediateFuture:
    def __init__(self, action, args):
        self.error = None
        try:
            action(*args)
        except Exception as exc:
            self.error = exc

    def result(self):
        if self.error:
            raise self.error


class _ImmediateExecutor:
    def submit(self, action, *args):
        return _ImmediateFuture(action, args)


def _encoder(texts):
    return np.stack(
        [np.asarray([text.casefold().count("overwatch") + 0.01, text.casefold().count("hello") + 0.01], dtype=np.float32) for text in texts]
    )


def _event(name: str, **details):
    return SimpleNamespace(
        timestamp=datetime.now(timezone.utc),
        target="alice-live",
        event=name,
        message=None,
        details=details,
    )


def test_twitch_replay_to_live_search_finalize_clip_feedback_restart(sample_video_path: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    library = LibraryService(db_path)
    creator = library.create_creator("Alice")
    source = library.add_source(
        creator.id,
        platform="twitch",
        external_id="alice",
        channel_name="Alice",
        channel_url="https://twitch.tv/alice",
    )
    holder = {}
    calls = []

    def factory(recording_id, repository, root=None):
        def transcriber(_path, _output):
            calls.append(len(calls) + 1)
            text = "Overwatch tournament announced" if len(calls) == 1 else "hello from the second segment"
            return {"segments": [{"start": 0.2, "end": 0.8, "text": text}]}

        index = PersistentMomentIndex(repository, tmp_path / "index", encoder=_encoder)
        holder["live"] = LiveProcessingService(
            recording_id,
            repository,
            root=Path(root) if root else tmp_path / "recording",
            transcriber=transcriber,
            moment_index=index,
        )
        holder["index"] = index
        return holder["live"]

    bridge = StreamLibraryBridge(
        library,
        {"alice-live": source.id},
        live_factory=factory,
        executor=_ImmediateExecutor(),
    )
    bridge(_event("recording_started", output=str(sample_video_path), recording_root=str(tmp_path / "recording")))
    recording = library.list_recordings()[0]
    assert recording.recording_status == RecordingStatus.RECORDING

    bridge(_event("segment_closed", segment_id="segment_000001", path=str(sample_video_path), start_ms=0, end_ms=1000))
    bridge(_event("chat_message", timestamp_ms=500, username="viewer", message="Overwatch confirmed"))
    bridge(_event("segment_closed", segment_id="segment_000002", path=str(sample_video_path), start_ms=1000, end_ms=2000))

    retrieval = HybridRetrievalService(library.repository, holder["index"], reranker=lambda _q, texts: [float("overwatch" in text.casefold()) for text in texts])
    conversation = GroundedConversationService(retrieval)
    live_answer = conversation.ask("Overwatch", scope=SearchScope.LIVE_SESSION, recording_id=recording.id)
    assert not live_answer.grounded and live_answer.confidence == "evidence_only"
    assert live_answer.evidence_cards[0].moment_status == "PROVISIONAL"
    assert conversation.ask("Minecraft", scope=SearchScope.LIVE_SESSION, recording_id=recording.id).answer == LIVE_NO_EVIDENCE_ANSWER

    bridge(_event("recording_finished", output=str(sample_video_path)))
    assert all(moment.status.value == "FINAL" for moment in library.repository.list_moments(recording_id=recording.id))

    reopened = LibraryService(db_path)
    reopened_index = PersistentMomentIndex(reopened.repository, tmp_path / "index", encoder=_encoder)
    history = HybridRetrievalService(reopened.repository, reopened_index, reranker=lambda _q, texts: [float("overwatch" in text.casefold()) for text in texts])
    result = history.search("Overwatch", scope=SearchScope.ENTIRE_LIBRARY)[0]
    clips = ClipService(reopened.repository, output_root=tmp_path / "clips")
    clip = clips.create_proposal(result.moment_id, query="Overwatch")
    clip = clips.update_review(clip.id, start_ms=0, end_ms=2000, subtitle_text="Overwatch tournament", subtitle_style={"preset": "default"})
    rendered = clips.render(clip.id)
    feedback = FeedbackService(reopened.repository)
    feedback.decide(rendered.id, FeedbackDecision.ACCEPTED)
    feedback.add_preference("优先聊天互动", creator_id=creator.id)

    final_restart = LibraryService(db_path)
    assert final_restart.repository.get_clip(rendered.id).output_path
    assert len(final_restart.repository.list_feedback(creator.id)) == 1
    assert final_restart.repository.list_preferences(creator.id)[0].source == "USER_EXPLICIT"
