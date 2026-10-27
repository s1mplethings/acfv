# Feedback

- Purpose: persist explicit decisions and transparent creator preferences.
- Canonical Interface: `acfv.feedback.service.FeedbackService`.
- Implementation: `src/acfv/feedback/`.
- Inputs: Clip ID plus Accept/Reject and an optional explicit reason, or explicit preference text and optional Creator ID.
- Outputs: durable Feedback (including the reviewed boundary, subtitle edit, and reason) and `ExplicitPreference` rows.
- Effects: retrieval may apply transparent explicit-keyword score adjustments.
- Errors: missing Clip/Creator fails explicitly; inferred preferences are forbidden.
- Dependencies: LibraryRepository; no UI dependency.
- Acceptance: feedback/preferences survive restart and only explicit preferences affect ranking.
