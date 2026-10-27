from __future__ import annotations

import json
from pathlib import Path

import typer

from acfv.clips import (
    BilingualDisplayMode, ClipCandidateSelector, ClipEventPlan,
    ClipService, ClipVariantService, DurationProfile, DurationRequest, SemanticBoundaryUnit,
    FinalClipTranscriptService, SubtitleCompleteness, SubtitlePosition,
    default_final_translation_provider, words_from_payload,
)
from acfv.library import LibraryService
from acfv.retrieval import HybridRetrievalService, PersistentMomentIndex
from acfv.retrieval.query import SearchScope

clip_app = typer.Typer(no_args_is_help=True)


@clip_app.command("create")
def create(
    moment_id: str,
    query: str = "",
    render: bool = True,
    duration: str = typer.Option("standard", "--duration", help="short|standard|long|full-event|custom"),
    target_seconds: float | None = typer.Option(None, "--target-seconds"),
    min_seconds: float | None = typer.Option(None, "--min"),
    max_seconds: float | None = typer.Option(None, "--max"),
    all_variants: bool = typer.Option(False, "--all-variants"),
    subtitle: str = typer.Option("bilingual", "--subtitle", help="bilingual|source-only"),
    subtitle_order: str = typer.Option("zh-en", "--subtitle-order"),
    subtitle_mode: str = typer.Option("complete", "--subtitle-mode"),
    subtitle_position: str = typer.Option("auto", "--subtitle-position"),
    burn_subtitles: bool = typer.Option(True, "--burn-subtitles/--no-burn-subtitles"),
) -> None:
    library = LibraryService()
    service = ClipService(library.repository)
    clip = service.create_proposal(moment_id, query=query)
    profile = duration.replace("-", "_").upper()
    if profile not in {item.value for item in DurationProfile}:
        raise typer.BadParameter("duration must be short, standard, long, full-event, or custom")
    if not all_variants:
        clip = service.apply_duration_profile(
            clip.id, DurationProfile(profile), target_seconds=target_seconds,
            min_seconds=min_seconds, max_seconds=max_seconds,
        )
    display_mode = "ZH_EN" if subtitle_order.casefold() == "zh-en" else "EN_ZH"
    if subtitle.casefold() == "source-only":
        display_mode = "SOURCE_ONLY"
    clip = service.update_review(
        clip.id, duration_profile=profile, target_duration_seconds=target_seconds,
        min_duration_seconds=min_seconds, max_duration_seconds=max_seconds,
        display_mode=display_mode, subtitle_completeness=subtitle_mode.upper(),
        subtitle_position=subtitle_position.upper().replace("AUTO", "AUTO_SAFE_AREA"),
        selected_final_variant="ALL" if all_variants else profile,
        extension_reason="pending_semantic_boundary_generation",
    )
    if render:
        clip = service.render(clip.id)
    typer.echo(json.dumps({
        "clip_id": clip.id, "render_status": clip.render_status.value,
        "output_path": clip.output_path or "", "duration_profile": profile,
        "all_variants": all_variants, "display_mode": display_mode,
        "subtitle_mode": subtitle_mode.upper(), "burn_subtitles": burn_subtitles,
    }, ensure_ascii=False))


@clip_app.command("render")
def render_clip(clip_id: str) -> None:
    library = LibraryService()
    clip = ClipService(library.repository).render(clip_id)
    typer.echo(f"{clip.id}\t{clip.render_status.value}\t{clip.output_path or ''}")


@clip_app.command("variants")
def variants(
    plan: Path = typer.Argument(..., exists=True, dir_okay=False, help="Semantic event plan JSON"),
    output_root: Path = typer.Option(Path("outputs/bilingual-duration-validation"), "--output-root"),
    duration: str = typer.Option("all", "--duration", help="all|short|standard|long|full-event|custom"),
    target_seconds: float | None = typer.Option(None, "--target-seconds"),
    min_seconds: float | None = typer.Option(None, "--min"),
    max_seconds: float | None = typer.Option(None, "--max"),
    subtitle_order: str = typer.Option("zh-en", "--subtitle-order"),
    subtitle_mode: str = typer.Option("complete", "--subtitle-mode"),
    subtitle_position: str = typer.Option("auto", "--subtitle-position"),
) -> None:
    """Generate semantic duration variants with locked bilingual timelines."""
    raw = json.loads(plan.read_text(encoding="utf-8"))
    units = tuple(SemanticBoundaryUnit(
        int(item["start_ms"]), int(item["end_ms"]), str(item["text"]), tuple(item.get("roles") or ())
    ) for item in raw["units"])
    words = tuple(words_from_payload(raw["words"], language=str(raw.get("source_language") or "en")))
    event = ClipEventPlan(
        event_id=str(raw["event_id"]), clip_id=str(raw.get("clip_id") or raw["event_id"]),
        source_path=str(raw["source_path"]), source_duration_ms=int(raw["source_duration_ms"]),
        payoff_anchor_ms=int(raw["payoff_anchor_ms"]), source_language=str(raw.get("source_language") or "en"),
        units=units, words=words,
    )
    mode = BilingualDisplayMode.ZH_EN if subtitle_order.casefold() == "zh-en" else BilingualDisplayMode.EN_ZH
    completeness = SubtitleCompleteness(subtitle_mode.upper())
    position = SubtitlePosition.AUTO_SAFE_AREA if subtitle_position.casefold() == "auto" else SubtitlePosition(subtitle_position.upper())
    target = output_root / str(raw.get("recording_id") or event.event_id)
    service = ClipVariantService(transcript_service=FinalClipTranscriptService())
    provider = default_final_translation_provider()
    if duration.casefold() == "all":
        results = service.generate_all(event, output_root=target, provider=provider,
                                       display_mode=mode, completeness=completeness, position=position,
                                       glossary=dict(raw.get("glossary") or {}))
    else:
        profile = DurationProfile(duration.replace("-", "_").upper())
        results = [service.generate_one(
            event, DurationRequest(profile, target_seconds, min_seconds, max_seconds),
            output_root=target, provider=provider, display_mode=mode,
            completeness=completeness, position=position, glossary=dict(raw.get("glossary") or {}),
        )]
    typer.echo(json.dumps({
        "event_id": event.event_id, "output_root": str(target.resolve()),
        "variants": [
            {"profile": (item.boundary.profile if hasattr(item, "boundary") else item.profile).value,
             "status": (item.boundary.status if hasattr(item, "boundary") else item.status).value,
             "bilingual_path": getattr(item, "bilingual_path", None)}
            for item in results
        ],
    }, ensure_ascii=False))


@clip_app.command("candidates")
def candidates(
    recording_id: str = typer.Argument(..., help="Creator Library Recording ID"),
    query: str = typer.Argument(..., help="Event or reaction to find"),
    database: Path | None = typer.Option(None, "--database", help="Library database override"),
    index_root: Path | None = typer.Option(None, "--index-root", help="Moment index override"),
    output_root: Path = typer.Option(Path("outputs/candidates"), "--output-root", help="Candidate output directory"),
    render_previews: bool = typer.Option(False, "--render-previews/--no-render-previews"),
    save_proposals: bool = typer.Option(True, "--save-proposals/--no-save-proposals"),
) -> None:
    """Retrieve Top-10, rank diverse candidates, and optionally render previews."""
    library = LibraryService(database)
    recording = library.get_recording(recording_id)
    if recording is None:
        raise typer.BadParameter(f"Unknown recording: {recording_id}")
    retrieval = HybridRetrievalService(library.repository, PersistentMomentIndex(library.repository, index_root))
    results = retrieval.search(query, top_k=10, scope=SearchScope.RECORDING, recording_id=recording_id)
    selector = ClipCandidateSelector(library.repository)
    generated = selector.generate(query, results)
    target = output_root / recording_id
    if render_previews:
        if not recording.local_path:
            raise typer.BadParameter("Recording has no local media path")
        selector.render_previews(generated, recording.local_path, target)
    scores = selector.write_scores(generated, target / "candidate_scores.json")
    proposals = selector.save_proposals(generated) if save_proposals else []
    typer.echo(json.dumps({
        "recording_id": recording_id,
        "candidate_count": len(generated),
        "selected_candidate": next(item.candidate_id for item in generated if item.selected),
        "candidate_scores": str(scores.resolve()),
        "proposal_ids": [item.id for item in proposals],
    }, ensure_ascii=False))
