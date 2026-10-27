# Clip Duration Profile

- Purpose: generate semantic SHORT, STANDARD, LONG, FULL_EVENT, and CUSTOM variants around one event and payoff anchor.
- Canonical Interface: `acfv.clips.variants.ClipVariantService`.
- Implementation: `src/acfv/clips/duration.py` and `src/acfv/clips/variants.py`.
- Inputs: one Clip/event identity, semantic boundary units, payoff anchor, source duration, duration profile, and optional custom limits.
- Outputs: ordered variant boundaries, extension/conflict reason, shared event identity, persisted review metadata, and optionally rendered clean/bilingual media.
- Effects: writes per-profile artifacts through the existing Clip renderer and persists selected profile metadata through Clip review.
  The GUI workflow state records independent per-profile progress, the selected profile, latest
  revision output, subtitle configuration, and interruption/retry state beside the event outputs.
- Errors: missing setup/payoff, source-edge conflict, incomplete sentence boundary, unavailable short form, or incompatible custom duration returns an explicit status.
- Dependencies: Clip Review, Bilingual Subtitle, and canonical Clip Rendering; no ASR, Moment, or Retrieval rebuild.
- Acceptance: generated profiles share an event/payoff anchor, preserve sentence/event boundaries, satisfy SHORT < STANDARD < LONG <= FULL_EVENT when available, and never use fixed padding or a mechanical cut. Generate All invokes the canonical service for each profile without freezing the GUI; one failed profile remains retryable without discarding completed profiles.

Production-facing Create Clip defaults to semantic `STANDARD` through this owner. A fixed 20-second
window may exist only as an explicitly named `PREVIEW_PROXY`, with `is_preview=true`, and is excluded
from final quality statistics. Duration reports fail when more than 75% of final clips fall in 18-22s
and flag a profile when more than 50% of rounded durations are identical.
