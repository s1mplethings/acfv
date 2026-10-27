# Creator Adaptive ASR

- Purpose: rescue high-risk low-confidence spans with Creator-scoped candidates, hotwords, local re-decode, and evidence consensus.
- Canonical Owner: `acfv.creator_adaptive_asr.CreatorAdaptiveASRService`.
- Canonical Interface: `acfv.creator_adaptive_asr.CreatorAdaptiveASRService.shadow_decide`.
- Implementation: `src/acfv/creator_adaptive_asr/`.
- Inputs: audio span reference, identity decision, immutable generic text/confidence, language context, lexicon, trusted history, optional unnamed voice mode, and optional Creator/profile-scoped HuBERT/WavLM lexical-acoustic candidate evidence.
- Outputs: shadow `AdaptiveTranscriptDecision` with generic/adaptive text, KEEP/CORRECT/REVIEW/fallback action, and evidence.
- State: v3 IMPLEMENTED and REAL-PROXY VALIDATED in SHADOW; real visual identity unlocks only scoped candidate memory; `creator_adaptation_enabled=false` by default and production remains NOT_EVALUATED until per-Creator human truth proves readiness.
- Persistence: shadow table only; official/raw transcript, Moment, Retrieval, Conversation, and Clip state are unchanged.
- Effects: appends side-by-side comparison/evidence rows only.
- Errors: local re-decode failure is recorded and returns GENERIC_FALLBACK.
- Failure Modes: no profile, uncertain identity, empty lexicon, corrupt memory, or re-decode failure.
- Fallback: generic ASR is always available and remains authoritative.
- Invariants: no Creator memory on conflict/ambiguity/profile mismatch; speaker embeddings are never lexical evidence; lexical-acoustic representations may rank candidates but never rewrite transcripts directly; hotwords are limited to a small relevant set; correction requires acoustic re-decode plus independent history; LLM is never sole authority.
- Validation-corpus invariant: VALIDATION may tune thresholds but cannot create memory. HOLDOUT evaluation can read only frozen TRAIN memory/lexicon/acoustic exemplars plus causal local-neighbor context from the current VOD. UNKNOWN identity must use GENERIC_FALLBACK and cannot read known-Creator memory.
- Dependencies: generic ASR, Creator Identity, Trusted Speech Memory, and Creator Lexicon.
- Evidence: `adaptive-asr-results.json`; WER remains NOT_EVALUATED without human ground truth.
- Acceptance: safe correction consensus, conflict fallback, no-overwrite guard, and default-disabled tests pass.
- Out of Scope: replacing Library/Final ASR, ranking rewrite, production enablement without truth, and LoRA.

