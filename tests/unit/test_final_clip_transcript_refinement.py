import json
from pathlib import Path

from acfv.clips import (
    FinalAsrConfig,
    FinalClipTranscriptService,
    FinalTranscriptRequest,
    SourceCorrection,
    SourceCorrectionState,
    SourceTranscriptRefiner,
)


def test_final_asr_uses_padded_context_vad_alignment_and_cache(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media")
    calls = {"asr": 0, "align": 0}

    def extract(_source, target, **kwargs):
        target.write_bytes(b"wav")
        assert kwargs == {"start_ms": 25_000, "end_ms": 75_000}

    def asr(_audio, **kwargs):
        calls["asr"] += 1
        assert kwargs["vad_filter"] is True
        assert kwargs["recording_offset_ms"] == 25_000
        return ([{"start": 30.0, "end": 31.0, "text": "what the fuck",
                  "words": [{"start": 30.0, "end": 30.2, "word": "what"}]}], "en")

    def align(_audio, _segments, **kwargs):
        calls["align"] += 1
        return ([
            {"start_ms": 30_000, "end_ms": 30_200, "word": "what", "probability": .9},
            {"start_ms": 30_210, "end_ms": 30_400, "word": "the", "probability": .9},
            {"start_ms": 30_410, "end_ms": 30_800, "word": "fuck", "probability": .9},
        ], "forced-test-alignment")

    monkeypatch.setattr("acfv.clips.refinement._extract_audio", extract)
    service = FinalClipTranscriptService(
        config=FinalAsrConfig(model="candidate", context_padding_ms=5_000),
        asr_runner=asr, aligner=align,
    )
    request = FinalTranscriptRequest(
        "recording", "event", str(source), 120_000, 30_000, 70_000, "en",
        raw_library_transcript="wrong library text",
    )
    first = service.refine(request, output_root=tmp_path / "out")
    second = service.refine(request, output_root=tmp_path / "out")

    assert calls == {"asr": 1, "align": 1}
    assert second.cache_hit is True
    assert first.raw_library_transcript == "wrong library text"
    assert first.raw_final_asr == "what the fuck"
    assert first.timing_backend == "forced-test-alignment"
    payload = json.loads(Path(first.path).read_text(encoding="utf-8"))
    assert payload["text_source"] == "corrected_final_transcript"
    assert payload["timing_source"] == "forced-test-alignment"


def test_source_refiner_rejects_profanity_removal() -> None:
    class Client:
        def complete_json(self, **_kwargs):
            return {"corrected_text": "what the heck", "changes": [], "confidence": .99, "reason": "cleaned"}

    result = SourceTranscriptRefiner(Client()).refine("what the fuck")
    assert result.corrected_text == "what the fuck"
    assert result.reason == "UNCERTAIN"


def test_source_refiner_preserves_oversized_input_without_calling_model() -> None:
    class NeverCalled:
        def complete_json(self, **_kwargs):
            raise AssertionError("oversized transcript must not be sent as one request")

    result = SourceTranscriptRefiner(NeverCalled(), max_input_chars=10).refine(
        "this source transcript is deliberately longer than ten characters"
    )

    assert result.corrected_text == result.raw_text
    assert result.confidence == 0.0
    assert result.reason == "UNCERTAIN_REFINER_INPUT_TOO_LONG"


def test_unchanged_uncertain_refinement_preserves_acoustic_word_confidence(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media")
    monkeypatch.setattr(
        "acfv.clips.refinement._extract_audio",
        lambda _source, target, **_kwargs: target.write_bytes(b"wav"),
    )

    def asr(_audio, **_kwargs):
        return ([{
            "start": 0.0, "end": 2.0, "text": "outside keep words",
            "words": [
                {"start": 0.0, "end": 0.4, "word": "outside", "probability": .95},
                {"start": 1.0, "end": 1.4, "word": "keep", "probability": .93},
                {"start": 1.4, "end": 1.8, "word": "words", "probability": .91},
            ],
        }], "en")

    class UncertainRefiner:
        def refine(self, raw_text, **_kwargs):
            return SourceCorrection(
                raw_text, raw_text, confidence=0.0, reason="UNCERTAIN",
                state=SourceCorrectionState.UNCHANGED_UNCERTAIN.value,
                needs_review_reasons=("EMPTY_CORRECTION",),
            )

    artifact = FinalClipTranscriptService(
        config=FinalAsrConfig(context_padding_ms=1_000, max_local_redecodes=0),
        asr_runner=asr, refiner=UncertainRefiner(),
    ).refine(FinalTranscriptRequest(
        "recording", "event", str(source), 3_000, 1_000, 2_000, "en",
    ), output_root=tmp_path / "out")

    assert [word.text for word in artifact.aligned_words] == ["keep", "words"]
    assert [word.confidence for word in artifact.aligned_words] == [.93, .91]
    assert all(word.source == "FINAL_ASR" for word in artifact.aligned_words)
    assert artifact.quality.low_confidence_words == 0
