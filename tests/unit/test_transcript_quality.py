from __future__ import annotations

from acfv.library.transcript_quality import (
    TranscriptSpanClassification,
    analyze_transcript,
)


def _payload(language: str, texts: list[str]):
    return {
        "language": language,
        "segments": [
            {"start": index * 3, "end": index * 3 + 2, "text": text, "confidence": 0.8}
            for index, text in enumerate(texts)
        ],
    }


def test_transcript_truth_wins_over_conflicting_metadata() -> None:
    profile, _ = analyze_transcript(
        _payload("ja", ["Today we are telling a complete story"] * 8),
        creator_default="ja",
        metadata_language="ja",
        analyzed_at="fixed",
    )

    assert profile.primary_language == "en"
    assert profile.source == "transcript_segments"


def test_english_primary_with_japanese_lyrics_is_mixed_and_classified() -> None:
    payload = _payload(
        "ja",
        ["I want to explain what happened today"] * 10
        + ["もう一回こっち向いて", "言いたいことがもっとあるから", "もう一回こっち向いて"] * 3
        + ["Now let me finish the story"] * 6,
    )

    profile, spans = analyze_transcript(payload, analyzed_at="fixed")

    assert profile.primary_language == "en"
    assert "ja" in profile.secondary_languages
    assert profile.mixed_language is True
    assert any(item.classification == TranscriptSpanClassification.LIKELY_BACKGROUND_LYRICS for item in spans)


def test_real_japanese_speech_remains_japanese() -> None:
    profile, spans = analyze_transcript(
        _payload("en", ["今日はゲームの話をします", "この場面について説明します", "次の質問に答えます"] * 3),
        analyzed_at="fixed",
    )

    assert profile.primary_language == "ja"
    assert all(item.classification == TranscriptSpanClassification.SPEECH for item in spans)


def test_chinese_english_mixture_records_secondary_language() -> None:
    profile, _ = analyze_transcript(
        _payload("zh", ["今天解释这个问题", "This answer has useful context"] * 5),
        analyzed_at="fixed",
    )

    assert profile.primary_language in {"zh", "en"}
    assert set(profile.secondary_languages) == ({"en"} if profile.primary_language == "zh" else {"zh"})
    assert profile.mixed_language is True


def test_empty_and_low_confidence_inputs_use_safe_fallbacks() -> None:
    empty, spans = analyze_transcript(_payload("", []), creator_default="en", analyzed_at="fixed")
    low, low_spans = analyze_transcript(
        {"segments": [{"start": 0, "end": 1, "text": "x", "confidence": 0.01}]},
        metadata_language="ja",
        analyzed_at="fixed",
    )

    assert empty.primary_language == "en" and empty.source == "creator_default" and spans == []
    assert low.primary_language == "ja" and low.source == "recording_metadata"
    assert low_spans[0].classification == TranscriptSpanClassification.UNCERTAIN


def test_raw_text_is_preserved_and_display_correction_is_derived() -> None:
    profile, spans = analyze_transcript(_payload("en", ["  hello   there  "]), analyzed_at="fixed")

    assert profile.primary_language == "en"
    assert spans[0].raw_text == "  hello   there  "
    assert spans[0].display_text == "hello there"
    assert spans[0].correction is not None
    assert spans[0].correction.raw_text == spans[0].raw_text


def test_profile_generation_is_idempotent_with_fixed_timestamp() -> None:
    payload = _payload("en", ["repeatable transcript profile"] * 3)

    first = analyze_transcript(payload, analyzed_at="fixed")
    second = analyze_transcript(payload, analyzed_at="fixed")

    assert first == second
