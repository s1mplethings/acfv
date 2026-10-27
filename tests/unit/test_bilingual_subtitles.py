from pathlib import Path

import pytest

from acfv.clips import (
    BilingualDisplayMode,
    BilingualSubtitleService,
    FallbackTranslationProvider,
    QwenTranslationProvider,
    TranslationMode,
    resolve_scoped_glossary,
    SubtitlePosition,
    SubtitleWord,
    words_from_payload,
)


def test_contextual_qwen_translates_cue_group_with_same_ids() -> None:
    class Client:
        def complete_json(self, **kwargs):
            assert "surrounding context" in kwargs["system_prompt"]
            return {"translations": [
                {"cue_id": "0001", "zh_text": "才没有！", "tone": "defensive", "contains_slang": True},
                {"cue_id": "0002", "zh_text": "我只是手滑了。", "tone": "deadpan"},
            ]}

    provider = QwenTranslationProvider(Client())
    rows = provider.translate_group(
        [{"cue_id": "0001", "text": "I did not!"}, {"cue_id": "0002", "text": "It was a misclick."}],
        source_language="en", target_language="zh", glossary={},
        mode=TranslationMode.LOCALIZED_CREATOR,
        context={"event_summary": "player denies a mistake"},
    )
    assert [row["cue_id"] for row in rows] == ["0001", "0002"]
    assert rows[0]["contains_slang"] is True


def test_contextual_qwen_accepts_wrapped_single_entry_and_repairs_missing_ids() -> None:
    class Client:
        def __init__(self):
            self.calls = 0

        def complete_json(self, **kwargs):
            self.calls += 1
            requested = "0001" if self.calls == 1 else "0002"
            payload = {"translated_entry": {"cue_id": requested, "translation": f"译文{requested}"}}
            return kwargs["validator"](payload)

    provider = QwenTranslationProvider(Client())
    rows = provider.translate_group(
        [{"cue_id": "0001", "text": "first"}, {"cue_id": "0002", "text": "second"}],
        source_language="en", target_language="zh", glossary={}, context={},
    )

    assert [row["cue_id"] for row in rows] == ["0001", "0002"]


def test_scoped_glossary_uses_recording_game_creator_global_precedence() -> None:
    glossary = resolve_scoped_glossary(
        global_terms={"ult": "大招", "Mercy": "天使"},
        creator_terms={"Mercy": "慈悲"}, game_terms={"ult": "终极技能"},
        recording_terms={"Mercy": "安吉拉"},
    )
    assert glossary == {"ult": "终极技能", "Mercy": "安吉拉"}


def test_short_word_before_long_pause_does_not_create_overlong_cue() -> None:
    words = [
        SubtitleWord("w1", "Oh", 1_000, 1_300, .9, "en"),
        SubtitleWord("w2", "what", 8_000, 8_300, .9, "en"),
        SubtitleWord("w3", "happened?", 8_310, 9_000, .9, "en"),
    ]
    groups = BilingualSubtitleService()._segment(words)
    assert groups[0][1] == "short_reaction_or_pause"
    assert max(group[-1].end_ms - group[0].start_ms for group, _ in groups) <= 6_000


class FakeJsonClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs["validator"](self.payload)


def test_qwen_provider_requires_a_non_empty_grounded_translation() -> None:
    client = FakeJsonClient({"translation": "保留专有名词 Pokémon。"})
    provider = QwenTranslationProvider(client)
    translated = provider.translate(
        "Keep the proper noun Pokémon.", source_language="en", target_language="zh",
        glossary={"Pokémon": "Pokémon"},
    )
    assert translated == "保留专有名词 Pokémon。"
    assert "Do not add facts" in client.calls[0]["system_prompt"]

    with pytest.raises(ValueError, match="empty"):
        QwenTranslationProvider(FakeJsonClient({"translation": "  "})).translate(
            "source", source_language="en", target_language="zh", glossary={},
        )


class FakeTranslator:
    name = "fake"
    model = "fake-v1"

    def __init__(self):
        self.calls = []

    def translate(self, text, *, source_language, target_language, glossary):
        self.calls.append((text, source_language, target_language, dict(glossary)))
        return f"中译：{text}" if target_language == "zh" else f"English: {text}"


def _words():
    raw = [
        ("Hello", 10_000, 10_400), ("there.", 10_450, 10_900),
        ("Something", 11_700, 12_100), ("is", 12_150, 12_300),
        ("behind", 12_350, 12_700), ("me!", 12_760, 13_100),
        ("No!", 13_900, 14_600),
    ]
    return [SubtitleWord(f"w{i}", text, start, end, .9, "en") for i, (text, start, end) in enumerate(raw)]


def test_word_timeline_is_clip_relative_bilingual_and_semantic(tmp_path: Path) -> None:
    provider = FakeTranslator()
    service = BilingualSubtitleService()
    track = service.build_track(
        clip_id="clip", words=_words(), clip_start_ms=10_000, clip_end_ms=15_000,
        source_language="en", provider=provider, cache_path=tmp_path / "cache.json",
        glossary={"Something": "Something"},
    )
    assert track.display_mode is BilingualDisplayMode.ZH_EN
    assert [(cue.start_ms, cue.end_ms) for cue in track.cues] == [(0, 900), (1700, 3100), (3900, 4600)]
    assert all(cue.zh_text.startswith("中译：") and cue.en_text == cue.source_text for cue in track.cues)
    assert [cue.segmentation_reason for cue in track.cues] == ["sentence_and_pause", "sentence_and_pause", "reaction"]

    artifacts = service.write_artifacts(track, tmp_path, position=SubtitlePosition.TOP, clip_duration_ms=5_000)
    assert "中译" in artifacts["srt"].read_text(encoding="utf-8")
    assert r"\N" in artifacts["ass"].read_text(encoding="utf-8-sig")
    report = service.quality_report(track, 5_000)
    assert report["timeline_validity"] is True and report["overlap_count"] == 0
    assert report["untranslated_cues"] == 0
    assert max(cue.end_ms - cue.start_ms for cue in track.cues) <= 6_000


def test_translation_cache_key_changes_with_source_and_glossary(tmp_path: Path) -> None:
    provider = FakeTranslator()
    service = BilingualSubtitleService()
    kwargs = dict(clip_id="clip", words=_words(), clip_start_ms=10_000, clip_end_ms=15_000,
                  source_language="en", provider=provider, cache_path=tmp_path / "cache.json")
    service.build_track(**kwargs, glossary_version="1")
    first = len(provider.calls)
    service.build_track(**kwargs, glossary_version="1")
    assert len(provider.calls) == first
    service.build_track(**kwargs, glossary_version="2")
    assert len(provider.calls) == first * 2


def test_provider_failure_is_not_disguised_as_bilingual() -> None:
    class Broken(FakeTranslator):
        def translate(self, *args, **kwargs):
            raise RuntimeError("offline")

    with pytest.raises(RuntimeError, match="TRANSLATION_UNAVAILABLE.*offline"):
        BilingualSubtitleService().build_track(
            clip_id="clip", words=_words(), clip_start_ms=10_000, clip_end_ms=15_000,
            source_language="en", provider=Broken(),
        )


def test_contextual_provider_records_argos_only_after_qwen_failure() -> None:
    class BrokenQwen(FakeTranslator):
        name = "qwen"

        def translate(self, *args, **kwargs):
            raise RuntimeError("qwen unavailable")

    class Argos(FakeTranslator):
        name = "argos"

    track = BilingualSubtitleService().build_track(
        clip_id="clip", words=_words(), clip_start_ms=10_000, clip_end_ms=15_000,
        source_language="en", provider=FallbackTranslationProvider(BrokenQwen(), Argos()),
    )

    assert track.translation_provider == "ARGOS_FALLBACK"
    assert all(cue.localization_note == "argos_provider_fallback" for cue in track.cues)


def test_nonzero_media_time_and_range_offset_are_normalized() -> None:
    words = words_from_payload(
        [{"word": "Hello", "start": 5.2, "end": 5.8}],
        media_start_ms=5_000, recording_offset_ms=90_000, language="en",
    )
    assert (words[0].start_ms, words[0].end_ms) == (90_200, 90_800)


@pytest.mark.parametrize("source_language", ["zh", "ja"])
def test_chinese_and_japanese_sources_produce_both_languages(source_language: str) -> None:
    provider = FakeTranslator()
    words = [SubtitleWord("w1", "こんにちは。" if source_language == "ja" else "你好。", 1_000, 2_000, .9, source_language)]
    track = BilingualSubtitleService().build_track(
        clip_id="clip", words=words, clip_start_ms=500, clip_end_ms=2_500,
        source_language=source_language, provider=provider,
    )
    assert track.cues[0].zh_text and track.cues[0].en_text
    assert track.cues[0].start_ms == 500 and track.cues[0].end_ms == 1_500


def test_overlap_and_out_of_range_are_rejected() -> None:
    from acfv.clips.subtitles import SubtitleCue

    cues = [
        SubtitleCue("1", 0, 1000, "a", "甲", "a", "en", ["1"], "sentence", .9, "TRANSLATION_READY"),
        SubtitleCue("2", 900, 1500, "b", "乙", "b", "en", ["2"], "sentence", .9, "TRANSLATION_READY"),
    ]
    with pytest.raises(ValueError, match="Overlapping"):
        BilingualSubtitleService.validate(cues, 2_000, require_bilingual=True)


def test_long_continuous_speech_splits_only_at_best_word_boundary() -> None:
    words = [SubtitleWord(f"w{i}", f"word{i}", i * 700, i * 700 + 500, .9, "en") for i in range(12)]
    track = BilingualSubtitleService().build_track(
        clip_id="clip", words=words, clip_start_ms=0, clip_end_ms=9_000,
        source_language="en", provider=FakeTranslator(),
    )
    assert len(track.cues) >= 2
    assert all(cue.end_ms - cue.start_ms <= 6_000 for cue in track.cues)
    assert sorted(word_id for cue in track.cues for word_id in cue.word_ids) == sorted(word.word_id for word in words)


def test_hard_limit_is_rechecked_after_pause_grouping() -> None:
    timings = [
        ("Something,", 0, 640), ("no,", 640, 1280), ("please", 1480, 1660), ("no", 1660, 2040),
        ("No", 2660, 2860), ("no", 2860, 3060), ("no", 3060, 4040),
        ("Turn", 4740, 5200), ("down", 5200, 5520), ("for", 5520, 5820), ("what", 5820, 6140),
    ]
    words = [SubtitleWord(f"w{i}", text, 10_000 + start, 10_000 + end, .9, "en")
             for i, (text, start, end) in enumerate(timings)]
    track = BilingualSubtitleService().build_track(
        clip_id="clip", words=words, clip_start_ms=10_000, clip_end_ms=17_000,
        source_language="en", provider=FakeTranslator(),
    )
    assert all(cue.end_ms - cue.start_ms <= 6_000 for cue in track.cues)
    assert [word for cue in track.cues for word in cue.word_ids] == [item.word_id for item in words]
