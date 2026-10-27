import json
from pathlib import Path

from acfv.library import LibraryService
from acfv.moments import MomentFinalizer, MomentService, MomentStatus, ProvisionalMomentBuilder


def test_finalization_replaces_provisional_and_is_idempotent(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Archive", require_file=False)
    provisional = MomentService(library.repository)
    provisional.ingest_incremental(recording.id, {"segments": [{"start": 0, "end": 2, "text": "partial"}]})
    transcript = {"segments": [
        {"start": 0, "end": 3, "text": "I was not scared"},
        {"start": 4, "end": 7, "text": "that monster surprised me"},
    ]}
    chat = {"records": [{"timestamp": 5, "message": "she got scared LMAO"}]}
    finalizer = MomentFinalizer(library.repository)

    first = finalizer.finalize(
        recording.id,
        transcript,
        chat,
        transcript_artifact="work/transcript_merged.json",
        chat_artifact="work/chat.json",
        enrichment=[{"start_ms": 0, "end_ms": 7000, "visual_text": "enemy appears", "ocr_text": "GAME OVER"}],
    )
    second = finalizer.finalize(recording.id, transcript, chat, transcript_artifact="work/transcript_merged.json", chat_artifact="work/chat.json", enrichment=[{"start_ms": 0, "end_ms": 7000, "visual_text": "enemy appears", "ocr_text": "GAME OVER"}])

    assert len(first) == len(second) == 1
    assert first[0].id == second[0].id
    assert second[0].status == MomentStatus.FINAL
    assert (second[0].start_ms, second[0].end_ms) == (0, 7000)
    assert second[0].visual_text == "enemy appears"
    evidence = json.loads(second[0].evidence_json)
    assert {item["type"] for item in evidence} == {"transcript", "chat"}
    stored = provisional.list_moments(recording_id=recording.id)
    assert [item.id for item in stored] == [second[0].id]


def test_finalize_reads_canonical_artifact_paths(tmp_path: Path) -> None:
    root = tmp_path / "run"
    work = root / "work"
    work.mkdir(parents=True)
    transcript_path = work / "transcript_merged.json"
    chat_path = work / "chat.json"
    transcript_path.write_text(json.dumps({"segments": [{"start": 1, "end": 3, "text": "artifact evidence"}]}), encoding="utf-8")
    chat_path.write_text(json.dumps({"records": []}), encoding="utf-8")
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Archive", require_file=False)
    recording.artifact_root = str(root)
    library.repository.save(recording)

    result = MomentFinalizer(library.repository).finalize_artifacts(recording.id)

    assert result[0].status == MomentStatus.FINAL
    assert json.loads(result[0].evidence_json)[0]["artifact"] == str(transcript_path)


def test_finalization_clamps_tail_to_recording_duration(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Bounded", require_file=False)
    recording.duration_ms = 6_500
    library.repository.save(recording)

    result = MomentFinalizer(library.repository).finalize(
        recording.id,
        {"segments": [{"start": 4, "end": 7, "text": "tail evidence"}]},
    )

    assert (result[0].start_ms, result[0].end_ms) == (4_000, 6_500)
    assert json.loads(result[0].evidence_json)[0]["end_ms"] == 6_500


def test_punctuation_only_moment_is_suppressed() -> None:
    assert ProvisionalMomentBuilder().build({"segments": [{"start": 0, "end": 2, "text": "..."}]}) == []


def test_short_meaningful_reaction_is_preserved() -> None:
    drafts = ProvisionalMomentBuilder().build({"segments": [{"start": 0, "end": 2, "text": "No!"}]})
    assert len(drafts) == 1


def test_contextless_low_information_tail_is_merged() -> None:
    drafts = ProvisionalMomentBuilder().build({"segments": [
        {"start": 0, "end": 3, "text": "I will explain the complete argument now."},
        {"start": 3.2, "end": 4, "text": "okay"},
    ]})

    assert len(drafts) == 1
    assert "okay" in drafts[0].transcript_text


def test_real_repeated_speech_at_distinct_times_is_not_deleted() -> None:
    text = "There is something behind me!"
    drafts = ProvisionalMomentBuilder(max_gap_ms=1_000).build({"segments": [
        {"start": 0, "end": 2, "text": text},
        {"start": 10, "end": 12, "text": text},
    ]})

    assert len(drafts) == 2


def test_background_lyrics_are_suppressed_but_raw_text_is_preserved_in_speech_evidence() -> None:
    payload = {"language": "en", "segments": [
        {"start": 0, "end": 3, "text": "I am explaining the story in English."},
        {"start": 4, "end": 7, "text": "The next part has useful context."},
        {"start": 8, "end": 11, "text": "This discussion continues with another point."},
        {"start": 12, "end": 15, "text": "We still have more context to explain."},
        {"start": 16, "end": 18, "text": "The conclusion belongs to this spoken topic."},
        {"start": 20, "end": 23, "text": "もう一回こっち向いて"},
        {"start": 23, "end": 26, "text": "言いたいことがもっとあるから"},
        {"start": 26, "end": 29, "text": "もう一回こっち向いて"},
        {"start": 29, "end": 32, "text": "言いたいことがもっとあるから"},
        {"start": 32, "end": 35, "text": "もう一回こっち向いて"},
        {"start": 35, "end": 38, "text": "言いたいことがもっとあるから"},
    ]}

    drafts = ProvisionalMomentBuilder(max_gap_ms=4_000).build(payload)

    assert len(drafts) == 1
    evidence = json.loads(drafts[0].evidence_json)
    assert evidence[0]["raw_text"] == "I am explaining the story in English."
    assert evidence[0]["classification"] == "SPEECH"


def test_continuous_topic_is_not_cut_at_sixty_seconds() -> None:
    segments = [
        {"start": index * 10, "end": (index + 1) * 10, "text": "the same continuous explanation" + ("." if index == 7 else "")}
        for index in range(8)
    ]
    drafts = ProvisionalMomentBuilder().build({"segments": segments})
    assert len(drafts) == 1
    assert drafts[0].end_ms == 80_000


def test_summary_is_concise_and_not_raw_long_transcript(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Summary", require_file=False)
    long_text = "First sentence explains the event. Second sentence gives context. " + "extra words " * 80
    result = MomentFinalizer(library.repository).finalize(recording.id, {"segments": [{"start": 0, "end": 30, "text": long_text}]})
    assert len(result[0].summary) <= 241
    assert result[0].summary != result[0].transcript_text


def test_versioned_rebuild_can_preserve_old_moments_until_reference_migration(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    recording = library.register_recording(creator_id=creator.id, title="Versioned", require_file=False)
    finalizer = MomentFinalizer(library.repository)
    old = finalizer.finalize(recording.id, {"segments": [{"start": 0, "end": 10, "text": "Old boundary."}]})[0]

    rebuilt = finalizer.finalize(
        recording.id,
        {"segments": [{"start": 0, "end": 20, "text": "New semantic boundary."}]},
        replace_existing=False,
    )[0]

    ids = {item.id for item in library.repository.list_moments(recording_id=recording.id)}
    assert ids == {old.id, rebuilt.id}
