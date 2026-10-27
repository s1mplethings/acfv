# Creator Lexicon

- Purpose: provide provenance-bound candidate terms and hotwords at Recording, Game, Creator, and Global scope.
- Canonical Owner: `acfv.trusted_speech_memory.TrustedSpeechMemoryService`.
- Canonical Interface: `acfv.trusted_speech_memory.TrustedSpeechMemoryService.promote_lexicon`.
- Implementation: `src/acfv/trusted_speech_memory/service.py`.
- Inputs: repeated trusted occurrences or one human confirmation.
- Outputs: typed, normalized, versioned `CreatorLexiconEntry` rows.
- State: IMPLEMENTED and VALIDATED in SHADOW; incremental per profile version and production status NOT_EVALUATED.
- Persistence: unique by Creator/text/scope/scope-key/version with source provenance.
- Effects: appends or reuses derived lexicon entries; no transcript mutation.
- Errors: weak or cross-scope evidence is rejected explicitly.
- Failure Modes: one pseudo occurrence is rejected; background repetition without creator speech is ineligible.
- Fallback: empty Creator lexicon still permits GLOBAL/GAME candidates and generic ASR.
- Invariants: Recording > Game > Creator > Global; cross-Creator access is forbidden; candidates must originate from pseudo/human trusted speech; catchphrases require repeated identified Creator speech.
- Validation-corpus invariant: lexicon candidates for a corpus-bound profile version derive from TRAIN VOD trusted units only. VALIDATION may tune thresholds but cannot promote entries; HOLDOUT and UNKNOWN text cannot be promoted or used for threshold selection.
- Dependencies: Trusted Speech Memory.
- Evidence: cross-Creator leakage and poisoning tests.
- Acceptance: repeated/human gate, priority order, and cross-Creator isolation tests pass.
- Out of Scope: LLM-only candidate authority and implicit content-preference learning.

