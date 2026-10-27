# Query-to-Clip Spec

## Purpose

Convert one selected Moment into one persistent Clip proposal and render it through
the existing canonical clip implementation. Moment boundaries remain retrieval
boundaries and are never treated as immutable Clip boundaries.

## Inputs

- Moment ID and originating query.
- Configurable leading/trailing context as fallback hints (defaults: 8s/12s).
- Optional retrieval relevance score for confident query-driven proposals.
- Recording local path.

## Outputs

- Persistent Clip row with original, proposed, and final boundaries.
- `selected_segments.json` and `clips_manifest.json` adapter artifacts.
- One playable MP4 from the existing `steps/render_clips` FFmpeg implementation.

## Error Handling

- Missing Moment/Recording/media fails explicitly.
- Low-value Moments and insufficient query relevance are rejected before rendering.
- Invalid boundaries are rejected before rendering.
- Render failures persist FAILED status and an error message for retry.

## Acceptance Criteria

- Proposal boundaries prefer complete transcript units, sentence endings, and pauses;
  fixed context is only a fallback and automatic Clips stay at or below 90 seconds.
- Rendering delegates through backend service, not a second renderer.
- Successful render persists READY and a local MP4 path.
- Review can adjust start/end, edit one subtitle text/style, and re-render to the
  same stable Clip output through the recovered subtitle render components.
