# Voice Profile

- Purpose: model WHO a speaker resembles across diverse trusted samples.
- Canonical Owner: `acfv.voice_profile.CreatorVoiceProfileService`.
- Canonical Interface: `acfv.voice_profile.CreatorVoiceProfileService`.
- Implementation: `src/acfv/voice_profile/` with provider interface in `src/acfv/providers/speaker_embedding.py`.
- Inputs: versioned voice exemplars from visual-strong/human-confirmed regions with embeddings, trust, quality, overlap/music flags, recordings, and temporal regions.
- Outputs: robust medoid/centroid profile, one or more unnamed acoustic mode sub-centres (`MODE_0`, `MODE_1`, ...), outlier audit, and cosine score labelled as similarity rather than probability.
- State: v3 IMPLEMENTED and REAL-PROXY VALIDATED as SHADOW_SUPPORT_SIGNAL; production identity remains NOT_EVALUATED. Runtime states are NOT_BUILT, INSUFFICIENT_DATA, or READY per profile version.
- Persistence: exemplars remain immutable; rebuild creates a new profile version and preserves old rows.
- Effects: appends derived exemplar/profile state only; raw audio stays read-only.
- Errors: insufficient data is the explicit `VOICE_PROFILE_INSUFFICIENT_DATA` state.
- Failure Modes: fewer than 20 clean samples, 60 seconds, or two regions gives `VOICE_PROFILE_INSUFFICIENT_DATA`.
- Fallback: provider/profile failure does not block generic ASR or visual identity.
- Invariants: speaker embedding answers WHO only and can never be lexical evidence; acoustic modes are data-derived and receive no accent/nationality/style label without human ground truth; a mismatch against the expected Creator is a `VOICE_MODE_SHIFT_CANDIDATE`, not an identity conflict, unless another known Creator strongly matches.
- Validation-corpus invariant: only TRAIN VOD audio can supply exemplars or profile state. VALIDATION is threshold-only. HOLDOUT and UNKNOWN cannot supply exemplars, profile state, outlier decisions, or threshold tuning.
- Dependencies: optional `SpeakerEmbeddingProvider`; first adapter is the existing Apache-2.0 resemblyzer dependency.
- Evidence: `voice-profile-build.json` with Windows, dependency, timing, and sample-limit audit.
- Acceptance: robust outlier handling, minimum-data gate, holdout separation, and WHO-only guards pass.
- Out of Scope: word recognition, voice cloning, and Whisper LoRA.

