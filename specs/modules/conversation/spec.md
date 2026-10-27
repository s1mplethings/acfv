# Grounded Conversation Spec

## Purpose

Answer a current Creator Library question with a short response plus real video
evidence cards. The Library, not chat history, is the long-term memory.

## Process

1. Retrieve up to eight scoped parent Moments before asking any language model.
2. Apply a calibrated sufficiency gate using reranker score plus meaningful lexical
   support across the parent text and the winning retrieval representation excerpt.
3. If support is insufficient, return `没有找到足够明确的视频证据。` and do not call an LLM.
4. Otherwise pass stable request-local evidence IDs (`E1`, `E2`, …), parent text,
   and the winning retrieval excerpt through the existing provider abstraction at
   low temperature.
5. Validate and deduplicate citations against the supplied evidence map. Invalid
   IDs are filtered and never produce cards or grounded claims.
6. A timeout or malformed response gets at most one bounded repair attempt, then
   falls back to truthful `EVIDENCE_ONLY` output.

## Outputs

- Short answer.
- Grounded boolean and confidence label.
- SearchResult evidence cards with Recording title, timestamp, summary, transcript,
  preview locator, and Moment ID for Create Clip.
- Explicit runtime mode: `GROUNDED_LLM`, `EVIDENCE_ONLY`, or `DEGRADED`.
- Citation details map the stable evidence ID to Moment ID, Recording ID, start,
  and end timestamps.

## Acceptance Criteria

- A supported query returns an answer and Moment references.
- An unsupported query cannot produce a factual answer, even if an LLM is configured.
- Invalid model citations are discarded and cannot create evidence.
- When the LLM is unavailable, evidence remains visible but `grounded` is false and
  the response is explicitly `EVIDENCE_ONLY`.
- The GUI can scope a query to the Library or Creator, render evidence cards, and
  preview the original Recording at the cited timestamp without direct SQL access.
