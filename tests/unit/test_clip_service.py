from pathlib import Path
import json

import pytest

from acfv.clips import ClipService, DurationProfile, DurationVariant, VariantStatus
from acfv.library import ClipRenderStatus, LibraryService
from acfv.moments import Moment, MomentService, MomentStatus


def test_moment_creates_contextual_proposal_and_renders_via_adapter(tmp_path: Path) -> None:
    video = tmp_path / "recording.mp4"
    video.touch()
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Stream", local_path=video)
    recording.duration_ms = 60_000
    library.repository.save(recording)
    moment = MomentService(library.repository).ingest_incremental(
        recording.id, {"segments": [{"start": 20, "end": 25, "text": "clip this moment"}]}
    )[0]
    calls = []

    def renderer(**kwargs):
        calls.append(kwargs)
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"mp4")
        return {"output_path": str(output)}

    service = ClipService(library.repository, renderer=renderer, output_root=tmp_path / "clips")
    proposal = service.create_proposal(moment.id, query="find this")

    assert (proposal.original_start_ms, proposal.original_end_ms) == (20_000, 25_000)
    assert (proposal.proposed_start_ms, proposal.proposed_end_ms) == (20_000, 25_000)
    rendered = service.render(proposal.id)
    assert rendered.render_status == ClipRenderStatus.READY
    assert Path(rendered.output_path).read_bytes() == b"mp4"
    assert calls[0]["start_ms"] == 20_000
    edited = service.update_review(
        proposal.id,
        start_ms=13_000,
        end_ms=36_000,
        subtitle_text="edited subtitle",
        subtitle_style={"preset": "clean", "fontsize": 42},
    )
    assert edited.render_status == ClipRenderStatus.PROPOSED
    rerendered = service.render(edited.id)
    assert rerendered.render_status == ClipRenderStatus.READY
    assert calls[-1]["start_ms"] == 13_000
    assert calls[-1]["subtitle_text"] == "edited subtitle"


def test_low_value_moment_is_not_auto_clipped(tmp_path: Path) -> None:
    video = tmp_path / "recording.mp4"
    video.touch()
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Stream", local_path=video)
    moment = library.repository.save(Moment(
        stable_key="low-value", creator_id=creator.id, recording_id=recording.id,
        start_ms=1_000, end_ms=2_000, status=MomentStatus.FINAL, transcript_text="oh", summary="oh",
        evidence_json=json.dumps([{"type": "transcript", "start_ms": 1_000, "end_ms": 2_000, "text": "oh"}]),
    ))
    with pytest.raises(ValueError, match="insufficient semantic"):
        ClipService(library.repository).create_proposal(moment.id)


def test_query_mismatch_can_block_confident_clip(tmp_path: Path) -> None:
    video = tmp_path / "recording.mp4"
    video.touch()
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Stream", local_path=video)
    moment = MomentService(library.repository).ingest_incremental(recording.id, {"segments": [{"start": 1, "end": 5, "text": "meaningful drawing discussion"}]})[0]
    with pytest.raises(ValueError, match="Insufficient retrieval evidence"):
        ClipService(library.repository).create_proposal(moment.id, query="unrelated", relevance_score=-2.0, minimum_relevance_score=0.0)


def test_legacy_fixed_window_cannot_become_final_when_standard_unavailable(tmp_path: Path) -> None:
    video = tmp_path / "recording.mp4"
    video.touch()
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Stream", local_path=video)
    recording.duration_ms = 60_000
    library.repository.save(recording)
    moment = MomentService(library.repository).ingest_incremental(
        recording.id, {"segments": [{"start": 20, "end": 25, "text": "clip this meaningful moment"}]}
    )[0]

    class UnavailableVariants:
        def select_boundary(self, plan, request):
            return DurationVariant(
                DurationProfile.STANDARD, VariantStatus.NOT_AVAILABLE, 0, 0,
                plan.event_id, plan.payoff_anchor_ms, "no_semantic_standard",
            )

    service = ClipService(library.repository, variant_service=UnavailableVariants())
    with pytest.raises(ValueError, match="STANDARD final variant unavailable"):
        service.create_proposal(moment.id)

    assert library.repository.list_clips() == []


def test_semantic_boundary_completes_sentence(tmp_path: Path) -> None:
    video = tmp_path / "recording.mp4"
    video.touch()
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Stream", local_path=video)
    rows = [
        (0, 4_000, "A complete setup."),
        (4_000, 8_000, "this thought starts"),
        (8_000, 12_000, "and finishes here."),
    ]
    created = []
    for number, (start, end, text) in enumerate(rows):
        created.append(library.repository.save(Moment(
            stable_key=f"m-{number}", creator_id=creator.id, recording_id=recording.id,
            start_ms=start, end_ms=end, status=MomentStatus.FINAL, transcript_text=text, summary=text,
            evidence_json=json.dumps([{"type": "transcript", "start_ms": start, "end_ms": end, "text": text}]),
        )))
    proposal = ClipService(library.repository).create_proposal(created[1].id)
    # STANDARD includes the preceding setup and the following sentence ending
    # instead of falling back to a narrower legacy context window.
    assert proposal.proposed_start_ms == 4_000
    assert proposal.proposed_end_ms == 12_000
    reasons = json.loads(proposal.reason)
    assert "event_shorter_than_profile_target_preserved" in reasons["end_reason"]
    assert "SOURCE_EDGE" in reasons["end_reason"]


def test_duration_and_bilingual_review_metadata_persists_and_invalidates_timeline(tmp_path: Path) -> None:
    video = tmp_path / "recording.mp4"
    video.touch()
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Stream", local_path=video)
    recording.duration_ms = 120_000
    library.repository.save(recording)
    moment = MomentService(library.repository).ingest_incremental(
        recording.id, {"segments": [{"start": 20, "end": 40, "text": "complete event sentence."}]}
    )[0]
    service = ClipService(library.repository)
    proposal = service.create_proposal(moment.id)
    edited = service.update_review(
        proposal.id, start_ms=19_000, end_ms=50_000, duration_profile="CUSTOM",
        target_duration_seconds=31, min_duration_seconds=25, max_duration_seconds=40,
        display_mode="ZH_EN", subtitle_completeness="COMPLETE",
        subtitle_position="AUTO_SAFE_AREA", selected_final_variant="CUSTOM",
        extension_reason="extended_for_sentence_or_payoff",
    )
    review = json.loads(edited.reason)["duration_review"]
    assert review["selected_duration_profile"] == "CUSTOM"
    assert review["original_boundaries"] == [20_000, 40_000]
    assert review["generated_boundaries"] == [19_000, 50_000]
    assert review["subtitle_timeline_status"] == "INVALIDATED_BY_BOUNDARY_CHANGE"
    assert review["subtitle_timeline_revision"] == 1


def test_selected_rendered_variant_persists_output_and_ready_status(tmp_path: Path) -> None:
    video = tmp_path / "recording.mp4"; video.touch()
    output = tmp_path / "standard.mp4"; output.write_bytes(b"mp4")
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Stream", local_path=video)
    recording.duration_ms = 120_000; library.repository.save(recording)
    moment = MomentService(library.repository).ingest_incremental(
        recording.id, {"segments": [{"start": 20, "end": 40, "text": "complete event sentence."}]}
    )[0]
    service = ClipService(library.repository)
    proposal = service.create_proposal(moment.id)
    selected = service.select_rendered_variant(
        proposal.id, profile="STANDARD", output_path=str(output), start_ms=20_000, end_ms=40_000,
        display_mode="ZH_EN", subtitle_completeness="COMPLETE", subtitle_position="AUTO_SAFE_AREA",
    )
    assert selected.render_status == ClipRenderStatus.READY
    assert selected.output_path == str(output.resolve())
    restored = LibraryService(tmp_path / "library.db").repository.get_clip(proposal.id)
    assert restored.output_path == str(output.resolve())
    assert json.loads(restored.reason)["duration_review"]["selected_final_variant"] == "STANDARD"
