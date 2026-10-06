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

## MVP direction

The current MVP is intentionally narrow:

- Detect and locally record configured Twitch creators.
- Analyze recordings while the stream is still live.
- Build provisional semantic moments that are searchable during the live session.
- Finalize/merge/split moments after the stream ends.
- Preserve recordings and derived artifacts in a persistent creator library.
- Answer library questions only when grounded in retrievable video evidence.
- Turn a selected moment into a clip, allow basic subtitle/boundary edits, and store explicit feedback.

Out of scope for the MVP: automatic publishing, multi-clip compilation, TTS, meme/effect enhancement, Dify integration, a standalone RAG manager, and a full nonlinear editor.

## Project direction

ACFV is moving from a one-shot clipping workflow toward a local-first creator library and grounded clip workflow. The existing pipeline remains the processing engine; persistent library, moment retrieval, review, and feedback are product layers built on top of it.

## Status

Active experimental project. Interfaces and pipeline details may change as the workflow is refined.
