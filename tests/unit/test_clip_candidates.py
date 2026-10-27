from __future__ import annotations

import json
from pathlib import Path

import pytest

from acfv.clips import CandidateType, ClipCandidate, ClipCandidateSelector, ClipService, WatchabilityScore, assign_clip_event_ids, classify_target_material
from acfv.library import LibraryService
from acfv.moments import Moment, MomentStatus
from acfv.retrieval.query import SearchResult


def _result(moment: Moment, rank_score: float) -> SearchResult:
    return SearchResult(
        moment_id=moment.id,
        creator_id=moment.creator_id,
        recording_id=moment.recording_id,
        start_ms=moment.start_ms,
        end_ms=moment.end_ms,
        score=rank_score,
        summary=moment.summary,
        transcript_excerpt=moment.transcript_text,
        recording_title="Horror stream",
        recorded_at=None,
        moment_status=moment.status.value,
        evidence=json.loads(moment.evidence_json),
    )


def _library(tmp_path: Path):
    video = tmp_path / "recording.mp4"
    video.touch()
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Streamer")
    recording = library.register_recording(
        creator_id=creator.id,
        title="VTuber horror game reaction",
        local_path=video,
        content_type="vtuber_game_reaction",
    )
    recording.duration_ms = 180_000
    library.repository.save(recording)
    return library, creator, recording


def _moment(library, creator, recording, key: str, start: int, end: int, text: str) -> Moment:
    return library.repository.save(Moment(
        stable_key=key,
        creator_id=creator.id,
        recording_id=recording.id,
        start_ms=start,
        end_ms=end,
        status=MomentStatus.FINAL,
        transcript_text=text,
        summary=text,
        evidence_json=json.dumps([
            {"type": "transcript", "start_ms": start, "end_ms": end, "text": text}
        ]),
    ))


def test_target_material_classification_is_content_generic():
    assert classify_target_material(
        title="A creator plays a horror game", content_type="vtuber_game_reaction", expected_event_types=["scare"]
    ) == "TARGET_PRODUCT_CONTENT"
    assert classify_target_material(title="Navigation tutorial", content_type="technical training") == "ENGINEERING_ONLY"
    assert classify_target_material(title="Game settings tutorial", content_type="gaming") == "ENGINEERING_ONLY"


def test_top_ten_becomes_diverse_watchability_ranked_candidates(tmp_path: Path):
    library, creator, recording = _library(tmp_path)
    informational = _moment(
        library, creator, recording, "info", 30_000, 48_000,
        "The configuration contains several technical parameters and menu values.",
    )
    reaction = _moment(
        library, creator, recording, "reaction", 70_000, 94_000,
        "We have to cross the dark room. Wait, there is something behind me! Oh no! I screamed and lost the challenge, right?",
    )
    aftermath = _moment(
        library, creator, recording, "aftermath", 100_000, 124_000,
        "Chat, you made a noise while I was whispering. The gasp was enough, so I will lower the sensitivity.",
    )
    selector = ClipCandidateSelector(library.repository)
    candidates = selector.generate(
        "What happened when something was behind the streamer and did she scream?",
        [_result(informational, 9.0), _result(reaction, 8.0), _result(aftermath, 7.0)],
    )

    assert len(candidates) >= 3
    assert {item.candidate_type for item in candidates} == set(CandidateType)
    assert len({(item.moment_id, item.start_ms, item.end_ms) for item in candidates}) == len(candidates)
    selected = next(item for item in candidates if item.selected)
    assert selected.watchability.total == max(item.watchability.total for item in candidates)
    assert selected.moment_id != informational.id  # Retrieval Top-1 is not the automatic edit.
    assert all(item.eligible for item in candidates)


def test_source_edge_is_rejected_without_explicit_natural_end_override(tmp_path: Path):
    library, creator, recording = _library(tmp_path)
    edge = _moment(
        library, creator, recording, "edge", 166_000, 179_000,
        "We have to escape now. Oh wow, we made it and won the game!",
    )
    selector = ClipCandidateSelector(library.repository)
    with pytest.raises(ValueError, match="SOURCE_EDGE"):
        selector.generate("How did they escape and win?", [_result(edge, 1.0)])

    candidates = selector.generate(
        "How did they escape and win?", [_result(edge, 1.0)],
        source_edge_override=True, source_edge_override_reason="The source naturally ends after the victory screen.",
    )
    assert candidates
    assert all(item.source_edge_override for item in candidates)
    assert all(item.source_edge_override_reason for item in candidates)


def test_preview_creation_reuses_injected_canonical_renderer(tmp_path: Path):
    library, creator, recording = _library(tmp_path)
    moment = _moment(
        library, creator, recording, "event", 60_000, 90_000,
        "We need to enter. Wait, what was that! Oh no, I screamed and lost the game!",
    )
    calls = []

    def renderer(**kwargs):
        calls.append(kwargs)
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"preview")
        return {"output_path": str(output)}

    selector = ClipCandidateSelector(library.repository, renderer=renderer)
    candidates = selector.generate("What made the streamer scream and lose?", [_result(moment, 1.0)])
    selector.render_previews(candidates, recording.local_path, tmp_path / "previews")

    assert len(calls) == 3
    assert all(Path(item.preview_path).is_file() for item in candidates)
    assert all(Path(item.preview_path).name.startswith("PREVIEW_PROXY_") for item in candidates)
    assert all(item.preview_metadata["is_preview"] is True for item in candidates)
    assert all(item.preview_metadata["excluded_from_final_quality_statistics"] is True for item in candidates)
    score_path = selector.write_scores(candidates, tmp_path / "candidate_scores.json")
    payload = json.loads(score_path.read_text(encoding="utf-8"))
    assert len(payload["candidates"]) == 3
    assert "source_edge_penalty" in payload["candidates"][0]["watchability"]

    proposals = selector.save_proposals(candidates)
    edited = ClipService(library.repository, renderer=renderer).update_review(
        proposals[0].id, start_ms=0, end_ms=20_000
    )
    with pytest.raises(ValueError, match="SOURCE_CONTEXT_INCOMPLETE"):
        ClipService(library.repository, renderer=renderer).render(edited.id)


@pytest.mark.parametrize(
    ("text", "query"),
    [
        ("ここは暗いから先に準備する。えっ、何？待って！逃げ切った。", "何に驚いてどう逃げた？"),
        ("因为前面很危险，我们必须准备。等等，什么声音？成功逃脱了！", "发生了什么并如何脱险？"),
    ],
)
def test_watchability_accepts_cjk_event_structure(tmp_path: Path, text: str, query: str) -> None:
    library, creator, recording = _library(tmp_path)
    moment = _moment(library, creator, recording, "cjk-event", 60_000, 90_000, text)

    candidates = ClipCandidateSelector(library.repository).generate(query, [_result(moment, 1.0)])

    assert len(candidates) == 3
    assert all(candidate.eligible for candidate in candidates)
    assert all(candidate.watchability.hook_strength >= 0.15 for candidate in candidates)
    assert all(candidate.watchability.payoff_completeness >= 0.15 for candidate in candidates)


def test_watchability_preserves_complete_talking_argument(tmp_path: Path) -> None:
    library, creator, recording = _library(tmp_path)
    text = (
        "Why did I change my schedule? I needed more time to prepare each stream, "
        "because rushing made every discussion less useful. The important point is that "
        "a slower schedule gives us a complete conversation and a clear conclusion."
    )
    moment = _moment(library, creator, recording, "talking", 60_000, 105_000, text)

    candidates = ClipCandidateSelector(library.repository).generate(
        "Why was the schedule changed?", [_result(moment, 1.0)]
    )

    assert len(candidates) == 3
    assert all(candidate.eligible for candidate in candidates)


def test_clip_event_identity_deduplicates_overlap_and_media_hash(tmp_path: Path) -> None:
    score = WatchabilityScore(*([1.0] * 13), *([0.0] * 4))
    candidates = [
        ClipCandidate("a", CandidateType.MOST_RELEVANT, "m1", "r", "q", 60_000, 90_000, 1, 1.0, score),
        ClipCandidate("b", CandidateType.MOST_COMPLETE, "m2", "r", "q", 62_000, 91_000, 2, 0.9, score),
        ClipCandidate("c", CandidateType.MOST_WATCHABLE, "m3", "r", "q", 120_000, 145_000, 3, 0.8, score),
    ]

    assigned = assign_clip_event_ids(candidates)

    assert len({item.event_id for item in assigned}) <= len(assigned)
    assert any(item.same_event_variant for item in assigned)


def test_clip_event_identity_uses_media_hash_for_duplicate_outputs(tmp_path: Path) -> None:
    score = WatchabilityScore(*([1.0] * 13), *([0.0] * 4))
    left = ClipCandidate("left", CandidateType.MOST_RELEVANT, "m1", "r1", "q", 30_000, 50_000, 1, 1.0, score)
    right = ClipCandidate("right", CandidateType.MOST_RELEVANT, "m2", "r2", "q", 120_000, 140_000, 1, 1.0, score)

    assign_clip_event_ids([left, right], media_hashes={"left": "same", "right": "same"})

    assert left.event_id == right.event_id
    assert right.same_event_variant is True
