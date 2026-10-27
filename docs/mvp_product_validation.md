# MVP Product Validation

Date: 2026-10-06

## Recovery Audit

- Recovered with adaptation: backup SQLModel repository/service/scanner, Creator
  Library GUI concepts, watchdog integration, and dependency declarations.
- Migrated: legacy `Video` became `Recording`; Creator gained display identity;
  Source became an independent Twitch identity.
- Recovered later when required by Review/regression: subtitle render helpers and
  clip filename parser, both isolated from removed products.
- Discarded: old product plan and any code coupled to Enhance, TTS, Dify, or the
  standalone RAG manager.
- Reused as foundation: canonical backend/pipeline, stream-monitor recorder,
  SentenceTransformers/FAISS, PyQt player, and render_clips FFmpeg implementation.

## Automated Quality Results

- Full pytest: 201 passed.
- Product-layer coverage: 83%.
- Retrieval benchmark: 10/10 expected Moments in Top 5 (gate: at least 7/10).
- Real local rendering: initial render and boundary/subtitle re-render produced
  non-empty MP4 files through the existing renderer.
- Restart persistence: Creator, Source, Recording, Moment, index, Clip, Feedback,
  and ExplicitPreference verified in the full local E2E.
- Grounding negative test: unsupported query does not call the LLM and returns
  `没有找到足够明确的视频证据。`
- `scripts/verify.ps1`: PASS, including compile, CLI smoke, pytest, and contracts.

## Gates Requiring Real User Data

- Moment Quality Report: automated identity/timestamp/evidence checks pass, but a
  random manual review of 20 Final Moments from real recordings is not yet run.
- Clip Quality Gate: real renderer integration passes, but 10 real creator clips
  have not been manually classified; the 60% minor-or-no-edit metric is unknown.
- Dataset Gate: no verified 10-recording / 20-hour local corpus was supplied to this
  worktree, so the real long-archive gate is not claimed.
- True live gate: stream-monitor persists recording lifecycle and automatically
  processes/finalizes after capture. Incremental pipeline artifacts become searchable
  while a processing job runs. The recorder still writes one whole-session file, so
  ASR/query before the live stream ends is not yet proven and requires segmented or
  growing-file-safe ingestion.

## Verdict

`MVP_NOT_READY`

The implementation is locally testable and end-to-end usable for completed
recordings, but the frozen READY definition requires the unresolved true-live and
real-corpus quality gates above.
