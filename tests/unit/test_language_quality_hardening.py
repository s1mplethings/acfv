import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from acfv.clips import (
    ASRQualityFlag,
    BilingualSubtitleService,
    FallbackTranslationProvider,
    FinalAsrConfig,
    FinalClipTranscriptService,
    FinalTranscriptRequest,
    QwenTranslationProvider,
    SourceCorrectionState,
    SourceTranscriptRefiner,
    SubtitleWord,
    TerminologyResolver,
    TranslationMemory,
    TranslationMemoryEntry,
    translation_semantic_guard,
    words_from_payload,
)
from acfv.clips.subtitles import _adaptive_translation_batches
from acfv.clips import refinement as refinement_module


class _CorrectionClient:
    def __init__(self, payload):
        self.payload = payload

    def complete_json(self, **_kwargs):
        return self.payload


def test_source_refiner_requires_external_evidence_for_lexical_change() -> None:
    payload = {
        "corrected_text": "high sensitivity", "confidence": 0.99,
        "reason": "typo", "changes": [{"before": "sensibility", "after": "sensitivity"}],
    }
    uncertain = SourceTranscriptRefiner(_CorrectionClient(payload)).refine("high sensibility")
    assert uncertain.state == SourceCorrectionState.UNCHANGED_UNCERTAIN.value
    assert uncertain.corrected_text == "high sensibility"
    assert "LEXICAL_CHANGE_WITHOUT_EXTERNAL_EVIDENCE" in uncertain.needs_review_reasons

    payload["changes"] = [
        {"before": "sensibility", "after": "sensitivity", "evidence_type": "acoustic_redecode"},
        {"before": "sensibility", "after": "sensitivity", "evidence_type": "glossary"},
    ]
    corrected = SourceTranscriptRefiner(_CorrectionClient(payload)).refine(
        "high sensibility", glossary={"sensitivity": "sensitivity"},
        acoustic_alternatives=({"text": "high sensitivity", "status": "READY"},),
    )
    assert corrected.state == SourceCorrectionState.AUTO_CORRECTED.value
    assert corrected.corrected_text == "high sensitivity"


def test_source_refiner_preserves_negation_and_profanity() -> None:
    payload = {
        "corrected_text": "I screamed", "confidence": 0.99, "reason": "rewrite",
        "changes": [{"before": "didn't", "after": ""}],
    }
    result = SourceTranscriptRefiner(_CorrectionClient(payload)).refine("I didn't scream")
    assert result.state == SourceCorrectionState.NEEDS_REVIEW.value
    assert result.corrected_text == "I didn't scream"
    assert "NEGATION_REMOVED" in result.needs_review_reasons


def test_word_payload_keeps_raw_text_source_and_quality_flags() -> None:
    word = words_from_payload([{
        "word": "Mercy", "start_ms": 10, "end_ms": 100, "probability": 0.4,
        "raw_text": "Murphy", "source": "SOURCE_REFINER",
        "quality_flags": ["LOW_WORD_CONFIDENCE", "UNCERTAIN_PROPER_NOUN"],
    }])[0]
    assert word.raw_text == "Murphy"
    assert word.source == "SOURCE_REFINER"
    assert word.quality_flags == ("LOW_WORD_CONFIDENCE", "UNCERTAIN_PROPER_NOUN")


def test_segment_quality_does_not_mark_every_high_confidence_word_broken_or_low() -> None:
    request = FinalTranscriptRequest("r", "e", "source", 10_000, 0, 5_000, "en")
    segment = {
        "start": 0.0, "end": 2.0, "text": "I know you", "avg_logprob": -1.0,
        "words": [
            {"start": 0.0, "end": .5, "word": "I", "probability": .95},
            {"start": .5, "end": 1.0, "word": "know", "probability": .95},
            {"start": 1.0, "end": 2.0, "word": "you", "probability": .95},
        ],
    }
    rows = refinement_module._annotate_aligned_words(
        segment["words"], [segment], request=request, detected_language="en",
        config=FinalAsrConfig(),
    )
    assert all("LOW_WORD_CONFIDENCE" not in row["quality_flags"] for row in rows)
    assert all("BROKEN_SENTENCE" not in row["quality_flags"] for row in rows)


def test_final_asr_low_confidence_triggers_local_redecode_and_release_gate(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media")
    calls = []

    def extract(_source, target, **_kwargs):
        target.write_bytes(b"wav")

    def asr(_audio, **kwargs):
        calls.append(kwargs["recording_offset_ms"])
        offset = kwargs["recording_offset_ms"] / 1000
        return ([{
            "start": offset + 1, "end": offset + 2, "text": "Maybe Mercy",
            "avg_logprob": -1.1, "no_speech_prob": 0.1,
            "words": [{"start": offset + 1, "end": offset + 1.4, "word": "Maybe", "probability": 0.3},
                      {"start": offset + 1.4, "end": offset + 2, "word": "Mercy", "probability": 0.4}],
        }], "en")

    monkeypatch.setattr("acfv.clips.refinement._extract_audio", extract)
    service = FinalClipTranscriptService(
        config=FinalAsrConfig(model="large-v3", context_padding_ms=0, max_local_redecodes=1),
        asr_runner=asr,
    )
    artifact = service.refine(FinalTranscriptRequest(
        "r", "e", str(source), 20_000, 1_000, 5_000, "en", payoff_anchor_ms=2_000,
    ), output_root=tmp_path / "out")

    assert len(calls) == 2
    assert artifact.quality is not None
    assert artifact.quality.low_confidence_words == 2
    assert artifact.quality.final_quality_state == "NEEDS_REVIEW"
    evidence = artifact.local_redecode_evidence[0]
    assert {
        "original_text", "original_probability", "original_segment_avg_logprob",
        "original_no_speech_prob", "candidate_text", "local_probability",
        "local_avg_logprob", "confidence_delta", "window_bounds", "model",
        "compute_type", "hotwords", "context", "decision",
    } <= evidence.keys()
    report = json.loads(Path(artifact.quality_report_path).read_text(encoding="utf-8"))
    assert report["ASR_RELEASE_STATE"] == "NEEDS_REVIEW"


def test_final_asr_reuses_loaded_model_for_local_windows(monkeypatch, tmp_path: Path) -> None:
    class Model:
        def transcribe(self, *_args, **_kwargs):
            return ([], type("Info", (), {"language": "en"})())

    class Adapter:
        _model = Model()

    calls = []

    def load(model, device):
        calls.append((model, device))
        return Adapter()

    monkeypatch.setitem(sys.modules, "acfv.steps.transcribe_audio.impl", SimpleNamespace(
        _load_faster_whisper_model=load,
    ))
    refinement_module._FINAL_ASR_ADAPTERS.clear()
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"wav")
    kwargs = dict(model="large-v3", language="en", device="cuda", vad_filter=True,
                  recording_offset_ms=0)
    refinement_module._run_faster_whisper(audio, **kwargs)
    refinement_module._run_faster_whisper(audio, **kwargs)
    assert calls == [("large-v3", "cuda")]
    refinement_module._FINAL_ASR_ADAPTERS.clear()


def test_music_and_overlap_flags_are_objective_and_lyrics_are_suppressed(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media")

    monkeypatch.setattr("acfv.clips.refinement._extract_audio", lambda _s, target, **_k: target.write_bytes(b"wav"))

    def asr(_audio, **_kwargs):
        return ([{
            "start": 1.0, "end": 2.0, "text": "singing words", "music": True,
            "words": [{"start": 1.0, "end": 1.4, "word": "singing", "probability": .9},
                      {"start": 1.4, "end": 2.0, "word": "words", "probability": .9}],
        }, {
            "start": 2.1, "end": 3.0, "text": "No way!", "overlap": True,
            "words": [{"start": 2.1, "end": 2.4, "word": "No", "probability": .9},
                      {"start": 2.4, "end": 3.0, "word": "way!", "probability": .9}],
        }], "en")

    artifact = FinalClipTranscriptService(
        config=FinalAsrConfig(context_padding_ms=0, max_local_redecodes=0), asr_runner=asr,
    ).refine(FinalTranscriptRequest(
        "r", "e", str(source), 5_000, 0, 4_000, "en",
    ), output_root=tmp_path / "out")

    assert [word.text for word in artifact.aligned_words] == ["No", "way!"]
    assert all(ASRQualityFlag.POSSIBLE_OVERLAP.value in word.quality_flags
               for word in artifact.aligned_words)
    assert artifact.quality.final_quality_state == "NEEDS_REVIEW"


@pytest.mark.parametrize("source,target,code", [
    ("I didn't scream.", "我尖叫了。", "NEGATION_MISMATCH"),
    ("Use 25%.", "使用 20%。", "NUMBER_MISMATCH"),
    ("Pick Mercy.", "选角色。", "GLOSSARY_MISMATCH"),
    ("This is fine.", "笑死，这很好。", "SUSPICIOUS_INVENTED_MEME"),
])
def test_translation_semantic_guards(source: str, target: str, code: str) -> None:
    failures = translation_semantic_guard(source, target, glossary={"Mercy": "天使"})
    assert code in {item["code"] for item in failures}


def test_translation_memory_ignores_unconfirmed_entries() -> None:
    memory = TranslationMemory([
        TranslationMemoryEntry("GG", "好耶", confirmed=False),
        TranslationMemoryEntry("GG", "打得好", confirmed=True, creator_id="creator"),
    ])
    assert memory.lookup("GG", creator_id="other") is None
    assert memory.lookup("GG", creator_id="creator") == "打得好"


def test_terminology_resolver_requires_term_in_context_and_respects_precedence() -> None:
    resolver = TerminologyResolver(
        global_terms={"Mercy": "天使"}, creator_terms={"Mercy": "慈悲"},
        game_terms={"Mercy": "安吉拉"}, recording_terms={"Mercy": "Mercy"},
    )
    assert resolver.applicable("Pick Mercy now") == {"Mercy": "Mercy"}
    assert resolver.applicable("Pick Ana now") == {}


def test_adaptive_batch_downsizes_long_text_and_expands_short_reactions() -> None:
    long = [{"cue_id": str(i), "source": "word " * 100} for i in range(8)]
    short = [{"cue_id": str(i), "source": "No!"} for i in range(9)]
    assert max(len(batch) for _, batch in _adaptive_translation_batches(long, preferred_size=7)) <= 2
    assert [len(batch) for _, batch in _adaptive_translation_batches(short, preferred_size=5)] == [9]


def test_mixed_provider_state_and_argos_threshold_are_visible() -> None:
    class Primary:
        name = "qwen"
        model = "qwen"

        def translate(self, *_args, **_kwargs):
            raise RuntimeError("unused")

        def translate_group(self, cues, **_kwargs):
            if len(cues) > 1 or cues[0]["cue_id"] == "0002":
                raise RuntimeError("structured failure")
            return [{"cue_id": cues[0]["cue_id"], "zh_text": "你好", "tone_preserved": True,
                     "slang_present": False, "uncertain": False}]

    class Argos:
        name = "argos"
        model = "argos"

        def translate(self, text, **_kwargs):
            return "后备：" + text

    words = [
        SubtitleWord("1", "Hello.", 0, 1_000, .9, "en"),
        SubtitleWord("2", "Second.", 1_500, 2_500, .9, "en"),
    ]
    track = BilingualSubtitleService().build_track(
        clip_id="clip", words=words, clip_start_ms=0, clip_end_ms=3_000,
        source_language="en", provider=FallbackTranslationProvider(Primary(), Argos()),
    )
    assert track.translation_provider == "MIXED_PROVIDER"
    assert track.fallback_cue_count == 1
    assert track.translation_release_state == "NEEDS_REVIEW"
    assert track.cues[1].translation_provider == "ARGOS_FALLBACK"
    assert track.cues[1].attempt_count == 4


def test_qwen_rejects_duplicate_cue_ids() -> None:
    with pytest.raises(ValueError, match="duplicated"):
        QwenTranslationProvider._validate_group({"translations": [
            {"cue_id": "1", "zh_text": "一"}, {"cue_id": "1", "zh_text": "二"},
        ]}, [{"cue_id": "1", "text": "one"}])
