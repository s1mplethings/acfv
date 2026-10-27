from pathlib import Path

import numpy as np

from acfv.clips import ClipService
from acfv.feedback import FeedbackService
from acfv.library import FeedbackDecision, LibraryService
from acfv.moments import MomentService
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex


def _encoder(texts):
    return np.ones((len(list(texts)), 4), dtype=np.float32)


def test_feedback_and_preference_survive_restart_and_affect_ranking(tmp_path: Path) -> None:
    db_path = tmp_path / "library.db"
    library = LibraryService(db_path)
    creator = library.create_creator("Alice")
    moments = []
    for title, text in (("Gameplay", "highlight pure gameplay"), ("Talking", "highlight talking interaction")):
        recording = library.register_recording(creator_id=creator.id, title=title, require_file=False)
        moments.append(MomentService(library.repository).ingest_incremental(
            recording.id, {"segments": [{"start": 5, "end": 8, "text": text}]}
        )[0])
    clip = ClipService(library.repository).create_proposal(moments[0].id, query="highlight")
    clip = ClipService(library.repository).update_review(clip.id, start_ms=4_000, end_ms=9_000)
    feedback = FeedbackService(library.repository)
    saved = feedback.decide(clip.id, FeedbackDecision.ACCEPTED, reason="complete evidence")
    preference = feedback.add_preference("不要 gameplay", creator_id=creator.id)

    reopened = LibraryService(db_path)
    reopened_feedback = FeedbackService(reopened.repository)
    assert reopened_feedback.list_feedback(creator.id)[0].id == saved.id
    assert reopened_feedback.list_feedback(creator.id)[0].reason == "complete evidence"
    assert reopened_feedback.list_feedback(creator.id)[0].subtitle_edit == clip.subtitle_text
    assert reopened_feedback.list_preferences(creator.id)[0].id == preference.id
    assert saved.boundary_delta_start == -1_000
    assert saved.boundary_delta_end == 1_000

    index = PersistentMomentIndex(reopened.repository, tmp_path / "index", encoder=_encoder)
    retrieval = HybridRetrievalService(
        reopened.repository,
        index,
        reranker=lambda _query, texts: [1.0 for _ in texts],
    )
    retrieval.rebuild()
    results = retrieval.search("highlight", creator_id=creator.id)
    assert results[0].recording_title == "Talking"


def test_explicit_preferences_are_isolated_between_creators(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    saruei = library.create_creator("Saruei")
    anny = library.create_creator("anny")
    feedback = FeedbackService(library.repository)
    feedback.add_preference("prefer reaction", creator_id=saruei.id)
    feedback.add_preference("prefer complete argument and chatting", creator_id=anny.id)

    assert [item.text for item in feedback.list_preferences(saruei.id)] == ["prefer reaction"]
    assert [item.text for item in feedback.list_preferences(anny.id)] == [
        "prefer complete argument and chatting"
    ]

    reopened = FeedbackService(LibraryService(tmp_path / "library.db").repository)
    assert [item.text for item in reopened.list_preferences(saruei.id)] == ["prefer reaction"]
    assert [item.text for item in reopened.list_preferences(anny.id)] == [
        "prefer complete argument and chatting"
    ]


def test_explicit_translation_edit_becomes_scoped_memory(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    service = FeedbackService(library.repository)
    saved = service.add_translation_preference(
        "skill issue", "纯纯技术问题", creator_id=creator.id,
        game_scope="Overwatch", recording_scope="vod-1",
    )
    assert saved.source == "USER_EXPLICIT_TRANSLATION_PREFERENCE"
    assert service.translation_preferences(
        creator_id=creator.id, game_scope="Overwatch", recording_scope="vod-1",
    )["skill issue"] == "纯纯技术问题"
