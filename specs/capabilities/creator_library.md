# Creator Library

- Purpose: persist Creator, Source, Recording, and artifact-location product state.
- Canonical Interface: `acfv.library.service.LibraryService`.
- Implementation: `src/acfv/library/`; repository owner is `LibraryRepository`.
- Inputs: creator/source metadata, local paths, capture events, processing requests.
- Outputs: durable product rows and canonical artifact locators.
- Effects: writes `var/acfv.db`; delegates processing to `acfv.backend.service`.
- Errors: missing files/IDs fail explicitly; interrupted states become retryable failures.
- Dependencies: backend service, runtime storage, SQLModel repository.
- Acceptance: persistence survives restart; GUI/CLI never write SQL directly; artifacts are referenced, not copied.
- Bulk-media invariant: large Twitch corpus media remains outside Git and is referenced
  through portable `BULK_MEDIA_ROOT/...` locators. A local ignored configuration resolves
  that alias; repository specs, fixtures, and manifests must not depend on one drive letter.

## Transcript-derived language profile

- Purpose: represent long-recording language truth without treating one ASR metadata label as authoritative for every span.
- Inputs: immutable transcript segments, Whisper's recording hint, optional Creator default, and legacy Recording metadata.
- Outputs: a versioned `RecordingLanguageProfile` plus per-span language and `TranscriptSpanClassification` metadata (`SPEECH`, `LIKELY_BACKGROUND_LYRICS`, `NON_SPEECH_REACTION`, `NOISE`, `UNCERTAIN`).
- Process: transcript evidence wins over Whisper/Creator/legacy hints; mixed-language state is derived from speech spans; repetitive discontinuous lyric/noise spans remain auditable but are down-weighted by product consumers.
- Persistence: derived metadata is stored in `Recording.analysis_profile_json`; raw transcript artifacts are never rewritten.
- Acceptance: metadata conflicts, English-plus-Japanese lyrics, Japanese speech, Chinese/English mixtures, empty text, low confidence, and repeat migration are covered by tests.

## Portable artifact locator

- Purpose: resolve processing artifacts after a Library root moves between machines or drives.
- Inputs: a relative canonical locator, ordered registered Library roots, and an optional legacy absolute root.
- Outputs: the first existing resolved path, with explicit diagnostics when no candidate exists.
- Process: a migration stores `runs/<recording-id>` as the canonical locator and preserves the old absolute path as `legacy_artifact_root`; no artifact or media file is moved.
- Acceptance: dry-run, idempotence, missing paths, spaces/Unicode, root replacement, restart, and legacy fallback are covered by tests.

Analysis Profile overrides (`Auto`, `Gaming`, `Talking`, `Collab`, `Other`, `Custom`)
are written through `LibraryService`. Creator overrides persist in Source metadata and are
inherited by new Twitch recordings; Recording overrides remain local to that recording.
