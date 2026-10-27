# Trusted Speech Memory

- Purpose: retain provenance-bound human and high-confidence speech evidence without self-training contamination.
- Canonical Owner: `acfv.trusted_speech_memory.TrustedSpeechMemoryService`.
- Canonical Interface: `acfv.trusted_speech_memory.TrustedSpeechMemoryService`.
- Implementation: `src/acfv/trusted_speech_memory/`.
- Inputs: visual-strong/human-confirmed creator identity provenance, profile compatibility, raw ASR, confidence, local-redecode agreement, overlap/music state, critical flags, timestamps, audio locator, and independent evidence.
- Outputs: RAW, AUTO_HIGH_CONFIDENCE, TRUSTED_PSEUDO_LABEL, HUMAN_CONFIRMED, or REJECTED units plus acoustic exemplars.
- State: versioned and append-only by Creator/profile.
- Persistence: stores locators and timestamps, never copies or rewrites raw media/transcripts.
- Effects: appends derived memory and acoustic-exemplar rows only.
- Errors: failed trust gates downgrade/reject the requested promotion without changing source truth.
- Failure Modes: ambiguous identity rejects trust; corrected text without two independent signals cannot self-promote.
- Fallback: untrusted units remain auditable but cannot bias Creator ASR.
- Invariants: human confirmation is highest priority; visual UNKNOWN/AMBIGUOUS cannot create trusted speech; PSEUDO_TRUSTED rejects overlap/music suspicion and profile mismatch; auto-corrected text cannot self-promote; lexicon derives only from trusted units; identity and acoustic/lexical memory remain separate.
- Validation-corpus invariant: only frozen TRAIN VODs may bootstrap a profile-version's trusted speech. VALIDATION is threshold-only; HOLDOUT and UNKNOWN are evaluation-only. None of those three roles may create known-Creator memory.
- Final-holdout invariant: every V1/V2 final-holdout VOD remains evaluation-only even if a malformed split labels it TRAIN. Attempts are blocked before persistence and append a `FINAL_HOLDOUT_LEAKAGE_ATTEMPT` audit event. A reserved final dataset is claimed atomically once after preflight; consumed datasets cannot be claimed again.
- Dependencies: Creator Identity and generic ASR evidence.
- Evidence: `trusted-speech-memory-results.json` and poisoning regressions.
- Acceptance: ambiguous identity, poisoning, human priority, provenance, and restart tests pass.
- Out of Scope: value/preference learning and direct acoustic word-similarity claims.

