from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from acfv.clips import ClipService
from acfv.conversation import GroundedConversationService
from acfv.feedback import FeedbackService
from acfv.library import FeedbackDecision, LibraryService, RecordingStatus, StreamLibraryBridge
from acfv.moments import MomentFinalizer, MomentService, MomentStatus
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex, SearchScope


def _encoder(texts):
    vocabulary = ["overwatch", "scared", "denied", "drawing"]
    return np.asarray(
        [[float(text.lower().count(term)) for term in vocabulary] for text in texts],
        dtype=np.float32,
    )


def _event(event: str, output: Path):
    return SimpleNamespace(
        timestamp=datetime.now(timezone.utc),
        target="alice-live",
        event=event,
        message=None,
        details={"output": str(output), "url": "https://live.example/alice.m3u8"},
    )


def test_full_local_mvp_product_lifecycle(sample_video_path: Path, tmp_path: Path) -> None:
    db_path = tmp_path / "acfv.db"
    index_root = tmp_path / "moment_index"
    library = LibraryService(db_path)
    creator = library.create_creator("Alice")
    source = library.add_source(
        creator.id,
        platform="twitch",
        external_id="alice",
        channel_name="Alice",
        channel_url="https://twitch.tv/alice",
    )
    bridge = StreamLibraryBridge(library, {"alice-live": source.id})
    bridge(_event("recording_started", sample_video_path))
    recording = library.list_recordings()[0]
    assert recording.recording_status == RecordingStatus.RECORDING

    moment_service = MomentService(library.repository)
    provisional = moment_service.ingest_incremental(
        recording.id,
        {"segments": [{"start": 0.2, "end": 2.0, "text": "I was scared in Overwatch then denied it"}]},
        {"records": [{"timestamp": 1.0, "message": "she got scared"}]},
    )[0]
    live_index = PersistentMomentIndex(library.repository, index_root, encoder=_encoder)
    live_retrieval = HybridRetrievalService(library.repository, live_index, load_default_reranker=False)
    live_retrieval.rebuild()
    live = live_retrieval.search("Overwatch scared", scope=SearchScope.LIVE_SESSION, recording_id=recording.id)
    assert live[0].moment_id == provisional.id

    bridge(_event("recording_finished", sample_video_path))
    final = MomentFinalizer(library.repository).finalize(
        recording.id,
        {"segments": [{"start": 0.2, "end": 2.0, "text": "I was scared in Overwatch then denied it"}]},
        {"records": [{"timestamp": 1.0, "message": "she got scared"}]},
    )[0]
    assert final.status == MomentStatus.FINAL
    HybridRetrievalService(library.repository, live_index, load_default_reranker=False).rebuild()

    reopened = LibraryService(db_path)
    reopened_index = PersistentMomentIndex(reopened.repository, index_root, encoder=_encoder)
    retrieval = HybridRetrievalService(reopened.repository, reopened_index, load_default_reranker=False)
    answer = GroundedConversationService(retrieval).ask("Overwatch scared")
    assert not answer.grounded and answer.confidence == "evidence_only"
    assert answer.evidence_cards[0].moment_id == final.id

    clips = ClipService(reopened.repository, output_root=tmp_path / "clips")
    proposal = clips.create_proposal(final.id, query="Overwatch scared", context_before_ms=0, context_after_ms=800)
    rendered = clips.render(proposal.id)
    edited = clips.update_review(
        rendered.id,
        start_ms=300,
        end_ms=2_300,
        subtitle_text="I was not scared!",
        subtitle_style={"preset": "clean"},
    )
    rerendered = clips.render(edited.id)
    feedback = FeedbackService(reopened.repository)
    accepted = feedback.decide(rerendered.id, FeedbackDecision.ACCEPTED)
    preference = feedback.add_preference("优先聊天互动", creator_id=creator.id)

    final_restart = LibraryService(db_path)
    assert final_restart.list_creators()[0].id == creator.id
    assert final_restart.list_sources(creator.id)[0].id == source.id
    assert final_restart.get_recording(recording.id).recording_status == RecordingStatus.COMPLETE
    assert final_restart.repository.get_moment(final.id).status == MomentStatus.FINAL
    assert final_restart.repository.get_clip(rerendered.id).output_path == rerendered.output_path
    assert final_restart.repository.list_feedback(creator.id)[0].id == accepted.id
    assert final_restart.repository.list_preferences(creator.id)[0].id == preference.id
    assert Path(rerendered.output_path).stat().st_size > 0
