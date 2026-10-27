# Live Processing

- Purpose: turn closed Twitch capture segments into searchable provisional evidence before the stream ends.
- Canonical Interface: `acfv.live.service.LiveProcessingService`.
- Implementation: `src/acfv/live/`, fed by `acfv.runtime.stream_monitor` through `StreamLibraryBridge`.
- Inputs: Recording ID, ordered CLOSED media segment, recording-relative time range, optional aligned chat; monitor event timestamps are timezone-aware UTC values.
- Outputs: durable segment manifest/events, absolute-time transcript chunks, partial merged transcript, PROVISIONAL Moments, and live index entries.
- Effects: writes beneath `recordings/<recording_id>/` under the runtime storage root and updates Library/index state.
- Errors: failed segments remain retryable; DONE segments are never transcribed twice; optional evidence absence does not fail finalization.
- Dependencies: existing transcribe implementation (single-worker GPU model reuse when an isolated CUDA environment is detected), MomentService/MomentFinalizer, PersistentMomentIndex, LibraryRepository.
- Acceptance: given live capture, when a segment closes, its transcript and PROVISIONAL Moment are persisted and retrievable with LIVE_SESSION scope before stream end; finalization replaces provisional index entries idempotently.
