from __future__ import annotations

from pathlib import Path

from acfv.library import LibraryService
from acfv.library.models import Clip
from acfv.moments import MomentService, MomentStatus
from acfv.moments.quality import MomentQualityAction, classify_moments, repair_moments


def _moment(library, recording, start: float, end: float, text: str):
    item = MomentService(library.repository).ingest_incremental(
        recording.id, {"segments": [{"start": start, "end": end, "text": text}]}
    )[0]
    item.status = MomentStatus.FINAL
    return library.repository.save(item)


def test_low_info_reaction_is_kept_and_garbage_is_suppressed(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(creator_id=creator.id, title="Recording", require_file=False)
    reaction = _moment(library, recording, 0, 2, "No!")
    garbage = _moment(library, recording, 10, 12, "okay")

    decisions = {item.moment_id: item for item in classify_moments([reaction, garbage])}

    assert decisions[reaction.id].action == MomentQualityAction.KEEP_REACTION
    assert decisions[garbage.id].action == MomentQualityAction.SUPPRESS


def test_structural_duplicate_removed_but_real_repeated_speech_kept(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(creator_id=creator.id, title="Recording", require_file=False)
    first = _moment(library, recording, 0, 10, "There is something behind me")
    overlap = _moment(library, recording, 0.5, 10.2, "There is something behind me")
    later = _moment(library, recording, 50, 60, "There is something behind me")

    decisions = {item.moment_id: item for item in classify_moments([first, overlap, later])}

    assert decisions[overlap.id].action == MomentQualityAction.STRUCTURAL_DUPLICATE
    assert decisions[later.id].action == MomentQualityAction.KEEP


def test_chatting_argument_and_collab_interruption_are_kept(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(creator_id=creator.id, title="Recording", require_file=False)
    argument = _moment(library, recording, 0, 40, "I disagree because the first assumption changes the conclusion completely")
    interruption = _moment(library, recording, 50, 65, "Wait let them finish and then I will answer the question")

    decisions = classify_moments([argument, interruption])

    assert {item.action for item in decisions} == {MomentQualityAction.KEEP}


def test_repair_dry_run_and_referenced_moment_are_safe(tmp_path: Path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Creator")
    recording = library.register_recording(creator_id=creator.id, title="Recording", require_file=False)
    garbage = _moment(library, recording, 0, 2, "okay")
    library.repository.save(Clip(
        creator_id=creator.id, recording_id=recording.id, moment_id=garbage.id,
        original_start_ms=0, original_end_ms=2000, proposed_start_ms=0,
        proposed_end_ms=2000, final_start_ms=0, final_end_ms=2000,
    ))

    dry = repair_moments(library.repository, creator_id=creator.id, dry_run=True)
    applied = repair_moments(library.repository, creator_id=creator.id, dry_run=False)

    assert dry["removed_ids"] == []
    assert applied["removed_ids"] == []
    assert library.repository.get_moment(garbage.id) is not None
