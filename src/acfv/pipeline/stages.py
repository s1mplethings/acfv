from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class StageDefinition:
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    modules: tuple[str, ...]
    optional: bool = False
    description: str = ""


CLIP_PIPELINE_STAGES: tuple[StageDefinition, ...] = (
    StageDefinition(
        name="ingest_video",
        inputs=("job_request.input_url_or_path",),
        outputs=("video_source", "chat_source?"),
        modules=("backend_orchestrator",),
        description="Resolve a Twitch VOD or local path into a local video source.",
    ),
    StageDefinition(
        name="extract_audio",
        inputs=("video_source",),
        outputs=("audio_extracted",),
        modules=("extract_audio",),
        description="Extract normalized audio from the resolved source media.",
    ),
    StageDefinition(
        name="build_audio_chunk_manifest",
        inputs=("audio_extracted",),
        outputs=("audio_chunk_manifest",),
        modules=("transcribe_audio",),
        description="Build a minimal chunk manifest that describes planned transcription chunks.",
    ),
    StageDefinition(
        name="transcribe_chunks",
        inputs=("audio_chunk_manifest",),
        outputs=("chunk_transcripts",),
        modules=("transcribe_audio",),
        description="Transcribe planned chunks into transcript fragments.",
    ),
    StageDefinition(
        name="merge_transcript",
        inputs=("chunk_transcripts",),
        outputs=("merged_transcript",),
        modules=("transcribe_audio",),
        description="Merge chunk-level transcript results into the transcript contract consumed downstream.",
    ),
    StageDefinition(
        name="optional_analysis",
        inputs=("merged_transcript", "chat_log?", "screen?", "emotion?", "speaker?", "subtitle?", "llm?"),
        outputs=("analysis_context", "analysis_segments", "semantic_segments?", "llm_segments?"),
        modules=(
            "screen_detect",
            "screen_understanding",
            "video_emotion",
            "speaker_separation",
            "streamer_subtitles",
            "subtitle_translate",
            "analyze_segments",
            "semantic_merge",
            "llm_highlight",
        ),
        optional=True,
        description="Run required base analysis plus optional enrichments before final segment selection.",
    ),
    StageDefinition(
        name="select_segments",
        inputs=("analysis_segments", "semantic_segments?", "llm_segments?"),
        outputs=("selected_segments",),
        modules=("render_clips.preselect",),
        description="Choose the final ordered segments that will be turned into clip work items.",
    ),
    StageDefinition(
        name="build_clip_manifest",
        inputs=("selected_segments", "video_source"),
        outputs=("clip_manifest",),
        modules=("render_clips.plan",),
        description="Build a deterministic clip manifest for the batch render stage.",
    ),
    StageDefinition(
        name="render_clips_batch",
        inputs=("clip_manifest",),
        outputs=("rendered_clips", "subtitles?", "thumbnails?"),
        modules=("render_clips",),
        description="Render the batch of clips described by the clip manifest.",
    ),
    StageDefinition(
        name="export_results",
        inputs=("rendered_clips", "clip_manifest", "merged_transcript"),
        outputs=("clips_manifest", "contract_output", "result_summary"),
        modules=("render_clips.export",),
        description="Write final manifests and export summaries for GUI/CLI consumers.",
    ),
)


_RAW_STAGE_TO_CANONICAL = {
    "ingest_video": "ingest_video",
    "audio_extract": "extract_audio",
    "extract_audio": "extract_audio",
    "build_audio_chunk_manifest": "build_audio_chunk_manifest",
    "transcribe": "transcribe_chunks",
    "transcribe_chunks": "transcribe_chunks",
    "merge_transcript": "merge_transcript",
    "analysis": "optional_analysis",
    "screen_detect": "optional_analysis",
    "screen_understanding": "optional_analysis",
    "video_emotion": "optional_analysis",
    "speaker_separation": "optional_analysis",
    "streamer_subtitles": "optional_analysis",
    "subtitle_translate": "optional_analysis",
    "semantic_merge": "optional_analysis",
    "llm_highlight": "optional_analysis",
    "optional_analysis": "optional_analysis",
    "select_segments": "select_segments",
    "build_clip_manifest": "build_clip_manifest",
    "clip": "render_clips_batch",
    "render_clips_batch": "render_clips_batch",
    "export_results": "export_results",
}


def get_stage_plan() -> list[dict]:
    return [asdict(stage) for stage in CLIP_PIPELINE_STAGES]


def get_stage_plugin_mapping() -> list[dict]:
    return [
        {
            "stage": stage.name,
            "modules": list(stage.modules),
            "inputs": list(stage.inputs),
            "outputs": list(stage.outputs),
            "optional": stage.optional,
        }
        for stage in CLIP_PIPELINE_STAGES
    ]


def normalize_stage_name(raw_stage: str | None) -> Optional[str]:
    if not raw_stage:
        return None
    return _RAW_STAGE_TO_CANONICAL.get(str(raw_stage))


def write_stage_plan(run_dir: Path | str, extra: Optional[dict] = None) -> Path:
    run_dir_path = Path(run_dir)
    work_dir = run_dir_path / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0.0",
        "pipeline": "clip",
        "stages": get_stage_plan(),
    }
    if extra:
        payload.update(extra)
    out_path = work_dir / "stage_plan.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def stage_names(stages: Optional[Iterable[StageDefinition]] = None) -> list[str]:
    target = tuple(stages or CLIP_PIPELINE_STAGES)
    return [stage.name for stage in target]
