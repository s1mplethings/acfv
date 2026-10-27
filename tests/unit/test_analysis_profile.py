from acfv.live import resolve_analysis_profile
from acfv.library import LibraryService, RecordingStatus, StreamLibraryBridge
from datetime import datetime, timezone
from types import SimpleNamespace


def test_auto_profiles_and_user_override_are_bounded() -> None:
    assert resolve_analysis_profile({"title": "Overwatch ranked game"}).name == "gaming"
    assert resolve_analysis_profile({"title": "Just Chatting"}).name == "talking"
    collab = resolve_analysis_profile({"title": "Collab with guest"})
    assert collab.name == "collab" and collab.speaker is True
    assert resolve_analysis_profile({}, override="Gaming").visual == "medium"


def test_creator_profile_persists_and_new_capture_inherits(tmp_path) -> None:
    library = LibraryService(tmp_path / "library.db")
    creator = library.create_creator("Alice")
    source = library.add_source(creator.id, platform="twitch", external_id="alice", channel_name="Alice")
    assert library.set_creator_analysis_profile(creator.id, "Gaming") == []

    reopened = LibraryService(tmp_path / "library.db")
    bridge = StreamLibraryBridge(reopened, {"alice-live": source.id})
    bridge(
        SimpleNamespace(
            timestamp=datetime.now(timezone.utc),
            target="alice-live",
            event="recording_started",
            message=None,
            details={"output": str(tmp_path / "recording.mp4")},
        )
    )
    recording = reopened.list_recordings()[0]
    assert recording.recording_status == RecordingStatus.RECORDING
    assert recording.content_type == "gaming"
    assert recording.profile_source == "user"
