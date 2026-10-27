# Creator-Adaptive Understanding Architecture

## Data flow

```text
Recording (read-only media)
  ├─ frames ─> existing AvatarIdentityProvider ─> visual observations
  ├─ speech spans ─> SpeakerEmbeddingProvider ─> voice observations
  └─ recording context ────────────────────────> recording prior
                         │
                         v
              CreatorIdentityService
              CONFIRMED / PROBABLE / AMBIGUOUS / UNKNOWN / CONFLICT
                         │
            only safe known identity
                         v
Generic ASR (authoritative) ─> trusted gate ─> TrustedSpeechMemoryService
                         │                         ├─ scoped lexicon
                         │                         └─ acoustic exemplars
                         v
             CreatorAdaptiveASRService
       candidates → hotwords → local re-decode → evidence consensus
                         │
                         v
              shadow comparison only
                         │
                         v
       existing Moment → Retrieval → Conversation → Clip pipeline
```

## Ownership

Providers load models and emit typed observations. They cannot write Creator/Recording state or transcript decisions. `CreatorIdentityService` alone fuses identity. `CreatorVoiceProfileService` owns WHO profiles. `TrustedSpeechMemoryService` owns trust, provenance, lexicon, and acoustic exemplars. `CreatorAdaptiveASRService` owns shadow decisions while generic ASR remains canonical.

## Safety and fallback

- Visual presence never implies active speech.
- Speaker embeddings never provide lexical evidence.
- Ambiguous/conflicting identity blocks Creator-scoped memory.
- Human truth has priority; adaptive output cannot self-promote.
- Media and raw/final transcripts are immutable.
- Provider/profile/memory/re-decode failures fall back to generic ASR.
- Profiles are versioned; rebuild never deletes old versions.

## Runtime lifecycle

Model-heavy work is offline and sequential: visual batches release their model before large ASR or speaker embedding work is loaded. Frame identity and voice embeddings are cached as versioned exemplars. New recordings add only new spans. The main pipeline does not rescan a Library at startup.

## Production gate

Shadow readiness requires contracts, fallback, isolation, and repeatable tests. Production enablement additionally requires independent human transcripts showing no increase in critical semantic errors and a real per-Creator improvement. Without those labels, WER and production readiness are `NOT_EVALUATED`/`NO`.

## Avatar-driven phase-2 bootstrap

```text
bounded model discovery/configuration
  -> existing AvatarIdentityProvider
  -> raw frame observations (unknown labels retained)
  -> explicit versioned label mapping
  -> multi-frame VisualIdentitySpan
  -> Visual + Recording prior + Voice support/conflict
  -> Generic ASR
  -> strict trusted/uncertain split
  -> versioned Trusted Speech Memory
  -> Creator Lexicon + pronunciation exemplars
  -> relevance-limited local re-decode
  -> blind shadow comparison
  -> Human Review
  -> per-Creator production recommendation (never automatic enablement)
```

Changing from an unconfigured avatar provider to a real model starts `creator_profile_v2`. Profile mismatch blocks memory lookup and adaptive decoding. The previous v1 evidence remains immutable.

