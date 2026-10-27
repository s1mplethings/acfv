# Retrieval

- Purpose: retrieve scoped Moment evidence with hybrid lexical/vector ranking.
- Canonical Interface: `acfv.retrieval.service.HybridRetrievalService`.
- Implementation: `src/acfv/retrieval/` using the existing FAISS/NumPy and SQLite FTS paths.
- Inputs: query, Top-K, and optional creator/recording/live scope.
- Outputs: parent-Moment-deduplicated `SearchResult` evidence cards; debug metadata
  identifies the winning summary, transcript, passage, or neighbor representation.
- Effects: rebuild writes the persistent Moment index beneath `var/`.
- Errors: invalid scopes fail; missing indexes return no result, never invented evidence.
- Dependencies: LibraryRepository, Moment model, existing embedding/index adapters.
- Acceptance: immutable 20-query gate is Top-5 >=14; Dense 128 + FTS 128 are fused
  to no more than 50 parents before reranking.
  Creator and Recording scopes are strict. A Recording-scoped search applies global plus
  that Recording owner's explicit preferences without leaking another Creator's preference.
  Scoped Dense and FTS candidate limits are satisfied after scope filtering, so a large
  unrelated Creator cannot crowd the requested Creator or Recording out of the lexical pool.

Search representations may use high-confidence corrected display text and span classification from Moment evidence. Speech has normal weight; likely background lyrics remain searchable through an explicitly labelled, lower-priority representation instead of being silently deleted. Recording-wide legacy language metadata never changes E5 `query:`/`passage:` encoding semantics.
