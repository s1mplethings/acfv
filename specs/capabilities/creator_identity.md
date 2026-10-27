# Creator Identity

- Purpose: fuse visual, voice, recording-prior, and human observations into a creator identity decision for each speech span.
- Canonical Owner: `acfv.creator_identity.CreatorIdentityService`.
- Canonical Interface: `acfv.creator_identity.CreatorIdentityService`.
- Implementation: `src/acfv/creator_identity/` and shared `src/acfv/creator_adaptive/` domain persistence.
- Inputs: immutable `IdentityObservation` rows from VISUAL, VOICE, RECORDING_PRIOR, or HUMAN sources.
- Outputs: versioned `CreatorIdentityDecision` in CONFIRMED, PROBABLE, AMBIGUOUS, UNKNOWN, or CONFLICT state.
- State: IMPLEMENTED and VALIDATED in SHADOW. Visual is the primary presence prior, Recording ownership is a strong contextual prior, Voice is support/conflict evidence, and HUMAN is authoritative.
- Persistence: forward-only creator-adaptive tables in the Library SQLite database; every row keeps recording, model, evidence, and profile provenance.
- Effects: appends observations/decisions only; no raw transcript, Recording ownership, or media mutation.
- Errors: invalid observations fail explicitly; missing evidence resolves to UNKNOWN rather than throwing into the pipeline.
- Failure Modes: missing providers yield UNKNOWN; close candidates yield AMBIGUOUS; a sustained expected-voice mismatch is a `VOICE_MODE_SHIFT_CANDIDATE`; it becomes CONFLICT only when another known Creator strongly matches.
- Fallback: AMBIGUOUS, UNKNOWN, and CONFLICT use the generic pipeline and cannot access creator-scoped memory.
- Invariants: visual presence is not active speech; single-frame output cannot become strong identity; HUMAN wins over automatic evidence; unknown labels are persisted but never auto-create Creators; unlabeled acoustic style changes must not be interpreted as nationality/accent; confirmed conflicts force generic fallback.
- Dependencies: avatar provider, speaker embedding provider, Creator Library identifiers.
- Evidence: `creator-adaptive-test-receipt.json` and `identity-fusion-results.json`.
- Acceptance: fusion matrix, human priority, conflict fallback, migration, and provider-boundary tests pass.
- Out of Scope: avatar-model training, cross-library unknown-speaker identification, and Moment schema replacement.

