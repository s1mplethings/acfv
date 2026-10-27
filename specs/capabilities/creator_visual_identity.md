# Creator Visual Identity

- Purpose: classify a detected avatar crop as a configured Creator or explicitly reject it as UNKNOWN/AMBIGUOUS.
- Canonical Owner: `acfv.creator_visual_identity.CreatorVisualIdentityService`.
- Canonical Interface: `CreatorVisualIdentityService.identify_crops` and the two-stage `TwoStageCreatorVisualIdentityProvider` adapter.
- Implementation: `src/acfv/creator_visual_identity/`, dataset/benchmark scripts, and `config/creator_visual_identity.json`.
- Inputs: versioned avatar crops, timestamps, detector bbox/confidence, and immutable model configuration.
- Outputs: candidate Creator ID, state, score, margin, support distance, prototype/classifier version, and raw presence provenance.
- State: ENGINEERING_READY in `SHADOW_VISUAL_IDENTITY`; per-frame human precision remains NOT_EVALUATED.
- Persistence: model artifacts and audit evidence only; the service cannot create or mutate Creator records.
- Effects: returns observations for temporal aggregation and Creator Identity Fusion.
- Errors: missing or hash-mismatched dependencies fail closed before inference.
- Failure Modes: low score, low margin, or low support becomes UNKNOWN/AMBIGUOUS; missing visual evidence falls back to generic processing.
- Invariants: presence is not identity; raw `vtuber` is never mapped to a Creator; UNKNOWN is first-class; one recording cannot cross train/validation/holdout; holdout evaluation is mandatory.
- Validation-corpus invariant: a frozen Twitch VOD ID is the highest split boundary. HOLDOUT VOD frames cannot enter prototype creation, classifier training, or threshold tuning; UNKNOWN VODs cannot be relabelled as a known Creator through Recording ownership.
- Dependencies: avatar presence provider, frozen ResNet18 encoder weights, and versioned open-set linear probe.
- Evidence: `visual-dataset-audit.json`, `visual-model-benchmark.json`, `visual-holdout-results.json`, and `visual-identity-spans-real.json`.
- Acceptance: recording-isolated split, contamination gates, known/unknown/ambiguous tests, false-strong safety threshold, temporal span gate, and real 500-frame-per-Creator validation pass.
- Out of Scope: active-speaker detection, ASR, Creator database ownership, and automatic production enablement.
