from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "src" / "acfv"


def test_providers_do_not_import_persistence_or_transcript_services() -> None:
    sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "providers").glob("*identity.py"))
    assert "CreatorAdaptiveRepository" not in sources
    assert "TrustedSpeechMemoryService" not in sources
    assert "AdaptiveTranscriptDecision" not in sources


def test_human_review_routes_adaptive_writes_through_services() -> None:
    source = (ROOT / "human_review" / "gui.py").read_text(encoding="utf-8")
    assert "TrustedSpeechMemoryService().store_unit" in source
    assert "TrustedSpeechMemoryService().confirm_unit" in source
    assert "CreatorIdentityService().record_observation" in source
    assert "INSERT INTO trusted_speech_units" not in source


def test_adaptive_asr_is_shadow_only_and_never_mutates_raw_transcript() -> None:
    source = (ROOT / "creator_adaptive_asr" / "service.py").read_text(encoding="utf-8")
    assert '"shadow": 1' in source
    assert "UPDATE transcript" not in source
    assert "DELETE FROM" not in source


def test_profile_build_has_no_raw_media_write_operations() -> None:
    source = (ROOT / "voice_profile" / "service.py").read_text(encoding="utf-8")
    assert ".write_" not in source
    assert "unlink(" not in source

