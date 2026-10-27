# Creator Library Retrieval Spec

## Purpose

Persist searchable Moment representations above the Creator Library without
creating another media-processing pipeline.

## Index Backend Decision

ACFV reuses Transformers mean pooling plus the persistent FAISS
index with a NumPy fallback instead of adding
LanceDB, avoiding a second vector dependency and index lifecycle. Moment UUID and
scope metadata are stored in a versioned JSON manifest beside the vector files.

Production defaults to `intfloat/multilingual-e5-base`, promoted only after the
fixed-20/cross-language benchmark clearly outperformed e5-small. A load failure is explicit
`DEGRADED_FTS_ONLY`; deterministic hash vectors require
`ACFV_TEST_DETERMINISTIC_EMBEDDING=1` and are never a silent production fallback.

## Representation Contract

The product result and evidence unit remains the parent Moment. FINAL Moments are
indexed through multiple bounded retrieval representations: `SUMMARY`,
`FULL_TRANSCRIPT`, 100–250-token `PASSAGE` windows made from 2–6 transcript units
with one-unit overlap, and `NEIGHBOR_CONTEXT`. PROVISIONAL live Moments use the
lighter summary/full-transcript path. Each representation records its stable ID,
parent Moment, Recording, timestamp range, type, and text.

Dense and FTS retrieval operate on representations, then aggregate to a parent by
its best hit plus a small bounded second-hit bonus. Scores are never summed across
all passages, preventing long Moments from gaining a representation-count bias.

## Persistence

- Default root: `var/moment_index/`.
- Vector index/cache, numeric row map, and UUID metadata survive restart.
- Rebuild replaces dense and FTS generations together. Manifest v4 records model,
  dimension, backend/config hash, representation schema/config hash, creation time,
  parent Moments, and representation metadata.

## Acceptance Criteria

- PROVISIONAL and FINAL Moments can be indexed.
- Creator and Recording scopes are enforced after retrieval.
- Ten or more recordings remain searchable after service recreation.
- Missing/empty index returns no result rather than inventing evidence.
- Dense Top-128 and SQLite FTS5 Top-128 representation candidates are aggregated;
  English question stopwords are removed before constructing the FTS OR query,
  cheaply fused, and capped at 50 parent Moments before the multilingual
  CrossEncoder rerank; unavailable/disabled reranking is explicit and retains RRF.
- Debug output identifies the winning representation ID/type/excerpt, dense/FTS
  ranks and scores, and the reranker score without changing the Moment result API.
- A ten-query benchmark returns the expected evidence in Top 5 at least 7/10.
