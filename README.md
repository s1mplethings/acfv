# ACFV

**AI-assisted video clipping workflow for VTubers and creators.**

ACFV is an open-source video clip workflow orchestrator that turns long-form video into manageable, searchable, and exportable clip candidates. It connects audio extraction, speech transcription, optional semantic analysis, segment selection, clip rendering, and result export behind a unified CLI/GUI workflow.

> 中文：ACFV 是一个面向 VTuber 和视频创作者的 AI 切片工作流工具，用于把长视频拆解为可分析、可筛选、可批量导出的片段。

## What it does

- Extracts audio and prepares chunk manifests for long videos.
- Transcribes audio chunks and merges transcripts into a project-level transcript.
- Supports optional analysis for semantic highlights and segment selection.
- Builds clip manifests and renders selected segments in batch.
- Provides both command-line and graphical entry points for the same backend workflow.

## Workflow

```text
ingest_video
  -> extract_audio
  -> build_audio_chunk_manifest
  -> transcribe_chunks
  -> merge_transcript
  -> optional_analysis
  -> select_segments
  -> build_clip_manifest
  -> render_clips_batch
  -> export_results
```

## Quick start

```bash
python -m acfv.cli gui
```

Or, after installing the console scripts:

```bash
acfv gui
```

Other available entry points are defined in `pyproject.toml`, including GUI and development utilities.

## Project direction

ACFV focuses on making creator clipping workflows more structured, inspectable, and reusable. The project is designed around explicit stages, runtime state, and visible outputs rather than a single black-box edit command.

## Status

Active experimental project. Interfaces and pipeline details may change as the workflow is refined.
