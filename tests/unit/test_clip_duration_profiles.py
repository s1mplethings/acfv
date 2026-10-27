import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from acfv.clips import (
    ClipEventPlan,
    ClipVariantService,
    DurationProfile,
    DurationProfileService,
    DurationRequest,
    RenderedVariant,
    SemanticBoundaryUnit,
    SubtitleWord,
    VariantStatus,
    duration_distribution,
)


def _units():
    return [
        SemanticBoundaryUnit(100_000, 120_000, "early setup", ("setup",)),
        SemanticBoundaryUnit(120_000, 135_000, "fear setup", ("setup",)),
        SemanticBoundaryUnit(135_000, 155_000, "event and result!", ("event", "payoff")),
        SemanticBoundaryUnit(155_000, 180_000, "reaction.", ("reaction",)),
        SemanticBoundaryUnit(180_000, 220_000, "discussion.", ("aftermath",)),
        SemanticBoundaryUnit(220_000, 245_000, "natural ending.", ("aftermath",)),
    ]


def test_profiles_share_anchor_and_increase_semantically() -> None:
    variants = DurationProfileService().generate_all(
        event_id="event", units=_units(), payoff_anchor_ms=145_000, source_duration_ms=400_000,
    )
    assert [item.profile for item in variants] == [
        DurationProfile.SHORT, DurationProfile.STANDARD, DurationProfile.LONG, DurationProfile.FULL_EVENT,
    ]
    assert all(item.status is VariantStatus.READY and item.payoff_anchor_ms == 145_000 for item in variants)
    durations = [item.duration_ms for item in variants]
    assert durations == sorted(durations) and len(set(durations)) == 4
    assert variants[0].start_ms == 120_000
    assert variants[-1].start_ms == 100_000 and variants[-1].end_ms == 245_000


def test_custom_duration_conflict_returns_nearest_natural_boundary() -> None:
    result = DurationProfileService().generate(
        event_id="event", units=_units(), payoff_anchor_ms=145_000, source_duration_ms=400_000,
        request=DurationRequest(DurationProfile.CUSTOM, min_seconds=5, max_seconds=10),
    )
    assert result.status is VariantStatus.DURATION_CONFLICT
    assert result.duration_ms > 10_000
    assert result.extension_reason == "content_first_natural_boundary_outside_custom_range"


def test_missing_setup_and_source_edge_are_explicit() -> None:
    no_setup = [SemanticBoundaryUnit(100_000, 130_000, "result", ("payoff",))]
    unavailable = DurationProfileService().generate(
        event_id="event", units=no_setup, payoff_anchor_ms=110_000, source_duration_ms=200_000,
        request=DurationRequest(DurationProfile.SHORT),
    )
    assert unavailable.status is VariantStatus.NOT_AVAILABLE
    edge = DurationProfileService().generate(
        event_id="event", units=[
            SemanticBoundaryUnit(1_000, 12_000, "setup", ("setup",)),
            SemanticBoundaryUnit(12_000, 25_000, "result", ("payoff",)),
        ], payoff_anchor_ms=15_000, source_duration_ms=200_000,
        request=DurationRequest(DurationProfile.SHORT),
    )
    assert edge.status is VariantStatus.NOT_AVAILABLE and edge.extension_reason.endswith("+SOURCE_EDGE")


def test_sub_15_second_semantic_event_is_not_promoted_to_a_final_profile() -> None:
    units = [
        SemanticBoundaryUnit(100_000, 105_000, "setup", ("setup",)),
        SemanticBoundaryUnit(105_000, 112_000, "payoff.", ("event", "payoff")),
    ]
    result = DurationProfileService().generate(
        event_id="event", units=units, payoff_anchor_ms=108_000,
        source_duration_ms=300_000,
        request=DurationRequest(DurationProfile.STANDARD),
    )
    assert result.status is VariantStatus.NOT_AVAILABLE
    assert result.extension_reason == "semantic_event_below_15s_viability_floor"


def test_variant_service_reuses_renderer_for_clean_and_bilingual(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def renderer(**kwargs):
        calls.append(kwargs)
        output = Path(kwargs["output_path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"bilingual" if kwargs.get("subtitle_path") else b"clean")
        return {"output_path": str(output)}

    class Translator:
        name = "fake"
        model = "v1"

        def translate(self, text, **kwargs):
            return "中译" + text

    service = ClipVariantService(renderer=renderer)
    monkeypatch.setattr(service, "_preview_frames", lambda video, duration, target: tuple(
        (target / f"subtitle_preview_{name}.jpg") for name in ("start", "middle", "end")
    ))
    for path in (tmp_path / "short").glob("never"):
        path.touch()
    words = tuple(SubtitleWord(f"w{i}", text, start, end, .9, "en") for i, (text, start, end) in enumerate([
        ("fear.", 120_000, 122_000), ("event!", 136_000, 138_000), ("result.", 145_000, 147_000),
    ]))
    plan = ClipEventPlan("event", "clip", str(tmp_path / "source.mp4"), 400_000, 145_000, "en", tuple(_units()), words)
    (tmp_path / "source.mp4").touch()
    result = service.generate_one(plan, DurationRequest(DurationProfile.SHORT), output_root=tmp_path, provider=Translator())
    assert isinstance(result, RenderedVariant)
    assert len(calls) == 2 and calls[1]["subtitle_path"].endswith("clip_zh_en.ass")
    assert Path(result.clean_path).read_bytes() != Path(result.bilingual_path).read_bytes()
    quality = json.loads((Path(result.output_dir) / "final_language_quality.json").read_text(encoding="utf-8"))
    assert quality["PUBLISHABLE"] is False
    assert "publishable" not in quality


def test_duration_distribution_detects_legacy_20s_and_exact_target_concentration() -> None:
    failed = duration_distribution([20_000] * 10 + [35_000, 47_000])
    assert failed["fail_fixed_duration_path"] is True
    assert failed["auto_suspect_exact_duration"] is True
    varied = duration_distribution([31_200, 48_400, 57_700, 63_100, 71_900, 84_300])
    assert varied["fail_fixed_duration_path"] is False
    assert varied["auto_suspect_exact_duration"] is False


def test_generate_all_runs_final_event_asr_once_for_all_profiles(tmp_path: Path, monkeypatch) -> None:
    calls = []

    class TranscriptService:
        def refine(self, request, *, output_root):
            calls.append((request.event_id, output_root))
            return SimpleNamespace(aligned_words=())

    service = ClipVariantService(transcript_service=TranscriptService())
    plan = ClipEventPlan(
        "event", "clip", str(tmp_path / "source.mp4"), 400_000, 145_000, "en",
        tuple(_units()), (), recording_id="recording",
    )
    monkeypatch.setattr(
        service, "_generate_prepared",
        lambda prepared, request, **_kwargs: service.select_boundary(prepared, request),
    )

    results = service.generate_all(plan, output_root=tmp_path, provider=object())

    assert len(calls) == 1
    assert len(results) == 4


def test_generate_one_limits_final_asr_to_selected_semantic_variant(tmp_path: Path, monkeypatch) -> None:
    requests = []

    class TranscriptService:
        def refine(self, request, *, output_root):
            requests.append(request)
            return SimpleNamespace(aligned_words=())

    service = ClipVariantService(transcript_service=TranscriptService())
    plan = ClipEventPlan(
        "event", "clip", str(tmp_path / "source.mp4"), 400_000, 145_000, "en",
        tuple(_units()), (), recording_id="recording",
    )
    monkeypatch.setattr(
        service, "_generate_prepared",
        lambda prepared, request, **_kwargs: service.select_boundary(prepared, request),
    )

    result = service.generate_one(
        plan, DurationRequest(DurationProfile.STANDARD), output_root=tmp_path, provider=object(),
    )

    assert len(requests) == 1
    assert (requests[0].event_start_ms, requests[0].event_end_ms) == (result.start_ms, result.end_ms)


def test_final_asr_rejects_temporal_evidence_with_wrong_semantics() -> None:
    words = (
        SubtitleWord("w1", "Okay", 100_000, 101_000, .9, "en"),
        SubtitleWord("w2", "screenshot", 101_000, 102_000, .9, "en"),
        SubtitleWord("w3", "mouse", 102_000, 103_000, .9, "en"),
    )
    plan = ClipEventPlan(
        "event", "clip", "source.mp4", 400_000, 145_000, "en", tuple(_units()), words,
        raw_library_transcript="Animal Crossing Harvest Moon was on screen",
        required_evidence_text="Animal Crossing Harvest Moon",
    )

    assert ClipVariantService._final_asr_supports_required_evidence(plan) is False


def test_final_asr_accepts_inflected_query_when_event_evidence_agrees() -> None:
    words = (
        SubtitleWord("w1", "small", 100_000, 101_000, .9, "en"),
        SubtitleWord("w2", "horse", 101_000, 102_000, .9, "en"),
        SubtitleWord("w3", "running", 102_000, 103_000, .9, "en"),
    )
    plan = ClipEventPlan(
        "event", "clip", "source.mp4", 400_000, 145_000, "en", tuple(_units()), words,
        raw_library_transcript="tiny little horses love running",
        required_evidence_text="tiny little horses",
    )

    assert ClipVariantService._final_asr_supports_required_evidence(plan) is True


def test_standard_prefers_complete_25_second_reaction_over_nominal_target() -> None:
    units = [
        SemanticBoundaryUnit(100_000, 108_000, "Here is the setup.", ("setup",)),
        SemanticBoundaryUnit(108_000, 125_000, "That was the payoff!", ("event", "payoff")),
        SemanticBoundaryUnit(125_000, 165_000, "New unrelated topic.", ("unrelated",)),
    ]
    result = DurationProfileService().generate(
        event_id="reaction", units=units, payoff_anchor_ms=116_000,
        source_duration_ms=300_000, request=DurationRequest(DurationProfile.STANDARD),
    )
    assert result.status is VariantStatus.READY
    assert result.duration_ms == 25_000
    assert result.extension_reason == "complete_event_shorter_than_profile_range"


def test_standard_preserves_complete_95_second_chatting_story() -> None:
    units = [
        SemanticBoundaryUnit(100_000, 130_000, "The question was simple.", ("setup", "topic")),
        SemanticBoundaryUnit(130_000, 175_000, "Here is the full explanation.", ("core",)),
        SemanticBoundaryUnit(175_000, 195_000, "That is my conclusion.", ("payoff", "conclusion")),
    ]
    result = DurationProfileService().generate(
        event_id="chat", units=units, payoff_anchor_ms=185_000,
        source_duration_ms=300_000, request=DurationRequest(DurationProfile.STANDARD),
    )
    assert result.status is VariantStatus.READY
    assert result.duration_ms == 95_000


@pytest.mark.parametrize("required", [(100_000, 106_000), (145_000, 154_000)])
def test_every_profile_keeps_required_evidence_near_event_edges(required) -> None:
    units = [
        SemanticBoundaryUnit(100_000, 115_000, "Setup.", ("setup",)),
        SemanticBoundaryUnit(115_000, 145_000, "Core.", ("event",)),
        SemanticBoundaryUnit(145_000, 155_000, "Payoff!", ("payoff",)),
        SemanticBoundaryUnit(155_000, 180_000, "Useful aftermath.", ("aftermath",)),
    ]
    results = DurationProfileService().generate_all(
        event_id="evidence", units=units, payoff_anchor_ms=150_000,
        source_duration_ms=300_000, required_evidence_span_ms=required,
    )
    for item in results:
        if item.status is VariantStatus.READY:
            assert item.start_ms <= required[0] and item.end_ms >= required[1]


def test_short_and_long_are_not_available_without_semantic_fit() -> None:
    story = [
        SemanticBoundaryUnit(100_000, 145_000, "Long setup.", ("setup",)),
        SemanticBoundaryUnit(145_000, 175_000, "Long core.", ("event",)),
        SemanticBoundaryUnit(175_000, 195_000, "Conclusion.", ("payoff",)),
    ]
    service = DurationProfileService()
    short = service.generate(
        event_id="story", units=story, payoff_anchor_ms=185_000, source_duration_ms=300_000,
        request=DurationRequest(DurationProfile.SHORT),
    )
    long = service.generate(
        event_id="story", units=story, payoff_anchor_ms=185_000, source_duration_ms=300_000,
        request=DurationRequest(DurationProfile.LONG),
    )
    assert short.status is VariantStatus.NOT_AVAILABLE
    assert long.status is VariantStatus.NOT_AVAILABLE
