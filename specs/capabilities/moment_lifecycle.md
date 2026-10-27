# Moment Lifecycle

- Purpose: create persistent evidence units from incremental and final artifacts.
- Canonical Interface: `MomentService.ingest_incremental`; finalization is `MomentFinalizer.finalize`.
- Implementation: `src/acfv/moments/`.
- Inputs: Recording ID, transcript/chat evidence, artifact references.
- Outputs: PROVISIONAL or FINAL Moment rows.
- Effects: upserts stable time-window identities, supports PROVISIONAL → FINALIZING → FINAL, and removes replaced provisional/stale rows on finalization.
- Errors: missing recording and malformed timestamps fail; chat alone creates no claim.
- Dependencies: LibraryRepository and canonical pipeline artifacts.
- Acceptance: closed segments create searchable PROVISIONAL rows before stream end; repeat finalization is idempotent and creates no duplicate FINAL moments or index entries.

Derived transcript classification is evidence metadata, not a raw-transcript rewrite. Background-lyric-only or noise-only groups without chat/visual/reaction evidence are suppressed from product FINAL Moments; short reactions with event evidence remain valid. Structural duplicate repair requires the same Recording plus strongly overlapping time evidence and equivalent content, so deliberate repeated speech at different times is retained.
