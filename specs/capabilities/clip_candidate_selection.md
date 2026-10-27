# Clip Candidate Selection

- Purpose: turn the top retrieval evidence into a small, diverse set of editable Clip
  candidates without treating retrieval rank as an editing decision.
- Canonical Interface: `acfv.clips.candidates.ClipCandidateSelector`.
- Implementation: `src/acfv/clips/candidates.py`, with thin CLI and GUI review adapters.
- Inputs: query, up to ten scoped `SearchResult` objects, Recording/Moment state, and an
  optional explicit natural-edge override.
- Outputs: three to five transparent candidates, watchability feature scores, eligibility
  decisions, one ranked selection, and optional previews through the existing renderer.
- Effects: optional preview files and persisted review proposals; no source media mutation.
- Process: Retrieval Top 10 -> eligibility -> `MOST_RELEVANT` / `MOST_COMPLETE` /
  `MOST_WATCHABLE` candidates -> watchability ranking -> preview -> review -> final render.
- Source Edge: a candidate less than 10 seconds from source start or 20 seconds from source
  end is ineligible with `SOURCE_EDGE` / `SOURCE_CONTEXT_INCOMPLETE`, unless an explicit
  natural-ending override and reason are recorded.
- Ranking: query relevance is important but cannot decide the final candidate alone.
  Self-contained context, hook, setup, event/reaction change, payoff, complete speech, and
  natural boundaries are positive signals. Dead air, jargon dependence, source-edge
  proximity, and low information are penalties.
  Text structure and information density must work for Latin and CJK scripts; English
  reaction keywords cannot be a prerequisite for Japanese/Chinese or long-form talking
  candidates.
- Errors: empty retrieval, query mismatch, incomplete context, low information, no hook,
  or no payoff are returned as explicit rejection reasons; the service must not silently
  force an ineligible final Clip.
- Dependencies: Creator Library, Retrieval, existing `ClipService`, and
  `backend.service.render_review_clip`; no second repository, pipeline, or renderer.
- Acceptance:
  - A Top-10 result set yields at least three directionally distinct candidates when three
    eligible moments or boundary variants exist.
  - Selection is based on watchability and eligibility, not `retrieval_rank == 1`.
  - Edge candidates are rejected unless the explicit override records its reason.
  - Candidate JSON contains every score dimension and every rejection reason.
  - Preview rendering delegates to the canonical review renderer.

