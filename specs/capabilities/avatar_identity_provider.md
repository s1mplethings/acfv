# Avatar Identity Provider

- Purpose: adapt the user's existing VTuber/avatar model into visual identity observations.
- Canonical Owner: provider contract `acfv.providers.avatar_identity.AvatarIdentityProvider`; fused identity remains owned by Creator Identity.
- Canonical Interface: `acfv.providers.avatar_identity.AvatarIdentityProvider.identify_frame`.
- Implementation: `src/acfv/providers/avatar_identity.py` and `src/acfv/providers/ultralytics_avatar.py`.
- Inputs: frame and recording-relative timestamp.
- Outputs: creator external label, confidence, timestamp, provider/model version, frame quality, optional bbox/track, and raw metadata.
- State: IMPLEMENTED / REAL_MODEL_PRESENCE_VALIDATED. The recovered YOLO11l detector is READY and validated on 1,000 real frames; its sole `vtuber` class remains presence-only and feeds the separate Creator Visual Identity capability.
- Persistence: none; the provider cannot write domain or Library tables.
- Effects: returns in-memory observations only.
- Errors: unavailable or adapter-required providers raise `AvatarProviderUnavailable` and are isolated from generic processing.
- Failure Modes: missing path, unsupported model-specific preprocessing/labels, load error, or inference error.
- Fallback: visual observation is absent; voice/prior may contribute and generic ASR remains available.
- Invariants: no model training/replacement; provider output does not imply active speaker; framework internals are not a domain contract.
- Dependencies: external checkpoint `G:/Cliper/acfv/model/best.pt`, Ultralytics 8.x, `ACFV_AVATAR_MODEL_PATH`, optional `ACFV_AVATAR_MODEL_ENTRYPOINT`, and optional `ACFV_AVATAR_MODEL_CONFIG`. The weight is not copied into the repository or deliverable.
- Evidence: `avatar-model-real-load.json`, `avatar-frame-inference.json`, `visual-identity-spans.json`, and the Creator Visual Identity v1 evidence set.
- Acceptance: bounded discovery, explicit configuration, explicit versioned label mapping, format detection, custom-adapter normalization, timestamp/model provenance, unavailable fallback, and architecture guards pass.
- Out of Scope: inventing Saruei/anny mappings for the generic `vtuber` label, accuracy retraining, relabelling, and direct Creator/Recording/Moment mutation.

