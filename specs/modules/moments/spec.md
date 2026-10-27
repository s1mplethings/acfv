# Moment Lifecycle Spec

## Purpose

Turn incremental canonical-pipeline evidence into persistent, searchable product
objects while a Recording is still in progress. A Moment is an understanding and
retrieval unit; it is not a rendered Clip or a fixed clip boundary.

## Inputs

- A Library Recording ID.
- Incremental transcript payload using the canonical `segments` contract.
- Optional chat payload using the canonical `records` contract.
- Optional source-artifact paths for evidence provenance.

## Outputs

- Persistent Moment rows linked to Creator and Recording.
- PROVISIONAL moments available to live keyword search before the stream ends.
- Evidence JSON with typed time ranges, text, confidence, and artifact reference.

## Process

1. Normalize seconds or millisecond timestamps to integer milliseconds.
2. Group adjacent transcript segments with sentence, pause, and lightweight topic
   boundaries; prefer 20–75 seconds, use 90 seconds as a soft maximum and 120 as safety.
3. Attach chat records in the same window as supporting, never sole, evidence.
4. Upsert by a deterministic recording/time identity so repeated incremental
   snapshots do not duplicate moments.
5. Query only the requested Library/Creator/Recording/Live scope.
6. On completion, rebuild deterministic FINAL windows from complete artifacts and
   converge the Recording to only the current final identities.
7. While a backend job is active, watch canonical transcript mtime and synchronize
   changed snapshots into stable PROVISIONAL windows; on success finalize and reindex.

## Error Handling

- Missing Recording IDs and malformed segment timestamps fail explicitly.
- Empty transcript input creates no Moment, even when chat exists.
- Duplicate incremental input updates the existing Moment revision.
- Repeated finalization reuses stable Moment IDs; changed evidence increments revision.
- Punctuation-only FINAL Moments are suppressed. Low-information speech merges with
  temporal context unless chat/event evidence makes it meaningful.
- Summary fallback is a grounded 1–2 sentence extract, never an unbounded raw transcript copy.
- Versioned rebuild may retain old rows until Clip/Feedback references are migrated,
  then atomically promote a validated database copy.

## Acceptance Criteria

- Incremental transcript creates a PROVISIONAL Moment in real SQLite.
- Relevant live queries find the Moment; unrelated queries do not.
- Chat can enrich evidence but cannot create a claim by itself.
- Moments survive database reopen.
- Finalization removes replaced provisional/stale rows and is idempotent.
